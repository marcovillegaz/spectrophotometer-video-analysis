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
   ├─ img_8102/
   │  ├─ config.json                # receta + video, fps, ROI propia, umbrales de qc, offset
   │  ├─ frames/                    # fotogramas (no se versionan; se regeneran con extract)
   │  ├─ frames_index.csv
   │  ├─ truth.csv                  # muestras de ENTRENAMIENTO (file,value)
   │  ├─ test.csv                   # muestras de PRUEBA: nunca entran a la biblioteca
   │  └─ out/                       # absorbance.csv, qc_report.csv, readings.csv, read_meta.json…
   ├─ img_8106/
   ├─ img_8110/
   └─ img_8112/
```

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
| muestras de entrenamiento y de prueba | **por corrida** — `truth.csv`, `test.csv` | apuntan a fotogramas de un video concreto |
| fotogramas | **por corrida** — `frames/` | regenerables; son miles (contalos con `frames_index.csv`, no listando la carpeta) |

**`read` toma de `calib/` solo la biblioteca** (`templates/`); todo lo demás sale de
`runs/<id>/config.json`. `calib/config.json` sirve para sembrar corridas nuevas, para
`calibrate --auto` y para los umbrales `acceptance`. El detalle de cada campo está en
[config](config.md). Qué contiene cada archivo de `out/` está en [salidas](salidas.md).

## Qué se versiona

Se versionan `calib/` (salvo `.backups/`), `runs/*/config.json`, las muestras y `runs/*/out/`.
No se versionan `videos/` ni `runs/*/frames/`, que son pesados y regenerables.

## El id de la corrida

El **id de corrida** sale del nombre del video: `IMG_8102.MOV` → `img_8102` (minúsculas, y lo que
no es letra ni número pasa a `_`). Los videos de iPhone con fecha en el nombre usan otra regla:
`AAAAMMDD_HHMMSSmmm_iOS.MOV` → `AAAAMMDD_HHMMSS` (fecha y hora, sin los milisegundos). `--name`
(de [`new`](comandos.md#new--dar-de-alta-una-corrida)) lo reemplaza.

---

**Siguiente paso:** cada campo de los dos `config.json`, en [config](config.md).
