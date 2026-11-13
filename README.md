# Tiquetmania: pruebas de rendimiento con JMeter

Monorepo del taller de Pruebas de Software. Contiene la API de compra de boletas (Colombia vs Chile), el plan de JMeter que la prueba y el pipeline de GitHub Actions que ejecuta ese plan en cada `push`.

## Estructura

```
tiquetmania/
├── api/
│   └── ticketmania_simple.py        # API simulada (Python 3.8+, solo biblioteca estándar)
├── pruebas/
│   ├── jmeter/                      # lo que ejecuta el pipeline
│   │   ├── Ticketmania.jmx          # plan: 200 usuarios, subida 300 s, bucle 1, timer 500-1500 ms
│   │   └── datos.csv                # tarifa,cantidad (misma carpeta que el .jmx)
│   └── experimentacion/             # ejercicio individual de las 10 preguntas (local; el pipeline NO lo ejecuta)
├── .github/workflows/
│   └── rendimiento.yml              # pipeline (GitHub solo lee .github/workflows/ en la raíz)
└── README.md
```

## El plan `Ticketmania.jmx`

Flujo de una compra, una vez por usuario:

1. `GET /api/tarifas`
2. `POST /api/seleccion` con `{"tarifa":"${tarifa}","cantidad":${cantidad}}` (valores del CSV). Un **Extractor JSON** (`$.reserva`) guarda el número de reserva en `${num_reserva}`.
3. `POST /api/pago` con `{"reserva":"${num_reserva}"}`. Una **Aserción JSON** comprueba `$.estado = APROBADO`.

| Parámetro | Valor |
|---|---|
| Grupo de Hilos | estándar, 200 hilos |
| Periodo de subida | 300 s |
| Contador del bucle | 1 |
| Temporizador | Aleatorio Uniforme: desplazamiento 500 ms + aleatorio hasta 1000 ms (pausas de 500 a 1500 ms) |
| CSV Data Set | `datos.csv` (ruta relativa), variables `tarifa,cantidad`, primera línea como nombres, reciclar en EOF |

El plan solo usa elementos del núcleo de JMeter (sin plugins) para que corra en GitHub Actions. El *Debug Sampler* y *Ver Árbol de Resultados* vienen deshabilitados: actívalos solo para depurar con pocos hilos.

> El README original de la API propone un extractor por expresión regular (`"reserva":"([^"]+)"`), pero la API responde con un espacio después de los dos puntos (`"reserva": "abc..."`), así que esa regex no encuentra nada. Por eso el plan usa el Extractor JSON.

## Ejecutarlo en tu computador

```bash
# 1) API (queda en http://127.0.0.1:8080)
python3 api/ticketmania_simple.py          # en Windows: python api/ticketmania_simple.py

# 2) JMeter en modo no-GUI, DESDE la carpeta del plan (así encuentra datos.csv)
cd pruebas/jmeter
jmeter -n -t Ticketmania.jmx -l resultados.jtl -e -o reporte
```

Abre `pruebas/jmeter/reporte/index.html` en el navegador. La carpeta `reporte` debe estar vacía o no existir antes de correr. Para construir o depurar, abre `Ticketmania.jmx` con la interfaz gráfica (`bin/jmeter`); para medir, usa siempre no-GUI.

## Pipeline (`.github/workflows/rendimiento.yml`)

Se dispara con un `push` a `main` o a mano desde la pestaña **Actions → Run workflow**. Pasos:

1. Descarga el código y prepara **Java 17**.
2. Descarga **JMeter 5.6.3** y agrega su `bin` al `PATH` con `$GITHUB_PATH`.
3. Levanta la API en segundo plano (puerto 8080) y **espera a que `/api/salud` responda**.
4. Ejecuta JMeter en modo no-GUI desde `pruebas/jmeter/`.
5. **Revisa el `.jtl`**: JMeter termina "bien" aunque una petición falle, así que este paso pone el job en **rojo** si hay muestras fallidas (o ninguna muestra).
6. Sube el reporte HTML como artefacto **`reporte-rendimiento`** con `if: always()`, aunque algo haya fallado antes.

El job tarda unos 6 minutos (5 de subida de usuarios). Para ver el reporte: **Actions → la ejecución → Artifacts → `reporte-rendimiento`**, descomprime y abre `index.html`.

Recuerda: en el pipeline la API y JMeter comparten la misma máquina virtual y esa máquina es compartida; el resultado comprueba que la prueba corre de principio a fin, no la capacidad real de la API. PerfMon no está disponible en el pipeline.

## Subirlo a GitHub

```bash
git init
git add .
git commit -m "Monorepo Tiquetmania: API, plan JMeter y pipeline"
git branch -M main
git remote add origin https://github.com/<tu-usuario>/tiquetmania.git
git push -u origin main
```

Crea antes el repositorio vacío `tiquetmania` en GitHub (sin README ni .gitignore). Al hacer el `push` el pipeline arranca solo.

## Limitaciones

- Los datos de la API están en memoria: reiniciarla borra las reservas.
- El pago siempre se aprueba y responde al instante; el taller solo prueba el camino feliz.
- Un solo equipo genera la carga y además aloja la API.
