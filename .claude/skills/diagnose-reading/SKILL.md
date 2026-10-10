---
name: diagnose-reading
description: Diagnostica por que una corrida de spectro lee mal. Usar cuando el porcentaje de lecturas validas es bajo, hay muchos `low_confidence` con confianza alta, una lectura aceptada no coincide con lo que muestra el display, o hay que revisar etiquetas sospechosas en truth.csv/test.csv o plantillas danadas en la biblioteca. Incluye cuatro scripts de solo lectura (cells, crops, tally, culprits).
---

# Diagnosticar una corrida que lee mal

**Principio:** medir antes de tocar. Todo el diagnóstico es de **solo lectura**; cualquier corrección se cuantifica primero sobre una **copia** (`--sin` en memoria, o `calib/` copiada a una carpeta temporal y usada con `--calib-dir`).

Los scripts viven en `.claude/skills/diagnose-reading/scripts/` y se ejecutan con `.venv/Scripts/python`. Todos aceptan `--run <id>`, `--runs-dir` y `--calib-dir`.

| script | responde | ejemplo |
|---|---|---|
| `tally.py` | ¿por qué se rechazan los fotogramas? (motivos por celda, rechazo por tramo, pares de caracteres que se estorban) | `tally.py --run img_8110 --every 3` |
| `culprits.py` | ¿qué plantillas están dañadas y de qué muestra salieron? | `culprits.py --run img_8110` · `culprits.py --all-runs` |
| `cells.py` | ¿qué pasa celda por celda en este fotograma? | `cells.py --run img_8110 t_0000205.000.jpg` |
| `crops.py` | ¿qué se ve en estos fotogramas? (hoja de recortes para mirar a ojo) | `crops.py --run img_8110 --out <tmp>/hoja.png t_0000205.000.jpg …` |

## Procedimiento

1. **Panorama.** `tally.py --every 3` da el porcentaje aceptado, los motivos de rechazo y si hay tramos del video que fallan más que otros. Comparalo con `out/readings.csv` (estados) y `out/qc_report.csv`.
2. **Interpretar el motivo dominante** (tabla de abajo). El que más pesa decide por dónde seguir.
3. **Buscar plantillas dañadas.** `culprits.py --run <id>` (o `--all-runs`: la biblioteca es global, así que una etiqueta mala en cualquier video contamina a todos).
4. **Ver casos concretos.** `cells.py` sobre 3 o 4 fotogramas representativos y `crops.py` para **mirarlos**: confirmá con tus ojos qué dice el display antes de culpar al lector o a la etiqueta.
5. **Cuantificar la corrección sin tocar nada.** `tally.py --sin 0_3 1_3` recalcula la aceptación sin esas plantillas (en memoria). Para reconstruir la biblioteca, hacelo en una copia de `calib/` con `--calib-dir` (el comando de entrenamiento vigente está en `teach --help`).
6. **Informar** en este formato: síntoma con cifras → causa con la evidencia (fotograma, plantilla, NCC) → corrección propuesta con la mejora medida → qué **no** se arregla y por qué. No ejecutes la corrección sobre los datos reales: se la proponés al usuario.

## Qué significa cada motivo

| lo que ves | causa probable | siguiente paso |
|---|---|---|
| mayoría de rechazos **por margen**, con puntaje alto (0,9+) | dos plantillas de **distinto** carácter casi iguales | `culprits.py`: sección 2 (pares) y 1 (ganan mal) |
| rechazos por **puntaje** concentrados en el último dígito | parpadeo: el display redibuja el último dígito | normal; son fotogramas que no se pueden etiquetar |
| rechazo alto solo en un **tramo** del video | cambió la luz, el enfoque o hay una mano; o ese tramo tiene valores que la biblioteca no vio | `crops.py` sobre ese tramo; muestrear ahí |
| `signo con tinta` | la ROI incluye ruido o parte de otro elemento en la celda del signo | revisar la ROI en `calibracion.png` |
| aceptadas pero erróneas (confianza media/alta) | variante de un dígito que falta, o etiqueta equivocada | `cells.py` y `crops.py` sobre ese fotograma |
| leave-one-out bajo con confianza alta (`teach … --check`) | etiquetas equivocadas en `truth.csv` | `crops.py` sobre las muestras que no coinciden |

## Firmas conocidas (de incidentes reales)

- **Etiqueta equivocada:** una plantilla con NCC ≥ 0,96 contra otra de **otro carácter** (en `img_8110`, `0_3` era un `1` etiquetado como `0`: se tipeó `0.239` y el display decía `1.269`). Hace rechazar todo fotograma que contenga ese dígito.
- **Fotograma a medio dibujar:** plantilla casi vacía, o con manchas rojizas en el recorte. El último dígito se redibuja con un parpadeo de segundos; no es una muestra válida para etiquetar.
- **Parpadeo:** rachas de lecturas `ok` y `low_confidence` alternadas de ≤ 1 s alrededor de cada cambio de valor.
- **Variante que falta:** un dígito leído con confianza alta pero equivocado (un `6` leído como `5`): no aparece en la incertidumbre; lo encuentra la prueba (`test.csv`).
- **Valor tipeado distinto del display:** pasa más de lo que parece (`-0.001` por `-0.011`, `-0.006` por `-0.016`). Siempre se verifica contra el recorte.

## Qué no hacer

- No edites `calib/templates/`, `truth.csv` ni `test.csv` (hay reglas que lo bloquean; los cambios van por los comandos `teach`).
- No ejecutes comandos que escriben sobre la biblioteca real para "probar".
- No concluyas solo con fixtures sintéticas: los errores de etiquetado y el parpadeo se vieron **únicamente** con fotogramas reales.
- No listes `runs/<id>/frames/` (miles de archivos): usá `frames_index.csv`.
