#!/usr/bin/env python3
"""
Ejecuta los experimentos de las 10 preguntas "¿Qué pasaría si...?" con JMeter en modo no-GUI.

Para cada ejecución:
  1. Levanta una API nueva en el puerto 8080 (así cada corrida empieza sin reservas en memoria).
  2. Mide CPU y memoria del equipo cada segundo (necesita `pip install psutil`; es opcional).
  3. Corre JMeter: genera resultados.jtl y el reporte HTML.
  4. Apaga la API y resume los resultados en resultados/resumen.md y resultados/resumen.csv.

Uso (desde cualquier carpeta):
  python3 ejecutar_experimentos.py --lista               # ver qué se ejecutaría
  python3 ejecutar_experimentos.py --preguntas 1,2,3     # solo esas preguntas
  python3 ejecutar_experimentos.py                       # las 10 preguntas, 2 repeticiones cada una
  python3 ejecutar_experimentos.py --reps 1              # una sola repetición (más rápido)
  python3 ejecutar_experimentos.py --jmeter C:/apache-jmeter-5.6.3/bin/jmeter.bat

Requisitos: Python 3.8+, Java 17+, JMeter 5.6.3. La API no debe estar corriendo antes de empezar.
"""
import argparse
import csv
import datetime
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

try:
    import psutil
except ImportError:  # el monitoreo de recursos es opcional
    psutil = None

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
API = RAIZ / "api" / "ticketmania_simple.py"
SALIDA = AQUI / "resultados"
URL_SALUD = "http://127.0.0.1:8080/api/salud"

# (id, pregunta, plan, propiedades -Jclave=valor, qué cambia respecto a la otra corrida de la pregunta)
EXPERIMENTOS = [
    ("P01-20u", 1, "Exp_carga.jmx", {"hilos": 20, "subida": 30, "bucle": 1}, "20 usuarios"),
    ("P01-500u", 1, "Exp_carga.jmx", {"hilos": 500, "subida": 30, "bucle": 1}, "500 usuarios"),
    ("P02-subida1s", 2, "Exp_carga.jmx", {"hilos": 200, "subida": 1, "bucle": 1}, "subida de 1 s"),
    ("P02-subida60s", 2, "Exp_carga.jmx", {"hilos": 200, "subida": 60, "bucle": 1}, "subida de 60 s"),
    ("P03-con-timer", 3, "Exp_carga.jmx", {"hilos": 100, "subida": 10, "bucle": 10}, "con temporizador (500-1500 ms)"),
    ("P03-sin-timer", 3, "Exp_carga.jmx",
     {"hilos": 100, "subida": 10, "bucle": 10, "t_const": 0, "t_rango": 1}, "sin temporizador"),
    ("P04-escalones", 4, "Exp_estres.jmx", {}, "50 -> 100 -> 250 -> 500 usuarios, 60 s por escalón"),
    ("P05-1min", 5, "Exp_duracion.jmx", {"hilos": 50, "subida": 10, "duracion": 60}, "1 minuto"),
    ("P05-10min", 5, "Exp_duracion.jmx", {"hilos": 50, "subida": 10, "duracion": 600}, "10 minutos"),
    ("P06-endpoints", 6, "Exp_carga.jmx", {"hilos": 200, "subida": 30, "bucle": 5},
     "misma carga; se comparan /api/tarifas vs /api/seleccion"),
    ("P07-500-a-la-vez", 7, "Exp_concurrencia.jmx", {"hilos": 500, "subida": 1, "grupo": 500}, "500 reservas a la vez"),
    ("P08-sincronizado", 8, "Exp_concurrencia.jmx", {"hilos": 500, "subida": 1, "grupo": 500},
     "sincronizados (disparan juntos)"),
    ("P08-distribuido", 8, "Exp_concurrencia.jmx", {"hilos": 500, "subida": 60, "grupo": 1},
     "distribuidos en 60 s (sin sincronizar)"),
    ("P09-total", 9, "Exp_carga.jmx", {"hilos": 200, "subida": 30, "bucle": 3},
     "se valida total = precio x cantidad con el CSV"),
    ("P10-500u-recursos", 10, "Exp_carga.jmx", {"hilos": 500, "subida": 60, "bucle": 1}, "500 usuarios + CPU y memoria"),
]


# ------------------------------------------------------------------ utilidades
def buscar_jmeter(ruta_pedida):
    candidatos = []
    if ruta_pedida:
        candidatos.append(ruta_pedida)
    if os.environ.get("JMETER_HOME"):
        candidatos.append(str(Path(os.environ["JMETER_HOME"]) / "bin" / "jmeter"))
        candidatos.append(str(Path(os.environ["JMETER_HOME"]) / "bin" / "jmeter.bat"))
    candidatos += ["jmeter", "jmeter.bat"]
    home = Path.home()
    candidatos.append(str(home / "apache-jmeter-5.6.3" / "bin" / "jmeter"))
    for c in candidatos:
        encontrado = shutil.which(c)
        if encontrado:
            return encontrado
    sys.exit("No encuentro JMeter. Usa --jmeter <ruta a bin/jmeter> o define la variable JMETER_HOME.")


def api_responde():
    try:
        with urllib.request.urlopen(URL_SALUD, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def levantar_api():
    if api_responde():
        sys.exit("Ya hay una API respondiendo en el puerto 8080. Ciérrala: cada ejecución levanta la suya.")
    proceso = subprocess.Popen([sys.executable, str(API)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if api_responde():
            return proceso
        time.sleep(0.2)
    proceso.terminate()
    sys.exit("La API no arrancó en 10 s.")


class Monitor(threading.Thread):
    """Muestrea CPU y memoria del equipo completo (JMeter + API), como haría PerfMon."""

    def __init__(self, archivo):
        super().__init__(daemon=True)
        self.archivo = archivo
        self.parar = threading.Event()

    def run(self):
        with open(self.archivo, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["segundo", "cpu_pct", "mem_pct", "mem_usada_mb"])
            psutil.cpu_percent(None)
            t0 = time.time()
            while not self.parar.wait(1.0):
                m = psutil.virtual_memory()
                w.writerow([round(time.time() - t0), psutil.cpu_percent(None), m.percent,
                            round(m.used / 1048576)])
                f.flush()


def percentil(valores, p):
    if not valores:
        return 0
    v = sorted(valores)
    return v[max(0, math.ceil(p / 100.0 * len(v)) - 1)]


def estadisticas(filas):
    n = len(filas)
    if n == 0:
        return None
    tiempos = [int(x["elapsed"]) for x in filas]
    inicio = min(int(x["timeStamp"]) for x in filas)
    fin = max(int(x["timeStamp"]) + int(x["elapsed"]) for x in filas)
    seg = max((fin - inicio) / 1000.0, 0.001)
    fallos = sum(1 for x in filas if x["success"].strip().lower() != "true")
    return {"muestras": n, "media": round(sum(tiempos) / n, 1), "p95": percentil(tiempos, 95),
            "max": max(tiempos), "error_pct": round(100.0 * fallos / n, 2), "rendimiento": round(n / seg, 2)}


def leer_jtl(ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resumir_recursos(ruta):
    if not ruta.exists():
        return None
    with open(ruta, newline="") as f:
        filas = list(csv.DictReader(f))
    if not filas:
        return None
    cpu = [float(x["cpu_pct"]) for x in filas]
    mem = [float(x["mem_pct"]) for x in filas]
    return {"cpu_prom": round(sum(cpu) / len(cpu), 1), "cpu_max": max(cpu),
            "mem_ini": mem[0], "mem_fin": mem[-1], "mem_max": max(mem)}


def java_version():
    try:
        r = subprocess.run(["java", "-version"], capture_output=True, text=True)
        return (r.stderr or r.stdout).splitlines()[0]
    except Exception:
        return "no disponible"


def entorno(jmeter):
    ram = "{:.1f} GB".format(psutil.virtual_memory().total / 1024 ** 3) if psutil else "(instala psutil)"
    return [
        "- Fecha: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "- Sistema: %s %s | CPU lógicas: %s | RAM: %s" % (platform.system(), platform.release(), os.cpu_count(), ram),
        "- Java: " + java_version(),
        "- JMeter: " + jmeter,
        "- La API y JMeter corren en el MISMO equipo (limitación a anotar en el informe).",
    ]


# ------------------------------------------------------------------ ejecución
def ejecutar(exp, rep, jmeter, con_monitor):
    id_exp, pregunta, plan, props, descripcion = exp
    nombre = "%s-r%d" % (id_exp, rep)
    carpeta = SALIDA / nombre
    if carpeta.exists():
        shutil.rmtree(carpeta)  # JMeter exige que la carpeta del reporte no exista o esté vacía
    carpeta.mkdir(parents=True)

    cmd = [jmeter, "-n", "-t", str(AQUI / plan), "-l", str(carpeta / "resultados.jtl"),
           "-e", "-o", str(carpeta / "reporte"), "-j", str(carpeta / "jmeter.log")]
    cmd += ["-J%s=%s" % (k, v) for k, v in props.items()]

    print("\n=== %s  (P%d: %s) ===" % (nombre, pregunta, descripcion))
    print(" ".join(cmd))
    api = levantar_api()
    monitor = None
    if con_monitor:
        monitor = Monitor(carpeta / "recursos.csv")
        monitor.start()
    t0 = time.time()
    try:
        rc = subprocess.run(cmd, cwd=str(AQUI)).returncode
    finally:
        if monitor:
            monitor.parar.set()
            monitor.join(timeout=3)
        api.terminate()
        api.wait(timeout=5)
    print("JMeter terminó con código %s en %.0f s" % (rc, time.time() - t0))
    if rc != 0 or not (carpeta / "resultados.jtl").exists():
        print("  ! Falló esta ejecución; revisa %s" % (carpeta / "jmeter.log"))
        return None

    filas = leer_jtl(carpeta / "resultados.jtl")
    por_etiqueta = {}
    for f in filas:
        por_etiqueta.setdefault(f["label"], []).append(f)
    etiquetas = {k: estadisticas(v) for k, v in sorted(por_etiqueta.items())}
    etiquetas["TOTAL"] = estadisticas(filas)

    por_etapa = {}
    for f in filas:
        m = re.match(r"\[(E\d-\d+u)\]", f["label"])
        if m:
            por_etapa.setdefault(m.group(1), []).append(f)
    etapas = {k: estadisticas(v) for k, v in sorted(por_etapa.items())}

    return {"nombre": nombre, "pregunta": pregunta, "descripcion": descripcion, "props": props,
            "etiquetas": etiquetas, "etapas": etapas,
            "recursos": resumir_recursos(carpeta / "recursos.csv") if con_monitor else None}


def tabla(titulo_col, datos):
    lineas = ["| %s | Muestras | Media (ms) | p95 (ms) | Máx (ms) | %% Error | Rendimiento (req/s) |" % titulo_col,
              "|---|---|---|---|---|---|---|"]
    for k, s in datos.items():
        lineas.append("| %s | %d | %s | %s | %s | %s | %s |" % (k, s["muestras"], s["media"], s["p95"], s["max"],
                                                              s["error_pct"], s["rendimiento"]))
    return "\n".join(lineas)


def escribir_resumen(resultados, jmeter):
    SALIDA.mkdir(exist_ok=True)
    md = ["# Resumen de experimentos", "", "## Entorno", ""] + entorno(jmeter) + [""]
    with open(SALIDA / "resumen.csv", "w", newline="", encoding="utf-8") as fc:
        w = csv.writer(fc)
        w.writerow(["ejecucion", "pregunta", "etiqueta", "muestras", "media_ms", "p95_ms", "max_ms", "error_pct",
                    "rendimiento_rps", "cpu_prom", "cpu_max", "mem_ini_pct", "mem_fin_pct", "mem_max_pct"])
        for r in resultados:
            rec = r["recursos"] or {}
            md += ["## %s - P%d: %s" % (r["nombre"], r["pregunta"], r["descripcion"]), "",
                   "Propiedades: `%s`" % (", ".join("%s=%s" % kv for kv in r["props"].items()) or "(plan fijo)"), "",
                   tabla("Etiqueta", r["etiquetas"]), ""]
            if r["etapas"]:
                md += ["Por escalón:", "", tabla("Escalón", r["etapas"]), ""]
            if rec:
                md += ["Recursos del equipo: CPU promedio %s %%, CPU máxima %s %%, memoria %s %% al inicio, %s %% al "
                       "final, %s %% máxima." % (rec["cpu_prom"], rec["cpu_max"], rec["mem_ini"], rec["mem_fin"],
                                                 rec["mem_max"]), ""]
            for k, s in r["etiquetas"].items():
                w.writerow([r["nombre"], r["pregunta"], k, s["muestras"], s["media"], s["p95"], s["max"],
                            s["error_pct"], s["rendimiento"], rec.get("cpu_prom", ""), rec.get("cpu_max", ""),
                            rec.get("mem_ini", ""), rec.get("mem_fin", ""), rec.get("mem_max", "")])
    (SALIDA / "resumen.md").write_text("\n".join(md), encoding="utf-8")
    print("\nResumen escrito en %s y %s" % (SALIDA / "resumen.md", SALIDA / "resumen.csv"))


def main():
    ap = argparse.ArgumentParser(description="Ejecuta los experimentos de JMeter de las 10 preguntas.")
    ap.add_argument("--preguntas", default="1,2,3,4,5,6,7,8,9,10", help="lista separada por comas (por defecto, todas)")
    ap.add_argument("--reps", type=int, default=2, help="repeticiones por escenario (por defecto 2)")
    ap.add_argument("--jmeter", help="ruta al ejecutable jmeter (o jmeter.bat)")
    ap.add_argument("--sin-monitor", action="store_true", help="no medir CPU y memoria")
    ap.add_argument("--lista", action="store_true", help="solo mostrar las ejecuciones")
    args = ap.parse_args()

    elegidas = {int(x) for x in args.preguntas.split(",") if x.strip()}
    plan = [e for e in EXPERIMENTOS if e[1] in elegidas]
    if args.lista:
        for e in plan:
            print("P%02d  %-18s %-22s %s   %s" % (e[1], e[0], e[2], e[3] or "", e[4]))
        return
    if not plan:
        sys.exit("Ninguna pregunta seleccionada.")

    jmeter = buscar_jmeter(args.jmeter)
    con_monitor = psutil is not None and not args.sin_monitor
    if not con_monitor and not args.sin_monitor:
        print("Aviso: sin psutil no se mide CPU/memoria. Instálalo con: pip install psutil")

    resultados = []
    for e in plan:
        for rep in range(1, args.reps + 1):
            r = ejecutar(e, rep, jmeter, con_monitor)
            if r:
                resultados.append(r)
    if resultados:
        escribir_resumen(resultados, jmeter)


if __name__ == "__main__":
    main()
