# Decisiones de diseño

**Para quién y cuándo leerlo:** cuando querés saber **por qué** spectro hace algo de una manera y no
de otra (antes de cambiarlo, o para decidir si confiar en un resultado). Cada decisión dice qué se
decidió, por qué y qué riesgo cubre. Cómo está armado el programa (pipeline, módulos y contratos)
está en la [arquitectura](arquitectura.md); de ahí salen también las cifras del primer video del
proyecto (`20260901_164220`, sep-2026) que se citan acá.

## Una receta compartida y corridas aisladas

La cámara **se re-monta en cada sesión**. El encuadre cambia entre videos, pero el equipo y la
fuente del display son los mismos. Ese único hecho es el que define el layout (el árbol de carpetas
está en [carpetas](../referencia/carpetas.md)): parte los datos en lo que se comparte
(`calib/`) y lo que es propio de cada corrida (`runs/<id>/`).

**Por qué `calib/` separada de `runs/`.** La alternativa obvia —un `config.json` por corrida, con
todo adentro— obliga a re-etiquetar los glifos en cada video, que es el único paso verdaderamente
manual del pipeline. Los glifos no cambian: el display es el mismo equipo. Poner la biblioteca y la
geometría del número en `calib/` las convierte en un activo que se construye una vez. La
alternativa opuesta —un solo `config.json` global— no funciona porque la ROI **sí** cambia en cada
montaje, y una ROI de otra sesión recorta al lado de los dígitos. Por eso `read` toma de `calib/`
**solo** la biblioteca; la geometría la lee de la config de la corrida.

**Por qué `runs/<id>/` aislados.** Cada corrida es un experimento distinto con su propio libro
mayor. Que `qc_report.csv` y `absorbance.csv` vivan dentro de la corrida hace imposible pisar los
resultados de un video con los de otro, que es el modo de falla que de verdad importa en datos de
laboratorio: silencioso y difícil de detectar después. Por la misma razón, un subcomando de etapa
sin `--run` **falla listando las corridas** en vez de elegir una, y `teach` exige el id completo.

**El id sale del video, no de un contador.** Es derivable, ordena cronológicamente (para los videos
con fecha en el nombre) y no necesita ningún registro central que mantener sincronizado con el
disco. `project.py` es el único módulo que sabe dónde va cada cosa; todo lo demás recibe las rutas
ya resueltas por parámetro.

## `calibrate --auto`: el re-registro, aplicado entre sesiones

`qc` ya registra cada fotograma contra el fotograma de referencia de su corrida, para compensar la
deriva lenta de la cámara a lo largo de 20 minutos. `calibrate --auto` es **la misma operación con
otro alcance**: en vez de comparar dos fotogramas de la misma sesión, compara el fotograma de
referencia de la corrida nueva contra `calib/reference.jpg`, de otra sesión.

1. Toma el ancla y la ROI de referencia de `calib/config.json`, en coordenadas de
   `calib/reference.jpg`.
2. Busca ese parche de ancla en el fotograma de la corrida nueva con `estimate_shift`, con margen
   amplio (`--search-px`, default 200 px, bastante mayor que los 40 px del registro
   intra-corrida: entre sesiones el teléfono se re-monta y el encuadre salta de verdad).
3. Si `score >= --min-score` (default 0.6), corre ROI y ancla por `(dx, dy)` y las guarda en el
   config de la corrida.
4. Si no, **no inventa una ROI**: avisa y pide `calibrate` manual para esa corrida.

**Limitación: corrige traslación, no rotación ni escala.** Si el teléfono quedó a otra distancia o
inclinado, no existe un `(dx, dy)` que arregle eso, y el score cae por debajo del umbral. Que caiga
en el camino manual es el comportamiento correcto, no una carencia: una ROI rotada recortaría
medio dígito y produciría lecturas plausibles pero equivocadas. Por eso la función también se
niega cuando la resolución del fotograma no coincide con la de la referencia, y cuando el
corrimiento sacaría la ROI fuera del fotograma.

Es lo que hace viable `batch`: sin `--auto`, procesar diez videos son diez sesiones interactivas
con la UI de `calib_ui`. Su vista previa llama a `read.read_frame` con la biblioteca de
`calib/templates`, el mismo camino que `read`, así que muestra lo que el pipeline va a hacer con esa
calibración.

## Template matching, y no Tesseract ni un VLM

| alternativa | por qué se descartó |
|---|---|
| **Tesseract** | Está entrenado para texto impreso; con dígitos de LCD de siete u once segmentos confunde 8/B, 0/O, 1/7 sistemáticamente. Además obliga a instalar un binario a nivel de sistema, que era una restricción explícita del proyecto. |
| **Un VLM por API** | Costo por fotograma, dependencia de red, y sobre todo **no es determinista**: el mismo fotograma puede dar dos respuestas distintas, y no hay forma de auditar por qué. Inaceptable para datos de laboratorio. |
| **Una CNN entrenada** | Habría que etiquetar cientos de ejemplos para resolver un problema que con cámara fija ya es trivial. |
| **Template matching (elegido)** | Determinista, sin dependencias externas, y el trabajo manual es etiquetar unas decenas de fotogramas escribiendo su valor. Da además un score de confianza natural (la NCC). Cuánto acierta no se supone: se mide con una prueba aparte (ver la [guía](../calibrar/guia.md)). |

La condición para que funcione es que la cámara esté fija y la tipografía sea constante — y las
dos se cumplen. Si dejaran de cumplirse, la sección
[Cómo extenderlo](arquitectura.md#cómo-extenderlo) dice qué cambiar.

## La ROI se calibra una vez, y se re-registra en cada fotograma

Con cámara fija, la ROI fija alcanza *en teoría*. En la práctica, medir el corrimiento del primer
video mostró una **deriva lenta de hasta 3 px en 20 minutos** — el soporte cede, alguien roza la
mesa. Sobre una ROI de 48 px de alto eso empieza a comerse los dígitos.

La solución es el **re-registro**: `qc` busca un parche de referencia (el ancla) en cada fotograma
por template matching, obtiene el corrimiento `(dx, dy)`, lo escribe en `qc_report.csv`, y `read`
mueve la ROI por ese corrimiento antes de recortar. La ROI sigue a la escena en vez de quedarse
clavada en coordenadas absolutas. **Todo recorte de celda usa ese corrimiento**, también el que
arma la biblioteca: si no, las plantillas no coincidirían con lo que después se lee.

El ancla se elige automáticamente (`auto_anchor`) como la ventana con **máxima energía de
gradiente fuera de la vecindad del número**. Que tenga bordes es esencial: un parche de fondo liso
da una NCC ruidosa y "detecta" movimiento donde no lo hay. En el primer video eligió sola la
serigrafía `UV/VIS SPECTROPHOTOMETER` del gabinete, que es lo más estático y contrastado del cuadro.

Antes de implementar esto, 215 de 1203 fotogramas se marcaban como `camera_moved`. Con re-registro,
los 1203 pasan y la deriva queda medida y compensada.

**Si la ROI corrida no entra en el fotograma** (`roi_outside`), ese fotograma se descarta y la
corrida sigue: un recorte truncado daría celdas incompletas que el lector compararía igual, y un
error cortaría la etapa entera por un solo fotograma. Es un estado más del libro mayor, con su
columna `qc_roi_outside` en el reporte del lote.

## El punto decimal se asume, no se lee

El formato es fijo (`0.597`), así que el valor se arma con `decimal_after` de la configuración. El
punto **sí se lee**, pero sólo como **control de alineación**: es el glifo más chico y el más fácil
de confundir, y si el slot del separador no matchea un punto, es señal de que la ROI no está donde
debería y la lectura entera se descarta.

Detalle que sorprende y conviene tener presente: la fuente del equipo es monoespaciada y **el punto
ocupa su propia celda de caracter**. Por eso `0.597` son **5 slots**, no 4, y el reparto uniforme
de la ROI en 5 partes cae perfecto sobre los caracteres.

## Los valores escritos reemplazan el etiquetado a ciegas

Agrupar glifos por hash y pedir que el usuario adivine qué es cada uno (el viejo comando
`templates`) escalaba mal: con deriva de cámara salían 56 "glifos únicos" cuando el display sólo
tiene 12 caracteres. `teach` invierte el problema: el usuario escribe el valor de un fotograma
(`-0.018`) y, como el formato es fijo, cada celda queda etiquetada sola. Dos consecuencias:

* **Todo recorte usa el offset de `qc`**, igual que `read`. Si la biblioteca se armara sin
  compensar la deriva, sus glifos no serían los que después se leen.
* **Hay una verdad de referencia**, así que la confianza se mide en vez de suponerse. La validación
  es *leave-one-out*: cada muestra se lee sin los glifos que salieron de ella misma, porque si no
  la exactitud sería circular. Un `-` o un `7` con un único ejemplo se evalúa sin ninguno: el
  informe lo marca en vez de esconderlo.

## Agregar a la biblioteca deduplica, y la biblioteca se puede auditar

Sumar plantillas sin más hace crecer la biblioteca con casi-duplicados, y las variantes de un
carácter compiten con las de otro por el margen mínimo entre etiquetas. Por eso `library.add`
descarta lo que ya está (mismo carácter y NCC ≥ 0,95 contra una plantilla existente), cuenta lo
existente contra el tope por carácter (3 por defecto) y es idempotente. El criterio es la **NCC**,
la misma medida con la que lee el lector, y no el hash perceptual de 8×8: en `img_8102` el hash
declaraba "duplicado" a un `6` con NCC 0,755 contra la plantilla `6` que el lector confundía con un
`5` (NCC 0,84), y por eso nunca se agregaba (el caso completo, en el
[ejemplo resuelto](../calibrar/ejemplo-img_8102.md#lección-sobre-el-duplicado)). "Duplicado" tiene
que significar "no le aporta nada al lector". Cada plantilla lleva además cuántas celdas de las
muestras gana bien (`uses`) y cuántas gana mal (`errors`): una plantilla con errores o una
biblioteca armada con otra geometría se ve de inmediato (`teach lib list --usage`), en vez de
aparecer como lecturas perdidas.

## Una biblioteca compartida, muestras por corrida

La biblioteca (`calib/templates/`) es una sola porque el display es el mismo equipo; las muestras
(`teach/truth.csv`, `test/test.csv`) son por corrida porque cada una apunta a fotogramas de un video concreto y
se recorta con la config de ese video. `teach train` junta las muestras de entrenamiento de todas
las corridas: cada una pasa por su propia ROI, rotación, celdas y corrimiento de cámara, y los
glifos se mezclan porque `normalize_glyph` los lleva al mismo tamaño. Dos detalles de implementación
que importan: las muestras se identifican como `corrida/archivo` (los videos repiten nombres de
fotograma, y con el nombre solo el leave-one-out descartaría también los glifos homónimos de otro
video), y la validación lee cada muestra con la config de su corrida, no con una única.
`teach train --exclude <id>` reserva videos enteros como prueba. El riesgo de compartir es que una
etiqueta equivocada contamina a todos los videos; por eso el leave-one-out se informa por corrida.

## `teach` por áreas, con el id de la corrida explícito

`teach` creció hasta ser un solo comando con unos 30 flags que eran "modos" (`--build`, `--eval`,
`--suggest`…), con reglas que el parser no podía expresar (un flag que solo valía junto a otro) y
que se validaban a mano. Ahora cada acción es un **verbo dentro de un área** (`lib`, `train`,
`check`, `samples`, `test`, `status`) y acepta solo los flags que le sirven: un flag que no
corresponde lo rechaza el parser.

* **Lo global no pide corrida.** La biblioteca es una sola: `teach lib list` no nombra ningún video.
* **El id de la corrida va como argumento, completo**, y `teach` rechaza `--run`. Sin abreviaturas
  ni "corrida activa": nunca se adivina sobre qué experimento se trabaja.
* **`samples` y `test` son simétricos**, y un fotograma está en un solo conjunto.
* **La sintaxis vieja falla con la tabla de migración** en vez de interpretarse a medias.

## Respaldo de la biblioteca, uno por sesión de la ventana

Una biblioteca compartida que se puede borrar plantilla por plantilla necesita una red: ya pasó una
vez que reconstruirla con las muestras de un solo video borró la plantilla `-`. Antes de cada cambio
que borra algo (`train` sin `--keep`, `delete`, `relabel`, `clear`, `restore`) la biblioteca se
copia a `calib/.backups/<fecha_hora>/`, y se conservan los últimos 5.

Cinco respaldos se agotan rápido si cada borrado respalda: diez borrados seguidos en la ventana
dejarían cinco copias casi iguales y se llevarían la del estado previo a la sesión, que es la única
que importa. Por eso la ventana de `teach` (`TeachSession`) toma **un solo respaldo, antes del
primer cambio** a la biblioteca, y las operaciones siguientes de esa sesión no respaldan. Abrir la
ventana solo para etiquetar no respalda nada.

## La huella de la biblioteca

Cambiar la biblioteca invalida en silencio todo lo que se leyó con la anterior: las lecturas, sus
incertidumbres y las evaluaciones. Comparar fechas de archivo no alcanza: una restauración deja la
biblioteca igual a una anterior pero con fechas nuevas, y lo leído con esa misma biblioteca parecería
viejo. La **huella** es un resumen de 12 caracteres del contenido y los
nombres de todas las plantillas; `read` la guarda en `read_meta.json` y `teach test eval` en
`teach_history.csv`. `teach status`, `teach test eval` y `batch` la comparan con la de hoy y marcan
las salidas `stale`. Las salidas anteriores a la huella se juzgan por fecha, como antes.

## El veredicto del lote no tiene umbrales por defecto

`batch` resume cada corrida (descartes por motivo, cobertura, evaluación de la prueba con la
biblioteca vigente) en `runs/batch_report.csv`, calculado por una función pura
(`report.batch_summary`). El veredicto `accept` / `review` solo aparece si hay umbrales
(`acceptance` en `calib/config.json` o flags). No hay valores por defecto porque un umbral que nadie
midió da una confianza que no existe; y una corrida sin prueba, o con salidas de otra biblioteca,
queda en `review` aunque sus números se vean bien, porque no hay con qué verificarlos.

## `summary`: un reporte que no toca los datos, y un total que no promedia

`summary` existe porque saber si el lector funciona obligaba a juntar a mano `teach status`,
`teach check`, `teach test eval` y `batch`. Tres decisiones:

* **Solo lectura sobre los datos.** Reutiliza el evaluador único (vía `report.load_run_input`) y el
  leave-one-out de `teach.train(build=False)`, que no escribe la biblioteca; lo único que escribe son
  los `runs/summary.*`. Se puede correr en cualquier momento del ciclo sin cambiar ningún resultado.
* **La fila `TOTAL` mide la prueba con el _hold-out_ por video si existe.** Mezclar `same_run` con
  `other_video` en un solo porcentaje taparía con la cifra optimista la que importa. Si no hay
  ninguna `other_video`, usa `same_run` y lo dice, en vez de callarlo.
* **La cobertura total suma solo las corridas leídas, y las salidas toman el peor estado.** Una
  corrida sin `readings.csv` bajaría la cobertura sin decir nada del lector; una sola corrida
  `stale` alcanza para que el total no se presente como al día.

## La semilla: reproducible cuando se pide

Las sugerencias de `suggest` usan siempre la misma semilla si no se pasa `--seed`: repetir el
comando da la misma lista, que es lo que se espera de una herramienta de laboratorio. El botón
`Aleatorio` de la ventana, en cambio, es no determinista salvo que se pase `--seed`: sirve para
recorrer el video sin sesgo, y con semilla se puede repetir una sesión exacta.

## Muestreo por incertidumbre y conjunto de prueba

El ciclo de calibración (etiquetar, agregar, evaluar, repetir) es aprendizaje supervisado con humano
en el circuito. La [guía de calibración](../calibrar/guia.md) lo explica paso a paso; acá, las decisiones
y el riesgo que cada una cubre.

* **La prueba es al azar, estratificado por tiempo, nunca por incertidumbre.** Una prueba formada por
  los casos difíciles subestima la exactitud real; una formada por los fáciles la sobrestima. Solo el
  azar es representativo. Se arma primero y se aparta (`test/test.csv`, en su propia carpeta), y
  **nunca entra a la biblioteca**.
* **Distancia mínima entre prueba y entrenamiento (`--gap`, 5 s).** A 4 fotogramas por segundo los
  vecinos son casi la misma imagen; un fotograma de prueba pegado a uno de entrenamiento infla la
  exactitud (_data leakage_). Se avisa cuando se viola. Mover una muestra de entrenamiento a prueba
  avisa que **ya aportó glifos** a la biblioteca: no se guarda de qué muestra salió cada plantilla.
* **La métrica separa tres resultados**: correcta, **errónea aceptada** y descartada. El proyecto
  prefiere abstenerse a equivocarse, así que el número que importa es la tasa de error *entre las
  aceptadas* y la cobertura, no una exactitud única. Los intervalos de Wilson (95 %) acompañan a cada
  porcentaje porque con 20 muestras la cifra sola engaña; suponen independencia, y por eso el informe
  cuenta los **valores distintos** (con un valor que se mantiene minutos, 20 fotogramas pueden ser pocos).
* **`same_run` u `other_video`.** Una prueba de la misma corrida mide ese video; la medida honesta
  es la de un video sin entrenamiento propio (_hold-out_ por video). `teach test eval` lo marca, y la
  biblioteca compartida con pruebas por corrida permite reservar un video entero.
* **La incertidumbre mira confianza *y* margen** (`u = min((confidence − min_score)/min_score,
  (margin − min_margin)/min_margin)`), porque el lector descarta por ambos. Por eso `read` guarda
  `margin`.
* **Persistencia temporal al 80 %.** Los fotogramas más inciertos son, sobre todo, el último dígito a
  medio redibujar: no se pueden etiquetar. El display lo redibuja con un parpadeo `ok`/baja durante
  varios segundos cada vez que el valor cambia (en `img_8102`, ~60 % de los vecinos dudan y todas las
  rachas de baja confianza duran ≤ 1 s). Con un umbral de 50 % ese parpadeo pasaba el filtro (5 de 6
  sugerencias eran basura); con 80 %, solo califica lo que hace dudar a casi todos los vecinos, que es
  lo que haría un glifo desconocido. En una corrida donde no hay glifos desconocidos, el resultado
  correcto es "no hay inciertos persistentes" y completar con azar.
* **Mixto por defecto.** Etiquetar solo lo difícil sesga el modelo hacia lo raro; la mitad al azar
  mantiene el panorama general.
* **Arranque en frío y lecturas viejas.** Con menos del 10 % de lecturas `ok`, o sin `readings.csv`, la
  incertidumbre no informa y la ronda es uniforme. Si `readings.csv` es anterior a la biblioteca o a la
  config (algo que ya pasó al cambiar la geometría), sus confianzas son de otro modelo: se usa azar y se
  avisa.
* **Los errores confiados solo los encuentra la prueba.** Un `6` leído como `5` con confianza 0,84 no
  aparece en la incertidumbre. Las `erróneas aceptadas` de `teach test eval` son la señal para decidir
  qué etiquetar después.

## El signo se decide por tinta, y la rotación se aplica al cargar

Algunas mediciones son negativas (`-0.018`). El display no mueve los dígitos: el `-` aparece en una
**celda fija a la izquierda** (`digits.sign_slot`) que queda vacía cuando el valor es positivo. Esa
celda se decide por **fracción de tinta** y no por NCC: una celda vacía con ruido no correlaciona con
ninguna plantilla y daría falsos descartes. Si hay tinta, tiene que matchear la plantilla `-` con
score y margen suficientes; si no, la lectura se descarta. Sin `sign_slot` el comportamiento es el
de siempre, pero entonces un `-` fuera de la ROI se perdería sin aviso: en displays que pueden dar
negativos, hay que calibrar con signo. Si la geometría tiene signo y la biblioteca no tiene `-`,
`read`, `train` y `teach status` lo avisan.

Cuando el teléfono queda torcido, `rotation_deg` rota cada fotograma en `imaging.load_frame`, el
único punto donde se carga una imagen para analizarla. Se hace en runtime y no en `extract` porque
ffmpeg recorta (`--roi-only`) sobre el fotograma sin rotar, y porque así el ángulo se puede corregir
sin volver a decodificar el video.

## El QC mide sobre la ROI, no sobre el fotograma entero

Que la mitad de la mesa esté en penumbra, o que alguien pase por el fondo, no afecta la lectura.
Lo único que decide si un fotograma sirve es **cómo se ve el número**. Medir sobre el fotograma
completo generaría rechazos por cosas que no importan y, peor, dejaría pasar fotogramas donde el
display está velado pero el resto de la escena se ve bien.

Los umbrales se auto-sugieren de la distribución observada con **mediana ± 6·MAD**, no con media ±
k·σ: los fotogramas malos son justamente los outliers, y con σ ellos mismos inflarían el umbral que
debería rechazarlos. La MAD es insensible a eso.

## Las filas descartadas se omiten, no se interpolan

`absorbance.csv` lleva sólo lecturas reales. Interpolar generaría datos que parecen medidos y no
lo son — en un análisis cinético eso es exactamente el tipo de error que no se detecta después. Un
hueco en la serie es información honesta: dice "acá no se pudo leer", y `qc_report.csv` dice por
qué, fotograma por fotograma. Quien quiera interpolar puede hacerlo en Excel, sabiendo que lo hizo.

El **cuadre de conteos** al final de `report` verifica que
`filas(absorbance.csv) + descartadas(qc_report.csv) = fotogramas extraídos`. Si alguna vez no
cuadra, se perdió un fotograma en silencio y hay un bug.

## La confianza se mide con margen, no sólo con score

Aceptar un dígito por tener NCC alta no alcanza: un `8` degradado puede correlacionar 0.85 con la
plantilla del `8` **y** 0.84 con la del `6`. Por eso se exige además un **margen** contra la mejor
plantilla de una etiqueta *distinta* (`min_margin`). El margen se calcula entre etiquetas, no entre
plantillas, para que tener varias plantillas del `0` no penalice la confianza del `0`.

## Un spike aislado es un dígito mal leído

Después de leer todo, `flag_spikes` marca los puntos que se despegan de **ambos** vecinos por
encima de `max_rate`, **y** cuyos vecinos son coherentes entre sí. La segunda condición es la que
evita descartar una transición real y rápida del experimento: una transición verdadera se sostiene
en el tiempo, un dígito mal leído vuelve solo al valor anterior en la muestra siguiente.

## Las UI: lógica pura y loop delgado

Los loops de OpenCV no se pueden testear sin ventana. Por eso en las dos UI el estado, las acciones,
el layout y la vista previa son funciones puras (`calib_ui`, `teach_session`), y el loop solo lee
eventos y dibuja. Lo que comparten las dos ventanas vive en `ui_common` (antes `teach_ui` importaba
de `calib_ui`). En `teach` hay **un solo reducer** de acciones (`apply_action`), las teclas se
traducen por tabla, y el valor se escribe con el teclado físico: la ventana ya no tiene teclado
numérico de botones.

## El binario de ffmpeg se resuelve en runtime

`resolve_ffmpeg()` prueba el PATH del sistema y cae a `imageio-ffmpeg` (que vive en el venv). Nada
queda cableado: si la instalación de ffmpeg falla o se pospone, el pipeline sigue funcionando sin
tocar una línea de código, sólo más lento y leyendo los metadatos del stderr en vez de con ffprobe.
`extract` informa en su salida qué binario y versión usó, así queda en el log de la corrida.

## La frecuencia de muestreo es un parámetro, y no es gratis elegirla mal

El dígito menos significativo del display se redibuja varias veces por segundo. En el primer video,
a 1 Hz **el 59 % de los fotogramas lo agarraba a mitad del refresco** y quedaba ilegible — y
descartarlos es lo correcto, porque en esos fotogramas el dígito genuinamente no se puede
determinar. A 4 Hz, aunque el porcentaje de fotogramas legibles por separado era parecido (44 %),
**la serie final cubría el 86 % de los 1203 segundos** del video, contra el 41 % que daba 1 Hz. La
densidad de la serie se recupera muestreando más, no aflojando los umbrales.

Y aflojarlos no serviría: midiendo la desviación de cada punto respecto de la mediana de sus
vecinos (± 2 s), las lecturas de confianza 0.60–0.65 se desviaban **lo mismo** (mediana 0.002 Abs,
p95 0.011) que las de confianza > 0.80. El umbral de confianza gobierna cuántos datos hay, no cuán
buenos son — lo cual es la señal de que está bien calibrado.

---

**Siguiente paso:** cómo correr los tests, el flujo de agentes y las convenciones del código, en
[contribuir](../contribuir.md).
