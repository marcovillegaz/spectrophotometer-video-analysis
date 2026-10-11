# Continuación del plan v5 — dónde estamos y cómo seguir

Actualizado: 2026-10-11, al cierre de la Fase 5 (fases 0 a 5 hechas y commiteadas; falta la Fase 6). El plan original se escribió fuera del repositorio; todo lo que sigue vigente de él ya está en este documento, que resume lo hecho, **ajusta** las fases que faltan con lo que se aprendió y dice cómo retomar en una sesión nueva.

## 1. Estado

| fase | qué | estado |
|---|---|---|
| 0 | Red de seguridad: snapshot, golden de `read`, tests de caracterización, `pytest-cov` | **hecha** |
| 1 | Núcleo único (`library.py`, `cell_glyphs`, `RunContext`, evaluador único), guarda de recorte, eliminación de `templates` | **hecha** |
| 2 | `teach` por áreas (`teach_cli.py`), huella de la biblioteca, reporte de `batch` | **hecha** |
| 3 | UIs con base común y loop delgado | **hecha y commiteada** (`e30343d`); la prueba manual de la UI ya se hizo; se quitó el teclado numérico de botones de `teach` |
| 3.5 | Convención de nombres en inglés (identificadores, CSV, flags, config) | **hecha y commiteada** (`e30343d`, junto con la Fase 3) |
| 4 | Tests nuevos y piso de cobertura | **hecha y commiteada** (`76f8b9a`, 2026-10-11): 973 passed; `tests/check_cobertura.py` verifica el piso de 85 % en `library`, `teach_cli`, `evaluation` y `teach_session` (hoy 97–100 %) |
| 5 | Documentación con fuente única | **hecha y commiteada** (`0d94eba` documentos, `8cde925` reglas, skills y `check_docs.py`; 2026-10-11). Después se reorganizó en carpetas (ver [Fase 5](#fase-5--documentación-agente-writer--sesión-principal)); esa reorganización está **sin commitear**. Las cifras del Quickstart se completan tras la Fase 6 |
| 6 | Entrenamiento final (lo hacés vos) | pendiente |
| cierre | Commitear salidas y datos del entrenamiento (`runs/*/out/`, `calib/templates/`, `truth.csv`/`test.csv`, `batch_report.csv`) | pendiente |

**Medido al cierre de la Fase 1:** 419 tests en verde y 2 rotos a propósito (`tests/test_docs.py`, porque el README todavía cita el comando `templates`, que ya no existe; se arregla en la Fase 5). Cobertura de partida (Fase 0): 73 %. `read` sobre las 4 corridas es idéntico byte a byte al golden de la Fase 0.

**Medido al cierre de la Fase 2 (2026-10-10):** 714 tests en verde y 2 rotos a propósito (otra vez solo `tests/test_docs.py`: el README y la guía de calibración (hoy `docs/calibrar/guia.md`) citaban el comando `templates` y los flags viejos de `teach`; se arregla en la Fase 5). La suite tarda ~25-30 s. Cobertura: `library.py` 96 %, `teach_cli.py` 99 %, `evaluation.py` 97 %, `report.py` 97 %, total 83 %. `read` de `img_8110` sigue idéntico al golden (SHA256 `7093f654...47d44`).

**Medido al cierre de la Fase 3 en código (2026-10-11):** 901 passed, 1 xfailed y las 2 de `test_docs` rotas a propósito. `read` de `img_8110` idéntico al golden. `/code-review high`: 10 hallazgos, todos corregidos (umbrales de qc sin filas descartadas, respaldo al abrir la sesión, `respaldar` en `delete`/`relabel`, `is_slow`, `DEFAULT_SUGGEST_SEED`, centinela en `RunContext`). Sin commitear. Falta la prueba manual de las ventanas. Para el `writer` (Fase 5, ya resuelto): la referencia de config (hoy `docs/referencia/config.md`) documentaba `cluster_hamming`; `--seed` ahora es `None` (el botón Aleatorio es reproducible solo con `--seed`).

### Lo que no hay que perder de vista

- **Lo hecho hasta la Fase 5 está commiteado.** Fases 0 y 1: 12 commits, `aea57e4..72dab9e` (más `5d37302`, que registró ese cierre en los planes). Fase 2: 4 commits, `e7a2f66..361707d` (ver [§3, Fase 2](#fase-2--teach-por-áreas-y-reporte-de-batch-hecha)). Fases 3 y 3.5: `e30343d`. Fase 4: `76f8b9a`. Fase 5: `0d94eba` y `8cde925`. Quedan sin commitear la reorganización de `docs/` en carpetas y las salidas `runs/*/out/` (se commitean al final, tras la Fase 6). Las copias de `old_data/` siguen siendo la red de seguridad.
- **La biblioteca actual no tiene la plantilla `-`.** Con ella, `read` descarta ~90 % de 8102 y 8106 (medido; ver `docs/historia/AUDITORIA_v5.md` §4.1). Hasta la Fase 6 las lecturas de esas dos corridas no son representativas.
- **Estado de los datos reales al cierre de la Fase 2** (según `teach status` y `teach lib list --usage`, 2026-10-10): las 4 corridas figuran `desactualizadas` (8102, 8106) o `sin_huella` (8110, 8112), porque todavía no tienen `out/read_meta.json` (se crea en la próxima `read`); sigue faltando la plantilla `-`; `img_8110` no tiene muestras de `-`; la plantilla `1_0` aparece marcada como dañina en `lib list --usage`. Todo eso se resuelve en la Fase 6.
- **`old_data/` se conserva** (decisión tuya). Contiene `golden_f0/` (con `SHA256SUMS.txt`), `snapshot_f0_20261010/`, `snapshot_f1_20261010/` y el respaldo viejo.
- `calib/.backups/pre_v5_20261010/` es la biblioteca previa al plan. La poda automática (últimos 5) no lo toca.

## 2. Cómo retomar en una sesión nueva

1. Leé este documento y la sección de la fase que sigue (§3).
2. Comprobá la línea de base: `.venv/Scripts/python -m pytest -q` debe dar **975 passed** (medido el 2026-10-11, tras la reorganización de `docs/`; ~30-50 s). Si no, algo cambió desde este documento.
3. Antes de empezar cada fase, copiá el árbol: `old_data/snapshot_f<N>_<fecha>/` con `src`, `tests`, `docs` (incluye `docs/plans/`), `README.md`, `CLAUDE.md`, `pyproject.toml`, `requirements.txt`.
4. Ejecutá la fase con el agente indicado (ver §3) y verificá vos el resultado antes de darla por buena: suite, golden y, en las fases con cambio de comportamiento, `/code-review high`.
5. Al cerrar la fase, actualizá la tabla de §1 y commiteá con `/commit`.

**Verificación del golden** (cuesta ~25 minutos para las 4 corridas; 8110 sola tarda ~2 y alcanza como prueba rápida). Siempre con copias en scratch, nunca sobre `runs/`:

```bash
cp runs/img_8110/out/qc_report.csv "$TEMP/qc.csv"
.venv/Scripts/python -m spectro read --run img_8110 --qc-report "$TEMP/qc.csv" --readings "$TEMP/r.csv"
sha256sum "$TEMP/r.csv"   # comparar con old_data/golden_f0/SHA256SUMS.txt
```

Ojo: desde la Fase 2, `read` escribe además `out/read_meta.json` (la huella de la biblioteca), pero `readings.csv` no cambió de formato, así que la comparación con el golden sigue siendo válida (comprobado en `img_8110` al cerrar la Fase 2).

## 3. Las fases

### Fase 2 — `teach` por áreas y reporte de `batch` (hecha)

**Qué se hizo** (agentes `developer` y `test`, cerrada el 2026-10-10):
- Módulo `teach_cli.py` con el árbol `teach status | lib | train | check | samples | test`; el id de la corrida va como posicional. Desaparecieron `cmd_teach`, `_teach_context`, `_teach_eval_all`, `_teach_all_runs` y `_run_summary`. Un `teach --<flag viejo>` falla y muestra la tabla de migración (se ve en `teach --help`).
- **Huella de la biblioteca:** `read` escribe `out/read_meta.json`; `readings.csv` no cambió de formato. `teach_history.csv` ganó la columna `huella` (los historiales viejos se migran al leerlos).
- **Reporte de `batch`:** `runs/batch_report.csv` y la misma tabla impresa, calculados por la función pura `report.batch_summary(...)`.
- **Umbrales del veredicto:** flags `--min-exactitud`, `--max-error`, `--min-cobertura` y una sección `acceptance` opcional en `calib/config.json`, **sin defaults**: sin umbrales no hay veredicto. Se fijan en la Fase 6.
- `teach status` muestra el estado `roi_fuera` entre los motivos y avisa si falta la plantilla `-` o si una corrida está `desactualizada`/`sin_huella`. El mensaje de `library.load` ahora dice `teach train`.
- Los tests de CLI con flags viejos se migraron junto con el código (no quedaron para la Fase 4).

**Commits:** `e7a2f66` feat(report): huella de biblioteca, `read_meta` y reporte de `batch`; `b2f42f1` feat(teach): `teach` por áreas con tabla de migración; `bd3c229` test: migración y cobertura; `361707d` chore(claude): quitar de `settings.json` las reglas `Write` redundantes (las `Edit` ya cubren la escritura y las `Write` daban error al iniciar `claude`; `test_claude_agents` ahora exige solo `Edit`).

**Compuerta 2 (pasada).** Suite: 714 passed, 2 failed (solo `test_docs`, previstas). Golden de `img_8110` idéntico. Comandos de solo lectura sobre los datos reales sin errores (`teach status`, `teach lib list --usage`, `teach samples list`, `teach test list`, `teach test history img_8102`, `teach test eval`); los que escriben, probados sobre copias. `/code-review high`: 10 hallazgos, todos corregidos con test (entre ellos: umbrales de `batch` validados al inicio; conteos de `load_run_input` tomados de `readings.csv`; veredicto `revisar` con `sin_lectura`/`sin_huella`; huella en `teach_history.csv` con migración de historiales viejos; `restore_backup` con `copyfile`; mensajes de respaldo; área desconocida).

**Lo que deja para después:**
- Los `config.json` que se vuelvan a guardar ahora incluyen `"acceptance"` con `null`: un diff inocuo, no un error.
- `teach test eval` sin id de corrida no agrega filas al historial. Es por diseño.
- Los pendientes de código y tests quedaron anotados en las Fases 3 y 4.

### Fase 3 — UIs con base común y loop delgado (`refactor`, luego `developer`)

**Qué se hace.**
1. `ui_common.py`: `Button`, `hit_test`, colores, texto, títulos, separadores, dibujo de cortes de slot, etiquetas de carácter, un `BaseLayout` y el esqueleto del loop de OpenCV. `calib_ui` y `teach_ui` importan de ahí; hoy `teach_ui` importa de `calib_ui`, al revés de lo esperable.
2. Un `TeachSession` puro que absorbe `run_request`, `run_eval`, `library_request`, `_reselect`, la paginación, `persist` y `refresh_library`. `apply_action` pasa a ser el único reducer (incluidas `random`, navegación, `add`, `remove`). El "avanzar tras agregar" se decide por el resultado, no por `msg.startswith`. Teclas y requests por tabla. Objetivo: `run_teach_ui` en menos de 60 líneas (hoy 232).
3. `developer`: el botón "Aleatorio" usa `random.Random(seed)` con `--seed`; `refresh_library` actualiza el pool en el lugar en vez de reconstruirlo en cada borrado.

**Pendientes que la Fase 1 dejó para esta fase:**
- **Un respaldo por sesión de UI.** Hoy cada `delete`/`relabel` respalda: borrar muchas plantillas seguidas rota los 5 respaldos y puede perder el estado previo a la sesión. Hacer que la sesión tome un único respaldo al abrir y que las operaciones de la UI lo reutilicen (p. ej. un parámetro `backup=False` en `library.delete/relabel`).
- `qc.run_qc` repite tres veces el patrón "estado de descarte y `continue`", y un `blank` por carga fallida lo pisa `classify` (queda `dark`). Es un defecto previo: arreglarlo con `refactor` y un test.
- `RunPaths.glyph_sheet` y `TemplateConfig.cluster_hamming` quedaron huérfanos (dejados por compatibilidad con los `config.json` que ya existen). Decidir si se retiran; si se retiran, que `config.load` siga aceptando los `config.json` viejos (la regla es que los archivos existentes tienen que seguir cargando).
- `RunContext.names()` vuelve a parsear el reporte de qc que `load()` ya leyó.

**Pendientes que la Fase 2 dejó para esta fase:**
- `cmd_set_label` arma a mano un `Namespace` para llamar a `run_teach_ui`. Pasar un objeto de sesión (el `TeachSession` de arriba) en su lugar.
- El loop de `run_teach_ui` sigue sin test (lo cubre la prueba manual de esta compuerta).

**Compuerta 3.** Suite verde, golden idéntico, `/code-review high`, y una **prueba manual tuya** sobre una *copia* de una corrida: abrir `teach samples label <id>` y `calibrate`, etiquetar una muestra, deshacer y cerrar. Esta es la única compuerta que necesita ojos humanos, porque los loops de OpenCV no se pueden testear sin ventana (`teach_ui.py` 506-722 tiene 0 % de cobertura).

### Fase 3.5 — Convención de nombres en inglés (`developer`, luego `test`, luego `writer`)

**Decisión (2026-10-11):** los términos técnicos de datos e informática van en **inglés** en todo lo que es *interfaz*: identificadores, columnas de CSV, claves de `config.json`, flags del CLI y valores de estado. La prosa (comentarios, docstrings, mensajes, docs) sigue en español y puede usar el término en inglés cuando no se traduce bien. Los nombres de los tests siguen en español (regla de `.claude/rules/tests.md`).

**Glosario** (español → inglés): `archivo`→`file`, `valor`→`value`, `indice`→`index`, `confianza`→`confidence`, `margen`→`margin`, `caracteres`→`chars`, `estado`→`status`, `huella`→`fingerprint`, `contraste`→`contrast`, `absorbancia`→`absorbance`, `exactitud`→`accuracy`, `cobertura`→`coverage`, `umbral`→`threshold`, `respaldo/respaldar`→`backup`, `roi_fuera`→`roi_outside`, `acceptance` queda. Flags: `--min-exactitud`→`--min-accuracy`, `--min-cobertura`→`--min-coverage`.

**Compatibilidad (no negociable):** los archivos que ya existen siguen cargando. Los lectores aceptan los encabezados/claves/estados viejos (mapa de alias en un solo lugar) y los escritores emiten los nuevos. No se reescribe ningún `truth.csv`/`test.csv`/`config.json` real salvo cuando la herramienta los guarda por su cuenta. Un flag viejo falla mostrando la tabla de migración, como en la Fase 2.

**Verificación:** el golden cambia de encabezado, así que se compara por contenido: mismo `read` de `img_8110` con las columnas renombradas, valor por valor. Snapshot previo: `old_data/snapshot_f3c_20261011/`.

**Cierre (2026-10-11):** 957 passed, 1 xfailed y las 2 de `test_docs` rotas a propósito. `read` de `img_8110`: 3782 filas, 0 diferencias de contenido contra el golden (comparado con los encabezados renombrados). Alias en `src/spectro/compat.py`; 54 tests nuevos en `tests/test_compat.py`. `absorbancia.csv` pasó a `absorbance.csv` (el viejo se lee como respaldo y nunca se borra). **Decidido:** los textos de pantalla (encabezados de tablas del CLI, metavars, etiquetas de la UI) quedan en español. Huecos de test: `teach_history.csv` viejo vía CLI y `batch --skip-existing` con `absorbancia.csv` viejo. Para la Fase 5: la documentación completa debe usar este glosario.

**Fuera de alcance:** renombrar carpetas o módulos que ya están en inglés; la documentación de usuario (Fase 5, usa este glosario).

### Fase 4 — Tests (agente `test`)

- Los tests de CLI con flags viejos ya se migraron en la Fase 2 (`bd3c229`). De la lista siguiente, `test_teach_cli.py` y `test_batch_report.py` ya existen desde la Fase 2: ampliarlos, no recrearlos.
- Nuevos: `test_teach_cli.py`, `test_library.py`, `test_batch_report.py`, `test_teach_session.py`, `test_ui_common.py`.
- **Pendientes que dejó la Fase 2:** la poda a 5 respaldos y el sufijo `_2`..`_10` de respaldos en el mismo segundo siguen sin test.
- **Cubrir lo que la Fase 1 dejó sin test directo:** `backup`/`list_backups`/`restore_backup`/`clear` (incluido el sufijo `_2`..`_10` de respaldos en el mismo segundo y la poda a 5), `delete`/`relabel`/`write` que respaldan, `DEFAULT_MAX_PER_LABEL == 3`, `warn_missing_sign` en `read` y en `train`, que `templates` ya no es un comando, `qc.run_qc` con un fotograma chico y sidecar válido, y `teach --eval` con una corrida `--roi-only` completa.
- Por cada test nuevo, una **mutación** que lo haga fallar (skill `testing-patterns`), documentada en el informe del agente.
- Cobertura: piso del 85 % para `library.py`, `teach_cli.py`, `evaluation.py` y la sesión de teach, en `pyproject.toml` (todavía **no está fijado**; al cierre de la Fase 2 esos módulos ya están en 96 %, 99 % y 97 %). No fijar un piso global: el total (73 % en la Fase 0, 83 % al cierre de la Fase 2) incluye módulos que este plan no toca (`extract`, `calibrate`).

**Compuerta 4.** Suite verde, mutaciones documentadas, cobertura sobre el piso.

### Fase 5 — Documentación (agente `writer` + sesión principal)

Estructura de fuente única (decidida):

| documento | cubre | deja de cubrir |
|---|---|---|
| `README.md` | instalación, Quickstart con `img_8102`, carpetas, **referencia de comandos y flags**, salidas, troubleshooting | el ciclo de calibración (2 líneas + enlace) |
| `docs/GUIA_CALIBRACION.md` | el proceso por rondas (5 bloques), ejemplo, diagnóstico y la ronda final | su §6 de referencia de flags |
| `docs/ARQUITECTURA.md` | módulos, contratos y decisiones | el layout de carpetas |
| `docs/CONFIG.md` | todos los campos, incluido `acceptance` | |
| `CLAUDE.md` | invariantes, convenciones y trampas | las tablas de datos y documentos pasan a enlaces |
| `docs/historia/` | `AUDITORIA_v5.md` y planes cerrados | |

**Trabajo concreto que ya se sabe:**
- Reescribir las ~70 menciones de `teach --…` (GUIA: 40, README: 20, PLAN_v5: 7, ARQUITECTURA: 2, más una en `CLAUDE.md` y en dos skills).
- Quitar del README las líneas de `templates` (~297 y ~309): esto arregla las 2 pruebas rotas de `test_docs`.
- Quitar la corrida `20260901_164220` del Quickstart y del árbol de carpetas (ya no existe).
- Quitar de `docs/CONFIG.md` los campos sin uso (`cluster_hamming`, `min_count`) o marcarlos como ignorados, según lo que se decida en la Fase 3.
- Documentar el estado nuevo `roi_fuera` y el `read_meta.json`.
- Actualizar la tabla de módulos de `ARQUITECTURA.md` (el informe del `refactor` de la Fase 1 trae la lista de lo nuevo: `library`, `RunContext`, `cell_glyphs`/`CellGlyph`/`read_roi`, `qc.load_offsets`, `DigitsConfig.expected_chars`/`required_chars`, `evaluation.evaluate`, `teach.train`/`parse_value`, y la baja de `templates.py`).
- **Sesión principal** (el `writer` no puede tocar `.claude/`): ampliar `.claude/skills/docs-sync/scripts/check_docs.py` para revisar comandos citados en prosa entre backticks y avisar de ids de corrida inexistentes; actualizar las skills `diagnose-reading` y `testing-patterns`.
- Las cifras del Quickstart se toman **después** de la Fase 6, no antes.

**Compuerta 5.** `test_docs.py` verde con el verificador ampliado, búsqueda sin ningún `teach --<flag viejo>`, y los comandos de solo lectura de los docs ejecutados tal cual.

**Las rutas de esta sección son las de entonces.** La tabla y la lista de arriba son lo que se decidió antes de escribir; la reorganización posterior (abajo) cambió las rutas.

**Lo que hizo el `writer` (2026-10-11).** README, guía, ARQUITECTURA, CONFIG y CLAUDE.md reescritos con la estructura de la tabla y el glosario de la Fase 3.5. `AUDITORIA_v5.md` y `PLAN_v5.md` copiados a `docs/historia/` con una nota de procedencia (el `writer` no puede borrar: los originales `docs/AUDITORIA_v5.md` y `PLAN_v5.md` los quita la sesión principal con `git rm`). `min_count` nunca fue un campo de `config.json` (era el flag `--min-count` del viejo `templates`): CONFIG solo documenta `cluster_hamming` como clave ignorada. Las cifras del Quickstart y del resultado de la ronda final quedan marcadas **Pendiente** hasta la Fase 6.

**Reorganización en carpetas (2026-10-11, sin commitear).** La documentación pasó a una estructura por tarea, con el mapa de documentos como única lista en el README:

| antes | ahora |
|---|---|
| README: instalación | `docs/empezar/instalar.md` |
| README: Quickstart, re-calibrar una corrida, Excel | `docs/empezar/primera-corrida.md` |
| `docs/GUIA_CALIBRACION.md` §1-3 y §5 | `docs/calibrar/guia.md` (la ronda final pasó a ser §4) |
| `docs/GUIA_CALIBRACION.md` §4 (ejemplo) | `docs/calibrar/ejemplo-img_8102.md` |
| README: Troubleshooting + guía §6 | `docs/diagnosticar/problemas.md` |
| README: referencia de comandos / formato de salida / carpetas | `docs/referencia/comandos.md`, `salidas.md`, `carpetas.md` |
| `docs/CONFIG.md` | `docs/referencia/config.md` |
| `docs/ARQUITECTURA.md` | `docs/diseno/arquitectura.md` y `docs/diseno/decisiones.md` |
| README: Tests | `docs/contribuir.md` (con flujo de agentes, convenciones y trampas) |
| `PLAN_CONTINUACION.md` (raíz), `docs/historia/PLAN_v5.md` | `docs/plans/` |

### Fase 6 — Entrenamiento final (vos, con la guía)

1. `teach status`: línea de base y avisos (sobre todo el `-` faltante). Al cierre de la Fase 2, además, `teach lib list --usage` marca como dañina la plantilla `1_0`: revisarla antes de entrenar.
2. Cubrir el signo: `teach samples label img_8102` (y `img_8110`, que no tiene negativos en `truth.csv`) hasta que `status` no avise.
3. Ampliar la prueba donde sea chica (`teach test suggest <id> 20`, `teach test label <id>`).
4. `teach train` → `teach test eval`. Iterar con `samples suggest --strategy uncertain` en las corridas que salgan peor. `img_8112` se mide primero como **video sin entrenamiento**.
5. Fijar los umbrales `acceptance` en `calib/config.json` a partir de lo medido.
6. `batch videos/*.MOV --no-skip-existing` → `absorbance.csv` por corrida y `runs/batch_report.csv` con el veredicto. Las corridas en `review` vuelven al paso 4.
7. El `writer` completa los **Pendiente** con las cifras reales: el Quickstart (`docs/empezar/primera-corrida.md`), la ronda final de la guía (`docs/calibrar/guia.md` §4) y la salida de `doctor`, que hoy muestra `absorbancia.csv`.

**Sobre los números.** Los umbrales no se fijan de antemano. Con 20–40 muestras de prueba por corrida, una exactitud del 95 % tiene un intervalo muy ancho (la auditoría lo marca para 8102), así que conviene ampliar la prueba antes de decidir los umbrales.

### Cierre — commits

Desde la Fase 2 se commitea al cerrar cada fase (con `/commit`, pidiendo el plan antes). Al final, un commit con los datos del entrenamiento: `calib/templates/`, `truth.csv`/`test.csv`, `runs/*/out/` y `runs/batch_report.csv`. Después, si ya no hacen falta, borrar los `old_data/snapshot_*`.

## 4. Decisiones que siguen abiertas

| # | decisión | cuándo | recomendación |
|---|---|---|---|
| 1 | ¿Se retiran `cluster_hamming`, `min_count` y `RunPaths.glyph_sheet`? | resuelta en Fase 3 (`e30343d`) | Retirados del código; `config.load` ignora la clave vieja (`docs/referencia/config.md`, *Claves que ya no se usan*) |
| 2 | Un respaldo por sesión de UI (ver Fase 3) | resuelta en Fase 3 (`e30343d`) | `TeachSession` toma un solo respaldo antes del primer cambio (`docs/diseno/decisiones.md`) |
| 3 | ¿El aviso del `-` en `read` va a stderr siempre o solo con `verbose`? | resuelta en Fase 2: ya sale una sola vez por corrida | Siempre en `batch`/`run` una sola vez por corrida, no por fotograma |
| 4 | Umbrales de aceptación (`acceptance`) | Fase 6 | Los fijás vos con los datos medidos |
| 5 | ¿`extract_frames` (12 parámetros) y `cmd_doctor`/`cmd_batch` se extraen a módulos? | después del plan | Dejarlo fuera: el plan ya es grande |

## 5. Riesgos

- **Los commits 3 a 5 no son autónomos** (código y tests de varias fases comparten archivos): `git bisect` entre ellos no funciona. Desde la Fase 2 los commits se hacen al cerrar cada fase y sí quedan sanos.
- **Las UIs no tienen tests del loop.** Un error en la Fase 3 puede pasar la suite y romper la ventana. Por eso la prueba manual de la Compuerta 3 no es opcional.
- **El golden tarda ~25 minutos.** Correrlo en segundo plano mientras se revisa otra cosa; 8110 sola sirve de prueba rápida.
- **Los agentes dicen "hecho" antes de que sea cierto.** En las fases 0 a 2 verifiqué por mi cuenta la suite y el golden de 8110 después de cada informe, y la revisión de código encontró problemas reales que los tests no veían (5 corregidos en la Fase 1, 10 en la Fase 2). Mantener ese hábito.

## 6. Archivos de referencia

- Plan completo: este documento (el original, fuera del repositorio, ya está volcado acá).
- Auditoría de partida: [`docs/historia/AUDITORIA_v5.md`](../historia/AUDITORIA_v5.md)
- Red de seguridad: `old_data/` (`golden_f0/`, `snapshot_f0_*`, `snapshot_f1_*`) y `calib/.backups/pre_v5_20261010/`
- Plan anterior de `teach` por áreas (cerrado en la Fase 2; el árbol de comandos sigue vigente): [`docs/plans/PLAN_v5.md`](PLAN_v5.md)
- Mapa de la documentación vigente: [README](../../README.md#mapa-de-la-documentación)
