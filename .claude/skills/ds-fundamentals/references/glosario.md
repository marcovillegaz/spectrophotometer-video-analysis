# Glosario: ciencia de datos ↔ spectro ↔ laboratorio

Usá el **término de la primera columna** (en español, con el nombre en inglés entre paréntesis la primera vez). Las analogías de la tercera columna son ayudas para entender, no equivalencias exactas.

| término técnico | en spectro | analogía de laboratorio |
|---|---|---|
| **Clasificador de vecino más cercano** (1-NN) | el lector: compara cada celda del número con todas las plantillas y elige el carácter de la más parecida | identificar un compuesto buscando su espectro en una biblioteca de referencia |
| **Correlación cruzada normalizada** (NCC) | el *puntaje* de parecido entre una celda y una plantilla, de −1 a 1 (1 = idénticas) | el coeficiente de correlación entre dos espectros |
| **Biblioteca / plantilla** | `calib/templates/`: una imagen por glifo etiquetado, compartida por todos los videos | la biblioteca de espectros de referencia |
| **Etiqueta** (*label*) | el valor que escribís para un fotograma (`-0.018`) | el valor certificado de un estándar |
| **Conjunto de entrenamiento** | `runs/<id>/truth.csv`: las muestras con las que se arma la biblioteca | los estándares con los que se construye la curva de calibración |
| **Conjunto de prueba** (*test set*, *hold-out*) | `runs/<id>/test.csv`: muestras con valor conocido que **nunca** entran a la biblioteca | una muestra ciega o un estándar de verificación independiente |
| **Entrenar** | construir o ampliar la biblioteca a partir de las muestras | armar la curva de calibración |
| **Inferencia** | `read`: leer el resto de los fotogramas con la biblioteca ya armada | medir las muestras desconocidas con la curva |
| **Validación leave-one-out** (*leave-one-out*) | cada muestra se lee con la biblioteca armada **sin sus propios glifos** | validación cruzada: medir cada estándar con una curva que no lo incluye |
| **Sobreajuste** (*overfitting*) | la biblioteca lee perfecto las muestras con las que se armó y peor las demás | ajustar la curva con tantos parámetros que pasa por todos los puntos pero no predice |
| **Fuga de datos** (*data leakage*) | un fotograma de prueba casi idéntico a uno de entrenamiento (vecinos a 0,25 s) | verificar la calibración con el mismo estándar con el que se calibró |
| **Ruido de etiquetas** (*label noise*) | un valor mal tipeado en `truth.csv` | un estándar mal rotulado o mal preparado |
| **Sesgo de muestreo** | etiquetar solo lo difícil, o solo el primer tramo del video | medir solo las muestras convenientes |
| **Aprendizaje activo** (*active learning*) | `suggest`: proponer los fotogramas donde el lector duda más | repetir las mediciones donde la incertidumbre es mayor |
| **Arranque en frío** (*cold start*) | la primera ronda, sin biblioteca: no hay lecturas que informen | la primera calibración, sin curva previa |
| **Abstención** (*abstention*) | descartar una lectura dudosa (`low_confidence`) y dejar un hueco | informar «por debajo del límite de cuantificación» en vez de inventar un número |
| **Clasificación selectiva** (*selective classification*) | medir el **error entre las aceptadas** y la **cobertura** (aceptadas / total) | la tasa de resultados erróneos entre los que se reportan, y qué fracción se reporta |
| **Confianza y margen** | `min_score` (puntaje mínimo) y `min_margin` (ventaja mínima sobre la mejor plantilla de otro carácter) | el criterio de aceptación de una coincidencia espectral: calidad del hit y diferencia con el segundo candidato |
| **Compromiso precisión–cobertura** | subir los umbrales baja los errores y sube los huecos | endurecer un criterio de aceptación: menos falsos positivos, más muestras sin resultado |
| **Intervalo de Wilson** | el `[IC95 a%–b%]` que acompaña cada porcentaje | el rango plausible de un % de recuperación medido con pocas réplicas |
| **Tamaño efectivo de muestra** | los *valores distintos* de la prueba | réplicas técnicas frente a muestras independientes |
| **Hold-out por video** | una corrida sin entrenamiento propio (tipo `other_video`) | validar el método con otro lote, otro equipo u otro día |
| **Generalización** | cuánto sirve la biblioteca para un video que no vio | que el método funcione fuera del lote de desarrollo |
| **Registro de imagen / deriva de cámara** | `qc` mide `dx`, `dy` por fotograma y `read` recorta con ese corrimiento | la deriva de la línea base o del instrumento durante la corrida |
