# Continuación del plan v5 — dónde estamos y cómo seguir

Actualizado: 2026-10-10, al cierre de la Fase 1. El plan completo está en `C:\Users\marco\.claude\plans\a-partir-dela-informacion-cozy-hellman.md`; este documento resume lo hecho, **ajusta** las fases que faltan con lo que se aprendió y dice cómo retomar en una sesión nueva.

## 1. Estado

| fase | qué | estado |
|---|---|---|
| 0 | Red de seguridad: snapshot, golden de `read`, tests de caracterización, `pytest-cov` | **hecha** |
| 1 | Núcleo único (`library.py`, `cell_glyphs`, `RunContext`, evaluador único), guarda de recorte, eliminación de `templates` | **hecha** |
| 2 | `teach` por áreas (`teach_cli.py`), huella de la biblioteca, reporte de `batch` | pendiente |
| 3 | UIs con base común y loop delgado | pendiente |
| 4 | Tests nuevos y piso de cobertura | pendiente |
| 5 | Documentación con fuente única | pendiente |
| 6 | Entrenamiento final (lo hacés vos) | pendiente |
| cierre | Ejecutar los commits documentados | pendiente |

**Medido al cierre de la Fase 1:** 419 tests en verde y 2 rotos a propósito (`tests/test_docs.py`, porque el README todavía cita el comando `templates`, que ya no existe; se arregla en la Fase 5). Cobertura de partida (Fase 0): 73 %. `read` sobre las 4 corridas es idéntico byte a byte al golden de la Fase 0.

### Lo que no hay que perder de vista

- **Nada está commiteado.** Todo el trabajo (previo al plan y de las fases 0 y 1) está sin commit. Los commits propuestos están en `COMMITS_PENDIENTES.md` y se ejecutan al final con `/commit`. La red de seguridad son las copias en `old_data/`.
- **La biblioteca actual no tiene la plantilla `-`.** Con ella, `read` descarta ~90 % de 8102 y 8106 (medido; ver `docs/AUDITORIA_v5.md` §4.1). Hasta la Fase 6 las lecturas de esas dos corridas no son representativas.
- **`old_data/` se conserva** (decisión tuya). Contiene `golden_f0/` (con `SHA256SUMS.txt`), `snapshot_f0_20261010/`, `snapshot_f1_20261010/` y el respaldo viejo.
- `calib/.backups/pre_v5_20261010/` es la biblioteca previa al plan. La poda automática (últimos 5) no lo toca.

## 2. Cómo retomar en una sesión nueva

1. Leé este documento, `COMMITS_PENDIENTES.md` y la sección de la fase que sigue en el plan.
2. Comprobá la línea de base: `.venv/Scripts/python -m pytest -q` debe dar **419 passed, 2 failed** (solo las dos de `test_docs`). Si no, algo cambió desde este documento.
3. Antes de empezar cada fase, copiá el árbol: `old_data/snapshot_f<N>_<fecha>/` con `src`, `tests`, `docs`, `README.md`, `CLAUDE.md`, `PLAN_v5.md`, `pyproject.toml`, `requirements.txt`.
4. Ejecutá la fase con el agente indicado (ver §3) y verificá vos el resultado antes de darla por buena: suite, golden y, en las fases con cambio de comportamiento, `/code-review high`.
5. Al cerrar la fase, agregá la entrada a `COMMITS_PENDIENTES.md` y actualizá la tabla de §1.

**Verificación del golden** (cuesta ~25 minutos para las 4 corridas; 8110 sola tarda ~2 y alcanza como prueba rápida). Siempre con copias en scratch, nunca sobre `runs/`:

```bash
cp runs/img_8110/out/qc_report.csv "$TEMP/qc.csv"
.venv/Scripts/python -m spectro read --run img_8110 --qc-report "$TEMP/qc.csv" --readings "$TEMP/r.csv"
sha256sum "$TEMP/r.csv"   # comparar con old_data/golden_f0/SHA256SUMS.txt
```

Ojo: hasta que la Fase 2 agregue `read_meta.json`, esa comparación sigue siendo válida. Después de la Fase 2, `read` escribe un archivo más en `out/`, pero `readings.csv` no cambia de formato.

## 3. Las fases que faltan

### Fase 2 — `teach` por áreas y reporte de `batch` (agente `developer`)

**Qué se hace.** Un módulo `teach_cli.py` con el árbol del plan: `teach status | lib {list,delete,relabel,clear,backups,restore} | train | check | samples {list,add,remove,suggest,label} | test {list,add,remove,suggest,label,eval,history}`. El id de la corrida va como posicional explícito. Desaparecen `cmd_teach`, `_teach_context`, `_teach_suggestions`, `_teach_eval_all`, `_teach_all_runs`, el bypass de `resolve_paths` (`cli.py` ~119) y las claves de teach en `_DERIVED_PATHS`. Un `teach --<flag viejo>` falla con una tabla de migración.

**Lo que ya existe y se reutiliza** (de la Fase 1): `RunContext.load`, `teach.train`, `teach.parse_value`, `evaluation.evaluate`, y de `library`: `load`, `write`, `add`, `list_entries`, `usage`, `delete`, `relabel`, `clear`, `backup`, `list_backups`, `restore_backup`, `warn_missing_sign`. Los subcomandos `lib backups/restore/clear` son las llamadas directas a esas funciones: **hoy no tienen ningún llamador ni test**, así que esta fase es la primera que los ejercita de verdad.

**Agregados respecto del plan original:**
1. `teach status` avisa si falta la plantilla `-` (con `library.warn_missing_sign`) y si una corrida tiene salidas más viejas que la biblioteca.
2. **Huella de la biblioteca:** `read` escribe `out/read_meta.json` (hash, fecha, cantidad de plantillas). No se cambia el formato de `readings.csv`.
3. **Reporte de `batch`:** `runs/batch_report.csv` + la misma tabla impresa. Una fila por corrida: fotogramas, descartados por qc (por motivo, incluido el nuevo `roi_fuera`), `ok`, `low_confidence`, cobertura, exactitud y error entre aceptadas de `test.csv` (si hay), plantillas, huella y veredicto `acepta` / `revisar`. Cálculo en una función pura `report.batch_summary(...)` que reemplaza a `_run_summary`.
4. **Umbrales del veredicto**: flags `--min-exactitud`, `--max-error`, `--min-cobertura` y una sección `acceptance` en `calib/config.json`. **El código no inventa defaults**: sin umbrales, el veredicto queda vacío. Los fijás vos en la Fase 6.
5. El mensaje de `library.load` hoy dice `Corre primero: python -m spectro teach --run <id> --build`. Cambiarlo a `teach train` y reescribir los textos que citen flags viejos.

**Cuidado con lo que se aprendió en la Fase 1:**
- Los handlers deben pasar el `frames_roi` de la corrida (ya lo hace `SampleData`); no reintroducir `frames_roi=None`.
- `qc`/`read` descartan fotogramas que no caben en la ROI con estado `roi_fuera`: el reporte de `batch` tiene que contarlo como un motivo más.
- El estado `roi_fuera` también debe aparecer en la tabla de motivos de `status`.

**Compuerta 2.** Suite verde (con los tests viejos de CLI migrados; esto se coordina con la Fase 4), golden idéntico, y:
- solo lectura sobre los datos reales: `teach status`, `teach lib list --usage`, `teach samples list`, `teach test list`, `teach test history img_8102`, `teach test eval`;
- los comandos que escriben (`train`, `lib delete`, `lib clear`, `lib restore`) contra una **copia** de `calib/` con `--calib-dir`: comprobar que el respaldo se crea y se restaura;
- `/code-review high` sobre el diff de la fase.

**Riesgo.** Es el cambio más grande de interfaz. Los tests de CLI con flags viejos (`tests/test_evaluation.py` parte `main()`, `tests/test_teach_all_runs.py`, partes de `tests/test_caracterizacion_f0.py`) se rompen por diseño. Convenía migrarlos junto con el código (pedírselo al agente `test` en cuanto el `developer` termine, antes de la compuerta), y no dejarlos para la Fase 4.

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

**Compuerta 3.** Suite verde, golden idéntico, `/code-review high`, y una **prueba manual tuya** sobre una *copia* de una corrida: abrir `teach samples label <id>` y `calibrate`, etiquetar una muestra, deshacer y cerrar. Esta es la única compuerta que necesita ojos humanos, porque los loops de OpenCV no se pueden testear sin ventana (`teach_ui.py` 506-722 tiene 0 % de cobertura).

### Fase 4 — Tests (agente `test`)

- Migrar los tests de CLI con flags viejos (si no se hizo en la Fase 2).
- Nuevos: `test_teach_cli.py`, `test_library.py`, `test_batch_report.py`, `test_teach_session.py`, `test_ui_common.py`.
- **Cubrir lo que la Fase 1 dejó sin test directo:** `backup`/`list_backups`/`restore_backup`/`clear` (incluido el sufijo `_2`..`_10` de respaldos en el mismo segundo y la poda a 5), `delete`/`relabel`/`write` que respaldan, `DEFAULT_MAX_PER_LABEL == 3`, `warn_missing_sign` en `read` y en `train`, que `templates` ya no es un comando, `qc.run_qc` con un fotograma chico y sidecar válido, y `teach --eval` con una corrida `--roi-only` completa.
- Por cada test nuevo, una **mutación** que lo haga fallar (skill `testing-patterns`), documentada en el informe del agente.
- Cobertura: piso del 85 % para `library.py`, `teach_cli.py`, `evaluation.py` y la sesión de teach, en `pyproject.toml`. No fijar un piso global: el 73 % de partida incluye módulos que este plan no toca (`extract`, `report`, `calibrate`).

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

### Fase 6 — Entrenamiento final (vos, con la guía)

1. `teach status`: línea de base y avisos (sobre todo el `-` faltante).
2. Cubrir el signo: `teach samples label img_8102` (y `img_8110`, que no tiene negativos en `truth.csv`) hasta que `status` no avise.
3. Ampliar la prueba donde sea chica (`teach test suggest <id> 20`, `teach test label <id>`).
4. `teach train` → `teach test eval`. Iterar con `samples suggest --strategy uncertain` en las corridas que salgan peor. `img_8112` se mide primero como **video sin entrenamiento**.
5. Fijar los umbrales `acceptance` en `calib/config.json` a partir de lo medido.
6. `batch videos/*.MOV --no-skip-existing` → `absorbancia.csv` por corrida y `runs/batch_report.csv` con el veredicto. Las corridas en `revisar` vuelven al paso 4.
7. El `writer` actualiza el Quickstart y el ejemplo de la guía con las cifras reales.

**Sobre los números.** Los umbrales no se fijan de antemano. Con 20–40 muestras de prueba por corrida, una exactitud del 95 % tiene un intervalo muy ancho (la auditoría lo marca para 8102), así que conviene ampliar la prueba antes de decidir los umbrales.

### Cierre — commits

Seguir `COMMITS_PENDIENTES.md` en orden con `/commit`: estado previo (0.1–0.10), `.gitattributes` y herramientas (1.x), Fase 1 (2.x), y las que se agreguen. Los datos del entrenamiento (`calib/templates/`, `truth.csv`/`test.csv`, `runs/*/out/`, `runs/batch_report.csv`) van al final. Después borrar `COMMITS_PENDIENTES.md` y, si ya no hacen falta, los `old_data/snapshot_*`.

## 4. Decisiones que siguen abiertas

| # | decisión | cuándo | recomendación |
|---|---|---|---|
| 1 | ¿Se retiran `cluster_hamming`, `min_count` y `RunPaths.glyph_sheet`? | Fase 3 | Retirarlos del código y dejar que `config.load` ignore las claves viejas |
| 2 | Un respaldo por sesión de UI (ver Fase 3) | Fase 3 | Sí: es la protección real contra una sesión de borrados |
| 3 | ¿El aviso del `-` en `read` va a stderr siempre o solo con `verbose`? | Fase 2 | Siempre en `batch`/`run` una sola vez por corrida, no por fotograma |
| 4 | Umbrales de aceptación (`acceptance`) | Fase 6 | Los fijás vos con los datos medidos |
| 5 | ¿`extract_frames` (12 parámetros) y `cmd_doctor`/`cmd_batch` se extraen a módulos? | después del plan | Dejarlo fuera: el plan ya es grande |

## 5. Riesgos

- **Todo sin commitear.** Un `git clean` o un fallo de disco lo perdería. Mitigación: los snapshots de `old_data/`. Si preferís cortar el riesgo antes, es razonable ejecutar los commits 0.x y 1.x ahora y seguir con las fases en commits normales; el plan los pospuso por decisión tuya.
- **La Fase 2 rompe tests por diseño.** Si los tests viejos no se migran a la vez que el código, la compuerta se vuelve ambigua (no se sabe si un rojo es regresión o migración pendiente).
- **Las UIs no tienen tests del loop.** Un error en la Fase 3 puede pasar la suite y romper la ventana. Por eso la prueba manual de la Compuerta 3 no es opcional.
- **El golden tarda ~25 minutos.** Correrlo en segundo plano mientras se revisa otra cosa; 8110 sola sirve de prueba rápida.
- **Los agentes dicen "hecho" antes de que sea cierto.** En las fases 0 y 1 verifiqué por mi cuenta la suite y el golden de 8110 después de cada informe, y la revisión de código encontró 5 problemas reales que los tests no veían. Mantener ese hábito.

## 6. Archivos de referencia

- Plan completo: `C:\Users\marco\.claude\plans\a-partir-dela-informacion-cozy-hellman.md`
- Auditoría de partida: `docs/AUDITORIA_v5.md`
- Commits propuestos: `COMMITS_PENDIENTES.md`
- Red de seguridad: `old_data/` (`golden_f0/`, `snapshot_f0_*`, `snapshot_f1_*`) y `calib/.backups/pre_v5_20261010/`
- Plan anterior de `teach` por áreas (el árbol de comandos sigue vigente): `PLAN_v5.md`
