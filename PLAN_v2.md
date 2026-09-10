# Plan — Extractor de absorbancia desde video del espectrofotómetro

> **Este archivo es `PLAN_v2.md`** — el plan de ejecución acordado, con los supuestos ya
> confirmados y las decisiones tomadas. El `PLAN.md` original queda intacto como registro del
> requerimiento inicial. Este documento es autosuficiente: se puede ejecutar más tarde, en otra
> sesión, sin depender de la conversación que lo produjo.

## Contexto

El espectrofotómetro con celda de flujo continuo no tiene software de adquisición, así que el
experimento se registró **filmando la pantalla del equipo**. Existe un video de 20:03 min
(`20260901_164220000_iOS.MOV`, 1.17 GB, HEVC/hvc1, 36 059 fotogramas a ~29.97 fps, iPhone en
soporte fijo). El objetivo es convertir ese video en una **serie temporal absorbancia vs tiempo
en CSV**, lista para Excel u otros scripts.

Estado actual del repo: sólo el video y `PLAN.md`. No hay código, ni venv, ni git.
`ffmpeg`, OpenCV y Tesseract **no están instalados** en el sistema.

### Supuestos confirmados con el usuario

| Supuesto | Decisión |
|---|---|
| Cámara | **Fija** (trípode/soporte) → la ROI se define una vez y se reusa |
| Motor de lectura | **100 % local y offline**, sin API ni costo, determinista |
| Recorte | Se recorta **ajustado al número**, no a toda la pantalla |
| Formato del número | **Fijo**, ej. `0.245` → slots de dígitos fijos, punto decimal asumido |
| Frecuencia de muestreo | **Parámetro configurable** (`--fps`), se arranca en 1 Hz |
| Columna de tiempo | **Parámetro ajustable**, porque debe alinearse con el log manual del laboratorio |
| Fotogramas malos | **Se omiten** del CSV principal; quedan en `qc_report.csv` aparte |
| Instalaciones | **Nada se instala a nivel de sistema por mí.** Todo vive en el venv del proyecto |
| ffmpeg | El usuario instala **`Gyan.FFmpeg` 9.0.1** por su cuenta; el código autodetecta y cae a `imageio-ffmpeg` si no está |
| Documentación | Entregable de primera clase: **arquitectura y uso**, no un README de una línea |

### Supuesto abierto (se resuelve en el Paso 1)

No sabemos aún si el display es de **7 segmentos** o **matriz de puntos/LCD gráfico**. El plan
no depende de eso: el lector usa **template matching por dígito**, que funciona igual en ambos
casos con cámara fija. El Paso 1 extrae fotogramas de muestra para mirarlos y confirmarlo antes
de calibrar.

---

## Enfoque de lectura (por qué template matching)

Con cámara fija, tipografía constante y formato de número fijo, cada dígito en pantalla siempre
se ve **exactamente igual**. Eso convierte el "OCR" en un problema de clasificación trivial:
correlación cruzada normalizada (NCC) contra una biblioteca de 10 plantillas.

- Es **determinista y reproducible** — mismo frame, mismo resultado, siempre.
- No necesita Tesseract, ni modelos entrenados, ni API, ni GPU.
- La precisión es prácticamente 100 % en fotogramas que pasan el filtro de calidad.
- El único trabajo manual es etiquetar ~10 glifos únicos una sola vez (10 pulsaciones de tecla).
- Funciona igual con 7 segmentos que con matriz de puntos.

Como red de seguridad, cada lectura lleva un **score de confianza** (NCC del mejor match y
margen contra el segundo mejor); por debajo del umbral la fila se descarta en vez de inventar
un valor.

---

## Arquitectura

```
spectrometer-video-processer/
├─ .venv/                        # ambiente virtual (requisito del usuario)
├─ requirements.txt
├─ config.json                   # generado por `calibrate`, editable a mano
├─ README.md                     # instalación + uso + referencia de comandos
├─ docs/
│  ├─ ARQUITECTURA.md            # diseño del pipeline y decisiones
│  └─ CONFIG.md                  # referencia campo por campo de config.json
├─ src/spectro/
│  ├─ __init__.py
│  ├─ __main__.py                # entrypoint: python -m spectro <comando>
│  ├─ cli.py                     # argparse con subcomandos
│  ├─ config.py                  # dataclass Config + load/save JSON
│  ├─ extract.py                 # video → data/frames/
│  ├─ calibrate.py               # selección interactiva de ROI y slots de dígitos
│  ├─ templates.py               # construcción de la biblioteca de plantillas
│  ├─ qc.py                      # filtro de calidad
│  ├─ read.py                    # NCC → valor numérico
│  └─ report.py                  # CSV + gráfico + hoja de contacto
├─ data/
│  ├─ frames/                    # t_0000001.000.jpg ...
│  ├─ samples/                   # fotogramas de muestra del Paso 1
│  ├─ templates/                 # 0_a.png, 1_a.png, ... etiquetadas
│  └─ out/                       # absorbancia.csv, qc_report.csv, preview.png
└─ tests/
```

### Dependencias (`requirements.txt`)

```
numpy
opencv-python        # incluye GUI (selectROI) y decodificador HEVC; NO usar headless
imageio-ffmpeg       # respaldo: binario ffmpeg estático, por si el del sistema no está
pandas
matplotlib
pytest
```

Python 3.13.6 tiene wheels para todas estas.

### Política de instalación

**Yo no instalo nada a nivel de sistema.** Las dependencias de pip viven dentro de `.venv/`;
borrando esa carpeta el sistema queda como estaba. Cualquier requisito fuera del venv se
documenta en el README bajo "Requisitos del sistema" con el comando exacto, y **lo corrés vos**.

Hay exactamente uno, y ya lo decidiste:

```powershell
winget install Gyan.FFmpeg     # ffmpeg 9.0.1 + ffprobe
# cerrar y reabrir la terminal para que tome el PATH
ffprobe -version               # verificación
```

Ventajas que aporta sobre el respaldo de pip: trae **`ffprobe`** (que `imageio-ffmpeg` no
incluye) para leer metadatos como JSON limpio en vez de parsear stderr; **aceleración por
hardware** (`d3d11va`/`qsv`), que importa porque vamos a re-extraer varias veces al ajustar el
`--fps`; y **ffmpeg 9.x** en vez del ~6.x empaquetado.

### Resolución del binario (`extract.py`)

La elección **no queda cableada**. Una función `resolve_ffmpeg()` prueba en orden:

1. `ffmpeg` / `ffprobe` en el `PATH` del sistema → se usan (ruta preferida).
2. Si no, `imageio_ffmpeg.get_ffmpeg_exe()` → se usa, y se emite un aviso de que ffprobe no
   está disponible y los metadatos se leerán del stderr de ffmpeg.

El comando `extract` informa en su salida cuál binario y qué versión está usando, para que
quede registrado en el log. Consecuencia práctica: si la instalación de winget falla o se
pospone, el pipeline sigue funcionando sin cambiar una línea de código.

---

## Pasos de implementación

### Paso 0 — Bootstrap

Se crean `requirements.txt`, `.gitignore` (`.venv/`, `data/frames/`, `data/samples/`, `*.MOV`)
y el esqueleto de módulos. **Vos corrés estos comandos** — así el venv y todo lo que toca el
sistema quedan bajo tu control:

```powershell
winget install Gyan.FFmpeg          # una sola vez; luego reabrir la terminal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Después corro `python -m spectro doctor`, un subcomando de diagnóstico que reporta versión de
Python, paquetes instalados, qué ffmpeg/ffprobe resolvió y si hay aceleración por hardware
disponible. Sirve de verificación del bootstrap y de primera línea de troubleshooting.

`git init` queda a tu criterio (el directorio hoy no es un repo).

### Paso 1 — `extract`: video → fotogramas  (`src/spectro/extract.py`)

```
python -m spectro extract --video "20260901_164220000_iOS.MOV" --fps 1
```

- Lee primero los metadatos reales con `ffprobe -v quiet -print_format json -show_streams`
  (fps exacto, duración, resolución, matriz de rotación del iPhone) en vez de asumirlos.
  Sin ffprobe, cae a parsear el stderr de ffmpeg.
- Un solo pase de decodificación, con aceleración por hardware cuando está disponible:
  `ffmpeg -hwaccel auto -i <video> -vf fps=<FPS> -q:v 2 -y data/frames/f_%06d.jpg`
  (`-hwaccel auto` degrada solo a software si el build no la soporta, así que es seguro
  también con el respaldo de pip).
- Renombra según el tiempo real del fotograma: **`t_0000001.000.jpg`** (segundos desde el
  inicio del video, con ceros a la izquierda y 3 decimales, para que el orden alfabético sea
  el orden temporal). Cumple el requisito de "el nombre debe reflejar el tiempo del video".
- Emite `data/frames_index.csv` con `archivo, t_s, indice`.
- Flags: `--fps` (default 1.0), `--start` / `--duration` (para pruebas rápidas), `--scale`,
  `--jpeg-quality`, `--roi-only` (guarda sólo el recorte una vez calibrado: ~2 KB/fotograma
  en vez de ~400 KB).
- **Primero se corre con `--start 600 --duration 5 --output data/samples`** para obtener ~6
  fotogramas de muestra, mirarlos juntos y confirmar el tipo de display y el formato del número
  antes de la extracción completa.
- Nota de escala: a 1 Hz son ~1 203 fotogramas ≈ 400–500 MB en disco. `--roi-only` o `--scale`
  lo reducen drásticamente si molesta.

### Paso 2 — `calibrate`: definir la ROI y los slots  (`src/spectro/calibrate.py`)

```
python -m spectro calibrate
```

- Abre un fotograma de muestra con OpenCV y usa `cv2.selectROI` para que el usuario arrastre un
  rectángulo **ajustado al número** (exactamente como pidió).
- Pregunta cuántos dígitos hay (ej. `0.245` → 4 dígitos) y en qué posición va el punto decimal
  fijo. Divide la ROI en N slots iguales, dibuja el overlay y permite ajustar los cortes con las
  flechas si el reparto no queda perfecto.
- Detecta la polaridad (dígitos claros sobre fondo oscuro, o al revés) del histograma de la ROI.
- Guarda todo en `config.json`: `roi`, `n_digits`, `digit_splits`, `decimal_after`, `polarity`,
  `threshold_method`, umbrales de QC y de confianza.

### Paso 3 — `templates`: biblioteca de dígitos  (`src/spectro/templates.py`)

```
python -m spectro templates --sample 200
```

- Recorre una muestra de fotogramas, recorta cada slot, binariza y normaliza el tamaño.
- Agrupa los recortes por hash perceptual → quedan ~10–14 glifos **únicos**.
- Muestra cada glifo único una vez y pide al usuario teclear el dígito (`0`–`9`, o `x` para
  descartar). Trabajo manual total: ~10 pulsaciones, una sola vez.
- Guarda `data/templates/<digito>_<n>.png`. Se admiten varias plantillas por dígito (tolera
  variaciones de brillo o del punto decimal encendido/apagado).

### Paso 4 — `qc`: filtro de calidad  (`src/spectro/qc.py`)

Las métricas se calculan **sobre la ROI**, no sobre el fotograma completo — es lo único que
importa para la lectura:

| Métrica | Detecta | Estado |
|---|---|---|
| Luminancia media / percentiles | fotograma oscuro o quemado | `dark` / `blown` |
| Varianza del Laplaciano | desenfoque, movimiento | `blur` |
| Contraste (p95 − p05) | display apagado o velado | `low_contrast` |
| Fracción de píxeles de tinta tras umbralizar | mano delante, pantalla en blanco | `occluded` / `blank` |
| NCC contra un ancla estática del fotograma | la cámara se movió | `camera_moved` |

Los umbrales se **auto-sugieren** de la distribución sobre todos los fotogramas
(mediana ± k·MAD) y quedan escritos en `config.json` para poder anularlos a mano.
Salida: `data/out/qc_report.csv` con todas las métricas y el estado por fotograma.

### Paso 5 — `read`: fotograma → número  (`src/spectro/read.py`)

Por cada fotograma que pasa QC:

1. Recortar ROI → escala de grises → normalizar → umbralizar (Otsu, con la polaridad del config).
2. Por cada slot: recortar, redimensionar al tamaño de plantilla, NCC contra todas las plantillas.
3. Aceptar el dígito si `mejor_score ≥ min_score` **y** `mejor − segundo ≥ min_margin`;
   si no, la lectura completa se marca `low_confidence` y se descarta.
4. Ensamblar el valor con el punto decimal fijo del config.
5. **Chequeo de plausibilidad temporal**: si `|Δabs|/Δt` supera `max_rate` respecto de los
   vecinos, se marca `spike` (síntoma típico de un dígito mal leído) y se descarta.

### Paso 6 — `report`: salidas  (`src/spectro/report.py`)

`data/out/absorbancia.csv` — **sólo filas válidas**, como pidió el usuario:

| columna | contenido |
|---|---|
| `t_s` | segundos desde el inicio del video |
| `t_video` | `hh:mm:ss.mmm` — para volver al fotograma exacto |
| `t_exp` | `t_s + time.offset_s` → **el parámetro para alinear con el log manual del laboratorio** |
| `absorbancia` | el valor leído |
| `confianza` | NCC mínima entre los slots (0–1) |
| `frame` | nombre del archivo, para trazabilidad |

Parámetros de tiempo en `config.json`, ambos ajustables:
`time.offset_s` (default 0, admite negativos) y `time.absolute_start` (opcional; si se define,
ej. `2026-09-01 16:42:20`, agrega una columna de hora de reloj ISO).

Además:
- `data/out/preview.png` — gráfico absorbancia vs tiempo, para revisar la curva de un vistazo.
- `data/out/contact_sheet.png` — mosaico con los 40 recortes de menor confianza, para que el
  usuario detecte a ojo cualquier lectura dudosa.

### Paso 7 — `run`: pipeline completo

```
python -m spectro run --video "...MOV" --fps 1
```

Encadena `extract → qc → read → report` usando el `config.json` ya calibrado.

### Paso 8 — Documentación (entregable, no un extra)

**`README.md`** — el documento de uso, pensado para que alguien procese un video nuevo sin
preguntarte nada:

- Qué hace el proyecto y de qué problema nace (pantalla filmada → CSV de absorbancia).
- **Requisitos del sistema**: Python 3.11+ y **ffmpeg** (`winget install Gyan.FFmpeg`), con el
  comando exacto y el `ffprobe -version` de verificación. Se aclara que ffmpeg es *recomendado,
  no obligatorio* — sin él el proyecto cae a `imageio-ffmpeg` del venv — y qué se pierde en ese
  caso. OpenCV y Tesseract **no** se instalan en el sistema: OpenCV viaja en el venv y Tesseract
  no se usa.
- **Instalación**: los comandos del Paso 0, copiables tal cual, cerrando con `spectro doctor`.
- **Quickstart**: la secuencia completa para un video nuevo, de principio a fin, con la salida
  esperada de cada comando.
- **Referencia de comandos**: cada subcomando con todos sus flags, defaults y un ejemplo.
- **Formato de salida**: tabla de columnas de `absorbancia.csv` y de `qc_report.csv`, con
  unidades, y cómo abrirlo y graficarlo en Excel.
- **Cómo re-calibrar** cuando cambie el encuadre o el equipo.
- **Troubleshooting**: lecturas dudosas → agregar plantillas; muchos descartes de QC → aflojar
  umbrales en `config.json`; la curva muestra picos de un solo punto → bajar `max_rate`.

**`docs/ARQUITECTURA.md`** — el documento de diseño, para entender y modificar el código:

- **Diagrama del pipeline** en ASCII: `video → extract → frames/ → qc → read → report → CSV`,
  marcando qué archivo produce y consume cada etapa.
- **Responsabilidad de cada módulo** — una tabla de `src/spectro/*.py` con qué hace cada uno y
  cuál es su interfaz pública.
- **Contratos de datos** entre etapas: convención de nombres de fotogramas, `frames_index.csv`,
  `data/templates/`, `qc_report.csv`.
- **Decisiones de diseño y su porqué**: por qué template matching y no Tesseract ni un VLM; por
  qué ROI fija; por qué el QC mide sobre la ROI y no sobre el fotograma entero; por qué las
  filas descartadas se omiten en vez de interpolarse. Cada decisión con su alternativa
  descartada, para que un cambio futuro de condiciones se pueda reevaluar con criterio.
- **Cómo extenderlo**: qué tocar si el display cambia, si aparece un segundo número en pantalla
  (ej. %T o longitud de onda), o si la cámara deja de estar fija.

**`docs/CONFIG.md`** — referencia campo por campo de `config.json`: tipo, default, qué efecto
tiene, y cómo ajustarlo a mano.

**En el código**: docstring de módulo en cada archivo explicando su rol dentro del pipeline, y
texto de ayuda en todos los subcomandos y flags, de modo que `python -m spectro <cmd> --help`
sea suficiente sin abrir el README.

---

## Verificación

0. **`python -m spectro doctor`** — confirma el bootstrap antes de tocar el video: versión de
   Python, paquetes, qué ffmpeg/ffprobe resolvió y si hay hwaccel. Debe reportar el ffmpeg del
   sistema; si reporta el respaldo de pip, el PATH no tomó y hay que reabrir la terminal.

1. **Tests unitarios** (`pytest tests/`), sobre fixtures sintéticas — sin depender del video:
   - `test_naming`: índice de fotograma ↔ nombre con tiempo, ida y vuelta, a varios `--fps`.
   - `test_decode`: recortes de dígitos conocidos → dígito correcto vía NCC.
   - `test_assemble`: slots `[0,2,4,5]` + `decimal_after=1` → `0.245`; casos borde.
   - `test_qc`: fotogramas sintéticos oscuro / borroso / ocluido → el estado esperado.
   - `test_confidence`: un glifo ambiguo debe caer por debajo del umbral, no adivinar.

2. **Smoke end-to-end** en un tramo corto, antes de procesar los 20 minutos:
   ```
   python -m spectro extract --start 600 --duration 30 --fps 1
   python -m spectro calibrate && python -m spectro templates
   python -m spectro run --skip-extract
   ```
   Debe producir 30 filas coherentes en menos de un minuto.

3. **Chequeo de exactitud manual**: elegir 20 fotogramas al azar del CSV, leerlos a ojo en la
   imagen y comparar contra la columna `absorbancia`. Criterio de aceptación: **20/20 exactos**
   en fotogramas que pasaron QC. Si falla alguno, se agrega su glifo a las plantillas y se repite.

4. **Inspección de la curva**: `preview.png` debe mostrar una traza físicamente razonable para
   flujo continuo (línea base + picos suaves), sin escalones ni picos de un solo punto —
   esos son la firma de un dígito mal leído.

5. **Cuadre de conteos**: `filas(absorbancia.csv) + filas descartadas(qc_report.csv)` debe ser
   igual al total de fotogramas extraídos. Que no se pierda nada en silencio.

6. **La documentación se verifica ejecutándola**: seguir el Quickstart del `README.md` desde
   cero, copiando y pegando cada comando literalmente, y confirmar que produce el CSV. Si un
   comando del README no corre tal cual está escrito, el README está mal, no el usuario.

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El display resulta ser matriz de puntos y los dígitos se tocan entre sí | Los cortes de slots son ajustables a mano en `calibrate`; si no alcanza, se pasa a segmentación por componentes conexas |
| Deriva lenta de la cámara en 20 min pese al soporte | El ancla estática de QC lo detecta; si aparece, se agrega re-registro por template matching de la ROI |
| Uso de disco de la extracción completa | `--roi-only` y `--scale`, ya previstos en la CLI |
| Decodificar 1.17 GB de HEVC es lento | ffmpeg 9.x del sistema con `-hwaccel auto`, un solo pase con el filtro `fps` (no escribe 36 059 JPEG); flags `--start/--duration` para iterar rápido |
| El PATH no toma tras `winget install` | `spectro doctor` lo detecta y avisa; el fallback a `imageio-ffmpeg` evita que quedes bloqueado mientras tanto |
| El punto decimal fijo resulta no serlo | La biblioteca de plantillas ya tolera glifos variantes; el chequeo de plausibilidad temporal marcaría la inconsistencia |
