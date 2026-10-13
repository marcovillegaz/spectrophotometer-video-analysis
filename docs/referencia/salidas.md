# Formato de salida

**Para quién y cuándo leerlo:** para cuando abrís un CSV de `runs/<id>/out/`, `teach/` o `test/`
(o uno de los reportes de `runs/`) y querés saber qué significa cada columna y cada estado, o vas a
escribir un script que lo lea. Dónde vive cada archivo está en [carpetas](carpetas.md). Cómo abrir
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
| `accuracy`, `accepted_error` | exactitud y error entre aceptadas sobre `test/test.csv`, con la biblioteca vigente |
| `templates`, `fingerprint` | tamaño y huella de la biblioteca |
| `outputs` | `up_to_date`, `stale`, `no_fingerprint` o `no_reading` |
| `verdict`, `detail` | `accept` / `review` y el motivo; vacíos si no hay umbrales |

Las fracciones van entre 0 y 1 con 4 decimales. La tabla que imprime `batch` (y `teach test eval`
sin corrida) es la misma, resumida.

## `runs/summary.csv`, `runs/summary_chars.csv` y `runs/summary.html` — la efectividad de todas las corridas

Los escribe [`summary`](comandos.md#summary--cuánto-acierta-el-lector-en-todas-las-corridas), y los
reescribe completos cada vez. Cómo leerlos y por qué la fila `TOTAL` mide lo que mide, en la
[guía](../calibrar/guia.md#todas-las-corridas-a-la-vez--summary).

**`summary.csv`** tiene una fila por corrida y, al final, una fila `TOTAL`:

| columnas | contenido |
|---|---|
| `run`, `frames` | corrida y fotogramas extraídos |
| `qc_dark` … `qc_roi_outside` | descartes antes de leer, por motivo (los mismos 8 de `batch_report.csv`) |
| `ok`, `low_confidence`, `spike` | resultado de la lectura (de `readings.csv`); vacíos si la corrida no se leyó |
| `coverage` | `ok` / `frames` |
| `longest_hole_s`, `holes` | el hueco más largo, en segundos, entre lecturas válidas consecutivas (el primer y el último fotograma leídos cuentan como bordes), y cuántos huecos superan `--hole` |
| `test_kind`, `test` | tipo de prueba (`same_run` u `other_video`) y cantidad de muestras |
| `correct`, `wrong`, `discarded` | la prueba, fotograma por fotograma, con la biblioteca vigente |
| `accuracy`, `accuracy_lo`, `accuracy_hi` | exactitud (`correct` / `test`) y su intervalo de Wilson al 95 % |
| `accepted_error` | error entre las aceptadas: `wrong` / (`correct` + `wrong`) |
| `loo_exact`, `loo_total` | leave-one-out de las muestras de entrenamiento: leídas bien / total |
| `evals`, `accuracy_first`, `accuracy_last` | cuántas filas tiene `teach_history.csv` y la exactitud de la primera y de la última |
| `eval_current` | `yes` si la última evaluación se hizo con la biblioteca de hoy (misma huella), `no` si no, vacío si no se sabe |
| `outputs` | `up_to_date`, `stale`, `no_fingerprint` o `no_reading` |
| `verdict`, `detail` | `accept` / `review` y el motivo; vacíos si no hay umbrales |

La fila **`TOTAL`** no es un promedio de las filas de arriba:

* `frames`, los descartes, `ok` y `coverage` suman **solo las corridas que tienen `readings.csv`**:
  una corrida sin leer no tiene cobertura que aportar.
* La prueba junta las de todas las corridas, pero de **un solo tipo**: `other_video` si alguna
  corrida lo tiene y, si no, `same_run`. `test_kind` dice cuál se usó (y la consola lo repite).
* `longest_hole_s` es el máximo de las corridas y `holes`, la suma.
* `loo_exact` y `loo_total` son los del leave-one-out conjunto de todas las corridas.
* `outputs` es **el peor** estado de las corridas (`stale` gana sobre `no_reading`, este sobre
  `no_fingerprint` y este sobre `up_to_date`).
* Las columnas de tendencia quedan vacías.

**`summary_chars.csv`** tiene una fila por carácter:

| columna | contenido |
|---|---|
| `char` | el carácter (`0`-`9`, `.`, `-`) |
| `test_cells`, `test_errors` | celdas de ese carácter en la prueba y cuántas se leyeron como otro |
| `loo_cells`, `loo_errors` | lo mismo en el leave-one-out de las muestras de entrenamiento |
| `top_confusions` | las tres confusiones más frecuentes, prueba y leave-one-out juntas: `'6'->'5' x1; ...` |

Un carácter con `test_cells` en 0 no aparece en ninguna prueba: no se sabe cómo lo lee el lector.

**`summary.html`** es una sola página, sin archivos aparte (los gráficos van incrustados): las
mismas cinco secciones de la consola, más la exactitud por evaluación de cada corrida, el mapa de
confusiones, la cobertura por corrida y el histograma de confianza de todas las lecturas.
`--no-html` no la escribe.

## Salidas de `teach`

| archivo | columnas y contenido |
|---|---|
| `teach/truth.csv`, `test/test.csv` | `file,value`: muestras de entrenamiento / de prueba (el valor es texto) |
| `teach/rejected.csv` | `file,set,date`: fotogramas descartados al etiquetar; `set` es `train` o `test` (de qué conjunto se descartó). Solo lo lee el etiquetado: `read`, `qc`, `train`, `check`, `test eval` y `batch` lo ignoran |
| `teach/teach_report.csv` | `file,typed,read_value,confidence,status,matches,missing`: leave-one-out de las muestras de entrenamiento |
| `test/test_report.csv` | `file,typed,read_value,status,confidence,result`: una fila por fotograma de prueba; `result` es `correct`, `wrong` o `discarded` |
| `test/teach_history.csv` | `date,kind,templates,training,test,distinct_values,correct,wrong,discarded,accuracy,accepted_error,coverage,fingerprint`: una fila por `teach test eval <id>` |

Las rutas son relativas a `runs/<id>/`. Las corridas con el layout anterior (estos archivos sueltos
en `runs/<id>/` o dentro de `out/`) se mudan solas al primer uso: ver
[carpetas](carpetas.md#corridas-con-el-layout-anterior).

## Archivos de versiones anteriores

Hasta octubre de 2026 los archivos se escribían con nombres en español (`absorbancia.csv`,
encabezados `archivo,valor`, `confianza`, `estado`…, estados como `roi_fuera`, tipos como
`misma_corrida`, claves `min_exactitud`). **Siguen cargando**: los lectores traducen los nombres
viejos a los nuevos (un único mapa de equivalencias, `src/spectro/compat.py`) y los escritores
emiten siempre los nuevos. Ningún archivo se reescribe solo por leerlo; `absorbancia.csv` se lee
como respaldo y nunca se borra (la próxima `report` escribe `absorbance.csv` al lado). La excepción
es `teach_history.csv`: la próxima evaluación lo reescribe con el encabezado nuevo, conservando
las filas. Los archivos de entrenamiento y de prueba que estaban en la ubicación anterior se
**mueven** (sin cambiar su contenido) a `teach/` y `test/`: ver
[carpetas](carpetas.md#corridas-con-el-layout-anterior).

Un ejemplo real: el 11-oct-2026, el `teach_history.csv` de `img_8102` (entonces en `out/`) todavía
empezaba con `fecha,tipo,plantillas,…` y decía `misma_corrida`, y `teach test history img_8102` lo
mostraba así:

```
  fecha               tipo           plant. entren. prueba correctas erroneas descart.  exact.  error  cobert.  cambio
  2026-10-09 18:38:26 same_run           43      30     20        19        1        0   95.0%   5.0%   100.0%
```

Ese historial ya no se puede reproducir: el 13-oct-2026 `img_8102` no tenía prueba ni carpeta
`test/`.

Los flags `--min-exactitud` y `--min-cobertura` pasaron a `--min-accuracy` y `--min-coverage`; los
viejos fallan mostrando la tabla de migración.

---

**Siguiente paso:** dónde vive cada uno de estos archivos y qué se comparte entre corridas, en
[carpetas](carpetas.md).
