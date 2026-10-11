> **Documento histórico.** Auditoría de partida del plan v5, del 2026-10-10. Se movió de `docs/` a
> `docs/historia/` en la Fase 5 (2026-10-11). Describe el proyecto **antes** del plan: los comandos,
> módulos y cifras que cita (por ejemplo `templates.py` o `cmd_teach`) ya no existen o cambiaron. El
> estado vigente está en el `README.md` y en `docs/`.

# Auditoría previa al upgrade (insumo para `PLAN_v5.md`)

Fecha: 2026-10-10 · Rama `main` (`aea57e4`, con mucho trabajo sin commitear) · Suite: **386 tests en verde (4.5 s)**

Este documento junta lo que se midió en el proyecto antes de reescribir `PLAN_v5.md`. Cada hallazgo dice **cómo se verificó**; lo que es una inferencia está marcado como tal. No se modificó ningún dato real ni código: solo lectura, más la regeneración del grafo (`graphify-out/`, ignorado por git).

## 1. Resumen ejecutivo

| # | Hallazgo | Gravedad | Afecta a PLAN_v5 |
|---|---|---|---|
| 1 | Casi todo el trabajo (5 módulos, 9 archivos de test, `docs/GUIA_CALIBRACION.md`, `CLAUDE.md`, `.claude/`) está **sin commitear**; el historial tiene 7 commits | Alta (riesgo de pérdida) | Antes de empezar: commitear |
| 2 | La biblioteca actual (53 plantillas) **no tiene la plantilla `-`**, pero la config tiene `sign_slot: 0` | Alta (cambia las lecturas) | Prerrequisito: re-etiquetar el signo |
| 3 | Las salidas de `runs/*/out/` son del 9-oct; la biblioteca se reinició el 10-oct | Media | Re-correr `read`/`report` antes de comparar |
| 4 | `cli.py` (1054 líneas) concentra `teach` en `cmd_teach` + 3 helpers + ~30 flags | Media | Es lo que PLAN_v5 ya ataca |
| 5 | Lecturas descartadas por `low_confidence`: 5.6 % a 40 % según la corrida | Media | Medir contra la biblioteca nueva |
| 6 | `PLAN_v5.md` sigue vigente pero le falta un punto (`batch` con reporte está en una línea suelta) y `PLAN_v6.md` ya no existe | Baja | Ordenar los planes |
| 7 | Sin medidor de cobertura (`pytest-cov` no está instalado) | Baja | Agregarlo como dev-dependency |

## 2. Estado del grafo

`graphify update .` (solo código, sin LLM) reconstruyó `graphify-out/`:

- **Antes:** 381 nodos · 906 aristas · 12 comunidades.
- **Ahora:** 999 nodos · 2434 aristas · 79 comunidades (42 visibles, 37 chicas). 81 % `EXTRACTED`, 19 % `INFERRED`, 0 % `AMBIGUOUS`.
- El salto no es ruido: entraron `calib_ui.py`, `teach.py`, `teach_ui.py`, `sampling.py`, `evaluation.py` y los tests nuevos, que no estaban cuando se generó el grafo anterior.
- Los `config.json` (5) no produjeron nodos; el aviso es de graphify y se reintenta en cada corrida. No afecta al análisis.
- No hay ciclos de importación.
- **Dioses del grafo** (lo más conectado): `Config` (84), `render_display()` (61), `ROI` (45), `DigitsConfig` (44), `read_frame()` (43), `RunPaths` (31), `Sample` (27), `UIState` (26), `Reading` (26), `Template` (26).
- **Qué dice de la arquitectura:** `Config` y `read_frame` son el centro esperado. `render_display()` en el segundo lugar es un dato a mirar: es el renderizador sintético de los tests y está más conectado que casi todo el código de producción; indica que la suite depende mucho de una sola fixture.
- La comunidad "Package Entry Point" (52 nodos) mezcla `calib_ui`, `teach_ui` y utilidades de teach: las dos UI comparten código por convención, no por un módulo común.

Limitación: el grafo no se actualizó con extracción semántica de los `.md` (no hay clave de Gemini y no se lanzaron subagentes). Los nodos de documentos son los del grafo anterior.

## 3. Tamaño y forma del código

`src/spectro/` tiene 9503 líneas contando tests; el código de producción ronda las 5300 en 17 módulos. Los más grandes:

| módulo | líneas | nota |
|---|---|---|
| `cli.py` | 1054 | `build_parser` (254 líneas), `cmd_teach` (137), `cmd_doctor` (77), `cmd_batch` (69) |
| `teach_ui.py` | 722 | `run_teach_ui` tiene **232 líneas** y complejidad 65 (la mayor del proyecto) |
| `calib_ui.py` | 700 | `render` 108 líneas, `run_calibration_ui` 95 |
| `teach.py` | 587 | núcleo de entrenamiento: razonable |
| `extract.py` | 415 | `extract_frames` con 12 parámetros |
| `calibrate.py` | 421 | `_calibrate_manual` 120 líneas |

Cómo se midió: recorrido AST de `src/spectro/*.py`; complejidad = ramas (`if/for/while/try/and-or/except/comprensión`) + 1. Es una aproximación, no ciclomática exacta.

Lo que sale de ahí:

1. **Los dos loops de OpenCV no son delgados.** `CLAUDE.md` dice que la UI tiene "la lógica pura aparte y el loop delgado", pero `run_teach_ui` (232 líneas, 65 ramas) y `run_calibration_ui` (95) contienen bastante decisión. Es lo menos testeable del proyecto sin ventana.
2. **`cmd_teach` decide el modo mirando flags** (56 ramas), más `_teach_eval_all` y `_teach_all_runs`, más el bypass `eval_all`/`all_runs` en `resolve_paths` (`cli.py:119`). Es exactamente el problema que describe PLAN_v5.
3. `extract_frames` recibe 12 argumentos: candidato a un dataclass de opciones.
4. Cuatro `except Exception` en total (`calib_ui.py:411` y `:438`, `cli.py:181`, `extract.py:89`); los dos de `cli`/`extract` están marcados `pragma: no cover`. El de `calib_ui.py:411` está justificado en el comentario (la vista previa no debe tumbar la UI).
5. Sin `TODO`/`FIXME`/`HACK` en `src/`.

## 4. Datos reales

Estado de las cuatro corridas (conteos de `frames_index.csv`, `truth.csv`, `test.csv`, `readings.csv`):

| corrida | fotogramas | lecturas | entrenamiento | prueba | `ok` | `low_confidence` | % descartado por confianza |
|---|---|---|---|---|---|---|---|
| `img_8102` | 10817 | 10796 | 30 | 20 | 10196 | 600 | 5.6 % |
| `img_8106` | 17944 | 17360 | 30 | 40 | 15575 | 1785 | 10.3 % |
| `img_8110` | 3824 | 3782 | 26 | 43 | 2265 | 1517 | 40.1 % |
| `img_8112` | 10176 | 9922 | 0 | 20 | 6989 | 2933 | 29.6 % |

- El resto de los fotogramas (por ejemplo 8106: 17944 → 17360) los descartó `qc` antes de leer: `blank` (554 en 8106), `blown`, `camera_moved`, `occluded`, `blur`, `dark`.
- `img_8112` no tiene muestras de entrenamiento: se lee solo con glifos de otras corridas. Es el caso de generalización entre videos, y es el peor junto con 8110.
- `img_8110` tiene entrenamiento (26 muestras) pero **0 con signo negativo**, y el 40 % descartado: es la corrida que más ganaría con revisión.
- Evaluación de la única corrida con historial (`img_8102`, 20 muestras de prueba, biblioteca de 43 plantillas, 9-oct): exactitud 0.95 (19 de 20), 1 errónea (`-0.001` leído como `-0.004`, confianza 0.906). Con 20 muestras el intervalo de confianza es ancho; no hay que leer 0.95 como una cifra firme.
- La biblioteca es de **53 plantillas**: `0`: 5, `1`: 5, `2`: 4, `3`: 4, `4`: 4, `5`: 4, `6`: 6, `7`: 4, `8`: 6, `9`: 6, `.`: 5.

### 4.1 Hallazgo importante: falta la plantilla `-`

- `calib/templates/` no contiene ningún `minus_*.png` (tampoco en `HEAD`).
- Todas las configs tienen `digits.sign_slot: 0`. En `read.py` la celda del signo, si tiene tinta, solo se acepta como negativo cuando el matcheo da `-` con score y margen suficientes; con otro resultado la lectura queda `low_confidence` (`read.py:138-146`). `templates.py:242` ya avisa de esta situación al construir.
- Las muestras sí tienen signo: 26 de 30 líneas de `truth.csv` de 8102 y de 8106 son negativas.
- **Medido el 2026-10-10 (Fase 0 del plan, `read` con la biblioteca actual, salidas en scratch, sin tocar `runs/`):**

  | corrida | `ok` | `low_confidence` | % descartado | antes (biblioteca del 9-oct) |
  |---|---|---|---|---|
  | `img_8102` | 999 | 9797 | 90.7 % | 5.6 % |
  | `img_8106` | 1905 | 15455 | 89.0 % | 10.3 % |
  | `img_8110` | 3368 | 414 | 10.9 % | 40.1 % |
  | `img_8112` | 7915 (+3 `spike`) | 2004 | 20.2 % | 29.6 % |

  En ninguna corrida se aceptó un signo `-`. 8102 y 8106 descartan casi todo porque son las que tienen negativos; 8110 y 8112 (valores positivos) mejoran con la biblioteca nueva. Copias en `old_data/golden_f0/` (con `SHA256SUMS.txt`).
- Contexto: la biblioteca se reinició hoy (`old_data/backup_antes_de_reiniciar_20261010_1430/` existe; `calib/templates/` tiene fecha de hoy), mientras los `out/` son del 9-oct y todavía muestran lecturas como `-0.000`. O sea, **los números de la tabla de arriba pertenecen a la biblioteca anterior** y no se pueden comparar con la que hay ahora.

Esto tiene que resolverse antes del upgrade: es el tipo de error "una etiqueta mala contamina a todos los videos" que `CLAUDE.md` describe, aunque aquí la causa es la omisión, no una etiqueta equivocada.

## 5. Calidad de la documentación

- Los tests de documentación (`test_docs.py`) pasan; el parser real acepta los comandos documentados.
- `CLAUDE.md:19` dice que PLAN_v5 "todavía no está implementado": es correcto, no hay `teach_cli.py`.
- `README.md`, `docs/ARQUITECTURA.md`, `docs/CONFIG.md` tienen cambios sin commitear; `docs/GUIA_CALIBRACION.md` es nuevo y sin commitear.
- PLAN_v1..v3 se borraron del árbol de trabajo (`D` en `git status`) y no hay `PLAN_v4.md`: la numeración salta de v3 a v5. En el estado inicial había un `PLAN_v6.md` sin seguimiento; **ya no está en disco**. Confirmá si fue intencional.

## 6. Tests

- 386 tests, 21 archivos, 4.5 s. Buen reparto: pipeline, CLI, UI sin ventana, núcleo de `teach`, evaluación, muestreo y signo.
- `test_claude_agents.py` y `test_claude_config.py` (415 líneas) testean la configuración de `.claude/` (agentes, hooks, reglas). Es poco común y útil para el hook de alcance, pero vive en la suite del producto.
- Sin cobertura medida: `pytest_cov` no está instalado. Los lugares con menos probabilidad de estar cubiertos son los loops `run_teach_ui` y `run_calibration_ui` (necesitan ventana) y las ramas `pragma: no cover`.
- La fixture `render_display()` es el nodo más conectado del código de pruebas (ver §2). Un cambio en ella mueve decenas de tests.

## 7. Repositorio e higiene

- `git status`: ~70 archivos modificados/borrados/sin seguimiento; `git diff --stat`: 68 archivos, 1042 inserciones, 18 952 borrados (casi todo los `runs/` viejos que se quitaron del índice).
- Los módulos nuevos (`calib_ui`, `teach`, `teach_ui`, `sampling`, `evaluation`) **no están en ningún commit**: hoy un `git clean` o un disco roto los perdería.
- `.gitignore` ya excluye `videos/`, `runs/*/frames/`, `runs/*/samples/`, `old_data/`, `graphify-out/` y `calib/.backups/`.
- Avisos de CRLF/LF al tocar archivos: no hay `.gitattributes`. Conviene fijar `* text=auto eol=lf` antes del próximo commit grande para evitar diffs ruidosos.
- `old_data/` convive con el layout nuevo; el `.gitignore` dice "conservada hasta decidir". Pendiente de decisión.

## 8. Qué le falta a PLAN_v5 (entrada para la reescritura)

Lo que el plan actual ya cubre bien: subcomandos por área, id de corrida explícito, respaldo automático de la biblioteca, `--max-per-label` por defecto 3, `status` con siguiente paso sugerido, migración de tests.

Lo que habría que agregar o revisar:

1. **Línea suelta "nuevo: Batch debe hacer un reporte."** (línea 24, dentro del árbol de comandos): no tiene diseño. Falta definir qué contiene (conteo de lecturas por estado y por corrida, cobertura, exactitud si hay prueba) y dónde se escribe.
2. **Prerrequisito de datos:** resolver la plantilla `-` (§4.1) y re-correr `read`/`report` de las cuatro corridas, para que la línea de base del plan sea la biblioteca vigente. Sin eso no se puede decir si `train` mejora o empeora.
3. **`teach status` debería avisar** cuando `sign_slot` está configurado y falta la plantilla `-`: la advertencia hoy solo aparece al construir (`templates.py:242`).
4. **Salida de `read`:** hoy se escribe sobre `runs/<id>/out/` sin marca de qué biblioteca se usó. Guardar el hash o la fecha de la biblioteca en `readings.csv`/informe permitiría detectar salidas viejas (el problema del §4). Es una decisión de diseño a tomar.
5. **Las UI siguen sin diseño de refactor.** PLAN_v5 dice "la UI no cambia", pero `run_teach_ui` (232 líneas) y `run_calibration_ui` son los puntos más difíciles de mantener. Si el upgrade es "grande", conviene decidir si se parten ahora o después.
6. **`build_parser` (254 líneas)** crece con cada área: con `teach_cli.py` el árbol baja a un módulo propio, pero `cli.py` quedaría igual de largo en `cmd_doctor`/`cmd_batch`. Decidir si se extrae un `batch.py`.
7. **Casos de lectura entre videos** (8112 sin entrenamiento, 29.6 % descartado): el plan no dice cómo se mide la generalización a un video nuevo. Sugerencia: un informe `teach status` con una fila "video sin entrenamiento" y su cobertura.
8. **Rutas de `.claude/`:** el plan menciona qué agente escribe qué; con `teach_cli.py` y `test_teach_cli.py` nuevos, el hook de alcance y las reglas de `.claude/rules/` ya cubren `src/**` y `tests/**`, pero hay que confirmar que los tests de `test_claude_config.py` no tienen la lista de módulos fija.
9. **Medición:** agregar `pytest-cov` como dependencia de desarrollo y fijar un piso para los módulos nuevos.

## 9. Orden de trabajo sugerido

1. Commitear lo existente con `/commit` (módulos nuevos, tests, docs, `.claude/`), con un `.gitattributes` previo.
2. Decidir sobre `PLAN_v6.md` y `old_data/`.
3. Restaurar o reetiquetar la plantilla `-` (con `teach`, sobre una copia de `calib/` primero) y re-correr `read` + `report` en las cuatro corridas.
4. Recién ahí reescribir `PLAN_v5.md` con los puntos del §8 y una línea de base medida con la biblioteca vigente.
5. Implementar por el flujo del proyecto: `developer` → `test` (con mutación) → `refactor` si hace falta → `writer`.

## 10. Cómo se verificó

- `graphify update .` y `graphify-out/GRAPH_REPORT.md` (999 nodos, comunidades, dioses).
- `pytest -q`: 386 pasaron.
- Script AST (tamaño y ramas por función) sobre `src/spectro/*.py`.
- Conteos con `wc`/`csv` sobre `frames_index.csv`, `truth.csv`, `test.csv`, `readings.csv`, `qc_report.csv`, `teach_history.csv`.
- Lectura de `read.py`, `templates.py`, `PLAN_v5.md`, `CLAUDE.md`, `git status`, `git ls-tree`.
- No verificado: la cobertura de tests y el contenido de `old_data/backup_antes_de_reiniciar_*`.
