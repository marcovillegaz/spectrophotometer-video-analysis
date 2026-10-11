# Ejemplo resuelto: `img_8102`

**Para quién y cuándo leerlo:** después de leer la [guía de calibración](guia.md), para ver el ciclo
completo sobre un video real: qué dijo cada comando, qué se interpretó y qué decisión se tomó. Cada
párrafo nombra el paso de la guía al que corresponde.

Todo lo que sigue sale de una corrida real, del 8 de octubre de 2026 (verificación hecha sobre
copias, sin tocar `calib/`). **Los valores de las muestras los leyó a ojo una persona de recortes de
pantalla** y sirven de ejemplo del flujo, no de medida de laboratorio. Se hizo con la versión
anterior de `teach` (un comando con flags de modo); acá cada paso está escrito con el comando actual
que hace lo mismo, y las salidas son las de ese momento.

## Ronda 0

([Paso 2 — Etiquetar y entrenar](guia.md#paso-2--etiquetar-y-entrenar).) 14 muestras de
entrenamiento, repartidas parejo → biblioteca de 13 plantillas (varios dígitos con un solo
ejemplo). El leave-one-out ya lo dice: `9/14 lecturas exactas`, y los errores terminan en *"sin
ejemplos de '7' en las demás muestras"*. Con esa biblioteca `read` da `10115/10796 lecturas
válidas` (93,7 %).

## Muestreo por incertidumbre

([Paso 5 — Rondas siguientes](guia.md#paso-5--rondas-siguientes-dónde-etiquetar).) La primera
versión del filtro (50 % de vecinos dudosos) sugirió 6 fotogramas "inciertos"; mirándolos, 5 eran
el último dígito a medio redibujar. Midiendo se vio que las rachas de baja confianza duran **a lo
sumo 1 s**, con fotogramas `ok` intercalados. Con el umbral en 80 % (el que usa la herramienta) el
aviso es *"solo hay 0 fotogramas inciertos y persistentes"* y la ronda se completa al azar: en este
video no hay un carácter desconocido que cazar.

## La prueba

([Paso 1 — Armar la prueba](guia.md#paso-1--armar-la-prueba-primero) y
[Paso 4 — Evaluar](guia.md#paso-4--evaluar-en-la-prueba).) `teach test suggest img_8102 20` → 20
fotogramas al azar, de 20 tramos del video (`t = 103,5 s … 2665,75 s`). Tras etiquetarlos,
`teach test eval img_8102`:

```
prueba [misma corrida (optimista: mide este video)]: 20 muestras, 17 valores distintos
  correctas 19/20 = 95.0%  [IC95 76.4% a 99.1%]
  erroneas aceptadas 1/20 = 5.0%  [IC95 0.9% a 23.6%]
  descartadas 0/20   cobertura 100.0%
```

La errónea es `t_0001156.500.jpg`: se escribió `-0.016`, el lector aceptó `-0.015` con confianza
0,84. Mirando el recorte binarizado, el último dígito **es** un `6`: es un error real del lector, y de
los que no se detectan por incertidumbre. La NCC del glifo contra la plantilla `6` es 0,755 y contra la
`5`, 0,837: faltaba una variante del `6` con ese aspecto.

## Ronda 1 y curva plana

Se sumaron 13 muestras más (27 en total) y el entrenamiento con `--keep` agregó **0** plantillas
nuevas; la prueba siguió en 19/20. `teach_history.csv` quedó así (todavía con el encabezado en
español de esa versión, que se sigue leyendo; ver
[archivos de versiones anteriores](../referencia/salidas.md#archivos-de-versiones-anteriores)):

```
fecha,tipo,plantillas,entrenamiento,prueba,valores_distintos,correctas,erroneas,descartadas,exactitud,error_aceptadas,cobertura
2026-10-08 22:22:31,misma_corrida,13,14,20,17,19,1,0,0.9500,0.0500,1.0000
2026-10-08 22:22:52,misma_corrida,13,27,20,17,19,1,0,0.9500,0.0500,1.0000
```

## Lección sobre el "duplicado"

Que no se agregara nada llevó a revisar el filtro: se usaba un hash perceptual grueso (8×8) y
consideraba "duplicado" un `6` con NCC 0,755 contra la plantilla. Ahora la deduplicación usa la NCC
(≥ 0,95), la misma medida con la que lee el lector (la decisión, en
[decisiones](../diseno/decisiones.md#agregar-a-la-biblioteca-deduplica-y-la-biblioteca-se-puede-auditar)).
Reconstruida con las 27 muestras, la biblioteca pasa a 36 plantillas y `read` da
`10181/10796 válidas` (94,3 %) con confianza mediana 0,929 (antes 0,892) y sin saltos aislados. La
prueba sigue en 19/20 porque en el entrenamiento no hay ningún `6` con el aspecto del fotograma que
falla: la siguiente ronda correcta es **etiquetar fotogramas parecidos a ese** (misma zona, a más de
5 s) como entrenamiento.

## Lo que este ejemplo no mide

Es una prueba `same_run`: dice cómo lee *este* video. Para estimar un video nuevo hace falta una
prueba en otro video sin entrenamiento propio (hoy `img_8112` cumple ese papel) y correr
`teach test eval`. Eso es lo que hace la [ronda final](guia.md#4-la-ronda-final).

---

**Siguiente paso:** qué hacer cuando un síntoma no se parece a este ejemplo, en el
[diagnóstico](../diagnosticar/problemas.md). Para volver al proceso, la [guía](guia.md).
