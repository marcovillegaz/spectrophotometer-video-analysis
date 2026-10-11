> **Plan cerrado.** Se implementó en la Fase 2 del plan v5 (commits `e7a2f66..361707d`,
> 2026-10-10) y se movió de la raíz a `docs/historia/` en la Fase 5 (2026-10-11). Los comandos
> `teach --…` que cita son la sintaxis **anterior**, la que este plan reemplazó; la vigente está en
> la referencia de `teach` del `README.md`. El seguimiento del plan v5 está en `PLAN_CONTINUACION.md`.

# Plan: comandos de `teach` por área (biblioteca global, entrenamiento, muestras y pruebas)

## Contexto

`teach` creció con cada función nueva y hoy es **un solo comando con ~30 flags**, casi todos "modos" (`--build`, `--eval`, `--suggest`, `--library`, `--delete`, `--all-runs`…). Eso trae tres problemas que ya aparecieron al usarlo:

1. **Mezcla lo global con lo de cada corrida.** La biblioteca (`calib/templates/`) es **una sola para todos los videos**, pero `teach --run <id> --library` obliga a nombrar una corrida para listarla. Y las muestras de entrenamiento (`truth.csv`) y de prueba (`test.csv`) son **por corrida**, sin una forma simétrica de verlas.
2. **`--run <id>` en casi todo.** Hasta lo que no depende de una corrida lo pide, o necesita un flag especial (`--all-runs`, `--eval-all`) para saltearlo.
3. **Flags que solo valen combinados.** `--keep` sin `--build`, `--exclude-runs` sin `--all-runs`, `--for` solo con `--suggest`: el parser no puede expresar esas reglas, y se validan a mano en `cmd_teach` (~150 líneas que deciden el modo mirando flags).

Lo que pediste:
- `--library` sin referencia a una corrida, y una forma de ver la biblioteca de entrenamiento de cada corrida (`truth`): `teach --library global` / `teach --library <id>`.
- Un sistema más amigable que cubra **gestionar la biblioteca global**, **entrenar con las muestras de cada corrida** y **gestionar las pruebas**, sin repetir `--run <id>`.

Decisiones que tomaste:
- **Subcomandos por área**, en vez de flags con valor (sustantivo + verbo; cada comando solo acepta sus flags).
- **Los flags actuales se reemplazan en este cambio** (no quedan como obsoletos).
- **El id de corrida va como argumento posicional, completo y explícito** (`teach test eval img_8112`). Sin abreviaturas y sin "run activo": nunca se adivina sobre qué experimento se trabaja.

---

## El árbol de comandos

nuevo: Batch debe hacer un reporte. 

```
python -m spectro teach <área> <verbo> [argumentos]
```

| área      | para qué                                                                        | comandos                                                                                                                     |
| --------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `status`  | panorama de todo                                                                | `teach status`                                                                                                               |
| `lib`     | **la biblioteca global** (`calib/templates/`), sin corrida                      | `list [--usage]` · `delete NOMBRE…` · `relabel NOMBRE CARÁCTER` · `clear --yes` · `backups` · `restore [NOMBRE]`             |
| `train`   | **entrenar**: construye la biblioteca global desde las muestras de las corridas | `teach train [RUN …] [--exclude RUN …] [--keep] [--max-per-label N]`                                                         |
| `check`   | validar las muestras sin tocar la biblioteca                                    | `teach check [RUN …]`                                                                                                        |
| `samples` | las muestras de **entrenamiento** de una corrida (`truth.csv`)                  | `list [RUN]` · `add RUN ARCH=VALOR…` · `remove RUN ARCH…` · `suggest RUN [N]` · `label RUN`                                  |
| `test`    | las **pruebas** de una corrida (`test.csv`)                                     | `list [RUN]` · `add RUN ARCH=VALOR…` · `remove RUN ARCH…` · `suggest RUN [N]` · `label RUN` · `eval [RUN …]` · `history RUN` |

Equivalencias con lo que pediste: `teach --library global` → **`teach lib list`**, y `teach --library <id>` → **`teach samples list <id>`**.

### Qué hace cada uno

**Biblioteca global (`lib`)** — no recibe corrida.
- `lib list` muestra la biblioteca por carácter (cantidad y nombres de archivo), el total y los caracteres que faltan. Con `--usage` suma, sobre las muestras de **todas** las corridas, cuántas celdas gana bien (`uses`) y cuántas gana mal (`errors`) cada plantilla, y marca las dañinas y las sin uso. Es el equivalente en consola de la vista `Gestionar biblioteca`.
- `lib delete`, `lib relabel` y `lib clear --yes` modifican la biblioteca. `clear` sin `--yes` falla con un mensaje.
- **Respaldo automático:** antes de cualquier cambio destructivo (`train` que reemplaza, `delete`, `relabel`, `clear`) se copia la biblioteca a `calib/.backups/<fecha_hora>/` y se conservan los últimos 5. `lib backups` los lista y `lib restore [NOMBRE]` vuelve al último (o al indicado), respaldando antes el estado actual. Es la red de seguridad para el error que ya pasó una vez: `--build` pisó la plantilla `-`.

**Entrenar (`train`, `check`)**
- `teach train` (sin corridas) usa las muestras de **todas** las corridas con `truth.csv`; `teach train img_8102 img_8106` usa solo esas; `--exclude img_8112` deja afuera una corrida (la reservás como prueba). Reemplaza la biblioteca; con `--keep` suma sin duplicar. `--max-per-label` pasa a **3** por defecto (medido: igual de bueno que 6, con la mitad de plantillas y de tiempo de `read`).
- Cada corrida se recorta con su propia config; imprime el leave-one-out por corrida, la biblioteca vigente y escribe `runs/<id>/out/teach_report.csv`. No usa los `test.csv`.
- `teach check` hace lo mismo pero **sin escribir la biblioteca**.

**Muestras de entrenamiento (`samples`) y pruebas (`test`)** — simétricas, con la corrida como primer argumento.
- `list` sin corrida da una tabla de todas; con corrida lista sus muestras (archivo, `t`, valor), la cobertura de `0-9 . -` y cuántas lee bien la biblioteca vigente.
- `add` / `remove`: `samples add` saca la muestra de la prueba si estaba (y viceversa): un fotograma está en un solo conjunto. Mover de entrenamiento a prueba avisa que ya aportó glifos a la biblioteca.
- `suggest RUN [N]` (N=20): `samples suggest` acepta `--strategy mixed|uncertain|random|uniform`; `test suggest` es siempre al azar y lejos del entrenamiento. Ambos aceptan `--seed` y `--gap`.
- `label RUN [--queue N]` abre la UI: `samples label` con `Entrenam.` activo, `test label` con `Prueba` activo.
- `test eval` **sin corridas** evalúa todas las que tengan prueba y muestra una tabla. Con **una** corrida da el informe detallado, escribe `test_report.csv` y agrega la fila a `teach_history.csv`. `test history RUN` muestra la curva de aprendizaje (con la diferencia contra la ronda anterior).

**`teach status`** — un panorama: la biblioteca (plantillas, caracteres faltantes, respaldos), una fila por corrida (muestras, pruebas, última evaluación) y, al final, el **siguiente paso sugerido** con reglas simples: biblioteca vacía → `teach train`; muestras más nuevas que la biblioteca → `teach train`; corridas con prueba sin evaluar → `teach test eval`.

---

## Cómo se implementa

### Estructura
- **`src/spectro/teach_cli.py` (nuevo)**: registra el árbol de subparsers y tiene un handler corto por verbo. `cli.py` solo lo registra. Los handlers calculan sus rutas con `RunPaths` / `CalibPaths` (todas derivadas del id y de `--runs-dir` / `--calib-dir`, que ya son flags globales), así que se eliminan los flags de ruta de `teach` (`--truth`, `--test`, `--teach-report`, `--history`, `--test-report`, `--readings`, `--qc-report`, `--frames-dir`, `--templates-dir`). Para probar sobre una copia basta `--calib-dir`.
- Todos los subcomandos de `teach` llevan `needs_paths=False`: no pasan por `resolve_paths`, que hoy exige `--run` y obligaba a los hacks `eval_all` / `all_runs`.
- Helpers compartidos: `project.require_run(id, runs_dir, calib_dir)` (valida que exista y, si no, lista las corridas disponibles, igual que hoy el error de `--run` ausente), un `RunContext` (config, fotogramas, offsets, lista de QC) que reemplaza a `_teach_context`, y la construcción del `Namespace` con las rutas que `teach_ui.run_teach_ui` ya espera (**la UI no cambia**).
- **Se elimina** de `cli.py`: `cmd_teach`, `_teach_context`, `_teach_suggestions`, `_teach_eval_all`, `_teach_all_runs`, los ~30 flags de `teach`, el bypass `eval_all`/`all_runs` de `resolve_paths` y las claves `truth`/`teach_report`/`test`/`test_report`/`history` de `_DERIVED_PATHS`. `teach` sin área muestra la lista de áreas, y el `--help` de `teach` lleva una tabla de migración "antes → ahora".

### Núcleo (`teach.py`)
- `backup_library(dir, keep_last=5)`, `list_backups(dir)` y `restore_backup(dir, name=None)`. `write_library` en modo reemplazo respalda antes si hay plantillas.
- `DEFAULT_MAX_PER_LABEL = 3`, usado por el CLI y por la UI.
- Se reutilizan sin cambios: `gather_runs`, `build_pool_runs`, `validate`, `evaluate_library`, `split_by_run`, `add_to_library`, `list_library`, `library_usage`, `delete_templates`, `relabel_template` (`teach.py`), `suggest` y `assign` (`sampling.py`), `evaluate_test`, `append_history` y `load_history` (`evaluation.py`).
- `.gitignore`: `calib/.backups/`.

---

## Documentación
- **README**: la sección `teach` se reescribe con el árbol de comandos, un ejemplo por área y la tabla de migración (los flags viejos ya no existen). Se actualiza el flujo por rondas y el Quickstart.
- **`docs/GUIA_CALIBRACION.md`**: todos los bloques de comandos y la referencia rápida pasan a los comandos nuevos.
- **`docs/ARQUITECTURA.md`**: `teach_cli.py` en la tabla de módulos y una decisión de diseño nueva: por qué subcomandos por área y no flags de modo (una acción = un verbo, flags solo válidos para ese verbo), por qué el id va explícito y sin run activo, y el respaldo automático.
- Se buscan y reemplazan todos los `teach --run …` que queden en los tres documentos.

## Tests
- **Se migran** a los comandos nuevos los tests de CLI que hoy usan flags: la parte de `main()` de `tests/test_evaluation.py` y todo `tests/test_teach_all_runs.py`. La lógica de núcleo (`test_teach.py`, `test_teach_library.py`, UI) no cambia.
- **`tests/test_teach_cli.py` (nuevo)**:
  - `lib list` no necesita corrida, y `--usage` marca la plantilla dañina;
  - `lib delete` / `relabel` / `clear` (con y sin `--yes`), respaldo automático, `backups` y `restore`;
  - `train` con todas / con corridas elegidas / `--exclude` / `--keep`, `--max-per-label` por defecto 3 y la prueba que nunca entra;
  - `check` no escribe la biblioteca;
  - `samples` y `test`: `list` sin y con corrida, `add` y `remove` (un solo conjunto, con el aviso), `suggest` (azar y lejos del entrenamiento para prueba), `history`;
  - `test eval` con una corrida (informe + historial) y sin corridas (tabla);
  - `status` con y sin biblioteca;
  - errores claros: corrida inexistente (lista las disponibles), `clear` sin `--yes`, flag inexistente.

## Verificación
1. `.venv/Scripts/python -m pytest -q` en verde, con los tests migrados y los nuevos.
2. Sobre tu proyecto real, **solo lectura**: `teach status`, `teach lib list`, `teach lib list --usage`, `teach samples list`, `teach samples list img_8102`, `teach test list`, `teach test history img_8102` y `teach test eval`.
3. Los comandos que escriben (`train`, `lib delete`, `lib clear`, `lib restore`) se ejecutan contra una **copia de `calib/` en scratch** con `--calib-dir`, comprobando que el respaldo se crea y se puede restaurar. Las únicas escrituras en tus corridas serían los `teach_report.csv` derivados de `train` / `check`.
4. `--help` de cada área, y que `teach --run img_8102 --suggest 5` (comando viejo) falle con el mensaje de migración.
5. Todos los comandos de la guía y del README se ejecutan tal cual aparecen.
