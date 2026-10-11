# Diagnóstico — síntoma, causa y qué hacer

**Para quién y cuándo leerlo:** cuando un comando falla, una salida no se parece a lo esperado o
un número no te cierra. Buscá el síntoma en el índice; cada entrada dice la causa probable y qué
hacer. Antes que nada, corré `python -m spectro doctor` y `python -m spectro teach status`: los dos
solo leen y suelen nombrar el problema.

Los nombres de estado (`low_confidence`, `roi_outside`, `stale`…) están explicados en
[salidas](../referencia/salidas.md), y los campos de `config.json` que se mencionan, en
[config](../referencia/config.md).

## Instalación y entorno

### `ffprobe` no aparece después del `winget install`

**Causa.** El PATH se toma al abrir la terminal.

**Qué hacer.** Cerrala y abrila de nuevo, y confirmá con `python -m spectro doctor`. Mientras
tanto el pipeline funciona igual con el respaldo del venv (ver [instalar](../empezar/instalar.md)).

### No se abre ninguna ventana

**Causa.** Sesión remota, WSL o servidor sin escritorio.

**Qué hacer.** Usá `calibrate --auto`, que no abre ventanas, o el modo no interactivo
`calibrate --roi x,y,w,h` mirando `runs/<id>/out/calibracion.png`. Las muestras se cargan sin
ventana con `teach samples add` y `teach test add`.

## Corridas y comandos

### `ERROR: falta --run`

**Causa.** Un subcomando de etapa no adivina sobre qué corrida trabajar: mezclar dos experimentos
corrompería los datos en silencio.

**Qué hacer.** El error lista las corridas disponibles; elegí una con `--run <id>`, o pasá las
rutas a mano. `python -m spectro doctor` las lista todas con su estado.

### `ERROR: teach no usa --run`

**Causa.** En `teach` el id de la corrida va como argumento (`teach samples list img_8102`), nunca
con `--run`.

**Qué hacer.** Pasá el id como argumento. Si usás la sintaxis vieja de `teach`, el error muestra la
tabla de migración.

### `calibrate --auto` no engancha (score por debajo del mínimo)

**Causa.** El registro corrige traslación, no rotación ni escala. Si el teléfono quedó a otra
distancia o inclinado, no hay corrimiento que arregle eso.

**Qué hacer.** Calibrar a mano es lo correcto. Si el encuadre es el mismo pero el salto fue
grande, subí `--search-px`. Si la referencia compartida quedó vieja, calibrá una corrida buena a
mano y corré `calibrate --run <id> --promote` (ver
[re-calibrar una corrida](../empezar/primera-corrida.md#cómo-re-calibrar-una-sola-corrida)).

## Calidad de imagen (QC)

### Muchos descartes de QC

**Causa.** Los umbrales automáticos quedaron estrictos para la iluminación de ese día, la cámara
se movió, o la ROI quedó pegada al borde.

**Qué hacer.** Aflojá los umbrales en `runs/<id>/config.json` (`qc.min_blur_var`,
`qc.min_contrast`, `qc.min_ink_fraction`) y corré `qc --run <id> --no-auto-thresholds`. Si el
estado es `camera_moved`, revisá `dx`/`dy` en `qc_report.csv`: si la deriva es de pocos píxeles el
re-registro ya la compensa y lo que hay que subir es `qc.max_shift_px`; si es de decenas, la
cámara se movió de verdad y hay que re-calibrar sobre el tramo afectado.

### Muchos `roi_outside` (en `qc_report.csv` o en `teach status`)

**Causa.** La ROI quedó pegada al borde del fotograma y la deriva la saca.

**Qué hacer.** Recalibrala con un poco más de margen.

## Lectura

### Muchas lecturas descartadas por baja confianza (`low_confidence`)

**Causa.** Faltan plantillas, falta la plantilla `-` en un display con negativos, o los fotogramas
agarran el display a medio redibujar.

**Qué hacer.** Mirá `runs/<id>/out/contact_sheet.png`: son los 40 recortes de menor confianza. Si
los dígitos se ven bien, faltan plantillas: etiquetá esos fotogramas (`teach samples label <id>`) y
sumalos con `teach train --keep`. Si el display muestra negativos, revisá que la biblioteca tenga
la plantilla `-` (`teach status` lo avisa). Si se ven a medio dibujar, es el display
refrescándose y la respuesta correcta es **subir `--fps`** (siguiente entrada).

**Subir `templates.min_score` no es la respuesta**: en el primer video del proyecto (sep-2026) las
lecturas de confianza 0.60–0.65 se desviaban de la mediana local lo mismo (0.002 Abs) que las de
confianza > 0.80, así que el umbral sólo cambia cuántos datos tenés, no cuán buenos son (la medición
completa, en [decisiones](../diseno/decisiones.md#la-frecuencia-de-muestreo-es-un-parámetro-y-no-es-gratis-elegirla-mal)).

### El último dígito sale cortado o fantasma

**Causa.** El dígito menos significativo se redibuja varias veces por segundo, así que a 1 Hz
muchos fotogramas lo agarran a mitad del refresco.

**Qué hacer.** Subí `--fps`. En el primer video del proyecto, a 1 Hz sólo el 41 % de los segundos
tenía una lectura válida; **a 4 Hz la serie final cubría el 86 %** de los 20 minutos. Subir `--fps`
cuesta disco y tiempo de decodificación, no precisión.

### La curva muestra picos de un solo punto

**Causa.** Es la firma de un dígito mal leído.

**Qué hacer.** Bajá `read.max_rate` en `runs/<id>/config.json` (es la máxima |ΔAbs|/Δt admitida
contra los vecinos) y volvé a correr `read --run <id>` y `report --run <id>`.

## Calibración del lector

Los síntomas que aparecen al etiquetar, entrenar y evaluar con `teach`. El proceso en el que
aparecen está en la [guía de calibración](../calibrar/guia.md).

| síntoma | causa probable | qué hacer |
|---|---|---|
| La biblioteca lee 0 de mis muestras | cambió la geometría (rotación, ROI, celdas) o se promovió una receta distinta | reconstruir la biblioteca (`teach train`) con las muestras actuales y `calibrate --promote` |
| `teach status`: `faltan: '-'`, y la exactitud cae en corridas con valores negativos (con 0 % de error) | falta la plantilla del signo: el lector descarta todos los negativos | etiquetar valores negativos (`teach samples label <id>`) y `teach train` |
| `test eval`: aceptadas erróneas con un dígito constante (p. ej. `6`→`5`) | falta una variante de ese dígito | etiquetar como **entrenamiento** fotogramas parecidos, separados de la prueba (como en el [ejemplo](../calibrar/ejemplo-img_8102.md#la-prueba)) |
| `test eval`: cobertura baja (muchas descartadas) con fotogramas bien dibujados | faltan plantillas, o hay variantes que se estorban entre sí | `teach lib list --usage`: borrar las `DANINA`; sumar variedad |
| Un aviso de **fugas** | fotogramas de prueba a menos de `--gap` s de entrenamiento | mover la muestra o ampliar `--gap`; la exactitud puede estar inflada |
| Aviso de **valores distintos** bajos | la prueba repite pocos valores | tomar más fotogramas, de tramos con otros valores |
| `suggest` dice *arranque en frío* | casi todo se descarta o no hay `readings.csv` | ronda uniforme; después de entrenar, correr `read` |
| `suggest` dice que `readings.csv` es anterior a la biblioteca | se cambió la biblioteca o la config después de `read` | correr `read` de nuevo |
| `suggest`: "solo hay N fotogramas inciertos y persistentes" | no hay un carácter desconocido; lo que duda es el parpadeo | normal; la ronda se completa al azar |
| `teach status` o `batch_report.csv`: salidas `stale` | `readings.csv` se leyó con una biblioteca distinta de la de hoy (la cambiaste con `train`, `delete`, `relabel` o `restore`): sus lecturas y sus incertidumbres son de otro lector | `read --run <id>` y `report --run <id>` (o `batch … --no-skip-existing`) |
| `read` se volvió lento | la biblioteca tiene muchas variantes | bajar `--max-per-label`, o borrar las que no aportan |
| Se borraron plantillas por error | — | `teach lib backups` lista los respaldos y `teach lib restore` vuelve al último (respaldando antes el estado actual) |

---

**Siguiente paso:** todos los comandos con sus flags, en la
[referencia de comandos](../referencia/comandos.md).
