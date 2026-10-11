# Referencia de comandos

**Para quién y cuándo leerlo:** para cuando ya sabés qué querés hacer y necesitás el comando
exacto, sus flags y sus valores por defecto. Para aprender el recorrido completo, empezá por la
[primera corrida](../empezar/primera-corrida.md); para el porqué de cada paso de calibración, por la
[guía](../calibrar/guia.md).

Todos aceptan `--help` y los cuatro flags globales del layout, que pueden ir antes o después del
subcomando:

| flag global | default | qué hace |
|---|---|---|
| `--run <id>` | — | deriva config, fotogramas, índice y salidas de `runs/<id>/` (no se usa en `teach`) |
| `--runs-dir` | `runs` | carpeta que contiene las corridas |
| `--calib-dir` | `calib` | carpeta de la calibración compartida |
| `--config` | `runs/<run>/config.json` | config de la corrida (no se usa en `teach`) |

**Un flag explícito siempre le gana a lo derivado**, así que se puede apuntar una etapa a otra
carpeta sin dejar de usar `--run`. Si a un subcomando de etapa le falta `--run` y no le pasaste
las rutas a mano, falla listando las corridas disponibles: adivinar cuál es mezclaría dos
experimentos en silencio. Para **probar algo que escribe sin tocar los datos reales**, apuntá
`--calib-dir` (y `--runs-dir`) a una copia. Dónde vive cada carpeta está en
[carpetas](carpetas.md).

## `doctor`
Diagnóstico del entorno: versión de Python, si el venv está activo, paquetes instalados, qué
ffmpeg/ffprobe resolvió y qué aceleradores por hardware hay. Después lista el estado de `calib/`
(receta, `reference.jpg`, cuántas plantillas) y **una línea por corrida** con su estado de
calibración, cuántos fotogramas tiene y si ya produjo salida. Es la primera línea de
[diagnóstico](../diagnosticar/problemas.md).

## `new` — dar de alta una corrida
```powershell
python -m spectro new videos/IMG_8102.MOV --fps 4
python -m spectro new videos/otro.MOV --name cinetica-fe-02
```
Crea `runs/<id>/`, siembra su `config.json` desde `calib/config.json` y registra el video con su
fps. **No toca el video ni lo copia**: la corrida lo referencia por ruta. Hereda geometría y
parámetros de matcheo; deja ROI, ancla y umbrales de QC sin fijar, que son de esta sesión. Cómo se
deriva el id del nombre del video está en [carpetas](carpetas.md#el-id-de-la-corrida).

| flag | default | qué hace |
|---|---|---|
| `--name` | derivado del video | id de la corrida |
| `--fps` | `1.0` | frecuencia de muestreo de esta corrida |
| `--force` | off | re-sembrar el `config.json` aunque la corrida ya exista |

## `extract` — video → fotogramas
```powershell
python -m spectro extract --run img_8102
```
| flag | default | qué hace |
|---|---|---|
| `--video` | el de `config.json` de la corrida | video de entrada |
| `--fps` | el de la corrida | frecuencia de muestreo en Hz |
| `--output` | `runs/<run>/frames` | carpeta destino |
| `--index` | `runs/<run>/frames_index.csv` | CSV de índice; `""` para no escribirlo |
| `--start` | `0` | segundo del video donde empezar |
| `--duration` | todo | segundos a extraer (para pruebas rápidas) |
| `--scale` | — | factor de escala, ej. `0.5` |
| `--jpeg-quality` | `2` | calidad JPEG de ffmpeg (2 mejor, 31 peor) |
| `--roi-only` | off | guarda sólo el recorte: ~2 KB/fotograma en vez de ~145 KB |
| `--no-clean` | off | no borrar los fotogramas previos |
| `--save-config` | off | guardar video y fps en el `config.json` de la corrida |

Los fotogramas se llaman **`t_0000601.000.jpg`**: segundos desde el inicio del video, con ceros
a la izquierda y 3 decimales, de modo que el orden alfabético sea el orden temporal.

> `--roi-only` ahorra disco pero **desactiva el re-registro**: al no guardar el contexto alrededor
> del número, ya no hay ancla contra la cual medir la deriva de la cámara. Tampoco es compatible
> con una rotación (`rotation_deg`).

## `calibrate` — definir la ROI y los slots
```powershell
python -m spectro calibrate --run <id> --auto     # registra contra calib/reference.jpg
python -m spectro calibrate --run <id>            # interactivo
python -m spectro calibrate --run <id> --roi 754,706,127,48 --n-digits 5 --decimal-after 1 --no-refine
```
El encuadre es **propio de cada corrida**, así que esto se hace una vez por corrida.

**`--auto`** es lo que hace viable el lote: toma la ROI y el ancla de referencia de
`calib/config.json` (coordenadas de `calib/reference.jpg`), busca ese parche de ancla en el
fotograma de esta corrida con un margen amplio (`--search-px`, default 200) y corre la ROI por el
`(dx, dy)` que encuentra. Si la NCC no llega a `--min-score` (default 0.6), **no inventa una
ROI**: avisa que el encuadre cambió demasiado y pide calibrar a mano. Corrige **traslación, no
rotación ni escala** — si el teléfono quedó a otra distancia o inclinado, el score cae y cae en el
camino manual, que es el comportamiento correcto.

Sin `--auto` abre una **UI** con el fotograma a la izquierda y un **panel lateral** a la derecha.
Arrastrá un rectángulo (amarillo, para que contraste con el fondo azul) sobre el número; el resto
se maneja con botones:

| sección del panel | qué tiene |
|---|---|
| **Encuadre** | rotación (botones −1 / −.1 / +.1 / +1 y un slider con los grados reales) y guías horizontales para nivelar |
| **Número** | celdas de caracter, dígitos antes del punto, `Signo` (suma o quita la celda del signo) y `Ajustar a tinta` |
| **Datos** | ROI final, celdas, separador, signo, polaridad, tamaño de imagen y plantillas de `calib/` |
| **Vista previa** | la ROI binarizada con los cortes de slot, el carácter y el score de cada celda (verde si pasa `min_score`) y el valor leído |
| **Prueba** | lee 20 fotogramas repartidos por la corrida y resume cuántos son válidos, el rango y el motivo de descarte |
| **Lupa** | mientras el cursor está sobre el fotograma aparece una lupa (arriba a la izquierda, se pasa a la derecha si el cursor se acerca) con el recorte a resolución completa, la mira, la ROI y los cortes de slot, y la posición `x, y` del cursor. Los botones `-` / `+` de la fila de guías cambian el aumento (x4, x8, x12, x16) |
| botones de abajo | `Resetear`, `Cancelar`, `Guardar` |

La **vista previa usa el mismo lector que `read`** con la biblioteca de `calib/templates`: si ahí
dice `No se puede leer`, el pipeline tampoco va a poder (falta una plantilla, p. ej. el `-`, o la
ROI/celdas no calzan). Es preliminar: la prueba de 20 fotogramas no aplica el re-registro de cámara
que hace `qc`. Lo que guarda `Guardar` es la **ROI final** que muestra el panel.

Las teclas siguen como atajos: `q`/`e` y `a`/`d` rotan, `+`/`-` celdas, `[`/`]` punto, `s` signo,
`g` guías, `z`/`x` lupa, `p` probar, `r` resetear, `ENTER` guarda y `ESC` cancela. Los tres
caminos guardan la misma configuración en `runs/<id>/config.json` y dejan
`runs/<id>/out/calibracion.png` con el overlay dibujado para auditar el corte.

**Las celdas se cuentan incluyendo el punto**: en `0.597` la fuente es monoespaciada y el punto
ocupa su propia celda, así que son **5 slots**, no 4. Con signo, `-0.018` son 6. `calibrate`
detecta solo cuál es el slot del punto (el de menos tinta) y lo anota en `separator_slots`.

| flag | qué hace |
|---|---|
| `--auto` | calibrar por registro contra `calib/reference.jpg` |
| `--search-px` | margen de búsqueda del ancla en `--auto` (default 200) |
| `--min-score` | NCC mínima del ancla en `--auto` (default 0.6) |
| `--promote` | copiar ROI, ancla y fotograma de esta corrida a `calib/` como nueva referencia |
| `--frame` | fotograma a usar (default: el del medio de la carpeta de fotogramas) |
| `--frames-dir` | carpeta de fotogramas de donde tomar la muestra |
| `--roi x,y,w,h` | modo no interactivo, sin ventana gráfica |
| `--no-refine` | usar la ROI tal cual, sin ajustarla al bounding box de la tinta |
| `--n-digits`, `--decimal-after` | celdas y posición del punto, sin preguntar |
| `--splits` | cortes manuales, ej. `0,26,52,78,104,127` |
| `--separators` | índices de slot que son separadores; vacío para ninguno |
| `--anchor x,y,w,h` | ancla de registro manual (default: automática) |
| `--polarity` | `auto` (default), `light_on_dark`, `dark_on_light` |
| `--sign` | el display muestra signo: la celda de más a la izquierda es el signo (se cuenta en `--n-digits`) |
| `--rotate DEG` | rotar los fotogramas DEG grados (antihorario) para dejar el número horizontal |
| `--preview` | PNG con el overlay de ROI y slots (default: `out/calibracion.png`) |

## `qc` — filtro de calidad
```powershell
python -m spectro qc --run <id>
```
Mide cada fotograma **sobre la ROI** y escribe `runs/<id>/out/qc_report.csv`. Los umbrales se
auto-sugieren de la distribución observada (mediana ± 6·MAD) y quedan escritos en el
`config.json` de la corrida; con `--no-auto-thresholds` usa los que ya estén ahí. Un fotograma en
el que la ROI (corrida por la deriva medida) no entra queda `roi_outside`: se descarta, no aborta
la corrida.

## `read` — fotogramas → números
```powershell
python -m spectro read --run <id>
```
Escribe `runs/<id>/out/readings.csv` (todas las lecturas, incluidas las descartadas, con su
`confidence` y su `margin`), actualiza la columna `status` de `qc_report.csv` y deja
`out/read_meta.json` con la **huella** de la biblioteca con la que leyó (ver
[salidas](salidas.md), sección `read_meta.json`). Las plantillas salen de
`calib/templates/`. Si la geometría tiene celda de signo y la biblioteca no tiene la plantilla `-`,
avisa una vez por corrida: las lecturas negativas se van a descartar.

## `report` — salidas finales
```powershell
python -m spectro report --run <id>
```
Escribe `runs/<id>/out/absorbance.csv`, `preview.png` (la curva) y `contact_sheet.png` (los 40
recortes de menor confianza). Cierra con el **cuadre de conteos**: válidas + descartadas debe dar
exactamente los fotogramas extraídos. `--no-plots` deja sólo el CSV.

## `run` — pipeline completo
```powershell
python -m spectro run --run <id> --fps 4
python -m spectro run --run <id> --skip-extract      # reusar los fotogramas ya extraídos
```
Acepta los flags de `extract`, `qc`, `read` y `report`.

## `batch` — varios videos de punta a punta
```powershell
python -m spectro batch videos/*.MOV --fps 4
python -m spectro batch videos/*.MOV --fps 4 --until qc    # solo prepara el pool, sin leer
python -m spectro batch videos/*.MOV --fps 4 --min-accuracy 0.95 --min-coverage 0.8   # valores de ejemplo
```
Por cada video: `new --force` → `extract` → `calibrate --auto` → `qc` → `read` → `report`. Salta
las corridas que ya tienen `out/absorbance.csv` (o el `absorbancia.csv` de versiones anteriores);
`--no-skip-existing` las rehace. Si `calibrate --auto` no llega al score, **saltea esa corrida y
sigue con la siguiente**; al final lista las que quedaron pendientes de calibración manual, con el
comando listo para copiar.

Cuando llega hasta `report`, imprime y escribe **`runs/batch_report.csv`** (sus columnas, en
[salidas](salidas.md)): una fila por corrida
(las procesadas y las salteadas por estar hechas) con los descartes por motivo, la cobertura, la
evaluación de su `test.csv` con la biblioteca vigente y un **veredicto** `accept` / `review`. El
veredicto solo existe si hay umbrales: los flags de abajo o la sección `acceptance` de
`calib/config.json` ([config](config.md#acceptance--criterio-del-lote--solo-en-calib)). **No
hay umbrales por defecto**: sin ellos el veredicto queda vacío y el comando lo avisa. Los valores
del ejemplo de arriba muestran la sintaxis; no son una recomendación.

| flag | default | qué hace |
|---|---|---|
| `--fps` | `1.0` | frecuencia de muestreo de todas las corridas del lote |
| `--until` | `report` | cortar después de `qc`, `read` o `report`. `qc` prepara los fotogramas sin leer: sirve antes de armar la biblioteca |
| `--skip-existing` / `--no-skip-existing` | saltear | saltear o re-procesar las corridas ya terminadas |
| `--search-px` | `200` | margen de búsqueda del ancla en `calibrate --auto` |
| `--min-score` | `0.6` | NCC mínima del ancla en `calibrate --auto` |
| `--min-accuracy` | `acceptance` | veredicto: exactitud mínima sobre `test.csv` (fracción, ej. `0.95`) |
| `--max-error` | `acceptance` | veredicto: error máximo entre las lecturas aceptadas de `test.csv` (fracción) |
| `--min-coverage` | `acceptance` | veredicto: cobertura mínima de la corrida, lecturas `ok` / fotogramas extraídos (fracción) |

Un flag le gana al valor de `acceptance`. Una corrida queda en `review` si no llega a un umbral,
si un umbral de la prueba no se puede verificar (no tiene `test.csv`), o si sus salidas no se
leyeron con la biblioteca vigente (`stale`, `no_fingerprint`, `no_reading`).

> **Cuidado:** `batch` re-siembra el `config.json` de cada corrida desde `calib/` (`new --force`).
> Si calibraste a mano una corrida que todavía no tiene salida, `batch` la pisa: para esas,
> corré las etapas sueltas.

## `teach` — entrenar y medir el lector

`teach` reúne todo lo que toca la biblioteca y las muestras. Se elige un **área** y un **verbo**, y
el **id de la corrida va como argumento**, completo (`img_8102`), nunca con `--run`:

```
teach status                                         panorama y siguiente paso
teach lib     list | delete | relabel | clear | backups | restore     la biblioteca GLOBAL
teach train   [RUN ...]                              arma la biblioteca desde las muestras
teach check   [RUN ...]                              valida las muestras sin escribir la biblioteca
teach samples list | add | remove | suggest | label  muestras de ENTRENAMIENTO (truth.csv)
teach test    list | add | remove | suggest | label | eval | history   muestras de PRUEBA (test.csv)
```

Cada área tiene su ayuda (`python -m spectro teach lib --help`, y lo mismo con las demás). La sintaxis anterior de `teach`
(un solo comando con flags de modo) ya no existe: si la usás, el comando falla y muestra la tabla
de migración, que también ves con:

```powershell
python -m spectro teach --help
```

**Para probar sobre una copia**, `--calib-dir` y `--runs-dir` funcionan igual que en el resto:

```powershell
python -m spectro teach train --calib-dir <copia_de_calib>
```

Cómo se usan estos comandos dentro del ciclo de calibración, y por qué, está en la
[guía](../calibrar/guia.md).

### `teach status` — dónde estoy
```powershell
python -m spectro teach status
```
Muestra la biblioteca (plantillas por carácter, los caracteres que faltan, su **huella** y los
respaldos), una fila por corrida (muestras de entrenamiento y de prueba, estado de las salidas,
última evaluación), los descartes de qc por motivo y una lista de **siguientes pasos**. No escribe
nada. El estado de las salidas de cada corrida es:

| estado | significa |
|---|---|
| `up_to_date` | `readings.csv` se leyó con la biblioteca de hoy (misma huella) |
| `stale` | se leyó con otra biblioteca: hay que volver a correr `read` y `report` |
| `no_fingerprint` | no hay `read_meta.json` y no se puede saber con qué biblioteca se leyó |
| `no_reading` | la corrida todavía no tiene `readings.csv` |

### `teach lib` — la biblioteca global (sin corrida)
```powershell
python -m spectro teach lib list                 # plantillas por carácter y los que faltan
python -m spectro teach lib list --usage         # cuántas celdas gana bien y mal cada plantilla
python -m spectro teach lib delete 0_3 5_1       # borrar plantillas por nombre
python -m spectro teach lib relabel 0_3 6        # cambiarle la etiqueta a una plantilla
python -m spectro teach lib clear --yes          # vaciarla (sin --yes, falla)
python -m spectro teach lib backups              # listar los respaldos
python -m spectro teach lib restore              # volver al último respaldo (o: restore <nombre>)
```
Las plantillas se llaman `<carácter>_<n>.png` (el punto es `dot_<n>`, el signo `minus_<n>`). Con
`--usage`, una plantilla que gana celdas de otro carácter sale marcada `DANINA` y una que no gana
ninguna, `sin uso`. Los borrados dejan huecos en la numeración (`0_0`, `0_2`), que es inofensivo.

**Respaldos.** Antes de cada cambio que borra algo (`train` sin `--keep`, `delete`, `relabel`,
`clear`, `restore`) la biblioteca se copia a `calib/.backups/<AAAAmmdd_HHMMSS>/` y se conservan
los **últimos 5**. `restore` respalda el estado actual antes de restaurar, así que también se
puede deshacer. La ventana de `teach` toma **un solo respaldo por sesión**, antes del primer
cambio a la biblioteca: borrar muchas plantillas seguidas en una sesión no rota los 5 respaldos ni
pierde el estado que había al abrirla. Los respaldos con otro nombre (hechos a mano) no se podan ni
aparecen en `backups`.

### `teach train` y `teach check` — armar la biblioteca
```powershell
python -m spectro teach train                       # con las muestras de TODAS las corridas
python -m spectro teach train --exclude img_8112    # ...menos un video reservado como prueba
python -m spectro teach train img_8102 --keep       # suma las de una corrida, sin duplicar
python -m spectro teach check                       # solo valida, no escribe la biblioteca
```
`train` junta los `truth.csv` de las corridas elegidas (sin argumentos, todas las que tengan) y
**reemplaza** la biblioteca, respaldando la anterior; con `--keep` **suma** sin duplicar (descarta
los glifos casi idénticos a uno que ya está). Cada corrida se recorta con **su propia** config y su
corrimiento de cámara. Imprime la cobertura de `0-9 . -`, el leave-one-out por corrida y escribe
`runs/<id>/out/teach_report.csv`. **Los `test.csv` no se usan nunca.** `check` hace lo mismo sin
escribir la biblioteca (sí escribe los `teach_report.csv`).

> `teach train img_8102` **sin** `--keep` reemplaza la biblioteca compartida con las muestras de
> ese solo video: si ese video no tiene valores negativos, se pierde la plantilla `-`. Para eso
> está `teach lib restore`.

| flag | default | qué hace |
|---|---|---|
| `RUN …` | todas las que tengan `truth.csv` | corridas cuyas muestras se usan |
| `--exclude RUN …` | — | corridas que no entrenan (hold-out por video) |
| `--keep` | off | (`train`) sumar a la biblioteca en vez de reemplazarla |
| `--max-per-label` | `3` | (`train`) variantes máximas por carácter |
| `--gap SEGUNDOS` | `5` | avisar si una prueba está a menos de esto de un fotograma de entrenamiento |

### `teach samples` y `teach test` — los dos conjuntos de una corrida

Son simétricos: `samples` maneja el **entrenamiento** (`runs/<id>/truth.csv`) y `test` la
**prueba** (`runs/<id>/test.csv`), que **nunca** entra a la biblioteca. Un fotograma está en un
solo conjunto: agregarlo a uno lo saca del otro (y si pasa de entrenamiento a prueba, avisa que ya
aportó glifos a la biblioteca).

```powershell
python -m spectro teach samples list                       # tabla de todas las corridas
python -m spectro teach samples list img_8102              # sus muestras y cuántas lee bien la biblioteca
python -m spectro teach samples suggest img_8102 30        # qué fotogramas etiquetar
python -m spectro teach samples label img_8102 --queue 30  # la ventana, solo con esos 30
python -m spectro teach samples label img_8102             # la ventana, con todos los que pasaron QC
python -m spectro teach samples add img_8102 t_0001352.000.jpg=-0.018 t_0000069.250.jpg=-0.004
python -m spectro teach samples remove img_8102 t_0000069.250.jpg
python -m spectro teach test suggest img_8102 20           # para la prueba: siempre al azar
python -m spectro teach test label img_8102 --queue 20
python -m spectro teach test add img_8102 t_0000103.500.jpg=-0.005
python -m spectro teach test eval img_8102                 # informe, test_report.csv e historial
python -m spectro teach test eval                          # tabla de todas las corridas con prueba
python -m spectro teach test history img_8102              # la curva de aprendizaje
```

**Corré `qc` antes**: `teach` recorta cada celda con el mismo corrimiento de cámara que usa `read`.
Sin eso la deriva corta los glifos y la biblioteca no coincide con lo que después se lee (si falta
`qc_report.csv`, avisa). Los valores se guardan como texto, así que conservan el signo de `-0.000`
y los ceros finales; un valor que no calza con la geometría (`-0.018` necesita 6 celdas con signo)
se rechaza al escribirlo.

**`suggest`** imprime fotogramas para etiquetar. En `samples`, `--strategy` elige el criterio:
`uniform` reparte parejo (la primera ronda, sin biblioteca), `random` es azar estratificado por
tiempo, `uncertain` elige donde el lector duda y `mixed` —el default— es mitad y mitad. En `test`
**siempre es al azar** y lejos del entrenamiento. Por qué se hace así está en la
[guía](../calibrar/guia.md#paso-5--rondas-siguientes-dónde-etiquetar).

**`eval`** con una corrida imprime el informe (correctas, erróneas aceptadas, descartadas, con
intervalos de Wilson al 95 %), escribe `out/test_report.csv` y agrega una fila a
`out/teach_history.csv`. Sin corridas (o con varias) imprime una tabla, la misma de `batch`, y no
escribe nada. `--min-accuracy`, `--max-error` y `--min-coverage` agregan el veredicto, igual que en
`batch`.

| flag | dónde | default | qué hace |
|---|---|---|---|
| `N` | `suggest` | `20` | cuántos fotogramas |
| `--strategy` | `samples suggest`, `samples label` | `mixed` | `mixed`, `uncertain`, `random` o `uniform` |
| `--seed S` | `suggest`, `label` | ninguna | semilla del azar (ver abajo) |
| `--gap G` | `suggest`, `label`, `eval` | `5` | separación mínima en segundos entre elegidos, y entre prueba y entrenamiento |
| `--queue N` | `label` | `0` (todos) | abrir la ventana solo con los N fotogramas sugeridos |
| `--max-per-label` | `label` | `3` | variantes máximas por carácter para los botones de biblioteca de la ventana |
| `--min-accuracy`, `--max-error`, `--min-coverage` | `test eval` | `acceptance` | umbrales del veredicto (fracciones) |

**`--seed`.** Sin `--seed`, las sugerencias usan siempre la semilla 0 (la misma lista cada vez) y
el botón `Aleatorio` de la ventana salta a un fotograma distinto cada vez. Con `--seed S` las dos
cosas son reproducibles: misma semilla, misma lista y misma secuencia de saltos.

### La ventana de `teach` (`samples label`, `test label`)

A la izquierda, la ROI del fotograma ampliada con los cortes de slot y, debajo de cada celda, el
carácter que le toca según el valor que escribiste y lo que lee hoy el lector, con su score. A la
derecha, el panel. **El valor se escribe con el teclado físico** (dígitos, `.` y `-`; `Backspace`
borra el último carácter); la ventana no tiene teclado numérico de botones.

| control | qué hace |
|---|---|
| `<`, `>`, `<<10`, `10>>` (o las flechas ← →) | moverse por los fotogramas que pasaron QC |
| `Aleatorio` | saltar a un fotograma al azar (reproducible solo con `--seed`) |
| `Color / binario` | ver el recorte en color o binarizado |
| `Borrar todo` | vaciar el valor escrito |
| `Agregar muestra` (o `Enter`) | guardar el valor en el conjunto activo y pasar al siguiente |
| `Quitar` | sacar la muestra de este fotograma |
| `Conjunto: Entrenam. / Prueba` | a qué conjunto va `Agregar muestra`; `samples label` abre en `Entrenam.`, `test label` en `Prueba` |
| `Agregar a biblioteca` | suma las muestras de entrenamiento a la biblioteca, sin duplicar (como `train --keep`) |
| `Reemplazar biblioteca` | la reescribe desde cero con las muestras actuales; pide un segundo clic |
| `Validar` | leave-one-out de las muestras, sin tocar la biblioteca |
| `Evaluar prueba` | lo mismo que `teach test eval <id>` |
| `Gestionar biblioteca` | la grilla de plantillas (abajo) |
| `Guardar y salir` (o `Esc`) | cerrar |

Abajo se ve la **cobertura** de `0-9 . -`: verde con 2+ ejemplos, naranja con 1, rojo si falta
(ese carácter no se va a poder leer). Cada muestra se guarda al agregarla.

**Gestionar biblioteca** muestra todas las plantillas de `calib/templates`, cada una con cuántas
celdas de tus muestras **gana bien** y cuántas **gana mal** (en rojo: esa plantilla confunde un
carácter con otro); las que no aportan aparecen atenuadas. Elegís una y podés `Borrar
seleccionada`, `Borrar todas las de '<c>'` (ambos piden confirmación), `Deshacer ultimo borrado`
o cambiarle el carácter con los botones `0-9 . -`. Tras cada cambio se recalcula la exactitud de la
biblioteca vigente sobre tus muestras. `Volver a muestras` regresa.

**Elegí fotogramas bien dibujados.** El último dígito se redibuja varias veces por segundo: si el
fotograma lo agarra a medio dibujar, saltalo. Si cambiaste la geometría (rotación, ROI o celdas),
reemplazá la biblioteca en vez de agregar: las plantillas viejas ya no coinciden con lo que se
recorta y, mezcladas con las nuevas, hacen perder lecturas.

---

**Siguiente paso:** qué escribe cada uno de estos comandos, columna por columna, en
[salidas](salidas.md).
