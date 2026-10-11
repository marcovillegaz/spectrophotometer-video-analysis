# Arquitectura

**Para quién y cuándo leerlo:** cuando vas a tocar el código, o querés entender cómo pasa un video
por el pipeline: qué hace cada módulo y qué contrato hay entre etapas. El **porqué** de cada
decisión está en [decisiones](decisiones.md). Para *usar* el proyecto, mirá la
[referencia de comandos](../referencia/comandos.md), [carpetas](../referencia/carpetas.md) y
[salidas](../referencia/salidas.md); para cada campo de configuración, [config](../referencia/config.md);
para el proceso de calibración del lector, la [guía](../calibrar/guia.md).

## El problema

Un espectrofotómetro UV/VIS con celda de flujo continuo, sin software de adquisición. La única
salida es su pantalla LCD. El primer video del proyecto (`20260901_164220`, sep-2026) tenía 20:03
min de pantalla filmados con un teléfono en soporte fijo (1920×1080, HEVC, 29.97 fps, 36 059
fotogramas, 1.17 GB), y hay que convertir eso en una serie temporal de absorbancia. Las cifras de
este documento y de [decisiones](decisiones.md) que no dicen otra cosa vienen de ese video; las
corridas actuales (`img_8102`, `img_8106`, `img_8110`, `img_8112`) son de otra sesión, con signo.

Tres condiciones del problema mandan sobre todo el diseño:

1. **La cámara está fija.** Entonces la región del número es la misma en todos los fotogramas: se
   define una vez y se reusa.
2. **La tipografía es constante y el formato del número es fijo** (`0.597`, `-0.018`). Entonces
   cada carácter se ve siempre igual, y "OCR" es en realidad un problema de clasificación entre 12
   glifos conocidos (`0-9`, `.`, `-`).
3. **Es un instrumento de medición.** Un valor equivocado en el CSV es peor que un valor faltante:
   contamina el análisis sin dejar rastro. Todo el pipeline está sesgado a descartar antes que a
   adivinar.

## El pipeline

```
 videos/IMG_8102.MOV         runs/<id>/config.json        calib/templates/
            │                    (calibrate)               (teach train)
            │                         │                          │
            ▼                         ▼                          │
    ┌───────────────┐          ROI, slots, umbrales,             │
    │    extract    │          offset de tiempo                  │
    └───────┬───────┘                 │                          │
            │  runs/<id>/frames/t_0000601.000.jpg                │
            │  runs/<id>/frames_index.csv                        │
            ▼                         │                          │
    ┌───────────────┐  ◄──────────────┘                          │
    │      qc       │  mide sobre la ROI + re-registra           │
    └───────┬───────┘                                             │
            │  runs/<id>/out/qc_report.csv  (métricas, dx, dy, status)
            ▼                                                     │
    ┌───────────────┐  ◄────────────────────────────────────────┘
    │     read      │  NCC por slot -> caracteres -> valor
    └───────┬───────┘
            │  runs/<id>/out/readings.csv   (incluye las descartadas)
            │  runs/<id>/out/read_meta.json (huella de la biblioteca)
            │  qc_report.csv                (status actualizado)
            ▼
    ┌───────────────┐
    │    report     │
    └───────┬───────┘
            │  runs/<id>/out/absorbance.csv    <- el entregable
            │  runs/<id>/out/preview.png       <- la curva
            │  runs/<id>/out/contact_sheet.png <- las 40 lecturas menos confiables
            ▼
       batch: runs/batch_report.csv (una fila por corrida, con veredicto)
```

Cada etapa es un subcomando independiente que lee de disco y escribe a disco. Se puede volver a
correr `read` sin re-extraer, o `report` con otro `offset_s` sin re-leer. Es deliberado: la
decodificación del video es lo caro (~3 min) y ajustar parámetros es lo frecuente.

## Módulos

| archivo | responsabilidad | interfaz pública |
|---|---|---|
| `cli.py` | argparse con un subcomando por etapa; `resolve_paths` convierte `--run <id>` en las rutas; `doctor`, `new` y `batch` (con su reporte); importa los módulos de forma perezosa para que `doctor` funcione aunque falte una dependencia | `main(argv)`, `build_parser()`, `resolve_paths(args)`, `batch_stages` |
| `teach_cli.py` | el árbol `teach status \| lib \| train \| check \| samples \| test`: un handler corto por verbo, con el id de la corrida posicional; la tabla de migración de la sintaxis vieja | `register(sub, layout)`, `legacy_error(argv)`, `MIGRATION` |
| `project.py` | el layout como código: id de corrida, rutas de `calib/` y `runs/<id>/`, siembra de configs; `RunContext` carga todo lo que `teach` necesita de una corrida por un solo camino | `run_id_from_video`, `RunPaths`, `CalibPaths`, `list_runs`, `require_run`, `seed_run_config`, `calib_recipe`, `RunContext.load` |
| `config.py` | esquema único de `config.json` como dataclasses anidadas; la geometría sabe qué caracteres espera cada celda | `Config.load/save/default`, `ROI`, `DigitsConfig` (`expected_chars`, `required_chars`), `AcceptanceConfig`, `DEFAULT_MAX_PER_LABEL` |
| `compat.py` | el único mapa de nombres viejos (español) a nuevos (inglés) para encabezados de CSV, claves, estados y flags | `normalize_row`, `read_csv_rows`, `normalize_keys`, `normalize_config`, `normalize_status`, `HEADER_ALIASES`, `VALUE_ALIASES`, `LEGACY_FLAGS` |
| `extract.py` | resolución de ffmpeg, metadatos, video → fotogramas, convención de nombres | `resolve_ffmpeg`, `probe_video`, `extract_frames`, `frame_name`, `time_from_name`, `load_frames_index`, `load_roi_sidecar` |
| `imaging.py` | primitivas de imagen compartidas: carga con rotación, recorte, binarización, slots, NCC; el recorte de celdas que usan **todos** los que leen o arman la biblioteca | `load_frame`, `crop_for_reading`, `binarize`, `slot_boxes`, `normalize_glyph`, `read_roi`, `cell_glyphs` (`CellGlyph`), `ncc`, `estimate_shift`, `auto_anchor` |
| `calibrate.py` | ROI, slots y polaridad → `runs/<id>/config.json`; interactivo, por flags o por registro contra `calib/reference.jpg` | `calibrate(args)`, `auto_calibrate(args)`, `refine_roi`, `pick_reference_frame` |
| `qc.py` | métricas de calidad sobre la ROI, re-registro, umbrales automáticos, `roi_outside` | `run_qc`, `measure`, `classify`, `suggest_thresholds`, `load_qc_report`, `load_offsets`, `write_qc_report` |
| `library.py` | la biblioteca de plantillas: cargarla, escribirla (reemplazar o sumar sin duplicar), listarla con su uso, borrar, re-etiquetar, respaldar y restaurar, y su huella | `load`, `write`, `add`, `dedup`, `list_entries`, `usage`, `delete`, `relabel`, `clear`, `backup`, `list_backups`, `restore_backup`, `fingerprint`, `warn_missing_sign` |
| `read.py` | NCC contra la biblioteca → caracteres → valor; chequeos de confianza y de plausibilidad; huella de la lectura | `run_read`, `read_frame`, `assemble`, `flag_spikes`, `load_readings`, `write_read_meta`, `load_read_meta`, `outputs_state` |
| `report.py` | CSV final, gráfico y hoja de contacto; cuadre de conteos; el resumen por corrida de `batch` y `teach test eval` | `run_report`, `write_absorbance_csv`, `plot_preview`, `batch_summary` (pura), `load_run_input`, `resolve_acceptance`, `format_batch_table`, `write_batch_report` |
| `teach.py` | valores escritos → una etiqueta por celda → glifos; entrenamiento desde una o varias corridas y validación leave-one-out | `parse_value`, `value_to_cells`, `build_pool`, `gather_runs`, `train`, `validate`, `evaluate_library`, `coverage`, `load_truth`/`save_truth` |
| `sampling.py` | qué fotogramas etiquetar: uniforme, azar estratificado, por incertidumbre (con persistencia y diversidad); conjuntos de entrenamiento y prueba | `suggest`, `suggest_uncertain`, `suggest_random`, `suggest_uniform`, `uncertainty`, `assign`, `leakage`, `readings_stale` |
| `evaluation.py` | el **único evaluador** (`evaluate`) y, sobre él, la evaluación de la prueba: correcta / errónea aceptada / descartada, intervalos de Wilson, tipo de prueba e historial | `evaluate`, `to_validation`, `to_test_report`, `evaluate_test`, `wilson`, `format_test_report`, `write_test_report`, `append_history`, `load_history` |
| `ui_common.py` | lo que comparten las dos ventanas de OpenCV: colores, `Button`, `BaseLayout`, `hit_test`, dibujo de texto, botones y títulos, apertura y cierre de la ventana | `Button`, `BaseLayout`, `hit_test`, `panel_geometry`, `draw_text`, `draw_button`, `draw_titles`, `open_window` |
| `calib_ui.py` | UI de calibración manual: panel lateral con botones, lupa del cursor, rotación y vista previa de lectura; la lógica (estado, acciones, layout) es pura | `UIState`, `apply_action`, `apply_key`, `layout_panel`, `preview_reading`, `probe_frames`, `render`, `run_calibration_ui` |
| `teach_session.py` | todo lo que decide la ventana de `teach`, sin ventana: estado, el reducer único de acciones, agregar y quitar muestras, los pedidos que tocan archivos, el respaldo único por sesión y las teclas | `TeachState`, `apply_action`, `TeachSession`, `TeachParams`, `add_sample`, `key_to_action` |
| `teach_ui.py` | la ventana de `teach`: solo layout, dibujo y el loop de eventos de OpenCV | `layout_teach`, `render_teach`, `run_teach_ui` |

**Se dio de baja `templates.py`** (y el comando `templates`): agrupaba glifos por hash perceptual y
pedía etiquetarlos a ciegas. Lo reemplazó `teach`, que etiqueta escribiendo el valor del display
(ver [decisiones](decisiones.md#los-valores-escritos-reemplazan-el-etiquetado-a-ciegas)).

`imaging.py` no estaba en el plan original y se agregó al implementar: `qc`, `teach` y `read`
tienen que binarizar y recortar **exactamente igual**, porque si la binarización con la que se
construye una plantilla difiere de la que se usa para compararla, la correlación cae sin motivo
aparente. Tener una sola implementación compartida (`cell_glyphs`) hace que eso no pueda pasar. Por
la misma razón hay **un solo evaluador**: la validación leave-one-out, la medida de la biblioteca
vigente y la prueba leen cada muestra con `evaluation.evaluate`, que a su vez usa `read_frame`.

## Contratos de datos entre etapas

Las columnas completas de cada archivo están en [salidas](../referencia/salidas.md); acá, lo que
cada contrato garantiza.

**Nombre de fotograma — `t_0000601.000.jpg`.** Segundos desde el inicio del video, 7 dígitos
enteros y 3 decimales. Cumple el requisito de que el nombre refleje el tiempo, y como el ancho es
fijo, **el orden alfabético es el orden temporal**: cualquier `sorted(glob(...))` queda ordenado en
el tiempo sin parsear nada. `frame_name` y `time_from_name` son inversas exactas y hay un test que
lo verifica a varios `--fps`.

**`runs/<id>/frames_index.csv`** — `file, t_s, index`. Es redundante con los nombres a propósito:
si se pierde, `index_from_dir()` lo reconstruye leyendo los nombres.

**`calib/templates/<carácter>_<n>.png`** — glifos binarizados y normalizados a 24×40. El punto
decimal se guarda como `dot_<n>.png` y el signo como `minus_<n>.png`, porque `.` y `-` no conviene
ponerlos en un nombre. Se admiten varias plantillas por carácter: `0_0.png` … `0_2.png` son todas
cero.

**`runs/<id>/out/qc_report.csv`** — el **libro mayor**: un renglón por fotograma extraído, siempre.
`qc` lo crea con las métricas y el estado inicial; `read` le actualiza la columna `status` con el
resultado de la lectura; `report` lo usa para el cuadre de conteos. Que exista un solo lugar donde
está el destino de cada fotograma es lo que permite garantizar que no se pierda ninguno en
silencio.

**`runs/<id>/out/readings.csv`** — todas las lecturas, incluidas las descartadas, con los caracteres
crudos que se leyeron, la confianza y el margen. Es lo que se mira cuando una lectura sospechosa hay
que rastrearla, y la fuente de la incertidumbre del muestreo.

**`runs/<id>/out/read_meta.json`** — la huella de la biblioteca con la que se produjo
`readings.csv`. Es lo que permite decir si una salida está al día sin comparar fechas.

**`runs/<id>/truth.csv` y `test.csv`** — `file,value`, con el valor como **texto** (conserva
`-0.000` y los ceros finales). Las muestras de varias corridas se identifican como
`corrida/archivo`, porque los videos repiten nombres de fotograma.

**Nombres en inglés, archivos viejos que siguen cargando.** Las columnas, claves, estados y flags
están en inglés; la prosa, en español. Los archivos escritos antes del cambio (encabezados en
español, `absorbancia.csv`, `roi_fuera`, `misma_corrida`…) se leen a través de `compat.py`, el único
lugar con el mapa de equivalencias. Los escritores emiten siempre los nombres nuevos y ningún
archivo se reescribe solo por leerlo.

## Cómo extenderlo

**Si cambia el display o el formato del número.** Volvé a correr `calibrate` (nueva ROI, nuevo
`n_digits`, nuevo `decimal_after`) sobre una corrida representativa, etiquetá unas muestras y
rearmá la biblioteca con `teach train`, y promové el resultado con `calibrate --promote`. Ni una
línea de código: el lector no sabe nada del equipo, todo está en `calib/config.json` y en
`calib/templates/`.

**Si el display fuera de siete segmentos con los dígitos pegados** — o si por cualquier motivo el
reparto uniforme de slots no cae bien — están los cortes manuales: `calibrate --splits
0,26,52,78,104,127`. Si ni eso alcanza porque los caracteres se tocan, el próximo paso es
segmentación por componentes conexas dentro de `slot_boxes`, que es el único punto que habría que
tocar.

**Si aparece un segundo número en pantalla** (%T, longitud de onda, temperatura): hoy `Config`
tiene una sola `roi`. La extensión natural es pasar `roi`/`digits` a una lista de "campos", con
`read_frame` devolviendo un valor por campo y `report` escribiendo una columna por campo. Las
funciones de `imaging.py` y `read.py` ya trabajan sobre una ROI recibida por parámetro, así que el
cambio queda contenido en `config.py`, en los bucles de `read.py`/`report.py` y en `calibrate.py`.

**Si la cámara deja de estar fija** (video a mano alzada). El re-registro por template matching ya
resuelve traslaciones de hasta `max_shift_px`. Para rotación o escala haría falta reemplazar
`estimate_shift` por una estimación de homografía (`cv2.findTransformECC` o detección de features
+ `estimateAffinePartial2D`) y aplicar el warp antes de recortar. El resto del pipeline no se
entera: sigue recibiendo una ROI ya alineada.

**Procesar varios videos en lote** ya está resuelto: `batch` encadena
`new → extract → calibrate --auto → qc → read → report` por cada video, saltea las corridas
terminadas, deja pendientes las que no engancharon la calibración automática y escribe
`runs/batch_report.csv`. Lo que deliberadamente **no** hace es un CSV combinado de absorbancias ni un
índice de corridas: no hacían falta, y un índice sería estado global que se desincroniza del disco.
El reporte del lote se recalcula entero en cada `batch` a partir de los archivos de cada corrida.

---

**Siguiente paso:** por qué cada pieza es como es, y qué riesgo cubre, en [decisiones](decisiones.md).
