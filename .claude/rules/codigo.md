---
paths:
  - "src/**/*.py"
---

# Convenciones de código (`src/spectro/`)

- Cada módulo abre con un docstring que explica **qué hace y por qué existe**, y termina con una sección `Interfaz publica:` que lista lo que expone. Mantenela al día cuando cambie la interfaz.
- `from __future__ import annotations` en todos los módulos; `dataclass` para los datos; rutas con `pathlib.Path`.
- **Reutilizá antes de escribir.** Binarizar, recortar la ROI, cortar en celdas, rotar y calcular la NCC ya existen en `imaging.py`; la lectura de una celda, en `read.read_frame`; la identificación de muestras, en `teach.py`. No dupliques esa lógica: una diferencia mínima entre quien arma la biblioteca y quien lee hace caer la correlación sin dejar rastro.
- **Un solo lugar para cada cosa:** la rotación se aplica en `imaging.load_frame`; las rutas de una corrida salen de `project.RunPaths` y las de `calib/` de `project.CalibPaths`; el esquema de `config.json` vive solo en `config.py`.
- **Lógica pura y bucles delgados.** En las UI (`calib_ui.py`, `teach_ui.py`) el estado, las acciones, el layout y la vista previa son funciones puras sin ventana; el loop de OpenCV solo lee eventos y dibuja. Así se testean sin pantalla.
- `cli.py` importa los módulos pesados **dentro de cada handler** (importación perezosa) para que `doctor` funcione aunque falte una dependencia.
- **Mensajes y errores:** en español **sin tildes ni eñes** (consola de Windows). Lo esperable se señala con `ValueError`, `FileNotFoundError` o `RuntimeError`, con un mensaje que diga **qué hacer**; `cli.main` los imprime como `ERROR: ...` con código 1. No uses `print` de depuración.
- **Compatibilidad de datos:** los CSV y JSON que ya existen en disco tienen que seguir cargando. Un campo nuevo se agrega con valor por defecto y la carga tolera su ausencia (como `margen` en `readings.csv` o `sign_slot` en `config.json`).
- Tipos concretos y nombres que describan el dominio (`muestras`, `confianza`, `margen`, `plantillas`); los verbos técnicos pueden estar en inglés (`read_frame`, `build_pool`).
- No agregues dependencias sin pedirlo: el proyecto usa `numpy`, `opencv-python`, `imageio-ffmpeg`, `pandas` y `matplotlib`.
