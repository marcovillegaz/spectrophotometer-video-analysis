# Referencia de `config.json`

Hay **dos** `config.json`, con el mismo esquema y distinto alcance:

| archivo | qué contiene | quién lo escribe |
|---|---|---|
| `calib/config.json` | la **receta compartida**: geometría del número, matcheo, la ROI/ancla de referencia que acompañan a `calib/reference.jpg` y los umbrales `acceptance` del lote | `calibrate --promote`; `acceptance` se edita a mano |
| `runs/<id>/config.json` | la corrida: la receta heredada + video, fps, su ROI, su ancla, sus umbrales de QC y su offset | `new`, `calibrate`, `qc`, `extract --save-config` |

`new` siembra el de la corrida desde el de `calib/`: hereda lo compartido y deja sin fijar lo que
es del encuadre de esa sesión (y `acceptance`, que solo se lee de `calib/`). **Cada campo de abajo
está marcado como 🔗 compartido o 📍 por corrida**, que es la pregunta que uno se hace al editar el
JSON a mano. Dónde vive cada archivo está en el
[README](../README.md#estructura-de-carpetas).

Es un JSON común: **se puede editar a mano** y las etapas siguientes lo respetan. Después de
editarlo, volvé a correr la etapa afectada (`qc --run <id>`, `read --run <id>` o
`report --run <id>`), no hace falta re-extraer.

Este es el `runs/img_8102/config.json` real (11-oct-2026), con cada campo explicado abajo:

```json
{
  "video": "videos\\IMG_8102.MOV",
  "fps": 4.0,
  "rotation_deg": 3.7,
  "roi": {
    "x": 776,
    "y": 670,
    "w": 129,
    "h": 36
  },
  "digits": {
    "n_digits": 6,
    "splits": [],
    "separator_slots": [
      2
    ],
    "decimal_after": 1,
    "polarity": "light_on_dark",
    "sign_slot": 0,
    "sign_max_ink": 0.03
  },
  "templates": {
    "size": [
      24,
      40
    ],
    "min_score": 0.6,
    "min_margin": 0.05,
    "cluster_hamming": 6
  },
  "qc": {
    "min_mean_luma": 34.395579268292714,
    "max_mean_luma": 53.77210365853656,
    "min_blur_var": 5.0,
    "min_contrast": 23.0,
    "min_ink_fraction": 0.14329268292682923,
    "max_ink_fraction": 0.3484756097560976,
    "anchor": {
      "x": 729,
      "y": 305,
      "w": 387,
      "h": 72
    },
    "min_anchor_ncc": 0.7,
    "reference_frame": "t_0001352.000.jpg",
    "max_shift_px": 40,
    "register": true
  },
  "time": {
    "offset_s": 0.0,
    "absolute_start": null
  },
  "read": {
    "max_rate": 0.5
  }
}
```

Dos detalles de este archivo: tiene `cluster_hamming`, una clave que ya no existe y se ignora
(ver [Claves que ya no se usan](#claves-que-ya-no-se-usan)), y no tiene `acceptance`, que es solo
de `calib/config.json`. La próxima vez que una etapa guarde este archivo, `cluster_hamming`
desaparece y aparece `"acceptance"` con sus tres campos en `null`: es un cambio inofensivo.

---

## Raíz — 📍 por corrida

| campo | tipo | default | efecto |
|---|---|---|---|
| `video` | string | `""` | 📍 Video de esta corrida. Lo escribe `new`, y también `extract --save-config`. En `calib/config.json` va vacío: la receta no pertenece a ningún video. |
| `fps` | float | `1.0` | 📍 Frecuencia de muestreo de esta corrida. La escribe `new --fps`; `extract` la usa si no le pasás `--fps`. |
| `rotation_deg` | float | `0.0` | 🔗 Grados (antihorario) que se rotan los fotogramas **al cargarlos** para dejar el número horizontal. `roi` y `qc.anchor` están en coordenadas del fotograma ya rotado. Lo fija `calibrate` (UI o `--rotate`); `calibrate --auto` lo hereda de la receta. Incompatible con `extract --roi-only`. |

## `roi` — la región del número — 📍 por corrida (🔗 en `calib/` es la *referencia*)

| campo | tipo | efecto |
|---|---|---|
| `x`, `y` | int | esquina superior izquierda, en píxeles del fotograma extraído |
| `w`, `h` | int | ancho y alto |

Coordenadas del **fotograma de referencia** (`qc.reference_frame`). En los demás fotogramas la ROI
se corre por el `(dx, dy)` que mide el re-registro; si corrida así no entra en el fotograma, ese
fotograma queda `roi_outside` y se descarta.

En `runs/<id>/config.json` es la ROI de **esta** sesión, la que fija `calibrate`. En
`calib/config.json` es la ROI de **referencia**: las coordenadas que corresponden a
`calib/reference.jpg`, contra las que `calibrate --auto` registra las corridas nuevas.

Ajustarla a mano es legítimo: mirá `runs/<id>/out/calibracion.png`, corregí los números y volvé a correr
`qc` y `read`. Conviene que abarque **celdas de caracter completas**, no sólo la tinta: el reparto
en slots es uniforme y se apoya en eso.

## `digits` — cómo se reparte la ROI — 🔗 compartido

| campo | tipo | default | efecto |
|---|---|---|---|
| `n_digits` | int | `5` | **Celdas de caracter**, incluyendo el punto y el signo. `0.597` → 5; `-0.018` → 6. |
| `splits` | lista de int | `[]` | Cortes en píxeles relativos al borde izquierdo de la ROI, `n_digits+1` valores. Vacío = reparto uniforme. Se usa cuando la fuente no es monoespaciada o los caracteres no quedan centrados. |
| `separator_slots` | lista de int | `[1]` | Índices (0-based) de los slots que son separadores. Se leen como control de alineación pero no aportan dígitos. Vacío = ninguno. |
| `decimal_after` | int | `1` | Dígitos antes del punto. Con dígitos `0,5,9,7` y `decimal_after: 1` → `0.597`. |
| `polarity` | string | `light_on_dark` | `light_on_dark` (display luminoso, como este) o `dark_on_light` (LCD reflectivo clásico). Lo detecta `calibrate` solo. |
| `sign_slot` | int o `null` | `null` | Índice de la **celda del signo** (normalmente `0`). Cuenta dentro de `n_digits`. La celda queda vacía cuando el valor es positivo; con `null` el display se trata como sin signo. Receta con signo: `n_digits: 6`, `sign_slot: 0`, `separator_slots: [2]`, como en el ejemplo. Con signo, la biblioteca **necesita** la plantilla `-`: sin ella las lecturas negativas se descartan (`teach status` y `read` lo avisan). |
| `sign_max_ink` | float | `0.03` | Fracción de tinta bajo la cual la celda del signo se considera vacía (valor positivo). |

De esta geometría sale también qué caracteres tiene que tener la biblioteca: los dígitos, el `.`
y, si hay `sign_slot`, el `-`. Es lo que `teach status` y `teach lib list` informan en `faltan:`.

## `templates` — matcheo contra la biblioteca — 🔗 compartido

| campo | tipo | default | efecto |
|---|---|---|---|
| `size` | `[ancho, alto]` | `[24, 40]` | Tamaño canónico al que se normaliza cada glifo. **Si lo cambiás hay que reconstruir la biblioteca** (`teach train`), porque las plantillas guardadas quedan de otro tamaño. |
| `min_score` | float | `0.60` | NCC mínima del mejor match para aceptar un dígito (la **confianza**). Subirlo descarta más y, en lo medido, **no mejora la exactitud**: en el primer video del proyecto (`20260901_164220`, sep-2026, 5 celdas sin signo; esa corrida ya no está en `runs/`) las lecturas de confianza 0.60–0.65 se desviaban de la mediana local exactamente lo mismo (0.002 Abs) que las de confianza > 0.80, y subirlo a 0.70 habría bajado la cobertura del 86 % al 55 % de los segundos sin ganar nada. |
| `min_margin` | float | `0.05` | Diferencia mínima entre el mejor match y el mejor de **otra etiqueta** (el **margen**). Es lo que evita aceptar un `8` que correlaciona casi igual con el `6`. |

## `qc` — filtro de calidad y registro — 📍 por corrida

Los seis umbrales se **auto-sugieren** de la distribución observada (mediana ± 6·MAD) cada vez que
corrés `qc`, y se guardan acá. Para congelarlos, editalos y corré `qc --no-auto-thresholds`.

| campo | tipo | efecto | estado que dispara |
|---|---|---|---|
| `min_mean_luma` | float | luminancia media mínima de la ROI | `dark` |
| `max_mean_luma` | float | luminancia media máxima | `blown` |
| `min_contrast` | float | contraste mínimo (p95 − p05) | `low_contrast` |
| `min_blur_var` | float | varianza del Laplaciano mínima (nitidez) | `blur` |
| `min_ink_fraction` | float | fracción mínima de píxeles de tinta | `blank` |
| `max_ink_fraction` | float | fracción máxima (una mano delante tapa todo) | `occluded` |
| `anchor` | ROI | parche estático usado para medir el corrimiento. Debe tener **estructura** (bordes, texto fijo): un fondo liso da una NCC ruidosa. Lo elige solo `auto_anchor`, normalmente sobre la serigrafía `UV/VIS SPECTROPHOTOMETER` del gabinete. | — |
| `min_anchor_ncc` | float | NCC mínima del ancla **ya alineada**. Por debajo, el fotograma no es comparable con la referencia. | `camera_moved` |
| `reference_frame` | string | fotograma contra el que se registran todos los demás. Es el mismo sobre el que se calibró la ROI, así que sus coordenadas son el origen. | — |
| `max_shift_px` | int | corrimiento máximo tolerado, y también el margen de búsqueda del template matching. Más allá, `camera_moved`. | `camera_moved` |
| `register` | bool | activa el re-registro. En `false`, la ROI queda clavada en coordenadas absolutas: sólo tiene sentido si comprobaste que no hay deriva. | — |

El estado `roi_outside` no depende de un umbral: es la ROI que, corrida por la deriva, no entra en
el fotograma.

## `time` — alineación temporal — 📍 por corrida

| campo | tipo | default | efecto |
|---|---|---|---|
| `offset_s` | float | `0.0` | Segundos que se suman a `t_s` para dar la columna `t_exp`. **Este es el parámetro para alinear con el log manual del laboratorio.** Admite negativos: si el video arrancó 30 s *antes* que tu planilla, poné `-30`. |
| `absolute_start` | string \| null | `null` | Hora de reloj del `t=0` del video, ej. `"2026-09-01 16:42:20"`. Si está, `absorbance.csv` gana una columna `datetime` en ISO. Formatos aceptados: `YYYY-MM-DD HH:MM:SS`, `YYYY-MM-DDTHH:MM:SS`, `YYYY-MM-DD HH:MM`. |

Cambiar cualquiera de los dos afecta sólo a `report`: volvé a correr `python -m spectro report`,
que es cuestión de segundos, sin re-leer los fotogramas.

## `read` — plausibilidad temporal — 🔗 compartido

| campo | tipo | default | efecto |
|---|---|---|---|
| `max_rate` | float | `0.5` | Máxima \|ΔAbs\|/Δt (Abs por segundo) admitida contra los vecinos. Un punto que se despega de **ambos** vecinos por encima de esto, y cuyos vecinos son coherentes entre sí, se marca `spike` y se descarta. Bajarlo detecta más dígitos mal leídos, pero si lo bajás demasiado empieza a comerse las transiciones reales del experimento. |

En el primer video del proyecto quedó en `0.5` y no descartó ningún punto: las dos excursiones
aisladas que tenía la curva (t = 138.75 s y t = 192.75 s) se verificaron a mano contra el fotograma
y eran **lecturas correctas** — el display realmente mostraba `0.781` y `0.832` durante un cambio de
solución.

## `acceptance` — criterio del lote — solo en `calib/`

Los umbrales con los que `batch` (y `teach test eval`) dan el veredicto `accept` / `review` de cada
corrida. Se leen **solo** de `calib/config.json`: al sembrar una corrida se dejan vacíos, porque el
criterio es el mismo para todos los videos. Los flags `--min-accuracy`, `--max-error` y
`--min-coverage` les ganan.

| campo | tipo | default | efecto |
|---|---|---|---|
| `min_accuracy` | float o `null` | `null` | Exactitud mínima sobre `test.csv` (correctas / muestras de prueba), como fracción: `0.95`, no `95`. |
| `max_error` | float o `null` | `null` | Error máximo entre las lecturas aceptadas de `test.csv` (erróneas / aceptadas). |
| `min_coverage` | float o `null` | `null` | Cobertura mínima de la corrida: lecturas `ok` / fotogramas extraídos. |

```json
  "acceptance": {
    "min_accuracy": null,
    "max_error": null,
    "min_coverage": null
  }
```

**No hay valores por defecto, a propósito.** Con los tres en `null` no hay veredicto (la columna
queda vacía y `batch` lo avisa): un criterio que nadie midió daría una confianza que no existe. Se
fijan con los números de la ronda final de la
[guía](GUIA_CALIBRACION.md#5-la-ronda-final), sabiendo que con 20-40 muestras de prueba cada
exactitud tiene un intervalo ancho. Las claves viejas `min_exactitud` y `min_cobertura` se siguen
aceptando.

## Claves que ya no se usan

| clave | era | ahora |
|---|---|---|
| `templates.cluster_hamming` | distancia de hash para agrupar glifos en el viejo comando `templates` | se ignora al cargar; la deduplicación usa la NCC (≥ 0,95) |

Los `config.json` que la tienen siguen cargando sin error: cualquier clave desconocida se ignora,
y desaparece la próxima vez que la herramienta guarda el archivo. No hace falta borrarla a mano.
(El `min_count` del viejo comando `templates` era un flag, `--min-count`, no un campo de
`config.json`; desapareció con el comando.)
