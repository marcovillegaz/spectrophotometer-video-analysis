# Arquitectura

Documento de diseño: cómo está armado el pipeline, qué hace cada módulo, qué contrato hay entre
etapas y **por qué** cada decisión es la que es. Para *usar* el proyecto, mirá el
[`README.md`](../README.md); para el detalle de cada campo de configuración,
[`CONFIG.md`](CONFIG.md).

## El problema

Un espectrofotómetro UV/VIS con celda de flujo continuo, sin software de adquisición. La única
salida es su pantalla LCD. Se filmaron 20:03 min de pantalla con un teléfono en soporte fijo
(1920×1080, HEVC, 29.97 fps, 36 059 fotogramas, 1.17 GB) y hay que convertir eso en una serie
temporal de absorbancia.

Tres condiciones del problema mandan sobre todo el diseño:

1. **La cámara está fija.** Entonces la región del número es la misma en todos los fotogramas: se
   define una vez y se reusa.
2. **La tipografía es constante y el formato del número es fijo** (`0.597`). Entonces cada dígito
   se ve siempre exactamente igual, y "OCR" es en realidad un problema de clasificación entre 11
   glifos conocidos.
3. **Es un instrumento de medición.** Un valor equivocado en el CSV es peor que un valor faltante:
   contamina el análisis sin dejar rastro. Todo el pipeline está sesgado a descartar antes que a
   adivinar.

## El pipeline

```
 videos/…_iOS.MOV            runs/<id>/config.json        calib/templates/
            │                    (calibrate)                (templates)
            │                         │                          │
            ▼                         ▼                          │
    ┌───────────────┐          ROI, slots, umbrales,             │
    │    extract    │          offset de tiempo                  │
    └───────┬───────┘                 │                          │
            │  runs/<id>/frames/t_0000601.000.jpg                │
            │  runs/<id>/frames_index.csv                        │
            ▼                         │                          │
    ┌───────────────┐  ◄──────────────┘                          │
    │      qc       │  mide sobre la ROI + re-registra           │
    └───────┬───────┘                                             │
            │  runs/<id>/out/qc_report.csv  (métricas, dx, dy, estado)
            ▼                                                     │
    ┌───────────────┐  ◄────────────────────────────────────────┘
    │     read      │  NCC por slot -> caracteres -> valor
    └───────┬───────┘
            │  runs/<id>/out/readings.csv   (incluye las descartadas)
            │  qc_report.csv                (estado actualizado)
            ▼
    ┌───────────────┐
    │    report     │
    └───────┬───────┘
            │  runs/<id>/out/absorbancia.csv   <- el entregable
            │  runs/<id>/out/preview.png       <- la curva
            │  runs/<id>/out/contact_sheet.png <- las 40 lecturas menos confiables
            ▼
```

Cada etapa es un subcomando independiente que lee de disco y escribe a disco. Se puede volver a
correr `read` sin re-extraer, o `report` con otro `offset_s` sin re-leer. Es deliberado: la
decodificación del video es lo caro (~3 min) y ajustar parámetros es lo frecuente.

## Layout de datos

La cámara **se re-monta en cada sesión**. El encuadre cambia entre videos, pero el equipo y la
fuente del display son los mismos. Ese único hecho es el que define el layout: parte los datos en
lo que se comparte y lo que es propio de cada corrida.

```
videos/         entradas, gitignored
calib/          la receta: config.json + reference.jpg + templates/
runs/<id>/      una corrida: config.json + frames/ + frames_index.csv + out/
```

**Por qué `calib/` separada de `runs/`.** La alternativa obvia —un `config.json` por corrida, con
todo adentro— obliga a re-etiquetar los glifos en cada video, que es el único paso verdaderamente
manual del pipeline (~40 teclas). Los glifos no cambian: el display es el mismo equipo. Poner la
biblioteca y la geometría del número en `calib/` las convierte en un activo que se construye una
vez. La alternativa opuesta —un solo `config.json` global— no funciona porque la ROI **sí** cambia
en cada montaje, y una ROI de otra sesión recorta al lado de los dígitos.

**Por qué `runs/<id>/` aislados.** Cada corrida es un experimento distinto con su propio libro
mayor. Que `qc_report.csv` y `absorbancia.csv` vivan dentro de la corrida hace imposible pisar los
resultados de un video con los de otro, que es el modo de falla que de verdad importa en datos de
laboratorio: silencioso y difícil de detectar después. Por la misma razón, un subcomando de etapa
sin `--run` **falla listando las corridas** en vez de elegir una.

**El id sale del video, no de un contador.** `20260901_164220000_iOS.MOV` → `20260901_164220`. Es
derivable, ordena cronológicamente y no necesita ningún registro central que mantener sincronizado
con el disco. `project.py` es el único módulo que sabe dónde va cada cosa; todo lo demás recibe
las rutas ya resueltas por parámetro.

Se versionan `calib/`, `runs/*/config.json` y `runs/*/out/` — la receta y los resultados. No se
versionan `videos/` ni `runs/*/frames/`: son pesados (~690 MB por video) y regenerables.

### `calibrate --auto`: el re-registro, aplicado entre sesiones

`qc` ya registra cada fotograma contra el fotograma de referencia de su corrida, para compensar la
deriva lenta de la cámara a lo largo de 20 minutos. `calibrate --auto` es **la misma operación con
otro alcance**: en vez de comparar dos fotogramas de la misma sesión, compara el fotograma de
referencia de la corrida nueva contra `calib/reference.jpg`, de otra sesión.

1. Toma el ancla y la ROI de referencia de `calib/config.json`, en coordenadas de
   `calib/reference.jpg`.
2. Busca ese parche de ancla en el fotograma de la corrida nueva con `estimate_shift`, con margen
   amplio (`--search-px`, default 200 px, bastante mayor que los 40 px del registro
   intra-corrida: entre sesiones el teléfono se re-monta y el encuadre salta de verdad).
3. Si `score >= --min-score` (default 0.6), corre ROI y ancla por `(dx, dy)` y las guarda en el
   config de la corrida.
4. Si no, **no inventa una ROI**: avisa y pide `calibrate` manual para esa corrida.

**Limitación: corrige traslación, no rotación ni escala.** Si el teléfono quedó a otra distancia o
inclinado, no existe un `(dx, dy)` que arregle eso, y el score cae por debajo del umbral. Que caiga
en el camino manual es el comportamiento correcto, no una carencia: una ROI rotada recortaría
medio dígito y produciría lecturas plausibles pero equivocadas. Por eso la función también se
niega cuando la resolución del fotograma no coincide con la de la referencia, y cuando el
corrimiento sacaría la ROI fuera del fotograma.

Es lo que hace viable `batch`: sin `--auto`, procesar diez videos son diez sesiones interactivas
con `cv2.selectROI`.

## Módulos

| archivo | responsabilidad | interfaz pública |
|---|---|---|
| `cli.py` | argparse con un subcomando por etapa; `resolve_paths` convierte `--run <id>` en las ocho rutas; importa los módulos de forma perezosa para que `doctor` funcione aunque falte una dependencia | `main(argv)`, `build_parser()`, `resolve_paths(args)` |
| `project.py` | el layout como código: id de corrida, rutas de `calib/` y `runs/<id>/`, siembra de configs | `run_id_from_video`, `RunPaths`, `CalibPaths`, `list_runs`, `seed_run_config`, `calib_recipe` |
| `config.py` | esquema único de `config.json` como dataclasses anidadas | `Config.load/save/default`, `ROI`, `DigitsConfig`, … |
| `extract.py` | resolución de ffmpeg, metadatos, video → fotogramas, convención de nombres | `resolve_ffmpeg`, `probe_video`, `extract_frames`, `frame_name`, `time_from_name` |
| `imaging.py` | primitivas de imagen compartidas: recorte, binarización, slots, NCC, hash, registro | `binarize`, `slot_boxes`, `normalize_glyph`, `ncc`, `phash`, `estimate_shift`, `auto_anchor` |
| `calibrate.py` | ROI, slots y polaridad → `runs/<id>/config.json`; interactivo, por flags o por registro contra `calib/reference.jpg` | `calibrate(args)`, `auto_calibrate(args)`, `refine_roi`, `pick_reference_frame` |
| `templates.py` | muestreo, agrupamiento por hash y etiquetado de glifos → `calib/templates/` (compartida) | `build_library(args)`, `collect_glyphs`, `load_templates` |
| `qc.py` | métricas de calidad sobre la ROI, re-registro, umbrales automáticos | `run_qc`, `measure`, `classify`, `suggest_thresholds`, `load/write_qc_report` |
| `read.py` | NCC contra la biblioteca → caracteres → valor; chequeos de confianza y de plausibilidad | `run_read`, `read_frame`, `match_slot`, `assemble`, `flag_spikes` |
| `report.py` | CSV final, gráfico y hoja de contacto; cuadre de conteos | `run_report`, `write_absorbance_csv`, `plot_preview` |

`imaging.py` no estaba en el plan original y se agregó al implementar: `qc`, `templates` y `read`
tienen que binarizar y recortar **exactamente igual**, porque si la binarización con la que se
construye una plantilla difiere de la que se usa para compararla, la correlación cae sin motivo
aparente. Tener una sola implementación compartida hace que eso no pueda pasar.

## Contratos de datos entre etapas

**Nombre de fotograma — `t_0000601.000.jpg`.** Segundos desde el inicio del video, 7 dígitos
enteros y 3 decimales. Cumple el requisito de que el nombre refleje el tiempo, y como el ancho es
fijo, **el orden alfabético es el orden temporal**: cualquier `sorted(glob(...))` queda ordenado en
el tiempo sin parsear nada. `frame_name` y `time_from_name` son inversas exactas y hay un test que
lo verifica a varios `--fps`.

**`runs/<id>/frames_index.csv`** — `archivo, t_s, indice`. Es redundante con los nombres a propósito:
si se pierde, `index_from_dir()` lo reconstruye leyendo los nombres.

**`calib/templates/<caracter>_<n>.png`** — glifos binarizados y normalizados a 24×40. El punto
decimal se guarda como `dot_0.png` porque un `.` no puede ir en el nombre. Se admiten varias
plantillas por dígito: `0_0.png` … `0_5.png` son todas cero.

**`runs/<id>/out/qc_report.csv`** — el **libro mayor**: un renglón por fotograma extraído, siempre.
`qc` lo crea con las métricas y el estado inicial; `read` le actualiza la columna `estado` con el
resultado de la lectura; `report` lo usa para el cuadre de conteos. Que exista un solo lugar donde
está el destino de cada fotograma es lo que permite garantizar que no se pierda ninguno en
silencio.

**`runs/<id>/out/readings.csv`** — todas las lecturas, incluidas las descartadas, con los caracteres
crudos que se leyeron. Es lo que se mira cuando una lectura sospechosa hay que rastrearla.

## Decisiones de diseño

### Template matching, y no Tesseract ni un VLM

| alternativa | por qué se descartó |
|---|---|
| **Tesseract** | Está entrenado para texto impreso; con dígitos de LCD de siete u once segmentos confunde 8/B, 0/O, 1/7 sistemáticamente. Además obliga a instalar un binario a nivel de sistema, que era una restricción explícita del proyecto. |
| **Un VLM por API** | Costo por fotograma, dependencia de red, y sobre todo **no es determinista**: el mismo fotograma puede dar dos respuestas distintas, y no hay forma de auditar por qué. Inaceptable para datos de laboratorio. |
| **Una CNN entrenada** | Habría que etiquetar cientos de ejemplos para resolver un problema que con cámara fija ya es trivial. |
| **Template matching (elegido)** | Determinista, sin dependencias externas, ~100 % de precisión en los fotogramas que pasan el filtro, y el trabajo manual es etiquetar ~40 glifos únicos una sola vez. Da además un score de confianza natural (la NCC). |

La condición para que funcione es que la cámara esté fija y la tipografía sea constante — y las
dos se cumplen. Si dejaran de cumplirse, la sección "Cómo extenderlo" dice qué cambiar.

### La ROI se calibra una vez, y se re-registra en cada fotograma

Con cámara fija, la ROI fija alcanza *en teoría*. En la práctica, medir el corrimiento de este
video mostró una **deriva lenta de hasta 3 px en 20 minutos** — el soporte cede, alguien roza la
mesa. Sobre una ROI de 48 px de alto eso empieza a comerse los dígitos.

La solución es el **re-registro**: `qc` busca un parche de referencia (el ancla) en cada fotograma
por template matching, obtiene el corrimiento `(dx, dy)`, lo escribe en `qc_report.csv`, y `read`
mueve la ROI por ese corrimiento antes de recortar. La ROI sigue a la escena en vez de quedarse
clavada en coordenadas absolutas.

El ancla se elige automáticamente (`auto_anchor`) como la ventana con **máxima energía de
gradiente fuera de la vecindad del número**. Que tenga bordes es esencial: un parche de fondo liso
da una NCC ruidosa y "detecta" movimiento donde no lo hay. En este video eligió sola la serigrafía
`UV/VIS SPECTROPHOTOMETER` del gabinete, que es lo más estático y contrastado del cuadro.

Antes de implementar esto, 215 de 1203 fotogramas se marcaban como `camera_moved`. Con re-registro,
los 1203 pasan y la deriva queda medida y compensada.

### El punto decimal se asume, no se lee

El formato es fijo (`0.597`), así que el valor se arma con `decimal_after` de la configuración. El
punto **sí se lee**, pero sólo como **control de alineación**: es el glifo más chico y el más fácil
de confundir, y si el slot del separador no matchea un punto, es señal de que la ROI no está donde
debería y la lectura entera se descarta.

Detalle que sorprende y conviene tener presente: la fuente del equipo es monoespaciada y **el punto
ocupa su propia celda de caracter**. Por eso `0.597` son **5 slots**, no 4, y el reparto uniforme
de la ROI en 5 partes cae perfecto sobre los caracteres.

### El QC mide sobre la ROI, no sobre el fotograma entero

Que la mitad de la mesa esté en penumbra, o que alguien pase por el fondo, no afecta la lectura.
Lo único que decide si un fotograma sirve es **cómo se ve el número**. Medir sobre el fotograma
completo generaría rechazos por cosas que no importan y, peor, dejaría pasar fotogramas donde el
display está velado pero el resto de la escena se ve bien.

Los umbrales se auto-sugieren de la distribución observada con **mediana ± 6·MAD**, no con media ±
k·σ: los fotogramas malos son justamente los outliers, y con σ ellos mismos inflarían el umbral que
debería rechazarlos. La MAD es insensible a eso.

### Las filas descartadas se omiten, no se interpolan

`absorbancia.csv` lleva sólo lecturas reales. Interpolar generaría datos que parecen medidos y no
lo son — en un análisis cinético eso es exactamente el tipo de error que no se detecta después. Un
hueco en la serie es información honesta: dice "acá no se pudo leer", y `qc_report.csv` dice por
qué, fotograma por fotograma. Quien quiera interpolar puede hacerlo en Excel, sabiendo que lo hizo.

El **cuadre de conteos** al final de `report` verifica que
`filas(absorbancia.csv) + descartadas(qc_report.csv) = fotogramas extraídos`. Si alguna vez no
cuadra, se perdió un fotograma en silencio y hay un bug.

### La confianza se mide con margen, no sólo con score

Aceptar un dígito por tener NCC alta no alcanza: un `8` degradado puede correlacionar 0.85 con la
plantilla del `8` **y** 0.84 con la del `6`. Por eso se exige además un **margen** contra la mejor
plantilla de una etiqueta *distinta* (`min_margin`). El margen se calcula entre etiquetas, no entre
plantillas, para que tener seis plantillas del `0` no penalice la confianza del `0`.

### Un spike aislado es un dígito mal leído

Después de leer todo, `flag_spikes` marca los puntos que se despegan de **ambos** vecinos por
encima de `max_rate`, **y** cuyos vecinos son coherentes entre sí. La segunda condición es la que
evita descartar una transición real y rápida del experimento: una transición verdadera se sostiene
en el tiempo, un dígito mal leído vuelve solo al valor anterior en la muestra siguiente.

### El binario de ffmpeg se resuelve en runtime

`resolve_ffmpeg()` prueba el PATH del sistema y cae a `imageio-ffmpeg` (que vive en el venv). Nada
queda cableado: si la instalación de ffmpeg falla o se pospone, el pipeline sigue funcionando sin
tocar una línea de código, sólo más lento y leyendo los metadatos del stderr en vez de con ffprobe.
`extract` informa en su salida qué binario y versión usó, así queda en el log de la corrida.

### La frecuencia de muestreo es un parámetro, y no es gratis elegirla mal

El dígito menos significativo del display se redibuja varias veces por segundo. A 1 Hz, **el 59 %
de los fotogramas lo agarra a mitad del refresco** y queda ilegible — y descartarlos es lo correcto,
porque en esos fotogramas el dígito genuinamente no se puede determinar. A 4 Hz, aunque el
porcentaje de fotogramas legibles por separado es parecido (44 %), **la serie final cubre el 86 %
de los 1203 segundos** del video, contra el 41 % que daba 1 Hz. La densidad de la serie se
recupera muestreando más, no aflojando los umbrales.

Y aflojarlos no serviría: midiendo la desviación de cada punto respecto de la mediana de sus
vecinos (± 2 s), las lecturas de confianza 0.60–0.65 se desvían **lo mismo** (mediana 0.002 Abs,
p95 0.011) que las de confianza > 0.80. El umbral de confianza gobierna cuántos datos hay, no cuán
buenos son — lo cual es la señal de que está bien calibrado.

## Cómo extenderlo

**Si cambia el display o el formato del número.** Volvé a correr `calibrate` (nueva ROI, nuevo
`n_digits`, nuevo `decimal_after`) y `templates` (nueva biblioteca) sobre una corrida
representativa, y promové el resultado con `calibrate --promote`. Ni una línea de código: el
lector no sabe nada del equipo, todo está en `calib/config.json` y en `calib/templates/`.

**Si el display fuera de siete segmentos con los dígitos pegados** — o si por cualquier motivo el
reparto uniforme de slots no cae bien — están los cortes manuales: `calibrate --splits
0,26,52,78,104,127`. Si ni eso alcanza porque los caracteres se tocan, el próximo paso es
segmentación por componentes conexas dentro de `slot_boxes`, que es el único punto que habría que
tocar.

**Si aparece un segundo número en pantalla** (%T, longitud de onda, temperatura): hoy `Config`
tiene una sola `roi`. La extensión natural es pasar `roi`/`digits` a una lista de "campos", con
`read_frame` devolviendo un valor por campo y `report` escribiendo una columna por campo. Las
funciones de `imaging.py` y `read.py` ya trabajan sobre una ROI recibida por parámetro, así que el
cambio queda contenido en `config.py`, en los bucles de `read.py`/`report.py` y en `calibrate.py`.

**Si la cámara deja de estar fija** (video a mano alzada). El re-registro por template matching ya
resuelve traslaciones de hasta `max_shift_px`. Para rotación o escala haría falta reemplazar
`estimate_shift` por una estimación de homografía (`cv2.findTransformECC` o detección de features
+ `estimateAffinePartial2D`) y aplicar el warp antes de recortar. El resto del pipeline no se
entera: sigue recibiendo una ROI ya alineada.

**Procesar varios videos en lote** ya está resuelto: `batch` encadena
`new → extract → calibrate --auto → qc → read → report` por cada video, saltea las corridas
terminadas y deja pendientes las que no engancharon la calibración automática. Lo que
deliberadamente **no** hace es un CSV combinado ni un índice de corridas: no hacían falta, y un
índice sería estado global que se desincroniza del disco. Si más adelante hacen falta, el lugar es
un subcomando nuevo que lea `list_runs()`, no un archivo que haya que mantener.
