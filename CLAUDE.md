# spectro — guía para trabajar en este proyecto

Convierte el **video de la pantalla de un espectrofotómetro** en una serie de **absorbancia vs tiempo** (CSV).
El lector es un clasificador de vecino más cercano (1-NN): compara cada celda del número contra una
**biblioteca de plantillas** con correlación cruzada normalizada (NCC). No hay OCR ni red neuronal.

```
video → extract → qc → read → report → absorbancia.csv
                       ↑
        teach (etiquetar, entrenar la biblioteca y medirla)
```

## Comandos

- **Tests:** `.venv/Scripts/python -m pytest -q` (~3 s, sin videos reales, fixtures sintéticas).
- **CLI:** `.venv/Scripts/python -m spectro --help` y `... teach --help`. El paquete está instalado en modo editable.
- **Documentación de usuario:** `README.md` (uso), `docs/GUIA_CALIBRACION.md` (proceso y fundamentos),
  `docs/ARQUITECTURA.md` (decisiones), `docs/CONFIG.md` (campos de `config.json`).
- **Planes:** `PLAN_v*.md` en la raíz. `PLAN_v5.md` reestructura `teach` por áreas (todavía no implementado).

## Dónde vive cada dato

| qué | dónde | alcance |
|---|---|---|
| biblioteca de plantillas | `calib/templates/` | **global**, compartida por todos los videos |
| receta de referencia | `calib/config.json`, `calib/reference.jpg` | global; solo siembra corridas nuevas y sirve a `calibrate --auto` |
| config de una corrida (ROI, rotación, celdas, umbrales) | `runs/<id>/config.json` | por corrida; **es la que usa `read`** |
| muestras de entrenamiento | `runs/<id>/truth.csv` | por corrida |
| muestras de prueba | `runs/<id>/test.csv` | por corrida; **nunca entran a la biblioteca** |
| fotogramas | `runs/<id>/frames/` | por corrida, regenerables (no listarlos: son miles) |

`read` toma de `calib/` **solo** `templates/`; todo lo demás sale de `runs/<id>/config.json`.

## Invariantes de diseño (no romperlos)

- **Descartar antes que adivinar.** Una lectura dudosa se descarta y deja un hueco; no se interpola ni se inventa.
- **Todo recorte de celda usa el corrimiento de cámara que midió `qc`**, igual que `read`. Si no, la biblioteca no coincide con lo que se lee.
- **La rotación se aplica en un solo lugar:** `imaging.load_frame`. La binarización y el recorte también viven en `imaging.py`.
- **Las UI tienen la lógica pura** (estado, acciones, layout, vista previa) y el loop de OpenCV delgado, para poder testearla sin ventana.
- **Las muestras de varias corridas se identifican como `corrida/archivo`**: los videos repiten nombres de fotograma.
- **La prueba nunca entra a la biblioteca**, y una etiqueta equivocada contamina a todos los videos (la biblioteca es compartida).

## Convenciones

- Comentarios, docstrings, mensajes y documentos **en español**. Voseo en la documentación (`corré`, `mirá`).
- **Sin tildes ni eñes en el código ni en las salidas del CLI**; con tildes en los `.md`.
- Las convenciones de `src/` y `tests/` están en `.claude/rules/` y se cargan al tocar esos archivos.
- Errores esperados: `ValueError`, `FileNotFoundError` o `RuntimeError`; `cli.main` los imprime como `ERROR: ...` con código 1.

## Seguridad de datos

- **No se edita a mano** `calib/templates/`, `runs/**/truth.csv` ni `runs/**/test.csv` (hay reglas que lo bloquean). Los cambios van por los comandos `teach`.
- Las pruebas que **escriben** se hacen sobre una copia: `--calib-dir <carpeta temporal>` o archivos en el directorio temporal de la sesión.
- Antes de una operación destructiva sobre datos reales, respaldo (`old_data/` o `calib/.backups/`).
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
