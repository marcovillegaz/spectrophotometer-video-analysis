# spectro — guía para trabajar en este proyecto

Convierte el **video de la pantalla de un espectrofotómetro** en una serie de **absorbancia vs tiempo** (CSV).
El lector es un clasificador de vecino más cercano (1-NN): compara cada celda del número contra una
**biblioteca de plantillas** con correlación cruzada normalizada (NCC). No hay OCR ni red neuronal.

```
video → extract → qc → read → report → absorbance.csv
                       ↑
        teach (etiquetar, entrenar la biblioteca y medirla)
```

## Comandos

- **Tests:** `.venv/Scripts/python -m pytest -q` (~30 s, sin videos reales, fixtures sintéticas).
- **CLI:** `.venv/Scripts/python -m spectro --help` y `... teach --help` (el árbol de `teach` y su tabla de migración). El paquete está instalado en modo editable.
- **Estado de los datos (solo lectura):** `teach status`, `teach lib list --usage`, `teach samples list`, `teach test list`.

## Documentos (cada tema vive en uno solo)

La lista de documentos, con el propósito de cada uno, es el [mapa del README](README.md#mapa-de-la-documentación): es la única. Al cambiar algo, actualizá el documento que es dueño del tema y enlazalo desde los demás.

## Invariantes de diseño (no romperlos)

- **Descartar antes que adivinar.** Una lectura dudosa se descarta y deja un hueco; no se interpola ni se inventa.
- **`read` toma de `calib/` solo `templates/`**; todo lo demás sale de `runs/<id>/config.json`. `calib/config.json` solo siembra corridas, sirve a `calibrate --auto` y guarda `acceptance`.
- **Todo recorte de celda usa el corrimiento de cámara que midió `qc`**, igual que `read`. Si no, la biblioteca no coincide con lo que se lee. El recorte vive en `imaging.cell_glyphs`.
- **La rotación se aplica en un solo lugar:** `imaging.load_frame`. La binarización y el recorte también viven en `imaging.py`.
- **Un solo evaluador:** leave-one-out, biblioteca vigente y prueba pasan por `evaluation.evaluate`.
- **La biblioteca se toca solo por `library.py`** (cargar, escribir, borrar, re-etiquetar, respaldar, huella).
- **Las UI tienen la lógica pura** (estado, acciones, layout, vista previa) y el loop de OpenCV delgado, para poder testearla sin ventana. En `teach`, la lógica vive en `teach_session.py`; lo común a las dos ventanas, en `ui_common.py`.
- **Las muestras de varias corridas se identifican como `corrida/archivo`**: los videos repiten nombres de fotograma.
- **La prueba nunca entra a la biblioteca**, y una etiqueta equivocada contamina a todos los videos (la biblioteca es compartida).
- **El id de la corrida nunca se adivina:** las etapas exigen `--run`; `teach` lo recibe como argumento posicional y rechaza `--run`.
- **Los archivos que ya existen siguen cargando.** Los nombres viejos (en español) se traducen en un solo lugar, `compat.py`; los escritores emiten siempre los nuevos.

## Convenciones

- **Nombres de interfaz en inglés** (identificadores, columnas de CSV, claves de `config.json`, flags, valores de estado); la prosa (comentarios, docstrings, mensajes, documentos) **en español**. Voseo en la documentación (`corré`, `mirá`). Los textos de pantalla (encabezados de tablas del CLI, etiquetas de la UI) quedan en español.
- **Sin tildes ni eñes en el código ni en las salidas del CLI**; con tildes en los `.md`.
- Las convenciones de `src/` y `tests/` están en `.claude/rules/` y se cargan al tocar esos archivos.
- Errores esperados: `ValueError`, `FileNotFoundError` o `RuntimeError`; `cli.main` los imprime como `ERROR: ...` con código 1.

## Seguridad de datos

- **No se edita a mano** `calib/templates/`, `runs/**/truth.csv` ni `runs/**/test.csv` (hay reglas que lo bloquean). Los cambios van por los comandos `teach`.
- Las pruebas que **escriben** se hacen sobre una copia: `--calib-dir <carpeta temporal>` o archivos en el directorio temporal de la sesión.
- Antes de una operación destructiva sobre datos reales, respaldo (`old_data/` o `calib/.backups/`). Los comandos de `teach` que borran respaldan solos (los últimos 5; `teach lib restore` vuelve atrás).
- Verificar sobre datos reales (solo lectura o copias), no solo con fixtures: varios errores se vieron solo así.
- **Nada de `git commit`, `git push` ni `git reset --hard`** sin que el usuario lo pida; los commits se hacen con `/commit`.

## Trampas del entorno (Windows + Git Bash)

- Los heredocs de Python con barras invertidas (`\n`, `\\`) se corrompen: escribir el script a un archivo y ejecutarlo.
- Listar los directorios de fotogramas es muy lento: contar con `frames_index.csv`.
- `.venv/Scripts/python` es el intérprete del proyecto.

## Agentes (`.claude/agents/`)

| agente | hace | escribe en |
|---|---|---|
| `developer` | implementa funciones y arregla bugs | `src/**`, `pyproject.toml`, `requirements.txt` |
| `test` | escribe y ejecuta tests; reporta bugs con un caso mínimo | `tests/**` |
| `refactor` | reestructura sin cambiar el comportamiento | `src/**`, `tests/**` (solo imports) |
| `writer` | documentación pedagógica; verifica los ejemplos con comandos de solo lectura | `README.md`, `docs/**`, `PLAN*.md`, `CLAUDE.md` |

Cada agente tiene un hook que **bloquea** las escrituras fuera de su zona y le dice a quién le toca
(`.claude/hooks/scope_guard.py`; el `writer` además solo puede correr comandos de lectura). Los agentes
nuevos se leen al iniciar la sesión o desde `/agents`.

**Flujo de una función nueva:** plan → `developer` implementa y corre la suite existente → `test` agrega los tests
y comprueba por mutación que fallan → (`refactor` si el código quedó torcido) → `writer` actualiza la
documentación y verifica los comandos → el usuario hace el commit. Los agentes **no hacen commits**.

Skills del proyecto (`.claude/skills/`): `diagnose-reading`, `testing-patterns`, `docs-style`, `ds-fundamentals`, `docs-sync`.
Además de las globales (`commit`, `simplify`, `code-review`).
