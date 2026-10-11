# Instalar spectro

**Para quién y cuándo leerlo:** la primera vez que vas a usar spectro en una computadora, o cuando
`doctor` no termina en `Estado: listo`.

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

`python -m spectro doctor` informa cuál de los dos está usando (por qué se resuelve así, en
[decisiones](../diseno/decisiones.md#el-binario-de-ffmpeg-se-resuelve-en-runtime)).

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

## Verificar con `doctor`

`doctor` debe terminar en `Estado: listo` y reportar `origen    : system` en la sección de ffmpeg.
Si reporta `imageio-ffmpeg`, el PATH todavía no tomó el `winget install`: cerrá y reabrí la
terminal. Qué más muestra `doctor` está en la [referencia](../referencia/comandos.md#doctor); si
algo no anda, mirá el [diagnóstico](../diagnosticar/problemas.md#instalación-y-entorno).

---

**Siguiente paso:** procesar tu primer video, en la [primera corrida](primera-corrida.md).
