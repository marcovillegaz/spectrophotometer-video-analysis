# Formato de salida

**Para quién y cuándo leerlo:** para cuando abrís un CSV de `runs/<id>/out/` y querés saber qué
significa cada columna y cada estado, o vas a escribir un script que lo lea. Cómo abrir
`absorbance.csv` en Excel está en la [primera corrida](../empezar/primera-corrida.md#abrirlo-y-graficarlo-en-excel).

## `runs/<id>/out/absorbance.csv` — sólo filas válidas

```
t_s,t_video,t_exp,absorbance,confidence,frame
```

| columna | unidad | contenido |
|---|---|---|
| `t_s` | s | segundos desde el inicio del video |
| `t_video` | hh:mm:ss.mmm | para volver al fotograma exacto en el reproductor |
| `t_exp` | s | `t_s + time.offset_s` — **la columna para alinear con el log manual** |
| `absorbance` | Abs | el valor leído, con tantos decimales como muestra el display |
| `confidence` | 0–1 | NCC mínima entre los slots del fotograma |
| `frame` | — | nombre del archivo, para trazabilidad |
| `datetime` | ISO | sólo si `time.absolute_start` está definido en `config.json` (columna extra al final) |

Las filas descartadas **no aparecen** y **no se interpolan**: un hueco en la serie es información
honesta (el porqué, en [decisiones](../diseno/decisiones.md#las-filas-descartadas-se-omiten-no-se-interpolan)).
Quedan documentadas, una por una y con su motivo, en `qc_report.csv`.

**Alinear el tiempo con el log del laboratorio**: si el video arrancó 12,5 s después del t=0 de
tu planilla, poné `"offset_s": 12.5` en `runs/<id>/config.json` y volvé a correr
`report --run <id>`. Para tener hora de reloj, agregá `"absolute_start": "2026-09-01 16:42:20"`.
El offset es **por corrida**: cada video arrancó en un momento distinto. Los dos campos están en
[config](config.md#time--alineación-temporal---por-corrida).

## `runs/<id>/out/qc_report.csv` — el libro mayor, un renglón por fotograma extraído

`file, t_s, index, mean_luma, p05, p95, contrast, blur_var, ink_fraction, anchor_ncc, dx, dy,
status`

`qc` lo crea con las métricas y el estado inicial; `read` le actualiza `status` con el resultado
de la lectura. Estados posibles:

| estado | lo pone | significa |
|---|---|---|
| `ok` | `read` | lectura aceptada |
| `dark`, `blown` | `qc` | ROI muy oscura / quemada |
| `blur` | `qc` | desenfoque o movimiento |
| `low_contrast` | `qc` | display apagado o velado |
| `blank`, `occluded` | `qc` | casi sin tinta (o el fotograma no cargó) / tapado, p. ej. una mano |
| `camera_moved` | `qc` | el ancla no coincide o el corrimiento supera `qc.max_shift_px` |
| `roi_outside` | `qc` o `read` | la ROI, corrida por la deriva, no entra en el fotograma |
| `low_confidence` | `read` | el lector se abstuvo: confianza o margen por debajo del umbral |
| `spike` | `read` | salto aislado contra ambos vecinos (`read.max_rate`) |

## `runs/<id>/out/readings.csv` — todas las lecturas

`file, t_s, index, value, confidence, margin, chars, dx, dy, status`. Incluye las descartadas
(con `value` vacío si no se pudo armar el número). `chars` es el texto crudo leído celda por celda;
`confidence` es la NCC mínima entre celdas y `margin` la ventaja mínima sobre la mejor plantilla
de otro carácter. Es la fuente de la incertidumbre que usa `suggest`.

## `runs/<id>/out/read_meta.json` — con qué biblioteca se leyó

```
{"fingerprint": "<12 caracteres hex>", "date": "<AAAA-MM-DD HH:MM:SS>", "templates": <cantidad>}
```

La **huella** (_fingerprint_) son los primeros 12 caracteres del SHA-256 de los nombres y el
contenido de todas las plantillas: cambia si se agrega, borra, renombra o modifica cualquiera.
`read` la escribe junto a `readings.csv`; `teach status`, `teach test eval` y `batch` la comparan
con la de la biblioteca de hoy para decir si las salidas están al día (`up_to_date`) o son de
otra biblioteca (`stale`). Las corridas leídas antes de que existiera este archivo se juzgan por
fecha.

## `runs/batch_report.csv` — una fila por corrida del lote

| columnas | contenido |
|---|---|
| `run`, `frames` | corrida y fotogramas extraídos |
| `qc_dark`, `qc_blown`, `qc_blur`, `qc_low_contrast`, `qc_occluded`, `qc_blank`, `qc_camera_moved`, `qc_roi_outside` | descartes antes de leer, por motivo |
| `ok`, `low_confidence`, `spike` | resultado de la lectura (de `readings.csv`) |
| `coverage` | `ok` / `frames` |
| `test_kind`, `test` | tipo de prueba (`same_run` u `other_video`) y cantidad de muestras |
| `accuracy`, `accepted_error` | exactitud y error entre aceptadas sobre `test.csv`, con la biblioteca vigente |
| `templates`, `fingerprint` | tamaño y huella de la biblioteca |
| `outputs` | `up_to_date`, `stale`, `no_fingerprint` o `no_reading` |
| `verdict`, `detail` | `accept` / `review` y el motivo; vacíos si no hay umbrales |

Las fracciones van entre 0 y 1 con 4 decimales. La tabla que imprime `batch` (y `teach test eval`
sin corrida) es la misma, resumida.

## Salidas de `teach`

| archivo | columnas y contenido |
|---|---|
| `runs/<id>/truth.csv`, `runs/<id>/test.csv` | `file,value`: muestras de entrenamiento / de prueba (el valor es texto) |
| `out/teach_report.csv` | `file,typed,read_value,confidence,status,matches,missing`: leave-one-out de las muestras de entrenamiento |
| `out/test_report.csv` | `file,typed,read_value,status,confidence,result`: una fila por fotograma de prueba; `result` es `correct`, `wrong` o `discarded` |
| `out/teach_history.csv` | `date,kind,templates,training,test,distinct_values,correct,wrong,discarded,accuracy,accepted_error,coverage,fingerprint`: una fila por `teach test eval <id>` |

## Archivos de versiones anteriores

Hasta octubre de 2026 los archivos se escribían con nombres en español (`absorbancia.csv`,
encabezados `archivo,valor`, `confianza`, `estado`…, estados como `roi_fuera`, tipos como
`misma_corrida`, claves `min_exactitud`). **Siguen cargando**: los lectores traducen los nombres
viejos a los nuevos (un único mapa de equivalencias, `src/spectro/compat.py`) y los escritores
emiten siempre los nuevos. Ningún archivo se reescribe solo por leerlo; `absorbancia.csv` se lee
como respaldo y nunca se borra (la próxima `report` escribe `absorbance.csv` al lado). La excepción
es `teach_history.csv`: la próxima evaluación lo reescribe con el encabezado nuevo, conservando
las filas.

Un ejemplo real: `runs/img_8102/out/teach_history.csv` todavía empieza con
`fecha,tipo,plantillas,…` y dice `misma_corrida`, y `teach test history img_8102` lo muestra así
(11-oct-2026):

```
  fecha               tipo           plant. entren. prueba correctas erroneas descart.  exact.  error  cobert.  cambio
  2026-10-09 18:38:26 same_run           43      30     20        19        1        0   95.0%   5.0%   100.0%
```

Los flags `--min-exactitud` y `--min-cobertura` pasaron a `--min-accuracy` y `--min-coverage`; los
viejos fallan mostrando la tabla de migración.

---

**Siguiente paso:** dónde vive cada uno de estos archivos y qué se comparte entre corridas, en
[carpetas](carpetas.md).
