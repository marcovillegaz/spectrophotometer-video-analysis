# Estructura de carpetas

**Para quién y cuándo leerlo:** para cuando buscás un archivo, querés saber si un dato es de una
sola corrida o de todas, o vas a editar algo a mano y necesitás saber a quién afecta.

La cámara se re-monta en cada sesión: el encuadre cambia entre videos, pero el equipo y el
display son los mismos. Eso parte los datos en dos mitades limpias — una **receta compartida** y
una **corrida aislada por video** (el porqué de esta separación está en
[decisiones](../diseno/decisiones.md#una-receta-compartida-y-corridas-aisladas)):

```
├─ videos/                          # entradas (no se versionan)
│    IMG_8102.MOV
├─ calib/                           # la receta, compartida por todas las corridas
│  ├─ config.json                   # geometría del número, matcheo, ROI/ancla de referencia, acceptance
│  ├─ reference.jpg                 # el fotograma al que corresponden esas coordenadas
│  ├─ templates/                    # la biblioteca de plantillas (una sola, global)
│  └─ .backups/                     # respaldos automáticos de la biblioteca (los últimos 5)
└─ runs/
   ├─ batch_report.csv              # una fila por corrida, lo escribe `batch`
   ├─ summary.csv                   # efectividad por corrida y TOTAL, lo escribe `summary`
   ├─ summary_chars.csv             # errores por carácter, lo escribe `summary`
   ├─ summary.html                  # la misma información con gráficos (salvo --no-html)
   ├─ img_8112/
   │  ├─ config.json                # receta + video, fps, ROI propia, umbrales de qc, offset
   │  ├─ frames/                    # fotogramas (no se versionan; se regeneran con extract)
   │  ├─ frames_index.csv
   │  ├─ teach/                     # ENTRENAMIENTO
   │  │  ├─ truth.csv               # muestras de entrenamiento (file,value)
   │  │  ├─ rejected.csv            # fotogramas descartados al etiquetar (file,set,date)
   │  │  └─ teach_report.csv        # leave-one-out de esas muestras (train / check)
   │  ├─ test/                      # PRUEBA: nunca entra a la biblioteca
   │  │  ├─ test.csv                # muestras de prueba (file,value)
   │  │  ├─ test_report.csv         # resultado de la última `teach test eval <id>`
   │  │  └─ teach_history.csv       # una fila por evaluación: la curva de aprendizaje
   │  └─ out/                       # salidas del pipeline
   │       absorbance.csv, readings.csv, qc_report.csv, read_meta.json,
   │       preview.png, contact_sheet.png, calibracion.png
   ├─ img_8102/
   ├─ img_8106/
   └─ img_8110/
```

Cada carpeta de la corrida responde a una pregunta distinta: `out/` es **lo que produce el
pipeline** (lo que entregás), `teach/` es **con qué se entrenó** y `test/` es **con qué se
midió**. Separar la prueba en su propia carpeta hace visible la regla de oro: nada de `test/`
entra a la biblioteca (el porqué, en la [guía](../calibrar/guia.md#las-tres-piezas-y-qué-toca-cada-comando)).
Las subcarpetas aparecen cuando hacen falta: una corrida sin prueba no tiene `test/` (así estaban
`img_8102`, `img_8106` e `img_8110` el 13-oct-2026). Qué contiene cada archivo, columna por
columna, está en [salidas](salidas.md).

## Corridas con el layout anterior

En las versiones anteriores, `truth.csv`, `rejected.csv` y `test.csv` vivían sueltos en `runs/<id>/`, y
`teach_report.csv`, `test_report.csv` y `teach_history.csv` dentro de `out/`. **No hay que
mudarlos a mano**: la primera vez que un comando abre la corrida, los mueve solo
(`compat.migrate_run_layout`) y avisa cada movimiento:

| antes | ahora |
|---|---|
| `runs/<id>/truth.csv` | `runs/<id>/teach/truth.csv` |
| `runs/<id>/rejected.csv` | `runs/<id>/teach/rejected.csv` |
| `runs/<id>/out/teach_report.csv` | `runs/<id>/teach/teach_report.csv` |
| `runs/<id>/test.csv` | `runs/<id>/test/test.csv` |
| `runs/<id>/out/test_report.csv` | `runs/<id>/test/test_report.csv` |
| `runs/<id>/out/teach_history.csv` | `runs/<id>/test/teach_history.csv` |

**Qué mirar** — Una línea por archivo movido, con la forma `aviso: se movio <origen> -> <destino>`.
Los archivos se **mueven**, no se reescriben: el contenido (incluidos los encabezados viejos en
español) queda igual y se sigue leyendo como antes. La migración es idempotente: lo que ya está en
su lugar no se toca, así que el aviso sale una sola vez por archivo.

**Errores comunes** — Que exista **el archivo viejo y el nuevo a la vez** (por ejemplo, porque
restauraste un respaldo viejo encima de una corrida ya migrada). En ese caso no se mueve ni se pisa
nada: el comando falla con `ERROR: Existen el archivo viejo ... y el nuevo ...: revisa cual
conservar y borra el otro a mano antes de seguir`. Compará los dos (cuál tiene más filas, cuál es
más reciente), respaldá el que vas a descartar en `old_data/` y dejá uno solo. Si es un `truth.csv`
o un `test.csv`, recordá que son tus etiquetas: no borres ninguno sin haberlo copiado antes.

## Qué se comparte y qué es de cada corrida

| qué | dónde | por qué |
|---|---|---|
| biblioteca de plantillas | **compartida** — `calib/templates/` | el display es el mismo equipo; una etiqueta equivocada afecta a **todos** los videos |
| geometría del número (celdas, punto decimal, signo, polaridad) | **compartida** — `calib/config.json`, copiada a cada corrida al crearla | no depende de dónde quedó el teléfono |
| parámetros de matcheo (`templates.*`, `read.*`) | **compartida**, copiada a cada corrida | son propiedades del lector, no de la sesión |
| umbrales de aceptación del lote (`acceptance`) | **solo** `calib/config.json` | es el criterio con el que aceptás un video, igual para todos |
| ROI, ancla, fotograma de referencia, rotación | **por corrida** — `runs/<id>/config.json` | cambian con el encuadre de cada montaje |
| video, fps, offset de tiempo | **por corrida** | son la sesión |
| umbrales de QC | **por corrida** | dependen de la iluminación de ese día |
| muestras de entrenamiento y de prueba | **por corrida** — `teach/truth.csv`, `test/test.csv` | apuntan a fotogramas de un video concreto |
| descartados al etiquetar | **por corrida** — `teach/rejected.csv` | solo los usa el etiquetado, para no volver a proponerlos |
| reporte general de efectividad | **de todas las corridas** — `runs/summary.*` | junta la prueba, el leave-one-out y la cobertura de todos los videos |
| fotogramas | **por corrida** — `frames/` | regenerables; son miles (contalos con `frames_index.csv`, no listando la carpeta) |

**`read` toma de `calib/` solo la biblioteca** (`templates/`); todo lo demás sale de
`runs/<id>/config.json`. `calib/config.json` sirve para sembrar corridas nuevas, para
`calibrate --auto` y para los umbrales `acceptance`. El detalle de cada campo está en
[config](config.md). Qué contiene cada archivo de `out/`, `teach/` y `test/` está en
[salidas](salidas.md).

## Qué se versiona

Se versionan `calib/` (salvo `.backups/`), `runs/*/config.json`, `runs/*/teach/`, `runs/*/test/`
y `runs/*/out/` (el `.gitignore` no excluye los `runs/summary.*` ni `runs/batch_report.csv`, así
que también quedan versionados si los agregás).
No se versionan `videos/` ni `runs/*/frames/`, que son pesados y regenerables.

## El id de la corrida

El **id de corrida** sale del nombre del video: `IMG_8102.MOV` → `img_8102` (minúsculas, y lo que
no es letra ni número pasa a `_`). Los videos de iPhone con fecha en el nombre usan otra regla:
`AAAAMMDD_HHMMSSmmm_iOS.MOV` → `AAAAMMDD_HHMMSS` (fecha y hora, sin los milisegundos). `--name`
(de [`new`](comandos.md#new--dar-de-alta-una-corrida)) lo reemplaza.

---

**Siguiente paso:** cada campo de los dos `config.json`, en [config](config.md).
