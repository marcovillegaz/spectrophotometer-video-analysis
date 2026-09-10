# Plan v3 — Reestructurar `spectro` para procesar múltiples videos

> **Este archivo es `PLAN_v3.md`** — el plan de reestructuración acordado, con los supuestos ya
> confirmados y las decisiones tomadas. `PLAN.md` (requerimiento original) y `PLAN_v2.md` (plan de
> ejecución del pipeline, ya implementado) quedan intactos como registro. Este documento es
> autosuficiente: se puede ejecutar más tarde, en otra sesión, sin depender de la conversación que
> lo produjo.

## Contexto

El proyecto se construyó para **un** video: `config.json` en la raíz, `data/frames/`,
`data/templates/`, `data/out/`. Todo funciona y produjo 2099 filas válidas para
`20260901_164220000_iOS.MOV`, pero la estructura no tiene dónde poner un segundo video sin
pisar el primero.

La buena noticia es que el trabajo pesado ya está hecho: **todas las rutas ya son flags**
(`--frames-dir`, `--out-dir`, `--templates-dir`, `--qc-report`, `--readings`, `--index`,
`--config`), y los valores `data/...` de `cli.py:239-351` son sólo *defaults*. No hay que
reescribir el pipeline, hay que darle una convención de carpetas y una forma de derivar las ocho
rutas de un solo dato en vez de tipearlas.

Condición del montaje, confirmada: **la cámara se re-monta en cada sesión**. El encuadre cambia
entre videos, pero el equipo y la fuente del display son los mismos. Eso parte el problema en dos
mitades limpias:

- **Se comparte** entre corridas: las plantillas de glifos, la geometría del número (5 celdas,
  punto en el slot 1, `decimal_after=1`), la polaridad y los parámetros de matcheo.
- **Es propio de cada corrida**: la ROI, el ancla, el fotograma de referencia, el video, el fps,
  los umbrales de QC auto-sugeridos y el offset de tiempo.

## Estructura final

```
spectrometer-video-processer/
├─ videos/                          # entradas (gitignored)
│    20260901_164220000_iOS.MOV
├─ calib/                           # la "receta", compartida y versionada
│  ├─ config.json                   # geometría de dígitos, params de matcheo, ROI/ancla de referencia
│  ├─ reference.jpg                 # el fotograma al que corresponden esas coordenadas
│  └─ templates/                    # glifos etiquetados una sola vez
├─ runs/
│  ├─ 20260901_164220/
│  │  ├─ config.json                # receta + video, fps, ROI propia, umbrales, offset
│  │  ├─ frames/                    # gitignored
│  │  ├─ frames_index.csv
│  │  └─ out/                       # absorbancia.csv, qc_report.csv, readings.csv, preview.png…
│  └─ 20260903_101500/
├─ src/spectro/
├─ tests/
└─ docs/
```

`calib/` y `runs/*/config.json` + `runs/*/out/` se versionan; `videos/` y `runs/*/frames/` no.

## Decisiones

| tema | decisión |
|---|---|
| Layout | `runs/<id>/` aislados + `calib/` compartida + `videos/` |
| Calibración | ROI/ancla por corrida; plantillas y geometría de dígitos compartidas |
| Fotogramas en disco | **se guardan todos** (~690 MB por video). Ver "Sobre el disco" al final |
| Lote | sí, comando `batch`; **sin** CSV combinado ni índice de corridas (no pedidos) |
| Id de corrida | del nombre del video; `--name` para overridear |

## Cambios de código

### 1. Nuevo `src/spectro/project.py` — el layout como código

Único lugar que sabe dónde va cada cosa. Sin estado escondido: todo se deriva del id de corrida.

```python
@dataclass
class RunPaths:
    id: str
    root: Path        # runs/<id>
    config: Path      # runs/<id>/config.json
    frames: Path      # runs/<id>/frames
    index: Path       # runs/<id>/frames_index.csv
    out: Path         # runs/<id>/out
    templates: Path   # calib/templates   (compartida)
```

- `run_id_from_video(path, name=None)` — default: stem saneado (minúsculas, no alfanumérico → `_`).
  Regla documentada para los videos de iPhone: `^(\d{8})_(\d{6})\d*_iOS$` → `YYYYMMDD_HHMMSS`, así
  `20260901_164220000_iOS.MOV` da `20260901_164220`.
- `RunPaths.for_run(run_id, base=Path("."))` y `list_runs(base)`.
- `seed_run_config(calib_config, video, fps)` — copia la receta de `calib/config.json` y le pone
  video y fps; deja ROI/ancla/reference_frame para que los fije `calibrate`.

### 2. `cli.py` — un `--run` que deriva las ocho rutas

- Flags globales nuevos: `--run <id>`, `--runs-dir` (default `runs`), `--calib-dir` (default `calib`).
- Los `default="data/..."` de todos los subcomandos pasan a `default=None`, y en `main()` una
  función `resolve_paths(args)` los completa desde `RunPaths`. **Un flag explícito siempre gana**
  sobre lo derivado — eso mantiene vivos los tests actuales, que pasan rutas a mano.
- Si falta `--run` en un subcomando de etapa, error claro **listando las corridas disponibles**.
  Nada de adivinar cuál es: mezclar dos corridas corrompe datos de laboratorio en silencio.
- `doctor` pasa a listar las corridas y el estado de `calib/` (plantillas, si hay `reference.jpg`).

### 3. Subcomando nuevo `new` — dar de alta una corrida

```
python -m spectro new videos/20260903_101500000_iOS.MOV [--name cinetica-fe-02] [--fps 4]
```
Crea `runs/<id>/`, siembra `config.json` desde `calib/config.json`, registra el video. No toca el
video ni lo copia.

### 4. `calibrate --auto` — calibrar por registro contra `calib/reference.jpg`

Es el cambio que hace viable el lote. Reusa `estimate_shift()` (`imaging.py:186`), que ya busca un
parche de ancla dentro de una ventana y devuelve `(dx, dy, score)`: se lo aplica **entre sesiones**
en vez de entre fotogramas de una misma sesión.

1. Toma el ancla y la ROI de referencia de `calib/config.json` (coordenadas de `calib/reference.jpg`).
2. Busca ese parche en el fotograma de referencia de la corrida nueva, con margen amplio
   (`--search-px`, default ~200, bastante mayor que los 40 px del registro intra-corrida).
3. Si `score >= --min-score` (default 0.6): corre ROI y ancla por `(dx, dy)`, las guarda en el
   config de la corrida y escribe `out/calibracion.png` para verificar a ojo.
4. Si no: **no inventa una ROI**. Avisa que el encuadre cambió demasiado y pide `calibrate`
   manual para esa corrida.

Limitación a documentar: esto corrige **traslación**, no rotación ni escala. Si el teléfono quedó a
otra distancia o inclinado, el score cae y cae en el camino manual, que es el comportamiento
correcto.

- `calibrate --promote` (opcional): copia la ROI/ancla de esta corrida y su fotograma a `calib/`
  como nueva referencia. Útil cuando el montaje nuevo es mejor que el viejo.

### 5. Subcomando nuevo `batch`

```
python -m spectro batch videos/*.MOV --fps 4
```
Por cada video: `new` → `extract` → `calibrate --auto` → `qc` → `read` → `report`.
- `--skip-existing` (default on): saltea corridas que ya tienen `out/absorbancia.csv`.
- Si `calibrate --auto` no llega al score, **saltea esa corrida y sigue con la siguiente**;
  al final imprime un resumen con cuáles quedaron pendientes de calibración manual.
- Resumen final por corrida: filas válidas, cobertura, rango de absorbancia.

### 6. Rutas por defecto en los módulos

Las constantes `FRAMES_DIR`, `QC_REPORT`, `READINGS`, `OUT_DIR`, `TEMPLATES_DIR`,
`DEFAULT_CONFIG_PATH` quedan sólo como defaults de las funciones (`run_qc`, `run_read`,
`run_report`, …), que ya reciben todas las rutas por parámetro. Se actualizan sus valores al nuevo
layout; **ninguna firma cambia**, así que `qc.py`, `read.py`, `report.py`, `templates.py` y
`extract.py` no se tocan salvo esas líneas.

### 7. `.gitignore`

Agregar `videos/`, `runs/*/frames/`, `runs/*/samples/`. Se versionan `calib/`,
`runs/*/config.json` y `runs/*/out/`. Sacar las entradas viejas `data/`.

## Migración de la corrida existente

Sin re-procesar nada: los 2099 resultados actuales se conservan tal cual.

| de | a |
|---|---|
| `20260901_164220000_iOS.MOV` | `videos/` |
| `data/templates/` (33 plantillas) | `calib/templates/` |
| `config.json` | `runs/20260901_164220/config.json` (completo) y receta → `calib/config.json` |
| `data/frames/t_0000601.000.jpg` | `calib/reference.jpg` (copia; es el fotograma de calibración) |
| `data/frames/`, `data/frames_index.csv` | `runs/20260901_164220/` |
| `data/out/` | `runs/20260901_164220/out/` |
| `data/samples/` | se descarta |

`calib/config.json` = el config actual **sin** `video`, `fps` ni los umbrales de QC de esta corrida
(que son propios de su iluminación), conservando `digits`, `templates`, `read`, y la ROI/ancla como
referencia junto con `reference.jpg`.

## Tests

Nuevo `tests/test_project.py`, sobre las fixtures sintéticas que ya existen en `tests/conftest.py`:

- derivación del id: patrón iOS, saneado genérico, `--name` que overridea.
- `RunPaths.for_run` arma las ocho rutas; `list_runs` las encuentra.
- **precedencia**: un flag explícito le gana a lo derivado de `--run`.
- `seed_run_config` hereda geometría y plantillas, y deja la ROI sin fijar.
- `calibrate --auto`: se renderiza un display sintético, se lo desplaza con `np.roll` (igual que
  `test_qc.py::test_registro_mide_el_corrimiento`) y se verifica que la ROI resultante cae sobre
  los dígitos y que un desplazamiento fuera de rango **falla en vez de devolver una ROI mala**.

Los 75 tests actuales deben seguir pasando sin cambios, porque pasan rutas explícitas.

## Documentación

- `README.md`: quickstart pasa a ser multi-video (`new` → `extract` → `calibrate` → `run`, y
  `batch` para el lote); sección nueva "Estructura de carpetas"; tabla de qué es compartido y qué
  es por corrida; cómo re-calibrar una sola corrida.
- `docs/ARQUITECTURA.md`: sección "Layout de datos" con el porqué de `calib/` vs `runs/`, y el
  `calibrate --auto` explicado como reuso del registro entre sesiones, con su limitación
  (traslación sí, rotación/escala no).
- `docs/CONFIG.md`: marcar cada campo como **compartido** (va en `calib/config.json`) o **por
  corrida**, que es la pregunta que uno se hace al editar el JSON a mano.

## Verificación

1. `python -m pytest -q` → los 75 actuales + los nuevos de `test_project.py`.
2. `python -m spectro doctor` → lista `20260901_164220` y la calib con 33 plantillas.
3. **No regresión sobre la corrida migrada**: `python -m spectro report --run 20260901_164220`
   debe reproducir **2099 filas** y el cuadre `2099 + 2714 = 4813`, idéntico al actual.
4. **Segunda corrida real**: crear una con un tramo del mismo video como si fuera otro
   (`extract --start 300 --duration 120`), correr `calibrate --auto` y confirmar que engancha la
   ROI sola y produce un CSV coherente.
5. `python -m spectro batch videos/*.MOV --fps 4 --skip-existing` → no re-procesa la corrida ya
   terminada e informa el resumen.
6. Seguir el quickstart nuevo del README copiando y pegando, para verificar que la doc corre.

## Sobre el disco (recomendación, no se implementa ahora)

Elegiste **guardar todos los fotogramas**, y así queda. Dicho eso, dejo asentado que la mejor
opción a mediano plazo es **recortar en `extract` a la banda que contiene la ROI y el ancla**:
en este video sería `x 696-1081, y 273-754` ≈ 381×481 px sobre 1920×1080, o sea **~10 % del
tamaño: ~70 MB por video en vez de ~690 MB**. A diez videos son 700 MB contra 7 GB.

A diferencia del `--roi-only` que existe hoy —que recorta *sólo* el número y por eso **desactiva el
re-registro**, perdiendo la corrección de deriva— la banda conserva el ancla dentro del recorte, así
que el registro sigue funcionando igual. Lo que hace falta para implementarlo: que el sidecar
`.roi.json` guarde el **origen del recorte** y que `crop_for_reading` y `estimate_shift` resten ese
origen a las coordenadas. Es acotado, pero toca aritmética de coordenadas en las tres etapas, así
que conviene hacerlo como cambio propio y con sus tests, no mezclado con esta reestructuración.
