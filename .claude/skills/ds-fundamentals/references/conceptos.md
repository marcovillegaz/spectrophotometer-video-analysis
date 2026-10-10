# Conceptos de ciencia de datos de spectro

Una entrada por concepto, con la misma forma: **en una frase**, **dónde aparece**, **ejemplo real** (con corrida y fecha: no inventes otros), **error típico** y **qué decir y qué límite aclarar**. El vocabulario está en [`glosario.md`](glosario.md).

Índice: 1 · el lector (1-NN y NCC) · 2 · entrenamiento y prueba · 3 · leave-one-out · 4 · sobreajuste · 5 · fuga de datos · 6 · ruido de etiquetas · 7 · sesgo de muestreo · 8 · aprendizaje activo · 9 · arranque en frío · 10 · abstención y clasificación selectiva · 11 · umbrales · 12 · intervalo de Wilson y tamaño efectivo · 13 · hold-out por video · 14 · registro de imagen.

---

## 1. El lector: vecino más cercano y correlación (NCC)

- **En una frase:** para cada celda del número, el lector la compara con todas las plantillas de la biblioteca y se queda con el carácter de la más parecida; «parecida» se mide con la correlación cruzada normalizada (NCC), de −1 a 1.
- **Dónde aparece:** `read.read_frame` y `read.match_slot`; `imaging.ncc`; las plantillas en `calib/templates/`. La lectura se acepta solo si el mejor puntaje llega a `min_score` **y** le saca `min_margin` de ventaja a la mejor plantilla **de otro carácter**.
- **Ejemplo real:** en un fotograma de `img_8102` (8-oct-2026) el último dígito era un `6`, y el lector lo leyó como `5` con confianza 0,84: su NCC contra la plantilla `6` era 0,755 y contra la `5`, 0,837. Faltaba una variante del `6` con ese aspecto.
- **Error típico:** creer que «más plantillas = mejor». Las variantes de un carácter ayudan; pero una plantilla de un carácter que se parece demasiado a otra de **otro** carácter hace caer el margen y el lector rechaza (ver 6).
- **Qué decir:** el modelo no «entiende» números: compara imágenes. Por eso aprende de ejemplos y por eso solo lee bien lo que se parece a algo que vio. Analogía: buscar un espectro en una biblioteca de referencia.

## 2. Entrenamiento y prueba (hold-out)

- **En una frase:** las muestras de **entrenamiento** construyen la biblioteca; las de **prueba** se apartan y sirven solo para medir qué tan bien lee con datos que nunca vio.
- **Dónde aparece:** `runs/<id>/truth.csv` (entrenamiento) y `runs/<id>/test.csv` (prueba); la prueba **nunca** entra a la biblioteca. La evaluación está en `evaluation.evaluate_test`.
- **Ejemplo real:** en `img_8102` (8-oct-2026) se separaron 20 fotogramas al azar, uno por tramo del video, antes de entrenar: 19 correctas, 1 errónea aceptada, 0 descartadas.
- **Error típico:** armar la prueba **después** de entrenar y «arreglar» lo que falla incorporando esos mismos fotogramas: deja de medir. O elegirla por incertidumbre: tendría solo casos difíciles y subestimaría el desempeño real.
- **Qué decir:** la prueba se elige **al azar y estratificada por tiempo**, se arma primero y se aparta. Analogía: la muestra ciega.

## 3. Validación leave-one-out

- **En una frase:** cada muestra de entrenamiento se lee con la biblioteca armada **sin los glifos que salieron de ella misma**, para ver si el modelo habría acertado con una muestra nueva.
- **Dónde aparece:** `teach.validate`; el informe `out/teach_report.csv`; el comando de validación (`check`).
- **Ejemplo real:** el 10-oct-2026, tras limpiar muestras mal etiquetadas, el leave-one-out global de las corridas `img_8102`, `img_8106` e `img_8110` pasó de 63/90 a 83/86. Los desacuerdos con estado `ok` fueron, casi siempre, **errores de tipeo**.
- **Error típico:** tomarlo por la medida de confianza final. Evalúa muestras con las que se entrena (menos una) y de **un solo video** a la vez; no reemplaza a la prueba. Con un carácter de un solo ejemplo (un `7` solo) esa muestra se evalúa sin ningún `7`: es más exigente que la lectura real.
- **Qué decir:** sirve sobre todo para **detectar etiquetas equivocadas**: si un valor escrito no coincide con lo leído y el lector estaba seguro, mirá el fotograma. Analogía: validación cruzada.

## 4. Sobreajuste

- **En una frase:** una biblioteca armada con unas muestras lee **perfecto esas mismas muestras** (porque contiene sus glifos) pero no dice nada sobre las demás.
- **Dónde aparece:** la línea «biblioteca vigente: 14/14 lecturas exactas» que imprime el comando de entrenamiento, junto a un leave-one-out mucho más bajo.
- **Ejemplo real:** en una ronda 0 de `img_8102` (8-oct-2026), con 14 muestras, la biblioteca vigente leía 14/14 y el leave-one-out, 9/14.
- **Error típico:** quedarse con el «14/14». Es el número más optimista de todos.
- **Qué decir:** el número que importa es el de la **prueba** (o, para un video nuevo, el de un video reservado). Analogía: una curva con tantos parámetros que pasa por todos los puntos de calibración y no predice.

## 5. Fuga de datos (data leakage)

- **En una frase:** si un fotograma de prueba es casi idéntico a uno de entrenamiento, el modelo acierta por haber visto casi ese mismo fotograma, y la prueba pierde sentido.
- **Dónde aparece:** `sampling.leakage`; el aviso de `--eval`; la distancia mínima `--gap` (5 s). A 4 fotogramas por segundo, dos vecinos distan 0,25 s y son casi la misma imagen. Mover una muestra de entrenamiento a prueba avisa que **ya aportó glifos** a la biblioteca.
- **Ejemplo real:** el 10-oct-2026, la prueba de `img_8110` tenía 8 fotogramas a menos de 5 s de uno de entrenamiento y 23 pares a menos de 1 s entre sí; la de `img_8106`, 20 pares.
- **Error típico:** tomar fotogramas consecutivos para la prueba (parecen muchos y son pocos) o pegados al entrenamiento.
- **Qué decir:** la exactitud puede estar inflada; el informe lo avisa. Analogía: verificar una calibración con el mismo estándar con el que se calibró.

## 6. Ruido de etiquetas

- **En una frase:** una etiqueta equivocada enseña algo falso, y como la biblioteca es **compartida**, contamina la lectura de todos los videos.
- **Dónde aparece:** `runs/<id>/truth.csv`; la biblioteca `calib/templates/`; `teach.library_usage` (plantillas que «ganan mal»).
- **Ejemplo real:** en `img_8110` (10-oct-2026) tres muestras se escribieron `0.xxx` cuando el display decía `1.xxx`; así nació `0_3.png`, un **`1` etiquetado como `0`** (NCC 0,968 contra las plantillas `1`). Todo fotograma con un `1` quedó rechazado por margen: aceptados 59,2 % → 88,1 % al quitar las cinco plantillas dañinas (medido sobre 1 de cada 3 fotogramas). En `img_8102` aparecieron también `-0.001` por `-0.011` y `-0.006` por `-0.016`.
- **Error típico:** confiar en lo que se tipeó. Hay que **mirar el recorte** antes de dar una muestra por buena, y no etiquetar fotogramas con el último dígito a medio dibujar.
- **Qué decir:** una etiqueta mala cuesta mucho más que la falta de una muestra. Analogía: un estándar mal rotulado que arruina toda la curva.

## 7. Sesgo de muestreo

- **En una frase:** si las muestras no representan el uso real (solo lo difícil, o solo el principio del video), el modelo aprende un panorama torcido.
- **Dónde aparece:** `sampling.suggest` con sus estrategias `uniform`, `random`, `uncertain` y `mixed` (por defecto, mitad y mitad).
- **Ejemplo real:** la prueba usa azar **estratificado por tiempo** (un fotograma por tramo del video) para no concentrarse en una zona.
- **Error típico:** etiquetar solo los fotogramas dudosos: el modelo mejora en lo raro y se desentiende de lo común.
- **Qué decir:** mezclar elegidas por incertidumbre con elegidas al azar.

## 8. Aprendizaje activo

- **En una frase:** en vez de etiquetar fotogramas al azar, se etiqueta donde el lector más duda, porque ahí una etiqueta nueva aporta más.
- **Dónde aparece:** `sampling.suggest_uncertain`. La incertidumbre `u = min((confianza − min_score)/min_score, (margen − min_margin)/min_margin)`: negativa si la lectura se descartó, cerca de 0 si está al borde de aceptarse. Un `spike` (salto aislado que pasó el umbral) cuenta como el más incierto.
- **Ejemplo real:** en `img_8102` (8-oct-2026) las rachas de baja confianza duraban **a lo sumo 1 s**, con fotogramas `ok` intercalados: el último dígito parpadea cada vez que cambia el valor. Con un umbral de persistencia del 50 %, 5 de 6 sugerencias eran ese parpadeo; con el 80 % (el vigente) no quedó ninguna, y la ronda se completó al azar.
- **Dos salvaguardas:** *persistencia* (un fotograma es candidato si ≥ 80 % de sus vecinos de ±1,5 s también duda: un glifo desconocido dura segundos, el parpadeo no) y *diversidad* (separación en el tiempo y no repetir el mismo texto leído).
- **Error típico:** esperar que encuentre todo. No encuentra los errores **seguros de sí mismos** (un `6` leído como `5` con 0,84): esos los encuentra la prueba.
- **Qué decir:** «no hay fotogramas inciertos persistentes» es una buena noticia, no un fallo.

## 9. Arranque en frío

- **En una frase:** sin biblioteca no hay lecturas útiles, así que la incertidumbre no informa y la primera ronda se reparte parejo por el video.
- **Dónde aparece:** `sampling.is_cold_start` (menos del 10 % de lecturas `ok`) y la estrategia `uniform`; si `readings.csv` es anterior a la biblioteca o a la config, se avisa y se usa azar.
- **Error típico:** correr el muestreo por incertidumbre con una biblioteca vacía o con lecturas viejas: da incertidumbres falsas (pasó al cambiar la geometría).

## 10. Abstención y clasificación selectiva

- **En una frase:** el lector prefiere **no responder** a equivocarse: una lectura dudosa se descarta y deja un hueco; por eso se mide el **error entre las aceptadas** y la **cobertura**, no una sola exactitud.
- **Dónde aparece:** `evaluation.evaluate_test` separa cada fotograma de prueba en *correcta*, *errónea aceptada* (lo grave: un dato falso en el CSV) o *descartada*.
- **Ejemplo real:** en `img_8110` (10-oct-2026), con la biblioteca dañada: 27 correctas, 2 erróneas aceptadas y 15 descartadas de 44; sin las plantillas dañinas: 37, 2 y 5.
- **Error típico:** leer «84 % de exactitud» como «16 % de datos falsos»: puede ser que gran parte sean huecos. Lo grave son las aceptadas erróneas.
- **Qué decir:** un hueco es información honesta; un valor inventado, no. Analogía: informar «bajo el límite de cuantificación» en vez de un número.

## 11. Umbrales: el compromiso precisión–cobertura

- **En una frase:** endurecer los umbrales (`min_score`, `min_margin`) baja los errores y sube los huecos; aflojarlos hace lo contrario.
- **Dónde aparece:** `templates.min_score` (0,60) y `templates.min_margin` (0,05) en `config.json`.
- **Ejemplo real:** no hay una regla general y hay que medir. En una corrida anterior, subir `min_score` solo cambió **cuántos** datos quedaban, no **qué tan buenos** eran; en `img_8110` (10-oct-2026) las dos erróneas aceptadas tenían confianza menor a 0,65, pero con solo dos casos no alcanza para concluir.
- **Error típico:** subir `min_score` esperando que «mejore la calidad»: muchas veces solo aumenta los huecos sin bajar los errores, porque una lectura de confianza 0,62 puede ser tan correcta como una de 0,90.
- **Qué decir:** cambiar un umbral se decide con la prueba (error entre aceptadas y cobertura), no a ojo.

## 12. Intervalo de Wilson y tamaño efectivo de muestra

- **En una frase:** un porcentaje con pocas muestras es incierto: el intervalo de Wilson da el rango plausible de la tasa real, y el tamaño efectivo cuenta cuántas muestras son realmente independientes.
- **Dónde aparece:** `evaluation.wilson` y el `[IC95 a%–b%]` de cada porcentaje; la línea de *valores distintos*.
- **Ejemplo real:** 19 correctas de 20 es 95 %, pero con un intervalo del 76,4 % al 99,1 % (`img_8102`, 8-oct-2026). Y la prueba de `img_8106` tenía 40 fotogramas con solo 14 valores distintos y 20 pares casi idénticos: valía bastante menos de 40.
- **Error típico:** citar el porcentaje sin el intervalo ni el tamaño. El intervalo supone muestras independientes; si no lo son, es optimista.
- **Qué decir:** siempre «k de n» junto al porcentaje.

## 13. Hold-out por video

- **En una frase:** la prueba más honesta no es de la misma corrida, sino de un **video que no se usó para entrenar**: mide cómo se comporta con un video nuevo, que es el uso real.
- **Dónde aparece:** el informe marca el tipo, `misma_corrida` (la corrida tiene entrenamiento propio: mide ese video) u `otro_video`; las corridas se pueden excluir del entrenamiento para reservarlas como prueba.
- **Ejemplo real:** el 10-oct-2026, entrenando con tres videos y sin muestras de `img_8112`, la prueba de ese video dio 17 correctas de 20 (85 %, intervalo de 64 % a 95 %).
- **Error típico:** presentar la exactitud de la misma corrida como si valiera para videos nuevos.
- **Qué decir:** son dos preguntas distintas: «¿lee bien este video?» y «¿leerá bien el próximo?». Analogía: validar el método con otro lote u otro equipo.

## 14. Registro de imagen (deriva de cámara)

- **En una frase:** el teléfono se mueve unos píxeles durante la grabación; `qc` mide cuánto (`dx`, `dy`) por fotograma y todo recorte de celda se corrige con ese corrimiento.
- **Dónde aparece:** `qc` (columnas `dx`, `dy` de `qc_report.csv`) y `crop_for_reading`. Debe usarlo igual quien arma la biblioteca y quien lee.
- **Ejemplo real:** `img_8110` derivó entre −2 y 9 px en x; `img_8102` entre −21 y 5 px. Sin compensar, el muestreo clásico de glifos produjo 56 «glifos únicos» cuando el display solo tiene 12 caracteres.
- **Error típico:** armar la biblioteca sin el corrimiento: sus glifos salen cortados y no coinciden con los que se leen.
- **Qué decir:** el `qc` va **antes** de etiquetar. Analogía: la deriva de la línea base durante una corrida.
