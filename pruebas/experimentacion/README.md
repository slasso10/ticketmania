# Experimentación (individual, local)

Escenarios para responder las 10 preguntas "¿Qué pasaría si...?". **No se ejecutan en el pipeline** y **no modifican** `pruebas/jmeter/Ticketmania.jmx`.

## Planes (uno por tipo de escenario)

| Plan | Tipo | Propiedades `-J` (con valor por defecto) |
|---|---|---|
| `Exp_carga.jmx` | Carga | `hilos`=50, `subida`=30, `bucle`=1, `t_const`=500, `t_rango`=1000 |
| `Exp_estres.jmx` | Estrés | fijo: 4 escalones de 60 s con 50, 100, 250 y 500 usuarios, uno tras otro |
| `Exp_duracion.jmx` | Duración | `hilos`=50, `subida`=10, `duracion`=60 (segundos) |
| `Exp_concurrencia.jmx` | Concurrencia | `hilos`=500, `subida`=1, `grupo`=500, `espera`=30000 (`grupo`=1 equivale a no sincronizar) |

Todos usan `datos.csv` (columnas `tarifa,cantidad,total_esperado`) y validan que el `total` de la respuesta sea precio × cantidad. Todos son abribles en la interfaz gráfica de JMeter para tomar los screenshots del escenario.

## Correrlos

```bash
pip install psutil                     # opcional: mide CPU y memoria (sustituye a PerfMon)
python3 ejecutar_experimentos.py --lista
python3 ejecutar_experimentos.py --preguntas 1,2,3 --reps 2
python3 ejecutar_experimentos.py       # las 10 preguntas, 2 repeticiones (cerca de 1 hora)
```

Si JMeter no está en el `PATH`: `--jmeter ~/apache-jmeter-5.6.3/bin/jmeter` (en Windows, `jmeter.bat`) o define `JMETER_HOME`.

Cada ejecución levanta su propia API en el puerto 8080 (no la tengas corriendo antes), guarda en `resultados/<ejecución>/` el `.jtl`, el reporte HTML (`reporte/index.html`) y `recursos.csv`, y al final escribe `resultados/resumen.md` y `resumen.csv` con muestras, media, p95, máximo, % error, rendimiento, CPU y memoria.

## Pregunta → ejecuciones

| Pregunta | Ejecuciones | Variable que cambia |
|---|---|---|
| 1 | P01-20u, P01-500u | usuarios |
| 2 | P02-subida1s, P02-subida60s | periodo de subida |
| 3 | P03-con-timer, P03-sin-timer | temporizador |
| 4 | P04-escalones | usuarios por escalón (resumen "Por escalón") |
| 5 | P05-1min, P05-10min | duración |
| 6 | P06-endpoints | ninguna: se comparan las etiquetas `Tarifas` y `SeleccionTarifaYCantidad` del mismo reporte |
| 7 | P07-500-a-la-vez | (una corrida con 500 usuarios sincronizados) |
| 8 | P08-sincronizado, P08-distribuido | sincronizados vs distribuidos en 60 s |
| 9 | P09-total | (la aserción del total ya va en todos los planes) |
| 10 | P10-500u-recursos | usuarios; mira `recursos.csv` y la sección de recursos del resumen |

## Buenas prácticas del taller

Cambia una sola variable por ejecución, repite cada escenario al menos dos veces, mide en no-GUI, cierra otros programas y anota el entorno (el resumen ya lo registra). Si el CPU del equipo llega al tope, el resultado mide al generador de carga y no a la API.
