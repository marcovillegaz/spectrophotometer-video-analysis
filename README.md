# spectro — absorbancia desde el video del espectrofotómetro

El espectrofotómetro UV/VIS con celda de flujo continuo del laboratorio no tiene software de
adquisición. El experimento se registró **filmando la pantalla del equipo** con un teléfono en
soporte fijo. Este proyecto convierte ese video en una **serie temporal de absorbancia vs
tiempo en CSV**, lista para Excel o para otros scripts.

```
video de la pantalla  ->  extract  ->  qc  ->  read  ->  report  ->  absorbance.csv
                                               ^
                  teach (etiquetar, armar la biblioteca y medirla)
```

La lectura del número es **comparación contra plantillas** (_template matching_) por carácter:
100 % local, sin API, sin Tesseract y determinista — el mismo fotograma da siempre el mismo
resultado. Cada lectura lleva un puntaje de confianza, y **los fotogramas dudosos se descartan en
vez de inventar un valor**. El porqué de cada decisión está en
[`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md); cómo enseñarle al lector un equipo nuevo y cuánto
confiar en él, en la [guía de calibración](docs/GUIA_CALIBRACION.md).

---

## Requisitos del sistema

**Python 3.11 o superior** (probado con 3.13.6) y, recomendado, **ffmpeg**:

```powershell
winget install Gyan.FFmpeg     # ffmpeg 9.0.1 + ffprobe
# cerrar y reabrir la terminal para que tome el PATH
ffprobe -version               # verificación
```

ffmpeg es **recomendado, no obligatorio**. Si no está en el PATH, el proyecto cae automáticamente
al binario de `imageio-ffmpeg`, que vive dentro del venv y se instala con las dependencias. Lo que
se pierde en ese caso:

| con ffmpeg del sistema | con el respaldo del venv |
|---|---|
| `ffprobe` da los metadatos como JSON limpio | se parsean del stderr de ffmpeg, más frágil |
| aceleración por hardware (`d3d11va`, `qsv`, …) | decodificación por software, más lenta |
| ffmpeg 9.x | ffmpeg ~6.x empaquetado |

`python -m spectro doctor` informa cuál de los dos está usando.

**No hace falta instalar nada más a nivel de sistema.** OpenCV viaja dentro del venv (`pip`),
y **Tesseract no se usa**: el lector es propio.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .                  # deja disponible `python -m spectro` desde cualquier lado
python -m spectro doctor          # verificación del bootstrap
```

`doctor` debe terminar en `Estado: listo` y reportar `origen    : system` en la sección de ffmpeg.
Si reporta `imageio-ffmpeg`, el PATH todavía no tomó el `winget install`: cerrá y reabrí la
terminal.

---

## Estructura de carpetas

La cámara se re-monta en cada sesión: el encuadre cambia entre videos, pero el equipo y el
display son los mismos. Eso parte los datos en dos mitades limpias — una **receta compartida** y
una **corrida aislada por video**:

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
[`docs/CONFIG.md`](docs/CONFIG.md).

Se versionan `calib/` (salvo `.backups/`), `runs/*/config.json`, las muestras y `runs/*/out/`.
No se versionan `videos/` ni `runs/*/frames/`, que son pesados y regenerables.

El **id de corrida** sale del nombre del video: `IMG_8102.MOV` → `img_8102` (minúsculas, y lo que
no es letra ni número pasa a `_`). Los videos de iPhone con fecha en el nombre usan otra regla:
`AAAAMMDD_HHMMSSmmm_iOS.MOV` → `AAAAMMDD_HHMMSS` (fecha y hora, sin los milisegundos). `--name`
lo reemplaza.

---

## Quickstart — de un video al CSV

Ninguna etapa lleva rutas a mano: **`--run <id>` las deriva todas** desde el layout de arriba.
El ejemplo usa el video `videos/IMG_8102.MOV`, cuya corrida es `img_8102`.

```powershell
# 1. Dar de alta la corrida (crea runs/img_8102/ y hereda la receta de calib/)
python -m spectro new videos/IMG_8102.MOV --fps 4

# 2. Extraer los fotogramas -> runs/img_8102/frames/ + frames_index.csv
python -m spectro extract --run img_8102

# 3. Calibrar el encuadre de ESTA sesión contra la referencia compartida
python -m spectro calibrate --run img_8102 --auto
#    Si el encuadre cambió demasiado, avisa y no inventa nada: calibrá a mano
#    sin --auto (ver "calibrate" más abajo)

# 4. qc -> read -> report sobre los fotogramas ya extraídos
python -m spectro run --run img_8102 --skip-extract
#    -> runs/img_8102/out/absorbance.csv, preview.png, qc_report.csv…
```

Si la corrida ya existe, `new` no la pisa (avisa y sale); `--force` la vuelve a sembrar desde
`calib/`.

Los pasos 1–4 en uno, para uno o varios videos:

```powershell
python -m spectro batch videos/*.MOV --fps 4
```

**Qué mirar.** `report` cierra con el **cuadre de conteos** (válidas + descartadas = extraídas) y
`[ok]`; si dice `[NO CUADRA]`, se perdió un fotograma y es un bug. `doctor` muestra una línea por
corrida con la salida que tiene:

```
Corridas (runs/): 4
  img_8102               calibrada      10817 fotogramas  absorbancia.csv video=IMG_8102.MOV
  img_8106               calibrada      17944 fotogramas  absorbancia.csv video=IMG_8106.MOV
  img_8110               calibrada       3824 fotogramas  absorbancia.csv video=IMG_8110.MOV
  img_8112               calibrada      10176 fotogramas  absorbancia.csv video=IMG_8112.MOV
```

(`doctor`, 11-oct-2026. Dice `absorbancia.csv` porque esas salidas son anteriores al cambio de
nombre a `absorbance.csv`; ver [Archivos de versiones anteriores](#archivos-de-versiones-anteriores).)

> **Pendiente:** la salida completa del paso 4 sobre `img_8102` (fotogramas que pasan QC, lecturas
> válidas, cobertura) se copia acá **después del entrenamiento final** de la biblioteca. Hoy a la
> biblioteca le falta la plantilla `-` y cualquier cifra de lectura de `img_8102`, que es casi toda
> negativa, no sería representativa.

**La primera vez** hay que sembrar `calib/`, porque todavía no hay receta que heredar: calibrá a
mano la primera corrida, etiquetá unos fotogramas, armá la biblioteca y promové el resultado.

```powershell
python -m spectro new videos/mi_primer_video.MOV --fps 4
python -m spectro extract --run <id>
python -m spectro calibrate --run <id>                 # UI: arrastrá el rectángulo (con lupa)
python -m spectro qc --run <id>                        # mide la deriva de cámara
python -m spectro teach samples label <id>             # escribí el valor de ~30 fotogramas
python -m spectro teach train <id>                     # arma calib/templates con esas muestras
python -m spectro calibrate --run <id> --promote       # sube ROI, ancla y fotograma a calib/
python -m spectro run --run <id> --skip-extract
```

Para re-procesar la misma corrida con otro `--fps` alcanza con repetir los pasos 2 y 4: la
calibración y las plantillas se reusan.

---

## Calibrar el lector (resumen)

Enseñarle al lector a leer un display nuevo es un ciclo corto que se repite: **etiquetar unas
muestras, armar la biblioteca, medirla con una prueba que nunca vio y volver a etiquetar donde
falla.** El proceso completo, con el fundamento de cada paso, un ejemplo resuelto y una tabla de
diagnóstico, está en la [guía de calibración por rondas](docs/GUIA_CALIBRACION.md).

---

## Referencia de comandos

Todos aceptan `--help` y los cuatro flags globales del layout, que pueden ir antes o después del
subcomando:

| flag global | default | qué hace |
|---|---|---|
| `--run <id>` | — | deriva config, fotogramas, índice y salidas de `runs/<id>/` (no se usa en `teach`) |
| `--runs-dir` | `runs` | carpeta que contiene las corridas |
| `--calib-dir` | `calib` | carpeta de la calibración compartida |
| `--config` | `runs/<run>/config.json` | config de la corrida (no se usa en `teach`) |

**Un flag explícito siempre le gana a lo derivado**, así que se puede apuntar una etapa a otra
carpeta sin dejar de usar `--run`. Si a un subcomando de etapa le falta `--run` y no le pasaste
las rutas a mano, falla listando las corridas disponibles: adivinar cuál es mezclaría dos
experimentos en silencio. Para **probar algo que escribe sin tocar los datos reales**, apuntá
`--calib-dir` (y `--runs-dir`) a una copia.

### `doctor`
Diagnóstico del entorno: versión de Python, si el venv está activo, paquetes instalados, qué
ffmpeg/ffprobe resolvió y qué aceleradores por hardware hay. Después lista el estado de `calib/`
(receta, `reference.jpg`, cuántas plantillas) y **una línea por corrida** con su estado de
calibración, cuántos fotogramas tiene y si ya produjo salida. Es la primera línea de
troubleshooting.

### `new` — dar de alta una corrida
```powershell
python -m spectro new videos/IMG_8102.MOV --fps 4
python -m spectro new videos/otro.MOV --name cinetica-fe-02
```
Crea `runs/<id>/`, siembra su `config.json` desde `calib/config.json` y registra el video con su
fps. **No toca el video ni lo copia**: la corrida lo referencia por ruta. Hereda geometría y
parámetros de matcheo; deja ROI, ancla y umbrales de QC sin fijar, que son de esta sesión.

| flag | default | qué hace |
|---|---|---|
| `--name` | derivado del video | id de la corrida |
| `--fps` | `1.0` | frecuencia de muestreo de esta corrida |
| `--force` | off | re-sembrar el `config.json` aunque la corrida ya exista |

### `extract` — video → fotogramas
```powershell
python -m spectro extract --run img_8102
```
| flag | default | qué hace |
|---|---|---|
| `--video` | el de `config.json` de la corrida | video de entrada |
| `--fps` | el de la corrida | frecuencia de muestreo en Hz |
| `--output` | `runs/<run>/frames` | carpeta destino |
| `--index` | `runs/<run>/frames_index.csv` | CSV de índice; `""` para no escribirlo |
| `--start` | `0` | segundo del video donde empezar |
| `--duration` | todo | segundos a extraer (para pruebas rápidas) |
| `--scale` | — | factor de escala, ej. `0.5` |
| `--jpeg-quality` | `2` | calidad JPEG de ffmpeg (2 mejor, 31 peor) |
| `--roi-only` | off | guarda sólo el recorte: ~2 KB/fotograma en vez de ~145 KB |
| `--no-clean` | off | no borrar los fotogramas previos |
| `--save-config` | off | guardar video y fps en el `config.json` de la corrida |

Los fotogramas se llaman **`t_0000601.000.jpg`**: segundos desde el inicio del video, con ceros
a la izquierda y 3 decimales, de modo que el orden alfabético sea el orden temporal.

> `--roi-only` ahorra disco pero **desactiva el re-registro**: al no guardar el contexto alrededor
> del número, ya no hay ancla contra la cual medir la deriva de la cámara. Tampoco es compatible
> con una rotación (`rotation_deg`).

### `calibrate` — definir la ROI y los slots
```powershell
python -m spectro calibrate --run <id> --auto     # registra contra calib/reference.jpg
python -m spectro calibrate --run <id>            # interactivo
python -m spectro calibrate --run <id> --roi 754,706,127,48 --n-digits 5 --decimal-after 1 --no-refine
```
El encuadre es **propio de cada corrida**, así que esto se hace una vez por corrida.

**`--auto`** es lo que hace viable el lote: toma la ROI y el ancla de referencia de
`calib/config.json` (coordenadas de `calib/reference.jpg`), busca ese parche de ancla en el
fotograma de esta corrida con un margen amplio (`--search-px`, default 200) y corre la ROI por el
`(dx, dy)` que encuentra. Si la NCC no llega a `--min-score` (default 0.6), **no inventa una
ROI**: avisa que el encuadre cambió demasiado y pide calibrar a mano. Corrige **traslación, no
rotación ni escala** — si el teléfono quedó a otra distancia o inclinado, el score cae y cae en el
camino manual, que es el comportamiento correcto.

Sin `--auto` abre una **UI** con el fotograma a la izquierda y un **panel lateral** a la derecha.
Arrastrá un rectángulo (amarillo, para que contraste con el fondo azul) sobre el número; el resto
se maneja con botones:

| sección del panel | qué tiene |
|---|---|
| **Encuadre** | rotación (botones −1 / −.1 / +.1 / +1 y un slider con los grados reales) y guías horizontales para nivelar |
| **Número** | celdas de caracter, dígitos antes del punto, `Signo` (suma o quita la celda del signo) y `Ajustar a tinta` |
| **Datos** | ROI final, celdas, separador, signo, polaridad, tamaño de imagen y plantillas de `calib/` |
| **Vista previa** | la ROI binarizada con los cortes de slot, el carácter y el score de cada celda (verde si pasa `min_score`) y el valor leído |
| **Prueba** | lee 20 fotogramas repartidos por la corrida y resume cuántos son válidos, el rango y el motivo de descarte |
| **Lupa** | mientras el cursor está sobre el fotograma aparece una lupa (arriba a la izquierda, se pasa a la derecha si el cursor se acerca) con el recorte a resolución completa, la mira, la ROI y los cortes de slot, y la posición `x, y` del cursor. Los botones `-` / `+` de la fila de guías cambian el aumento (x4, x8, x12, x16) |
| botones de abajo | `Resetear`, `Cancelar`, `Guardar` |

La **vista previa usa el mismo lector que `read`** con la biblioteca de `calib/templates`: si ahí
dice `No se puede leer`, el pipeline tampoco va a poder (falta una plantilla, p. ej. el `-`, o la
ROI/celdas no calzan). Es preliminar: la prueba de 20 fotogramas no aplica el re-registro de cámara
que hace `qc`. Lo que guarda `Guardar` es la **ROI final** que muestra el panel.

Las teclas siguen como atajos: `q`/`e` y `a`/`d` rotan, `+`/`-` celdas, `[`/`]` punto, `s` signo,
`g` guías, `z`/`x` lupa, `p` probar, `r` resetear, `ENTER` guarda y `ESC` cancela. Los tres
caminos guardan la misma configuración en `runs/<id>/config.json` y dejan
`runs/<id>/out/calibracion.png` con el overlay dibujado para auditar el corte.

**Las celdas se cuentan incluyendo el punto**: en `0.597` la fuente es monoespaciada y el punto
ocupa su propia celda, así que son **5 slots**, no 4. Con signo, `-0.018` son 6. `calibrate`
detecta solo cuál es el slot del punto (el de menos tinta) y lo anota en `separator_slots`.

| flag | qué hace |
|---|---|
| `--auto` | calibrar por registro contra `calib/reference.jpg` |
| `--search-px` | margen de búsqueda del ancla en `--auto` (default 200) |
| `--min-score` | NCC mínima del ancla en `--auto` (default 0.6) |
| `--promote` | copiar ROI, ancla y fotograma de esta corrida a `calib/` como nueva referencia |
| `--frame` | fotograma a usar (default: el del medio de la carpeta de fotogramas) |
| `--frames-dir` | carpeta de fotogramas de donde tomar la muestra |
| `--roi x,y,w,h` | modo no interactivo, sin ventana gráfica |
| `--no-refine` | usar la ROI tal cual, sin ajustarla al bounding box de la tinta |
| `--n-digits`, `--decimal-after` | celdas y posición del punto, sin preguntar |
| `--splits` | cortes manuales, ej. `0,26,52,78,104,127` |
| `--separators` | índices de slot que son separadores; vacío para ninguno |
| `--anchor x,y,w,h` | ancla de registro manual (default: automática) |
| `--polarity` | `auto` (default), `light_on_dark`, `dark_on_light` |
| `--sign` | el display muestra signo: la celda de más a la izquierda es el signo (se cuenta en `--n-digits`) |
| `--rotate DEG` | rotar los fotogramas DEG grados (antihorario) para dejar el número horizontal |
| `--preview` | PNG con el overlay de ROI y slots (default: `out/calibracion.png`) |

### `qc` — filtro de calidad
```powershell
python -m spectro qc --run <id>
```
Mide cada fotograma **sobre la ROI** y escribe `runs/<id>/out/qc_report.csv`. Los umbrales se
auto-sugieren de la distribución observada (mediana ± 6·MAD) y quedan escritos en el
`config.json` de la corrida; con `--no-auto-thresholds` usa los que ya estén ahí. Un fotograma en
el que la ROI (corrida por la deriva medida) no entra queda `roi_outside`: se descarta, no aborta
la corrida.

### `read` — fotogramas → números
```powershell
python -m spectro read --run <id>
```
Escribe `runs/<id>/out/readings.csv` (todas las lecturas, incluidas las descartadas, con su
`confidence` y su `margin`), actualiza la columna `status` de `qc_report.csv` y deja
`out/read_meta.json` con la **huella** de la biblioteca con la que leyó (ver
[Formato de salida](#formato-de-salida)). Las plantillas salen de `calib/templates/`. Si la
geometría tiene celda de signo y la biblioteca no tiene la plantilla `-`, avisa una vez por
corrida: las lecturas negativas se van a descartar.

### `report` — salidas finales
```powershell
python -m spectro report --run <id>
```
Escribe `runs/<id>/out/absorbance.csv`, `preview.png` (la curva) y `contact_sheet.png` (los 40
recortes de menor confianza). Cierra con el **cuadre de conteos**: válidas + descartadas debe dar
exactamente los fotogramas extraídos. `--no-plots` deja sólo el CSV.

### `run` — pipeline completo
```powershell
python -m spectro run --run <id> --fps 4
python -m spectro run --run <id> --skip-extract      # reusar los fotogramas ya extraídos
```
Acepta los flags de `extract`, `qc`, `read` y `report`.

### `batch` — varios videos de punta a punta
```powershell
python -m spectro batch videos/*.MOV --fps 4
python -m spectro batch videos/*.MOV --fps 4 --until qc    # solo prepara el pool, sin leer
python -m spectro batch videos/*.MOV --fps 4 --min-accuracy 0.95 --min-coverage 0.8   # valores de ejemplo
```
Por cada video: `new --force` → `extract` → `calibrate --auto` → `qc` → `read` → `report`. Salta
las corridas que ya tienen `out/absorbance.csv` (o el `absorbancia.csv` de versiones anteriores);
`--no-skip-existing` las rehace. Si `calibrate --auto` no llega al score, **saltea esa corrida y
sigue con la siguiente**; al final lista las que quedaron pendientes de calibración manual, con el
comando listo para copiar.

Cuando llega hasta `report`, imprime y escribe **`runs/batch_report.csv`**: una fila por corrida
(las procesadas y las salteadas por estar hechas) con los descartes por motivo, la cobertura, la
evaluación de su `test.csv` con la biblioteca vigente y un **veredicto** `accept` / `review`. El
veredicto solo existe si hay umbrales: los flags de abajo o la sección `acceptance` de
`calib/config.json` ([CONFIG](docs/CONFIG.md#acceptance--criterio-del-lote--solo-en-calib)). **No
hay umbrales por defecto**: sin ellos el veredicto queda vacío y el comando lo avisa. Los valores
del ejemplo de arriba muestran la sintaxis; no son una recomendación.

| flag | default | qué hace |
|---|---|---|
| `--fps` | `1.0` | frecuencia de muestreo de todas las corridas del lote |
| `--until` | `report` | cortar después de `qc`, `read` o `report`. `qc` prepara los fotogramas sin leer: sirve antes de armar la biblioteca |
| `--skip-existing` / `--no-skip-existing` | saltear | saltear o re-procesar las corridas ya terminadas |
| `--search-px` | `200` | margen de búsqueda del ancla en `calibrate --auto` |
| `--min-score` | `0.6` | NCC mínima del ancla en `calibrate --auto` |
| `--min-accuracy` | `acceptance` | veredicto: exactitud mínima sobre `test.csv` (fracción, ej. `0.95`) |
| `--max-error` | `acceptance` | veredicto: error máximo entre las lecturas aceptadas de `test.csv` (fracción) |
| `--min-coverage` | `acceptance` | veredicto: cobertura mínima de la corrida, lecturas `ok` / fotogramas extraídos (fracción) |

Un flag le gana al valor de `acceptance`. Una corrida queda en `review` si no llega a un umbral,
si un umbral de la prueba no se puede verificar (no tiene `test.csv`), o si sus salidas no se
leyeron con la biblioteca vigente (`stale`, `no_fingerprint`, `no_reading`).

> **Cuidado:** `batch` re-siembra el `config.json` de cada corrida desde `calib/` (`new --force`).
> Si calibraste a mano una corrida que todavía no tiene salida, `batch` la pisa: para esas,
> corré las etapas sueltas.

### `teach` — entrenar y medir el lector

`teach` reúne todo lo que toca la biblioteca y las muestras. Se elige un **área** y un **verbo**, y
el **id de la corrida va como argumento**, completo (`img_8102`), nunca con `--run`:

```
teach status                                         panorama y siguiente paso
teach lib     list | delete | relabel | clear | backups | restore     la biblioteca GLOBAL
teach train   [RUN ...]                              arma la biblioteca desde las muestras
teach check   [RUN ...]                              valida las muestras sin escribir la biblioteca
teach samples list | add | remove | suggest | label  muestras de ENTRENAMIENTO (truth.csv)
teach test    list | add | remove | suggest | label | eval | history   muestras de PRUEBA (test.csv)
```

Cada área tiene su ayuda (`python -m spectro teach lib --help`, y lo mismo con las demás). La sintaxis anterior de `teach`
(un solo comando con flags de modo) ya no existe: si la usás, el comando falla y muestra la tabla
de migración, que también ves con:

```powershell
python -m spectro teach --help
```

**Para probar sobre una copia**, `--calib-dir` y `--runs-dir` funcionan igual que en el resto:

```powershell
python -m spectro teach train --calib-dir <copia_de_calib>
```

#### `teach status` — dónde estoy
```powershell
python -m spectro teach status
```
Muestra la biblioteca (plantillas por carácter, los caracteres que faltan, su **huella** y los
respaldos), una fila por corrida (muestras de entrenamiento y de prueba, estado de las salidas,
última evaluación), los descartes de qc por motivo y una lista de **siguientes pasos**. No escribe
nada. El estado de las salidas de cada corrida es:

| estado | significa |
|---|---|
| `up_to_date` | `readings.csv` se leyó con la biblioteca de hoy (misma huella) |
| `stale` | se leyó con otra biblioteca: hay que volver a correr `read` y `report` |
| `no_fingerprint` | no hay `read_meta.json` y no se puede saber con qué biblioteca se leyó |
| `no_reading` | la corrida todavía no tiene `readings.csv` |

#### `teach lib` — la biblioteca global (sin corrida)
```powershell
python -m spectro teach lib list                 # plantillas por carácter y los que faltan
python -m spectro teach lib list --usage         # cuántas celdas gana bien y mal cada plantilla
python -m spectro teach lib delete 0_3 5_1       # borrar plantillas por nombre
python -m spectro teach lib relabel 0_3 6        # cambiarle la etiqueta a una plantilla
python -m spectro teach lib clear --yes          # vaciarla (sin --yes, falla)
python -m spectro teach lib backups              # listar los respaldos
python -m spectro teach lib restore              # volver al último respaldo (o: restore <nombre>)
```
Las plantillas se llaman `<carácter>_<n>.png` (el punto es `dot_<n>`, el signo `minus_<n>`). Con
`--usage`, una plantilla que gana celdas de otro carácter sale marcada `DANINA` y una que no gana
ninguna, `sin uso`. Los borrados dejan huecos en la numeración (`0_0`, `0_2`), que es inofensivo.

**Respaldos.** Antes de cada cambio que borra algo (`train` sin `--keep`, `delete`, `relabel`,
`clear`, `restore`) la biblioteca se copia a `calib/.backups/<AAAAmmdd_HHMMSS>/` y se conservan
los **últimos 5**. `restore` respalda el estado actual antes de restaurar, así que también se
puede deshacer. La ventana de `teach` toma **un solo respaldo por sesión**, antes del primer
cambio a la biblioteca: borrar muchas plantillas seguidas en una sesión no rota los 5 respaldos ni
pierde el estado que había al abrirla. Los respaldos con otro nombre (hechos a mano) no se podan ni
aparecen en `backups`.

#### `teach train` y `teach check` — armar la biblioteca
```powershell
python -m spectro teach train                       # con las muestras de TODAS las corridas
python -m spectro teach train --exclude img_8112    # ...menos un video reservado como prueba
python -m spectro teach train img_8102 --keep       # suma las de una corrida, sin duplicar
python -m spectro teach check                       # solo valida, no escribe la biblioteca
```
`train` junta los `truth.csv` de las corridas elegidas (sin argumentos, todas las que tengan) y
**reemplaza** la biblioteca, respaldando la anterior; con `--keep` **suma** sin duplicar (descarta
los glifos casi idénticos a uno que ya está). Cada corrida se recorta con **su propia** config y su
corrimiento de cámara. Imprime la cobertura de `0-9 . -`, el leave-one-out por corrida y escribe
`runs/<id>/out/teach_report.csv`. **Los `test.csv` no se usan nunca.** `check` hace lo mismo sin
escribir la biblioteca (sí escribe los `teach_report.csv`).

> `teach train img_8102` **sin** `--keep` reemplaza la biblioteca compartida con las muestras de
> ese solo video: si ese video no tiene valores negativos, se pierde la plantilla `-`. Para eso
> está `teach lib restore`.

| flag | default | qué hace |
|---|---|---|
| `RUN …` | todas las que tengan `truth.csv` | corridas cuyas muestras se usan |
| `--exclude RUN …` | — | corridas que no entrenan (hold-out por video) |
| `--keep` | off | (`train`) sumar a la biblioteca en vez de reemplazarla |
| `--max-per-label` | `3` | (`train`) variantes máximas por carácter |
| `--gap SEGUNDOS` | `5` | avisar si una prueba está a menos de esto de un fotograma de entrenamiento |

#### `teach samples` y `teach test` — los dos conjuntos de una corrida

Son simétricos: `samples` maneja el **entrenamiento** (`runs/<id>/truth.csv`) y `test` la
**prueba** (`runs/<id>/test.csv`), que **nunca** entra a la biblioteca. Un fotograma está en un
solo conjunto: agregarlo a uno lo saca del otro (y si pasa de entrenamiento a prueba, avisa que ya
aportó glifos a la biblioteca).

```powershell
python -m spectro teach samples list                       # tabla de todas las corridas
python -m spectro teach samples list img_8102              # sus muestras y cuántas lee bien la biblioteca
python -m spectro teach samples suggest img_8102 30        # qué fotogramas etiquetar
python -m spectro teach samples label img_8102 --queue 30  # la ventana, solo con esos 30
python -m spectro teach samples label img_8102             # la ventana, con todos los que pasaron QC
python -m spectro teach samples add img_8102 t_0001352.000.jpg=-0.018 t_0000069.250.jpg=-0.004
python -m spectro teach samples remove img_8102 t_0000069.250.jpg
python -m spectro teach test suggest img_8102 20           # para la prueba: siempre al azar
python -m spectro teach test label img_8102 --queue 20
python -m spectro teach test add img_8102 t_0000103.500.jpg=-0.005
python -m spectro teach test eval img_8102                 # informe, test_report.csv e historial
python -m spectro teach test eval                          # tabla de todas las corridas con prueba
python -m spectro teach test history img_8102              # la curva de aprendizaje
```

**Corré `qc` antes**: `teach` recorta cada celda con el mismo corrimiento de cámara que usa `read`.
Sin eso la deriva corta los glifos y la biblioteca no coincide con lo que después se lee (si falta
`qc_report.csv`, avisa). Los valores se guardan como texto, así que conservan el signo de `-0.000`
y los ceros finales; un valor que no calza con la geometría (`-0.018` necesita 6 celdas con signo)
se rechaza al escribirlo.

**`suggest`** imprime fotogramas para etiquetar. En `samples`, `--strategy` elige el criterio:
`uniform` reparte parejo (la primera ronda, sin biblioteca), `random` es azar estratificado por
tiempo, `uncertain` elige donde el lector duda y `mixed` —el default— es mitad y mitad. En `test`
**siempre es al azar** y lejos del entrenamiento. Por qué se hace así está en la
[guía](docs/GUIA_CALIBRACION.md#paso-5--rondas-siguientes-dónde-etiquetar).

**`eval`** con una corrida imprime el informe (correctas, erróneas aceptadas, descartadas, con
intervalos de Wilson al 95 %), escribe `out/test_report.csv` y agrega una fila a
`out/teach_history.csv`. Sin corridas (o con varias) imprime una tabla, la misma de `batch`, y no
escribe nada. `--min-accuracy`, `--max-error` y `--min-coverage` agregan el veredicto, igual que en
`batch`.

| flag | dónde | default | qué hace |
|---|---|---|---|
| `N` | `suggest` | `20` | cuántos fotogramas |
| `--strategy` | `samples suggest`, `samples label` | `mixed` | `mixed`, `uncertain`, `random` o `uniform` |
| `--seed S` | `suggest`, `label` | ninguna | semilla del azar (ver abajo) |
| `--gap G` | `suggest`, `label`, `eval` | `5` | separación mínima en segundos entre elegidos, y entre prueba y entrenamiento |
| `--queue N` | `label` | `0` (todos) | abrir la ventana solo con los N fotogramas sugeridos |
| `--max-per-label` | `label` | `3` | variantes máximas por carácter para los botones de biblioteca de la ventana |
| `--min-accuracy`, `--max-error`, `--min-coverage` | `test eval` | `acceptance` | umbrales del veredicto (fracciones) |

**`--seed`.** Sin `--seed`, las sugerencias usan siempre la semilla 0 (la misma lista cada vez) y
el botón `Aleatorio` de la ventana salta a un fotograma distinto cada vez. Con `--seed S` las dos
cosas son reproducibles: misma semilla, misma lista y misma secuencia de saltos.

#### La ventana de `teach` (`samples label`, `test label`)

A la izquierda, la ROI del fotograma ampliada con los cortes de slot y, debajo de cada celda, el
carácter que le toca según el valor que escribiste y lo que lee hoy el lector, con su score. A la
derecha, el panel. **El valor se escribe con el teclado físico** (dígitos, `.` y `-`; `Backspace`
borra el último carácter); la ventana no tiene teclado numérico de botones.

| control | qué hace |
|---|---|
| `<`, `>`, `<<10`, `10>>` (o las flechas ← →) | moverse por los fotogramas que pasaron QC |
| `Aleatorio` | saltar a un fotograma al azar (reproducible solo con `--seed`) |
| `Color / binario` | ver el recorte en color o binarizado |
| `Borrar todo` | vaciar el valor escrito |
| `Agregar muestra` (o `Enter`) | guardar el valor en el conjunto activo y pasar al siguiente |
| `Quitar` | sacar la muestra de este fotograma |
| `Conjunto: Entrenam. / Prueba` | a qué conjunto va `Agregar muestra`; `samples label` abre en `Entrenam.`, `test label` en `Prueba` |
| `Agregar a biblioteca` | suma las muestras de entrenamiento a la biblioteca, sin duplicar (como `train --keep`) |
| `Reemplazar biblioteca` | la reescribe desde cero con las muestras actuales; pide un segundo clic |
| `Validar` | leave-one-out de las muestras, sin tocar la biblioteca |
| `Evaluar prueba` | lo mismo que `teach test eval <id>` |
| `Gestionar biblioteca` | la grilla de plantillas (abajo) |
| `Guardar y salir` (o `Esc`) | cerrar |

Abajo se ve la **cobertura** de `0-9 . -`: verde con 2+ ejemplos, naranja con 1, rojo si falta
(ese carácter no se va a poder leer). Cada muestra se guarda al agregarla.

**Gestionar biblioteca** muestra todas las plantillas de `calib/templates`, cada una con cuántas
celdas de tus muestras **gana bien** y cuántas **gana mal** (en rojo: esa plantilla confunde un
carácter con otro); las que no aportan aparecen atenuadas. Elegís una y podés `Borrar
seleccionada`, `Borrar todas las de '<c>'` (ambos piden confirmación), `Deshacer ultimo borrado`
o cambiarle el carácter con los botones `0-9 . -`. Tras cada cambio se recalcula la exactitud de la
biblioteca vigente sobre tus muestras. `Volver a muestras` regresa.

**Elegí fotogramas bien dibujados.** El último dígito se redibuja varias veces por segundo: si el
fotograma lo agarra a medio dibujar, saltalo. Si cambiaste la geometría (rotación, ROI o celdas),
reemplazá la biblioteca en vez de agregar: las plantillas viejas ya no coinciden con lo que se
recorta y, mezcladas con las nuevas, hacen perder lecturas.

---

## Formato de salida

### `runs/<id>/out/absorbance.csv` — sólo filas válidas

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
honesta. Quedan documentadas, una por una y con su motivo, en `qc_report.csv`.

**Alinear el tiempo con el log del laboratorio**: si el video arrancó 12,5 s después del t=0 de
tu planilla, poné `"offset_s": 12.5` en `runs/<id>/config.json` y volvé a correr
`report --run <id>`. Para tener hora de reloj, agregá `"absolute_start": "2026-09-01 16:42:20"`.
El offset es **por corrida**: cada video arrancó en un momento distinto.

### `runs/<id>/out/qc_report.csv` — el libro mayor, un renglón por fotograma extraído

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

### `runs/<id>/out/readings.csv` — todas las lecturas

`file, t_s, index, value, confidence, margin, chars, dx, dy, status`. Incluye las descartadas
(con `value` vacío si no se pudo armar el número). `chars` es el texto crudo leído celda por celda;
`confidence` es la NCC mínima entre celdas y `margin` la ventaja mínima sobre la mejor plantilla
de otro carácter. Es la fuente de la incertidumbre que usa `suggest`.

### `runs/<id>/out/read_meta.json` — con qué biblioteca se leyó

```
{"fingerprint": "<12 caracteres hex>", "date": "<AAAA-MM-DD HH:MM:SS>", "templates": <cantidad>}
```

La **huella** (_fingerprint_) son los primeros 12 caracteres del SHA-256 de los nombres y el
contenido de todas las plantillas: cambia si se agrega, borra, renombra o modifica cualquiera.
`read` la escribe junto a `readings.csv`; `teach status`, `teach test eval` y `batch` la comparan
con la de la biblioteca de hoy para decir si las salidas están al día (`up_to_date`) o son de
otra biblioteca (`stale`). Las corridas leídas antes de que existiera este archivo se juzgan por
fecha.

### `runs/batch_report.csv` — una fila por corrida del lote

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

### Salidas de `teach`

| archivo | columnas y contenido |
|---|---|
| `runs/<id>/truth.csv`, `runs/<id>/test.csv` | `file,value`: muestras de entrenamiento / de prueba (el valor es texto) |
| `out/teach_report.csv` | `file,typed,read_value,confidence,status,matches,missing`: leave-one-out de las muestras de entrenamiento |
| `out/test_report.csv` | `file,typed,read_value,status,confidence,result`: una fila por fotograma de prueba; `result` es `correct`, `wrong` o `discarded` |
| `out/teach_history.csv` | `date,kind,templates,training,test,distinct_values,correct,wrong,discarded,accuracy,accepted_error,coverage,fingerprint`: una fila por `teach test eval <id>` |

### Archivos de versiones anteriores

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

### Abrirlo y graficarlo en Excel

1. **Datos → Obtener datos → Desde texto/CSV**, elegir `absorbance.csv`, origen **UTF-8** y
   delimitador **coma**. (Abrirlo con doble clic también funciona, pero si tu Excel usa la coma
   como separador decimal conviene el importador para que no rompa los números.)
2. Seleccionar las columnas `t_exp` y `absorbance` → **Insertar → Gráfico de dispersión con
   líneas suavizadas**.
3. Para filtrar lecturas dudosas: agregar un filtro sobre `confidence` y quedarse con `> 0,8`.

---

## Cómo re-calibrar una sola corrida

Re-calibrar **no toca las demás corridas**: la ROI vive en `runs/<id>/config.json`.

```powershell
# el camino normal: registrar contra la referencia compartida
python -m spectro calibrate --run <id> --auto

# si --auto no engancha (el encuadre cambió demasiado), a mano
python -m spectro calibrate --run <id>

# y volver a correr de qc en adelante; los fotogramas ya están extraídos
python -m spectro run --run <id> --skip-extract
```

Si sólo cambió la iluminación, alcanza con `qc --run <id>` para que se re-sugieran los umbrales:
la ROI sigue siendo válida.

**Cuando cambia el equipo o el formato del número** hay que rehacer la receta compartida, no una
corrida: calibrá a mano una corrida representativa, rearmá la biblioteca con sus muestras y
promové el resultado. La receta actual de `calib/` viene de `img_8102` (6 celdas: signo + `0.000`).

```powershell
python -m spectro calibrate --run <id>                  # nueva ROI y nuevos slots
python -m spectro qc --run <id>                         # offsets de cámara
python -m spectro teach samples label <id>              # muestras con valores reales
python -m spectro teach train <id>                      # biblioteca nueva (respalda la anterior)
python -m spectro calibrate --run <id> --promote        # sube ROI, ancla y fotograma a calib/
```

**Cuando el montaje nuevo es mejor que el viejo** —mejor foco, mejor encuadre— también conviene
`--promote`: las corridas siguientes van a registrar contra esa referencia, así que cuanto mejor
sea, más veces va a enganchar `--auto`.

---

## Troubleshooting

**Muchas lecturas descartadas por baja confianza (`low_confidence`).**
Mirá `runs/<id>/out/contact_sheet.png`: son los 40 recortes de menor confianza. Si los dígitos se
ven bien, faltan plantillas: etiquetá esos fotogramas (`teach samples label <id>`) y sumalos con
`teach train --keep`. Si el display muestra negativos, revisá que la biblioteca tenga la plantilla
`-` (`teach status` lo avisa). **Subir `templates.min_score` no es la respuesta**: en el primer
video del proyecto (sep-2026) las lecturas de confianza 0.60–0.65 se desviaban de la mediana local
lo mismo (0.002 Abs) que las de confianza > 0.80, así que el umbral sólo cambia cuántos datos
tenés, no cuán buenos son. Si se ven a medio dibujar, es el display refrescándose y la respuesta
correcta es **subir `--fps`** (ver el punto siguiente).

**El último dígito sale cortado o fantasma.**
El dígito menos significativo se redibuja varias veces por segundo, así que a 1 Hz muchos
fotogramas lo agarran a mitad del refresco. En el primer video del proyecto, a 1 Hz sólo el 41 % de
los segundos tenía una lectura válida; **a 4 Hz la serie final cubría el 86 %** de los 20 minutos.
Subir `--fps` cuesta disco y tiempo de decodificación, no precisión.

**`teach status` dice `stale` en las salidas.**
`readings.csv` se leyó con una biblioteca distinta de la de hoy (la cambiaste con `train`,
`delete`, `relabel` o `restore`). Sus lecturas y sus incertidumbres son de otro lector: corré
`read --run <id>` y `report --run <id>`.

**`ERROR: teach no usa --run`.**
En `teach` el id de la corrida va como argumento (`teach samples list img_8102`), nunca con
`--run`. Si usás la sintaxis vieja de `teach`, el error muestra la tabla de migración.

**`ERROR: falta --run`.**
Un subcomando de etapa no adivina sobre qué corrida trabajar: mezclar dos experimentos
corrompería los datos en silencio. El error lista las corridas disponibles; elegí una con
`--run <id>`, o pasá las rutas a mano. `python -m spectro doctor` las lista todas con su estado.

**`calibrate --auto` no engancha (score por debajo del mínimo).**
El registro corrige traslación, no rotación ni escala. Si el teléfono quedó a otra distancia o
inclinado, no hay corrimiento que arregle eso y calibrar a mano es lo correcto. Si el encuadre es
el mismo pero el salto fue grande, subí `--search-px`. Si la referencia compartida quedó vieja,
calibrá una corrida buena a mano y corré `calibrate --run <id> --promote`.

**Muchos descartes de QC.**
Aflojá los umbrales en `runs/<id>/config.json` (`qc.min_blur_var`, `qc.min_contrast`,
`qc.min_ink_fraction`) y corré `qc --run <id> --no-auto-thresholds`. Si el estado es
`camera_moved`, revisá `dx`/`dy` en `qc_report.csv`: si la deriva es de pocos píxeles el
re-registro ya la compensa y lo que hay que subir es `qc.max_shift_px`; si es de decenas, la
cámara se movió de verdad y hay que re-calibrar sobre el tramo afectado. Si es `roi_outside`, la
ROI quedó pegada al borde del fotograma: recalibrala con un poco más de margen.

**La curva muestra picos de un solo punto.**
Es la firma de un dígito mal leído. Bajá `read.max_rate` en `runs/<id>/config.json` (es la
máxima |ΔAbs|/Δt admitida contra los vecinos) y volvé a correr `read --run <id>` y
`report --run <id>`.

**Borré plantillas que no tenía que borrar.**
`teach lib backups` lista los respaldos y `teach lib restore` vuelve al último (respaldando antes
el estado actual).

**`ffprobe` no aparece después del `winget install`.**
El PATH se toma al abrir la terminal. Cerrala y abrila de nuevo, y confirmá con
`python -m spectro doctor`. Mientras tanto el pipeline funciona igual con el respaldo del venv.

**No se abre ninguna ventana** (sesión remota, WSL, servidor sin escritorio).
Usá `calibrate --auto`, que no abre ventanas, o el modo no interactivo `calibrate --roi x,y,w,h`
mirando `runs/<id>/out/calibracion.png`. Las muestras se cargan sin ventana con
`teach samples add` y `teach test add`.

---

## Tests

```powershell
python -m pytest -q
```

974 tests (11-oct-2026: 973 pasan y 1 se marca como falla esperada, `xfail`), en unos 30 s.
Usan fixtures sintéticas — un "display" de mentira dibujado con OpenCV — así que no dependen del
video ni de datos reales: convención de nombres, decodificación de dígitos, armado del número,
filtro de QC, umbrales de confianza, contratos entre etapas, derivación de rutas por corrida,
calibración automática, biblioteca y respaldos, entrenamiento y evaluación, el árbol de `teach`,
la lógica de las ventanas sin ventana, la compatibilidad con archivos viejos y esta misma
documentación (`tests/test_docs.py` comprueba que cada comando citado exista en el CLI y que cada
enlace apunte a algo real).
