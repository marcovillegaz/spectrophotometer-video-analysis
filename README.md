# spectro — absorbancia desde el video del espectrofotómetro

El espectrofotómetro UV/VIS con celda de flujo continuo del laboratorio no tiene software de
adquisición. El experimento se registró **filmando la pantalla del equipo** con un teléfono en
soporte fijo. Este proyecto convierte ese video en una **serie temporal de absorbancia vs
tiempo en CSV**, lista para Excel o para otros scripts.

```
video de la pantalla  ->  extract  ->  qc  ->  read  ->  report  ->  absorbancia.csv
```

La lectura del número es **template matching por dígito**: 100 % local, sin API, sin Tesseract
y determinista — el mismo fotograma da siempre el mismo resultado. Cada lectura lleva un score
de confianza, y **los fotogramas dudosos se descartan en vez de inventar un valor**. El porqué
de cada decisión está en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

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
y **Tesseract no se usa**: el lector es template matching propio.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .                  # deja disponible `python -m spectro` desde cualquier lado
python -m spectro doctor          # verificación del bootstrap
```

`doctor` debe terminar en `Estado: listo` y reportar `origen : system` en la sección de ffmpeg.
Si reporta `imageio-ffmpeg`, el PATH todavía no tomó el `winget install`: cerrá y reabrí la
terminal.

---

## Estructura de carpetas

La cámara se re-monta en cada sesión: el encuadre cambia entre videos, pero el equipo y el
display son los mismos. Eso parte los datos en dos mitades limpias — una **receta compartida** y
una **corrida aislada por video**:

```
├─ videos/                          # entradas (gitignored)
│    20260901_164220000_iOS.MOV
├─ calib/                           # la receta, compartida y versionada
│  ├─ config.json                   # geometría de dígitos, matcheo, ROI/ancla de referencia
│  ├─ reference.jpg                 # el fotograma al que corresponden esas coordenadas
│  └─ templates/                    # glifos etiquetados una sola vez
└─ runs/
   ├─ 20260901_164220/
   │  ├─ config.json                # receta + video, fps, ROI propia, umbrales, offset
   │  ├─ frames/                    # gitignored
   │  ├─ frames_index.csv
   │  └─ out/                       # absorbancia.csv, qc_report.csv, readings.csv, preview.png…
   └─ 20260903_101500/
```

| qué | dónde | por qué |
|---|---|---|
| biblioteca de glifos | **compartida** — `calib/templates/` | el display es el mismo equipo; se etiqueta una vez |
| geometría del número (celdas, punto decimal, polaridad) | **compartida** — `calib/config.json` | no depende de dónde quedó el teléfono |
| parámetros de matcheo (`templates.*`, `read.*`) | **compartida** | son propiedades del lector, no de la sesión |
| ROI, ancla, fotograma de referencia | **por corrida** | cambian con el encuadre de cada montaje |
| video, fps, offset de tiempo | **por corrida** | son la sesión |
| umbrales de QC | **por corrida** | dependen de la iluminación de ese día |

Se versionan `calib/`, `runs/*/config.json` y `runs/*/out/`. No se versionan `videos/` ni
`runs/*/frames/`, que son pesados y regenerables.

El **id de corrida** sale del nombre del video: para los videos de iPhone,
`20260901_164220000_iOS.MOV` → `20260901_164220` (fecha y hora, sin los milisegundos). Cualquier
otro nombre se sanea a minúsculas con `_`. `--name` lo overridea.

---

## Quickstart — de un video nuevo al CSV

Ninguna etapa lleva rutas a mano: **`--run <id>` deriva las ocho** desde el layout de arriba.

```powershell
# 1. Dar de alta la corrida (crea runs/<id>/ y hereda la receta de calib/)
python -m spectro new videos/20260903_101500000_iOS.MOV --fps 4
#    -> runs/20260903_101500/  con config.json sembrado

# 2. Extraer los fotogramas
python -m spectro extract --run 20260903_101500
#    -> runs/20260903_101500/frames/ + frames_index.csv

# 3. Calibrar el encuadre de ESTA sesión, contra la referencia compartida
python -m spectro calibrate --run 20260903_101500 --auto
#    -> ROI corrida por el desplazamiento medido + out/calibracion.png
#    Si el encuadre cambió demasiado, avisa y no inventa nada: calibrá a mano
#    con `python -m spectro calibrate --run 20260903_101500` (sin --auto)

# 4. Pipeline completo sobre los fotogramas ya extraídos
python -m spectro run --run 20260903_101500 --skip-extract
#    -> runs/20260903_101500/out/absorbancia.csv, preview.png, qc_report.csv…
```

Los pasos 1–4 en uno, para uno o varios videos:

```powershell
python -m spectro batch videos/*.MOV --fps 4
```

**La primera vez** hay que sembrar `calib/` una sola vez, porque todavía no hay receta que
heredar: calibrá a mano la primera corrida, etiquetá los glifos y promové el resultado.

```powershell
python -m spectro new videos/mi_primer_video.MOV --fps 4
python -m spectro extract --run <id>
python -m spectro calibrate --run <id>                 # interactivo: arrastrá el rectángulo
python -m spectro templates --run <id> --sample 300    # ~40 teclas, una única vez
python -m spectro calibrate --run <id> --promote       # sube ROI, ancla y fotograma a calib/
python -m spectro run --run <id> --skip-extract
```

Salida esperada del paso final:

```
== qc ==
  4813 fotogramas desde runs/20260901_164220/frames/
  re-registro activo contra t_0000601.000.jpg, ancla (696, 273, 381, 96)
  4809/4813 fotogramas pasan QC
    deriva de camara: dx -1..6 px, dy -8..1 px (compensada)
    descartados por blank: 4
== read ==
  biblioteca: 33 plantillas (., 0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
  2099/4809 lecturas validas
    descartadas por baja confianza: 2710
== report ==
  2099 filas validas -> runs/20260901_164220/out/absorbancia.csv
  cuadre: 2099 validas + 2714 descartadas = 4813 extraidas  [ok]
  absorbancia: min 0.000  max 0.851  confianza minima 0.600
```

Para re-procesar la misma corrida con otro `--fps` alcanza con repetir los pasos 2 y 4: la
calibración y las plantillas se reusan.

---

## Referencia de comandos

Todos aceptan `--help` y los tres flags globales del layout, que van **antes** del subcomando:

| flag global | default | qué hace |
|---|---|---|
| `--run <id>` | — | deriva config, frames, índice, salidas y plantillas de la corrida |
| `--runs-dir` | `runs` | carpeta que contiene las corridas |
| `--calib-dir` | `calib` | carpeta de la calibración compartida |
| `--config` | `runs/<run>/config.json` | config de la corrida |

**Un flag explícito siempre le gana a lo derivado**, así que se puede apuntar una etapa a otra
carpeta sin dejar de usar `--run`. Si a un subcomando de etapa le falta `--run` y no le pasaste
las rutas a mano, falla listando las corridas disponibles: adivinar cuál es mezclaría dos
experimentos en silencio.

### `doctor`
Diagnóstico del entorno: versión de Python, si el venv está activo, paquetes instalados, qué
ffmpeg/ffprobe resolvió y qué aceleradores por hardware hay. Después lista el estado de `calib/`
(receta, `reference.jpg`, cuántas plantillas) y **una línea por corrida** con su estado de
calibración, cuántos fotogramas tiene y si ya produjo salida. Es la primera línea de
troubleshooting.

### `new` — dar de alta una corrida
```powershell
python -m spectro new videos/20260903_101500000_iOS.MOV --fps 4
python -m spectro new videos/otro.MOV --name cinetica-fe-02
```
Crea `runs/<id>/`, siembra su `config.json` desde `calib/config.json` y registra el video con su
fps. **No toca el video ni lo copia**: la corrida lo referencia por ruta. Hereda geometría,
plantillas y parámetros de matcheo; deja ROI, ancla y umbrales sin fijar, que son de esta sesión.

| flag | default | qué hace |
|---|---|---|
| `--name` | derivado del video | id de la corrida |
| `--fps` | `1.0` | frecuencia de muestreo de esta corrida |
| `--force` | off | re-sembrar el `config.json` aunque la corrida ya exista |

### `extract` — video → fotogramas
```powershell
python -m spectro extract --run 20260903_101500
```
| flag | default | qué hace |
|---|---|---|
| `--video` | el de `config.json` de la corrida | video de entrada |
| `--fps` | `1.0` | frecuencia de muestreo en Hz |
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

> `--roi-only` ahorra disco pero **desactiva el re-registro** (ver más abajo): al no guardar el
> contexto alrededor del número, ya no hay ancla contra la cual medir la deriva de la cámara.

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

Sin `--auto` abre un fotograma con OpenCV y espera que arrastres un rectángulo **ajustado al
número**. Después pregunta cuántas celdas de caracter hay y dónde va el punto decimal. Los tres
caminos guardan la misma configuración en `runs/<id>/config.json` y dejan
`runs/<id>/out/calibracion.png` con el overlay dibujado para auditar el corte.

**Las celdas se cuentan incluyendo el punto**: en `0.597` la fuente es monoespaciada y el punto
ocupa su propia celda, así que son **5 slots**, no 4. `calibrate` detecta solo cuál es el slot del
punto (el de menos tinta) y lo anota en `separator_slots`.

| flag | qué hace |
|---|---|
| `--auto` | calibrar por registro contra `calib/reference.jpg` |
| `--search-px` | margen de búsqueda del ancla en `--auto` (default 200) |
| `--min-score` | NCC mínima del ancla en `--auto` (default 0.6) |
| `--promote` | copiar ROI, ancla y fotograma de esta corrida a `calib/` como nueva referencia |
| `--frame` | fotograma a usar (default: el del medio de la carpeta de fotogramas) |
| `--roi x,y,w,h` | modo no interactivo, sin ventana gráfica |
| `--no-refine` | usar la ROI tal cual, sin ajustarla al bounding box de la tinta |
| `--n-digits`, `--decimal-after` | celdas y posición del punto, sin preguntar |
| `--splits` | cortes manuales, ej. `0,26,52,78,104,127` |
| `--separators` | índices de slot que son separadores; vacío para ninguno |
| `--anchor x,y,w,h` | ancla de registro manual (default: automática) |
| `--polarity` | `auto` (default), `light_on_dark`, `dark_on_light` |

### `templates` — biblioteca de dígitos
```powershell
python -m spectro templates --run <id> --sample 300
```
La biblioteca es **compartida**: se construye desde los fotogramas de una corrida pero se escribe
en `calib/templates/`, y todas las demás corridas la reusan. En condiciones normales se corre una
sola vez, la primera.

Recorre una muestra de fotogramas, recorta cada slot, binariza y agrupa por hash perceptual.
Muestra cada glifo **único** y pide teclear su caracter (`0`-`9`, `.`, `x` para descartar).
Siempre escribe `runs/<id>/out/glifos.png` con todos los glifos numerados, así que también se
puede etiquetar sin ventana gráfica:

```powershell
python -m spectro templates --run <id> --sample 300 --labels ".,0,0,2,6,6,8,x,0,1,..."
```

Descartá con `x` los glifos rotos o a medio dibujar: dejarlos afuera sólo cuesta que esos
fotogramas se descarten; incluirlos mal etiquetados mete lecturas erróneas en el CSV.

### `qc` — filtro de calidad
```powershell
python -m spectro qc --run <id>
```
Mide cada fotograma **sobre la ROI** y escribe `runs/<id>/out/qc_report.csv`. Los umbrales se
auto-sugieren de la distribución observada (mediana ± 6·MAD) y quedan escritos en el
`config.json` de la corrida; con `--no-auto-thresholds` usa los que ya estén ahí.

### `read` — fotogramas → números
```powershell
python -m spectro read --run <id>
```
Escribe `runs/<id>/out/readings.csv` (todas las lecturas, incluidas las descartadas) y actualiza
la columna `estado` de `qc_report.csv`. Las plantillas salen de `calib/templates/`.

### `report` — salidas finales
```powershell
python -m spectro report --run <id>
```
Escribe `runs/<id>/out/absorbancia.csv`, `preview.png` (la curva) y `contact_sheet.png` (los 40
recortes de menor confianza). Cierra con el **cuadre de conteos**: válidas + descartadas debe dar
exactamente los fotogramas extraídos. `--no-plots` deja sólo el CSV.

### `run` — pipeline completo
```powershell
python -m spectro run --run <id> --fps 4
python -m spectro run --run <id> --skip-extract      # reusar los fotogramas ya extraídos
```

### `batch` — varios videos de punta a punta
```powershell
python -m spectro batch videos/*.MOV --fps 4
```
Por cada video: `new` → `extract` → `calibrate --auto` → `qc` → `read` → `report`. Salta las
corridas que ya tienen `out/absorbancia.csv` (`--no-skip-existing` para rehacerlas). Si
`calibrate --auto` no llega al score, **saltea esa corrida y sigue con la siguiente**; al final
imprime un resumen por corrida —válidas, cobertura, rango de absorbancia— y la lista de las que
quedaron pendientes de calibración manual, con el comando listo para copiar.

| flag | default | qué hace |
|---|---|---|
| `--fps` | `1.0` | frecuencia de muestreo de todas las corridas del lote |
| `--no-skip-existing` | off | re-procesar también las corridas ya terminadas |
| `--search-px` | `200` | margen de búsqueda del ancla en `calibrate --auto` |
| `--min-score` | `0.6` | NCC mínima del ancla en `calibrate --auto` |

---

## Formato de salida

### `runs/<id>/out/absorbancia.csv` — sólo filas válidas

| columna | unidad | contenido |
|---|---|---|
| `t_s` | s | segundos desde el inicio del video |
| `t_video` | hh:mm:ss.mmm | para volver al fotograma exacto en el reproductor |
| `t_exp` | s | `t_s + time.offset_s` — **la columna para alinear con el log manual** |
| `absorbancia` | Abs | el valor leído |
| `confianza` | 0–1 | NCC mínima entre los slots del fotograma |
| `frame` | — | nombre del archivo, para trazabilidad |
| `hora` | ISO | sólo si `time.absolute_start` está definido en `config.json` |

Las filas descartadas **no aparecen** y **no se interpolan**: un hueco en la serie es información
honesta. Quedan documentadas, una por una y con su motivo, en `qc_report.csv`.

**Alinear el tiempo con el log del laboratorio**: si el video arrancó 12,5 s después del t=0 de
tu planilla, poné `"offset_s": 12.5` en `runs/<id>/config.json` y volvé a correr
`report --run <id>`. Para tener hora de reloj, agregá `"absolute_start": "2026-09-01 16:42:20"`.
El offset es **por corrida**: cada video arrancó en un momento distinto.

### `runs/<id>/out/qc_report.csv` — el libro mayor, un renglón por fotograma extraído

`archivo, t_s, indice, mean_luma, p05, p95, contraste, blur_var, ink_fraction, anchor_ncc,
dx, dy, estado`

Estados posibles: `ok`, `dark`, `blown`, `blur`, `low_contrast`, `blank`, `occluded`,
`camera_moved`, `low_confidence`, `spike`.

### Abrirlo y graficarlo en Excel

1. **Datos → Obtener datos → Desde texto/CSV**, elegir `absorbancia.csv`, origen **UTF-8** y
   delimitador **coma**. (Abrirlo con doble clic también funciona, pero si tu Excel usa la coma
   como separador decimal conviene el importador para que no rompa los números.)
2. Seleccionar las columnas `t_exp` y `absorbancia` → **Insertar → Gráfico de dispersión con
   líneas suavizadas**.
3. Para filtrar lecturas dudosas: agregar un filtro sobre `confianza` y quedarse con `> 0,8`.

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
corrida: calibrá a mano una corrida representativa, reconstruí la biblioteca y promové el
resultado.

```powershell
python -m spectro calibrate --run <id>                  # nueva ROI y nuevos slots
python -m spectro templates --run <id> --sample 300     # nueva biblioteca de glifos
python -m spectro calibrate --run <id> --promote        # sube ROI, ancla y fotograma a calib/
```

**Cuando el montaje nuevo es mejor que el viejo** —mejor foco, mejor encuadre— también conviene
`--promote`: las corridas siguientes van a registrar contra esa referencia, así que cuanto mejor
sea, más veces va a enganchar `--auto`.

---

## Troubleshooting

**Muchas lecturas descartadas por baja confianza.**
Mirá `runs/<id>/out/contact_sheet.png`: son los 40 recortes de menor confianza. Si los dígitos se ven
bien, faltan plantillas: volvé a correr `templates` con `--sample` más alto y etiquetá los glifos
nuevos. **Subir `templates.min_score` no es la respuesta**: en esta corrida las lecturas de
confianza 0.60–0.65 se desvían de la mediana local lo mismo (0.002 Abs) que las de confianza
> 0.80, así que el umbral sólo cambia cuántos datos tenés, no cuán buenos son. Si se ven a medio dibujar, es el display refrescándose y la respuesta correcta es
**subir `--fps`** (ver el punto siguiente).

**El último dígito sale cortado o fantasma.**
El dígito menos significativo se redibuja varias veces por segundo, así que a 1 Hz muchos
fotogramas lo agarran a mitad del refresco. En este video, a 1 Hz sólo el 41 % de los fotogramas
era legible; **a 4 Hz la serie final cubre el 86 % de los segundos** de los 20 minutos. Subir
`--fps` cuesta disco y tiempo de decodificación, no precisión.

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
`qc.min_ink_fraction`) y corré `qc --run <id> --no-auto-thresholds`. Si el estado es `camera_moved`, revisá `dx`/`dy` en
`qc_report.csv`: si la deriva es de pocos píxeles el re-registro ya la compensa y lo que hay que
subir es `qc.max_shift_px`; si es de decenas, la cámara se movió de verdad y hay que re-calibrar
sobre el tramo afectado.

**La curva muestra picos de un solo punto.**
Es la firma de un dígito mal leído. Bajá `read.max_rate` en `runs/<id>/config.json` (es la
máxima |ΔAbs|/Δt admitida contra los vecinos) y volvé a correr `read --run <id>` y
`report --run <id>`.

**`ffprobe` no aparece después del `winget install`.**
El PATH se toma al abrir la terminal. Cerrala y abrila de nuevo, y confirmá con
`python -m spectro doctor`. Mientras tanto el pipeline funciona igual con el respaldo del venv.

**`cv2.selectROI` no abre ninguna ventana** (sesión remota, WSL, servidor sin escritorio).
Usá `calibrate --auto`, que no abre ninguna ventana, o el modo no interactivo
`calibrate --roi x,y,w,h` y `templates --labels ...`, mirando `runs/<id>/out/calibracion.png` y
`runs/<id>/out/glifos.png` para decidir los valores.

---

## Tests

```powershell
python -m pytest -q
```

105 tests sobre fixtures sintéticas — un "display" de mentira dibujado con OpenCV — así que no
dependen del video ni de datos reales: convención de nombres, decodificación de dígitos, armado
del número, filtro de QC, umbrales de confianza, contratos entre etapas, derivación de rutas por
corrida y calibración automática por registro.
