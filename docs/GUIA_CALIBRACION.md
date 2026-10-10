# Guía de calibración por rondas — paso a paso, con fundamentos

Esta guía explica **cómo enseñarle al lector a leer el display de un equipo nuevo** y **cuánto
confiar en lo que lee**, y por qué cada paso se hace como se hace. No hace falta saber ciencia de
datos: cada concepto se explica en lenguaje llano, y al lado se da su nombre técnico por si querés
buscarlo.

Los comandos usan `--run <id>`; reemplazá `<id>` por tu corrida (por ejemplo `img_8102`). Para el
detalle de cada flag está el [README](../README.md#referencia-de-comandos), y para el porqué de las
decisiones de diseño, [ARQUITECTURA.md](ARQUITECTURA.md).

---

## 1. El modelo en una página

El lector **no es una red neuronal ni un OCR**. Es un clasificador de **vecino más cercano**
(_1-NN_, aprendizaje basado en instancias):

1. Recorta la región del número (la ROI) y la parte en **celdas**, una por carácter.
2. Compara cada celda contra todas las **plantillas** de la biblioteca (`calib/templates/`).
3. Se queda con el carácter de la plantilla **más parecida**. "Parecida" se mide con la
   **correlación cruzada normalizada** (NCC, de −1 a 1).

Consecuencias que conviene tener presentes:

* **La biblioteca es el conjunto de entrenamiento.** "Entrenar" es agregar ejemplos; no hay
  nada que ajustar. Por eso la **calidad y la variedad** de los ejemplos importan más que la
  cantidad: un ejemplo borroso o a medio dibujar enseña algo falso.
* **Lo que el modelo no vio, no lo sabe leer.** Si en la biblioteca no hay ningún `7`, ningún
  fotograma con un `7` se va a leer bien.
* **El modelo puede abstenerse.** Una lectura se acepta solo si la mejor plantilla tiene NCC
  suficiente (**confianza**, `templates.min_score`) *y* le saca ventaja a la mejor plantilla de otro
  carácter (**margen**, `templates.min_margin`). Si no, el fotograma se **descarta** y queda un
  hueco en la serie. Un hueco es honesto; un valor inventado, no.

### Glosario

| término de ciencia de datos | en este proyecto |
|---|---|
| _pool_ de datos sin etiquetar | los fotogramas extraídos de los videos (`runs/<id>/frames/`) |
| etiqueta | el valor que escribís para un fotograma (`-0.018`) |
| conjunto de **entrenamiento** | `runs/<id>/truth.csv`; sus glifos forman la biblioteca |
| conjunto de **prueba** (_hold-out_, _test set_) | `runs/<id>/test.csv`; **nunca** entra a la biblioteca |
| entrenar | `Agregar a biblioteca` / `teach --build` |
| inferencia | `read` sobre el resto de los fotogramas |
| validación _leave-one-out_ | `teach --check`: cada muestra se lee sin sus propios glifos |
| **aprendizaje activo** (_active learning_) | `teach --suggest --strategy uncertain/mixed` |
| arranque en frío (_cold start_) | la primera ronda, cuando todavía no hay biblioteca |
| fuga de datos (_data leakage_) | un fotograma de prueba casi idéntico a uno de entrenamiento |
| abstención (_selective classification_) | `descartada` / `low_confidence`: el lector prefiere no responder |
| intervalo de confianza de Wilson | el `[IC95 a%–b%]` que acompaña a cada porcentaje |

---

## 2. El ciclo

```
   videos ──► (0) juntar el pool ─────────────────────────────────────────┐
                 batch --until qc                                          │
                                                                           ▼
   (1) armar la PRUEBA, una vez  ──►  runs/<id>/test.csv     (nunca entrena)
                 teach --suggest N --for test
                                                                           │
        ┌──────────────────────────────────────────────────────────────────┘
        ▼
   (2) ETIQUETAR y agregar ──► biblioteca (calib/templates)  ◄──────────────┐
         teach --suggest N        │                                          │
         teach --build [--keep]   ▼                                          │
                          (3) INFERIR sobre todo el pool                     │
                               read ──► readings.csv (confianza, margen)     │
                                  │                                          │
                                  ▼                                          │
                          (4) EVALUAR en la prueba                           │
                               teach --eval ──► test_report.csv, historial   │
                                  │                                          │
                                  ▼                                          │
                          (5) ¿alcanza? ── no ── nuevas muestras: los más ───┘
                                  │              inciertos + los errores de la prueba
                                  sí
                                  ▼
                          (6) APLICAR al resto:  read + report
```

Un buen ritmo es **rondas cortas**: unas 20-30 muestras, evaluar, mirar qué falló y recién
entonces decidir qué etiquetar. Cada ronda deja una fila en `runs/<id>/out/teach_history.csv`, que
es tu **curva de aprendizaje**.

---

## 3. Paso a paso

### Paso 0 — Juntar el pool

**Qué hago**

```powershell
python -m spectro batch videos/*.MOV --fps 4 --until qc
```

Si la calibración automática no engancha en algún video, el resumen final lo lista con el comando
para calibrarlo a mano (`calibrate --run <id>`); después corré `extract` y `qc` de esa corrida.

**Qué pasa por dentro** — por cada video: `new` → `extract` → `calibrate --auto` → `qc`. Escribe
`runs/<id>/frames/`, `config.json` (ROI, ancla, umbrales) y `out/qc_report.csv`. No lee ningún número:
por eso funciona **antes** de tener biblioteca.

**El fundamento** — Se procesan los videos *antes* de etiquetar nada por dos razones.
Primero, para tener de dónde elegir: las muestras se toman de todo el pool, no del primer tramo.
Segundo, porque el **QC mide la deriva de la cámara** (`dx`, `dy` por fotograma) y cada recorte de
glifo se corrige con ese corrimiento. Si la biblioteca se armara sin esa corrección, sus glifos
saldrían cortados y no coincidirían con lo que después se lee en el resto del video.

**Qué mirar** — En `qc` el porcentaje de fotogramas que pasan debería ser alto (>95 %). Si cae, ver
`qc_report.csv`. Revisá también `out/calibracion.png`: la ROI tiene que abarcar todas las celdas.

**Errores comunes** — `batch` vuelve a sembrar el `config.json` de cada corrida desde `calib/` (hace
`new --force`): si ya calibraste a mano una corrida que todavía no tiene `absorbancia.csv`, `batch` la
pisa. Para esas corridas usá `extract` y `qc` sueltos. Y cambiar la geometría (ROI, celdas, rotación, signo) **después** de haber
etiquetado: las plantillas viejas dejan de coincidir con los recortes nuevos. Si lo hacés, usá
`Reemplazar biblioteca`, no `Agregar`.

---

### Paso 1 — Armar la prueba primero

**Qué hago**

```powershell
python -m spectro teach --run <id> --suggest 20 --for test     # ver la lista
python -m spectro teach --run <id> --queue 20 --for test       # etiquetarlos en la UI
```

En la UI el conjunto activo ya aparece como `Prueba`: escribí el valor de cada fotograma y
`Agregar muestra`. Sin ventana: `teach --run <id> --add-test ARCHIVO=VALOR …`.

**Qué pasa por dentro** — `--for test` fuerza el muestreo **al azar, estratificado por tiempo**
(la corrida se parte en N tramos y se toma un fotograma por tramo; reproducible con `--seed`), y deja
al menos `--gap` segundos (5 por defecto) de distancia a cualquier muestra de entrenamiento. Se guarda
en `runs/<id>/test.csv`.

**El fundamento** — Para saber cuánto sirve el modelo hay que probarlo con datos que **no vio**: es el
conjunto de prueba, o _hold-out_. Tres decisiones lo hacen honesto:

* **Se arma primero y se aparta.** Si lo elegís después de entrenar, es tentador "arreglar" lo que
  falla incorporando esos mismos fotogramas, y la prueba deja de medir nada.
* **Es aleatoria, no por incertidumbre.** Una prueba formada por los casos más difíciles
  subestimaría la exactitud real; una formada por los más fáciles la sobrestimaría. Solo el azar
  representa el uso real.
* **Queda lejos en el tiempo del entrenamiento.** A 4 fotogramas por segundo, dos fotogramas vecinos
  son casi la misma imagen. Si uno está en entrenamiento y el otro en prueba, el modelo "acierta" por
  haber visto casi ese mismo fotograma (_data leakage_).

**Qué mirar** — Unos 20-30 fotogramas, con **valores distintos**. En un experimento donde el valor
se mantiene minutos, 20 fotogramas al azar pueden ser pocos valores distintos; `--eval` te lo avisa.

**Errores comunes** — Etiquetar fotogramas a medio redibujar (el último dígito se actualiza varias
veces por segundo): si no podés decir con certeza qué valor muestra, **saltalo** (`>`). Una verdad de
referencia dudosa convierte aciertos en "errores" y errores en "aciertos".

---

### Paso 2 — Etiquetar y agregar a la biblioteca

**Qué hago**

```powershell
python -m spectro teach --run <id> --suggest 30                 # ronda 0: parejo por la corrida
python -m spectro teach --run <id> --queue 30                   # etiquetar en la UI
python -m spectro teach --run <id> --build                      # primera vez: crea la biblioteca
python -m spectro teach --run <id> --build --keep               # rondas siguientes: suma, sin duplicar
python -m spectro teach --build --all-runs                      # con las muestras de TODOS los videos
python -m spectro teach --build --all-runs --exclude-runs <id>  # ...menos un video reservado como prueba
```

En la UI, `Agregar a biblioteca` equivale a `--build --keep` y `Reemplazar biblioteca` (pide
confirmación) a `--build`. `Gestionar biblioteca` muestra cada plantilla con cuántas celdas gana
bien y mal.

**Varios videos: una biblioteca, muestras de todos.** La biblioteca es **una sola**, compartida por
todos los videos, y `truth.csv` es **uno por video**. `teach --run <id> --build` arma la biblioteca solo
con las muestras de ese video y **reemplaza** lo anterior; si lo corrés video por video, cada uno pisa lo
que aprendió el anterior (en la práctica, un video sin valores negativos borra la plantilla `-`). Hay dos
formas correctas de combinar: `--build` en uno y `--build --keep` en los demás, o directamente
**`--build --all-runs`**, que junta las muestras de entrenamiento de todos los videos de una vez. Se
valida igual (leave-one-out, ahora sobre todas las corridas, con el resultado por video) y no usa ningún
`test.csv`. Para reservar un video como prueba final, `--exclude-runs <id>`. Se entrena con todos porque
más variedad (otra luz, otro enfoque) hace que el lector generalice mejor, y porque se etiquetan pocas
muestras por video; el costo es que **una etiqueta equivocada en cualquier video contamina a todos**, así
que revisá el leave-one-out y `Gestionar biblioteca` antes de procesar.

**Qué pasa por dentro** — Cada valor tipeado se convierte en **una etiqueta por celda**
(`-0.018` → `-`, `0`, `.`, `0`, `1`, `8`); `teach.value_to_cells` rechaza lo que no calce con la
geometría. Con el mismo recorte que usa `read` (incluido el offset del QC) se extrae el glifo de
cada celda y se guarda como plantilla. Al **agregar**, `add_to_library` descarta los glifos casi
idénticos (NCC ≥ 0,95) a uno que ya está de ese carácter, respeta el tope de variantes por carácter
(`--max-per-label`, 6) y no pisa archivos.

**El fundamento** — Es **aprendizaje supervisado**: ejemplos con la respuesta correcta. Escribir el
valor entero etiqueta todas las celdas de una vez, así que no hay que "adivinar qué es cada glifo". La
**primera ronda es uniforme** por el _arranque en frío_: sin biblioteca el lector no sabe nada, así
que su incertidumbre no informa y lo razonable es cubrir la corrida parejo.

Qué hace buena a una muestra: que esté **bien dibujada**, y que aporte **variedad** (distintos
dígitos, y el mismo dígito en distintas condiciones de luz o desenfoque). Diez fotogramas del mismo
valor enseñan menos que diez valores distintos.

**Qué mirar** — La **cobertura** de `0-9 . -` (en la UI, cuadritos de colores; en consola,
`cobertura: 0:34 1:5 …`): verde con 2+ ejemplos, naranja con 1, rojo si falta. Un carácter faltante no
se podrá leer. Y el **leave-one-out** que imprime `--build`: cada muestra se lee con la biblioteca
armada *sin sus propios glifos*. Si la leyó bien, el modelo generaliza; si falló, el informe dice
cuál y por qué (casi siempre "sin ejemplos de X en las demás muestras").

**Errores comunes** — Confundirse de conjunto en la UI (el botón `Conjunto: Entrenam. / Prueba`
decide a cuál va cada muestra). Y agregar sobre una biblioteca hecha con otra geometría: las
plantillas viejas compiten con las nuevas y se pierden lecturas (en `Gestionar biblioteca` aparecen
en rojo, "gana mal").

---

### Paso 3 — Inferir sobre todo el pool

**Qué hago**

```powershell
python -m spectro read --run <id>
```

**Qué pasa por dentro** — Lee cada fotograma que pasó el QC y escribe `out/readings.csv` con, por
fotograma, el valor, la **confianza** (mínimo de la NCC entre celdas), el **margen** (mínimo de la
ventaja sobre otra etiqueta), el texto leído y el estado (`ok`, `low_confidence`, `spike`).

**El fundamento** — Esto es la **inferencia**: aplicar el modelo a datos sin etiquetar. Las lecturas
sirven a la vez como producto y como **señal de incertidumbre**: el modelo duda donde confianza y
margen están cerca de los umbrales. Esa señal es la que usa el muestreo del paso 5.

**Qué mirar** — El porcentaje de lecturas válidas y los descartes por baja confianza. Un descarte
alto no es necesariamente malo: puede ser el último dígito redibujándose (ver el paso 5).

**Errores comunes** — Usar un `readings.csv` **viejo**. Si cambiaste la biblioteca o la config después
de correr `read`, sus confianzas ya no valen; `teach --suggest` lo detecta (compara fechas) y cae a
muestreo al azar con un aviso. Volvé a correr `read`.

---

### Paso 4 — Evaluar en la prueba

**Qué hago**

```powershell
python -m spectro teach --run <id> --eval
python -m spectro teach --eval-all        # todas las corridas que tengan test.csv
```

En la UI: el botón `Evaluar prueba`.

**Qué pasa por dentro** — Lee cada fotograma de `test.csv` con la biblioteca vigente (el mismo
`read_frame` del pipeline) y lo clasifica; escribe `out/test_report.csv` y agrega una fila a
`out/teach_history.csv`.

**El fundamento** — Un solo porcentaje de "exactitud" esconde lo que más importa, así que el
resultado se separa en tres:

| resultado | significa | por qué importa |
|---|---|---|
| **correcta** | el lector aceptó la lectura y coincide con tu valor | lo que querés |
| **errónea aceptada** | el lector aceptó la lectura y **no** coincide | **lo grave**: un dato falso en el CSV |
| **descartada** | el lector se abstuvo | un hueco honesto, no un error |

De ahí salen la **tasa de error entre las aceptadas** (erróneas / aceptadas) y la **cobertura**
(aceptadas / total). El proyecto prefiere subir los descartes antes que las erróneas.

Cada porcentaje lleva un **intervalo de confianza de Wilson al 95 %**. Con 20 muestras, "19/20 = 95 %"
es compatible con una exactitud real entre 76 % y 99 %: el intervalo dice cuánto ancho tiene tu
incertidumbre. Es mejor que el intervalo "normal" porque no se sale de [0, 1] ni con pocas muestras.
Supone muestras independientes; por eso el informe también cuenta los **valores distintos**.

El informe marca el **tipo** de prueba: `misma_corrida` si esa corrida tiene muestras de
entrenamiento propias (mide qué tan bien lee *ese video*; es optimista) u `otro_video` si no las tiene
(_hold-out por video_: mide cómo se comporta con un video nuevo, que es el uso real). Para una cifra
final, reservá un video entero como prueba y no lo uses para entrenar.

**Qué mirar** — (1) Las **erróneas aceptadas**: abrí el fotograma y mirá con tus ojos. Puede ser un
error tuyo al etiquetar, o una confusión real del lector (lo más valioso que podés encontrar).
(2) Las **descartadas**: ¿son fotogramas a medio dibujar? Entonces está bien. (3) Los avisos:
*valores distintos* bajos, *fugas* de entrenamiento, o *caracteres ausentes* de la biblioteca.

**Errores comunes** — Mover al conjunto de prueba una muestra que ya estaba en entrenamiento: sus
glifos **ya están en la biblioteca**, y eso contamina la prueba. La herramienta lo avisa; para una
prueba limpia, `Reemplazar biblioteca` después de moverla.

---

### Paso 5 — Rondas siguientes: dónde etiquetar

**Qué hago**

```powershell
python -m spectro teach --run <id> --suggest 20 --strategy mixed      # mitad inciertas, mitad azar
python -m spectro teach --run <id> --queue 20 --strategy mixed        # etiquetarlas en la UI
python -m spectro teach --run <id> --build --keep
python -m spectro read --run <id>
python -m spectro teach --run <id> --eval
```

**Qué pasa por dentro** — `--suggest` ordena las lecturas por **incertidumbre** `u`, la distancia a la
frontera de aceptación relativa a los umbrales: `u = min((confianza − min_score)/min_score,
(margen − min_margin)/min_margin)`. `u < 0` es una lectura descartada; cerca de 0, al borde.
Un `spike` (salto aislado que pasó el umbral) se trata como el más incierto. Después aplica dos filtros
y reparte con azar (`--strategy mixed`, el valor por defecto).

**El fundamento** — Es **aprendizaje activo** (_active learning_): en vez de etiquetar fotogramas al
azar, se etiqueta donde el modelo más duda, porque ahí una etiqueta nueva aporta más. Funciona con
tres cuidados, cada uno por un riesgo conocido:

* **Persistencia temporal.** Dudar no alcanza: el último dígito parpadea (`ok`/baja confianza
  alternando durante segundos cada vez que el valor cambia) y esos fotogramas no se pueden etiquetar
  con certeza. Un fotograma solo es candidato si **al menos el 80 %** de sus vecinos (±1,5 s) también
  duda. Un glifo que la biblioteca no conoce hace dudar a casi todos los vecinos; el parpadeo, a la
  mitad.
* **Diversidad.** Se exige separación en el tiempo (`--gap`) y no más de 2 fotogramas con el mismo
  texto leído; si no, saldrían 20 fotogramas consecutivos del mismo valor.
* **Mezcla con azar.** Etiquetar solo lo difícil sesga el modelo hacia los casos raros. La mitad
  al azar mantiene el panorama general.

Si el aviso dice *"solo hay 0 fotogramas inciertos y persistentes"*, es una buena noticia: lo que
queda por dudar es el parpadeo, no un carácter desconocido. El muestreo completa con azar.

**La señal más valiosa no sale de la incertidumbre.** Un lector puede equivocarse **con confianza**
(un `6` leído como `5` con 0,84). Esos errores no se ven en `readings.csv`; los encuentra la **prueba**
(`erróneas aceptadas`). Cuando aparezca uno, buscá fotogramas parecidos —misma zona del video, a más de
`--gap` segundos— y etiquetalos **como entrenamiento**; el fotograma original queda en la prueba.

**Cuándo parar** — Mirá `runs/<id>/out/teach_history.csv`: una fila por evaluación. Parás cuando
(a) la curva **se aplana** (dos rondas seguidas sin mejorar), o (b) el error entre aceptadas está
por debajo de lo que tu experimento tolera, con el extremo superior del intervalo a la vista.

**Errores comunes** — Esperar que el aprendizaje activo arregle todo: depende de que el modelo dude
donde se equivoca. Y repetir rondas sin volver a correr `read`: las incertidumbres serían de la
biblioteca anterior.

---

### Paso 6 — Aplicar al resto

**Qué hago**

```powershell
python -m spectro read --run <id>
python -m spectro report --run <id>
# o, para varios videos de punta a punta:
python -m spectro batch videos/*.MOV --fps 4
```

**Qué pasa por dentro** — `read` lee todo el pool con la biblioteca final, `report` escribe
`absorbancia.csv`, el gráfico y el **cuadre de conteos** (válidas + descartadas = extraídas).

**El fundamento** — Con el modelo ya "entrenado" y evaluado, la lectura del resto es **inferencia**
pura. Lo que reportaste en el paso 4 es tu estimación de cuánto confiar en ella: la tasa de error entre
aceptadas y la cobertura de la prueba predicen la de todo el video, **si la prueba es representativa**.

**Qué mirar** — Cobertura, descartes y el rango de la serie. Los saltos aislados los marca el filtro
`spike` de `read` (`read.max_rate`).

**Errores comunes** — Aplicar la biblioteca a un video con otro encuadre sin recalibrar la ROI
(`calibrate --auto`), o con otro zoom: es un video nuevo para el modelo; evaluá con una prueba de
*ese* video.

---

## 4. Ejemplo resuelto: `img_8102`

Todo lo que sigue sale de una corrida real (verificación hecha sobre copias, sin tocar `calib/`). **Los
valores de las muestras los leí yo a ojo de recortes de pantalla** y 19 más los cargó una persona; sirven
de ejemplo del flujo, no de medida de laboratorio.

**Ronda 0.** 14 muestras de entrenamiento, repartidas parejo → biblioteca de 13 plantillas (varios
dígitos con un solo ejemplo). El leave-one-out ya lo dice: `9/14 lecturas exactas`, y los errores
terminan en *"sin ejemplos de '7' en las demás muestras"*. Con esa biblioteca `read` da
`10115/10796 lecturas válidas` (93,7 %).

**Muestreo por incertidumbre.** La primera versión del filtro (50 % de vecinos dudosos) sugirió 6
fotogramas "inciertos"; mirándolos, 5 eran el último dígito a medio redibujar. Midiendo se vio que las
rachas de baja confianza duran **a lo sumo 1 s**, con fotogramas `ok` intercalados. Con el umbral en
80 % (el que usa la herramienta) el aviso es *"solo hay 0 fotogramas inciertos y persistentes"* y la
ronda se completa al azar: en este video no hay un carácter desconocido que cazar.

**La prueba.** `teach --suggest 20 --for test` → 20 fotogramas al azar, de 20 tramos del video
(`t = 103,5 s … 2665,75 s`). Tras etiquetarlos, `teach --eval`:

```
prueba [misma corrida (optimista: mide este video)]: 20 muestras, 17 valores distintos
  correctas 19/20 = 95.0%  [IC95 76.4% a 99.1%]
  erroneas aceptadas 1/20 = 5.0%  [IC95 0.9% a 23.6%]
  descartadas 0/20   cobertura 100.0%
```

La errónea es `t_0001156.500.jpg`: escribiste `-0.016`, el lector aceptó `-0.015` con confianza
0,84. Mirando el recorte binarizado, el último dígito **es** un `6`: es un error real del lector, y de
los que no se detectan por incertidumbre. La NCC del glifo contra la plantilla `6` es 0,755 y contra la
`5`, 0,837: faltaba una variante del `6` con ese aspecto.

**Ronda 1 y curva plana.** Se sumaron 13 muestras más (27 en total) y `--build --keep` agregó **0**
plantillas nuevas; la prueba siguió en 19/20. `teach_history.csv` quedó así:

```
fecha,tipo,plantillas,entrenamiento,prueba,valores_distintos,correctas,erroneas,descartadas,exactitud,error_aceptadas,cobertura
2026-10-08 22:22:31,misma_corrida,13,14,20,17,19,1,0,0.9500,0.0500,1.0000
2026-10-08 22:22:52,misma_corrida,13,27,20,17,19,1,0,0.9500,0.0500,1.0000
```

**Lección sobre el "duplicado".** Que no se agregara nada llevó a revisar el filtro: se usaba un hash
perceptual grueso (8×8) y consideraba "duplicado" un `6` con NCC 0,755 contra la plantilla. Ahora la
deduplicación usa la NCC (≥ 0,95), la misma medida con la que lee el lector. Reconstruida con las 27
muestras, la biblioteca pasa a 36 plantillas y `read` da `10181/10796 válidas` (94,3 %) con confianza
mediana 0,929 (antes 0,892) y sin saltos aislados. La prueba sigue en 19/20 porque en el entrenamiento
no hay ningún `6` con el aspecto del fotograma que falla: la siguiente ronda correcta es **etiquetar
fotogramas parecidos a ese** (misma zona, a más de 5 s) como entrenamiento.

**Lo que este ejemplo no mide.** Es una prueba `misma_corrida`: dice cómo lee *este* video. Para
estimar un video nuevo hace falta etiquetar una prueba en otro video (por ejemplo `IMG_8106`) sin darle
entrenamiento propio, y correr `teach --eval-all`.

---

## 5. Diagnóstico

| síntoma | causa probable | qué hacer |
|---|---|---|
| La biblioteca lee 0 de mis muestras | cambió la geometría (rotación, ROI, celdas) o se promovió una receta distinta | `Reemplazar biblioteca` con las muestras actuales y `calibrate --promote` |
| `--eval`: aceptadas erróneas con un dígito constante (p. ej. `6`→`5`) | falta una variante de ese dígito | etiquetar como **entrenamiento** fotogramas parecidos, separados de la prueba |
| `--eval`: cobertura baja (muchas descartadas) con fotogramas bien dibujados | faltan plantillas, o hay variantes que se estorban entre sí | `Gestionar biblioteca`: borrar las que ganan mal; sumar variedad |
| Un aviso de **fugas** | fotogramas de prueba a < `--gap` s de entrenamiento | mover la muestra o ampliar `--gap`; la exactitud puede estar inflada |
| Aviso de **valores distintos** bajos | la prueba repite pocos valores | tomar más fotogramas, de tramos con otros valores |
| `--suggest` dice *arranque en frío* | casi todo se descarta o no hay `readings.csv` | ronda uniforme; después de agregar a la biblioteca, correr `read` |
| `--suggest` dice *readings.csv anterior a la biblioteca* | se cambió la biblioteca o la config después de `read` | correr `read` de nuevo |
| `--suggest`: "solo hay N fotogramas inciertos y persistentes" | no hay un carácter desconocido; lo que duda es el parpadeo | normal; la ronda se completa al azar |
| `read` se volvió lento | la biblioteca tiene muchas variantes | bajar `--max-per-label`, o borrar las que no aportan en `Gestionar biblioteca` |

---

## 6. Referencia rápida

| archivo | contenido | quién lo escribe |
|---|---|---|
| `runs/<id>/truth.csv` | muestras de **entrenamiento** (`archivo,valor`, valor como texto) | `teach --add`, la UI |
| `runs/<id>/test.csv` | muestras de **prueba**; nunca entran a la biblioteca | `teach --add-test`, la UI |
| `calib/templates/` | la biblioteca de plantillas (compartida entre corridas) | `teach --build`, la UI |
| `runs/<id>/out/readings.csv` | lecturas de todo el pool, con `confianza` y `margen` | `read` |
| `runs/<id>/out/teach_report.csv` | validación leave-one-out de las muestras de entrenamiento | `teach --build/--check` |
| `runs/<id>/out/test_report.csv` | una fila por fotograma de prueba: correcta / errónea / descartada | `teach --eval` |
| `runs/<id>/out/teach_history.csv` | una fila por evaluación: la curva de aprendizaje | `teach --eval` |

| comando | para qué |
|---|---|
| `batch … --until qc` | juntar el pool sin leer |
| `teach --suggest N [--for test] [--strategy …] [--seed S] [--gap G]` | qué fotogramas etiquetar |
| `teach --queue N` | abrir la UI solo con esos fotogramas |
| `teach --add / --add-test ARCHIVO=VALOR …` | cargar muestras sin ventana |
| `teach --build [--keep]` | reemplazar / agregar a la biblioteca, y validar |
| `teach --build --all-runs [--exclude-runs ID …] [--keep]` | lo mismo con las muestras de **todas** las corridas (cada una con su config) |
| `teach --eval` / `--eval-all` | evaluar sobre la prueba |
| `teach --library` / `--delete NOMBRE …` | ver / borrar plantillas |
