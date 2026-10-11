# Guía de calibración por rondas — paso a paso, con fundamentos

**Para quién y cuándo leerlo:** cuando el lector todavía no lee bien tu display (biblioteca vacía,
un equipo nuevo, un carácter que falta) o cuando necesitás saber cuánto confiar en lo que lee.
Conviene haber hecho antes la [primera corrida](../empezar/primera-corrida.md).

Esta guía explica **cómo enseñarle al lector a leer el display de un equipo nuevo** y **cuánto
confiar en lo que lee**, y por qué cada paso se hace como se hace. No hace falta saber ciencia de
datos: cada concepto se explica en lenguaje llano, y al lado se da su nombre técnico por si querés
buscarlo.

Los comandos de `teach` llevan el id de la corrida como argumento; reemplazá `<id>` por tu corrida
(por ejemplo `img_8102`). Las etapas del pipeline (`qc`, `read`, `report`) lo llevan con `--run`.
La lista completa de comandos y flags está en la
[referencia de `teach`](../referencia/comandos.md#teach--entrenar-y-medir-el-lector), y el porqué de
las decisiones de diseño, en [decisiones](../diseno/decisiones.md). Un recorrido completo sobre
datos reales está en el [ejemplo resuelto](ejemplo-img_8102.md), y la tabla de síntomas, en el
[diagnóstico](../diagnosticar/problemas.md#calibración-del-lector).

---

## 1. El modelo en una página

El lector **no es una red neuronal ni un OCR**. Es un clasificador de **vecino más cercano**
(_1-NN_, aprendizaje basado en instancias), como identificar un compuesto buscando su espectro en
una biblioteca de referencia:

1. Recorta la región del número (la ROI) y la parte en **celdas**, una por carácter.
2. Compara cada celda contra todas las **plantillas** de la biblioteca (`calib/templates/`).
3. Se queda con el carácter de la plantilla **más parecida**. "Parecida" se mide con la
   **correlación cruzada normalizada** (NCC, de −1 a 1).

Consecuencias que conviene tener presentes:

* **La biblioteca es el conjunto de entrenamiento.** "Entrenar" es agregar ejemplos; no hay
  nada que ajustar. Por eso la **calidad y la variedad** de los ejemplos importan más que la
  cantidad: un ejemplo borroso o a medio dibujar enseña algo falso.
* **Lo que el modelo no vio, no lo sabe leer.** Si en la biblioteca no hay ningún `-`, ningún
  valor negativo se va a leer.
* **La biblioteca es una sola para todos los videos.** Una etiqueta equivocada en cualquier video
  contamina la lectura de todos.
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
| entrenar | `teach train` / el botón `Agregar a biblioteca` |
| inferencia | `read` sobre el resto de los fotogramas |
| validación _leave-one-out_ | `teach check` (y lo que imprime `teach train`): cada muestra se lee sin sus propios glifos |
| **aprendizaje activo** (_active learning_) | `teach samples suggest` con `--strategy uncertain` o `mixed` |
| arranque en frío (_cold start_) | la primera ronda, cuando todavía no hay biblioteca |
| fuga de datos (_data leakage_) | un fotograma de prueba casi idéntico a uno de entrenamiento |
| abstención (_selective classification_) | `discarded` / `low_confidence`: el lector prefiere no responder |
| intervalo de confianza de Wilson | el `[IC95 a% a b%]` que acompaña a cada porcentaje |
| _hold-out_ por video | una corrida sin entrenamiento propio (tipo `other_video`) |

---

## 2. El ciclo

```
   videos ──► (0) juntar el pool ─────────────────────────────────────────┐
                 batch --until qc                                          │
                                                                           ▼
   (1) armar la PRUEBA, una vez  ──►  runs/<id>/test.csv     (nunca entrena)
                 teach test suggest <id> / teach test label <id>
                                                                           │
        ┌──────────────────────────────────────────────────────────────────┘
        ▼
   (2) ETIQUETAR y entrenar ──► biblioteca (calib/templates)  ◄─────────────┐
         teach samples label <id>   │                                       │
         teach train                ▼                                       │
                          (3) INFERIR sobre todo el pool                     │
                               read ──► readings.csv (confidence, margin)    │
                                  │                                          │
                                  ▼                                          │
                          (4) EVALUAR en la prueba                           │
                               teach test eval <id> ──► informe, historial   │
                                  │                                          │
                                  ▼                                          │
                          (5) ¿alcanza? ── no ── nuevas muestras: las más ───┘
                                  │              inciertas + los errores de la prueba
                                  sí
                                  ▼
                          (6) APLICAR al resto:  batch (read + report) y veredicto
```

Un buen ritmo es **rondas cortas**: unas 20-30 muestras, evaluar, mirar qué falló y recién
entonces decidir qué etiquetar. Cada evaluación deja una fila en `runs/<id>/out/teach_history.csv`,
que es tu **curva de aprendizaje**. En cualquier momento, `teach status` te dice dónde estás.

---

## 3. Paso a paso

### En cualquier momento — `teach status`

**Qué hago**

```powershell
python -m spectro teach status
```

**Qué pasa por dentro** — Lee la biblioteca (`calib/templates/`), los `truth.csv` y `test.csv` de
cada corrida, sus `qc_report.csv`, `readings.csv`, `read_meta.json` y `teach_history.csv`. No
escribe nada.

**El fundamento** — El ciclo tiene estado repartido en muchos archivos, y el error típico es
comparar cosas de dos momentos distintos: lecturas hechas con una biblioteca y una evaluación hecha
con otra. Para eso existe la **huella** de la biblioteca (_fingerprint_): un código de 12
caracteres que cambia con cualquier cambio de plantillas. `read` la anota al leer y `status` la
compara con la de hoy. Es como anotar en el cuaderno con qué curva de calibración se midió cada
muestra.

**Qué mirar** — Tres cosas. (1) La línea `faltan:`: un carácter que falta no se va a leer nunca.
(2) La columna `salidas` de cada corrida: `stale` quiere decir que sus lecturas son de otra
biblioteca. (3) La lista `siguiente paso:`, que propone el comando que toca. Así se veía el 11 de
octubre de 2026, antes del entrenamiento final:

```
== teach status ==
biblioteca: calib\templates   53 plantillas   huella dc430831a1d7
  0:5  1:5  2:4  3:4  4:4  5:4  6:6  7:4  8:6  9:6  .:5  -:0
  faltan: '-'
  respaldos: 1 (ultimo 20261011_111910)
...
corridas (4):
  corrida                entren. prueba  salidas          ultima evaluacion
  img_8102                    30     20  stale            2026-10-09 18:38:45  exactitud 95.0%
  img_8106                    30     40  stale            -
  img_8110                    26     43  stale            -
  img_8112                     0     20  stale            -
```

**Errores comunes** — Leer la columna `ultima evaluacion` como el estado actual: es la de la última
vez que se evaluó, quizás con otra biblioteca. En el ejemplo, el 95 % de `img_8102` es del 9 de
octubre, con una biblioteca de 43 plantillas que ya no existe.

---

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
`qc_report.csv`, o la tabla de descartes por motivo de `teach status`. Revisá también
`out/calibracion.png`: la ROI tiene que abarcar todas las celdas.

**Errores comunes** — `batch` vuelve a sembrar el `config.json` de cada corrida desde `calib/` (hace
`new --force`): si ya calibraste a mano una corrida que todavía no tiene `absorbance.csv`, `batch` la
pisa. Para esas corridas usá `extract` y `qc` sueltos. Y cambiar la geometría (ROI, celdas, rotación,
signo) **después** de haber etiquetado: las plantillas viejas dejan de coincidir con los recortes
nuevos. Si lo hacés, reemplazá la biblioteca (`teach train` sin `--keep`), no agregues.

---

### Paso 1 — Armar la prueba primero

**Qué hago**

```powershell
python -m spectro teach test suggest <id> 20            # ver la lista
python -m spectro teach test label <id> --queue 20      # etiquetarlos en la ventana
```

En la ventana el conjunto activo ya aparece como `Prueba`: escribí el valor de cada fotograma con el
teclado y `Agregar muestra` (o `Enter`). Sin ventana: `teach test add <id> ARCHIVO=VALOR`.

**Qué pasa por dentro** — `test suggest` muestrea **al azar, estratificado por tiempo** (la corrida se
parte en N tramos y se toma un fotograma por tramo), y deja al menos `--gap` segundos (5 por defecto)
de distancia a cualquier muestra de entrenamiento. Sin `--seed` usa siempre la misma semilla, así que
repetir el comando da la misma lista. Lo que etiquetás se guarda en `runs/<id>/test.csv`.

**El fundamento** — Para saber cuánto sirve el modelo hay que probarlo con datos que **no vio**: es el
conjunto de prueba, o _hold-out_. Es la muestra ciega del laboratorio. Tres decisiones lo hacen
honesto:

* **Se arma primero y se aparta.** Si lo elegís después de entrenar, es tentador "arreglar" lo que
  falla incorporando esos mismos fotogramas, y la prueba deja de medir nada.
* **Es aleatoria, no por incertidumbre.** Una prueba formada por los casos más difíciles
  subestimaría la exactitud real; una formada por los más fáciles la sobrestimaría. Solo el azar
  representa el uso real.
* **Queda lejos en el tiempo del entrenamiento.** A 4 fotogramas por segundo, dos fotogramas vecinos
  son casi la misma imagen. Si uno está en entrenamiento y el otro en prueba, el modelo "acierta" por
  haber visto casi ese mismo fotograma (_data leakage_): es verificar la calibración con el mismo
  estándar con el que se calibró.

**Qué mirar** — Unos 20-30 fotogramas, con **valores distintos**. En un experimento donde el valor
se mantiene minutos, 20 fotogramas al azar pueden ser pocos valores distintos; `teach test list` los
cuenta y `teach test eval` te avisa.

**Errores comunes** — Etiquetar fotogramas a medio redibujar (el último dígito se actualiza varias
veces por segundo): si no podés decir con certeza qué valor muestra, **saltalo** (`>`). Una verdad de
referencia dudosa convierte aciertos en "errores" y errores en "aciertos".

---

### Paso 2 — Etiquetar y entrenar

**Qué hago**

```powershell
python -m spectro teach samples suggest <id> 30                 # qué fotogramas etiquetar
python -m spectro teach samples label <id> --queue 30           # etiquetarlos en la ventana
python -m spectro teach train                                   # biblioteca con las muestras de TODOS los videos
python -m spectro teach train --exclude <id>                    # ...menos un video reservado como prueba
```

En la ventana, `Agregar a biblioteca` suma las muestras de esa corrida sin duplicar (como
`teach train <id> --keep`) y `Reemplazar biblioteca` la reescribe solo con ellas (pide un segundo
clic). `Gestionar biblioteca` muestra cada plantilla con cuántas celdas gana bien y mal. Los
controles de la ventana están en la [referencia](../referencia/comandos.md#la-ventana-de-teach-samples-label-test-label).

**Varios videos: una biblioteca, muestras de todos.** La biblioteca es **una sola**, compartida por
todos los videos, y `truth.csv` es **uno por video**. `teach train` sin argumentos junta las muestras
de entrenamiento de **todas** las corridas y arma la biblioteca de una vez. `teach train <id>` usa solo
las de ese video y **reemplaza** lo anterior: si ese video no tiene valores negativos, la biblioteca
pierde la plantilla `-`. Para sumar un video a la biblioteca vigente, `teach train <id> --keep`. Se
entrena con todos porque más variedad (otra luz, otro enfoque) hace que el lector generalice mejor, y
porque se etiquetan pocas muestras por video; el costo es que **una etiqueta equivocada en cualquier
video contamina a todos**, así que revisá el leave-one-out y `teach lib list --usage` antes de
procesar. Si algo sale mal, `teach train` respaldó la biblioteca anterior: `teach lib restore` la
recupera.

**Qué pasa por dentro** — Cada valor tipeado se convierte en **una etiqueta por celda**
(`-0.018` → `-`, `0`, `.`, `0`, `1`, `8`); `teach.parse_value` rechaza lo que no calce con la
geometría. Con el mismo recorte que usa `read` (incluido el corrimiento del QC) se extrae el glifo de
cada celda. Cada corrida se recorta con **su propia** config. Al **agregar**, `library.add` descarta los
glifos casi idénticos (NCC ≥ 0,95) a uno que ya está de ese carácter, respeta el tope de variantes por
carácter (`--max-per-label`, 3 por defecto) y no pisa archivos. Al **reemplazar**, la biblioteca
anterior se copia antes a `calib/.backups/`.

**El fundamento** — Es **aprendizaje supervisado**: ejemplos con la respuesta correcta, como los
estándares con los que se arma una curva de calibración. Escribir el valor entero etiqueta todas las
celdas de una vez, así que no hay que "adivinar qué es cada glifo". La **primera ronda es uniforme**
por el _arranque en frío_: sin biblioteca el lector no sabe nada, así que su incertidumbre no informa y
lo razonable es cubrir la corrida parejo. `suggest` lo detecta solo (no hay `readings.csv`, o casi
todo se descarta) y lo avisa.

Qué hace buena a una muestra: que esté **bien dibujada**, y que aporte **variedad** (distintos
dígitos, y el mismo dígito en distintas condiciones de luz o desenfoque). Diez fotogramas del mismo
valor enseñan menos que diez valores distintos.

**Qué mirar** — La **cobertura** de `0-9 . -` (en la ventana, cuadritos de colores; en consola,
`cobertura: 0:34 1:5 …`): verde con 2+ ejemplos, naranja con 1, rojo si falta. Un carácter faltante no
se podrá leer. Y el **leave-one-out** que imprime `teach train`: cada muestra se lee con la biblioteca
armada *sin sus propios glifos*, como medir cada estándar con una curva que no lo incluye. Si la leyó
bien, el modelo generaliza; si falló, el informe (`runs/<id>/out/teach_report.csv`) dice cuál y por
qué (casi siempre "sin ejemplos de X en las demás muestras"). Con pocos ejemplos de un carácter esa
muestra se evalúa sin ninguno: es más exigente que la lectura real.

**Errores comunes** — Confundirse de conjunto en la ventana (el botón `Conjunto: Entrenam. / Prueba`
decide a cuál va cada muestra). Correr `teach train <id>` sin `--keep` creyendo que suma. Y agregar
sobre una biblioteca hecha con otra geometría: las plantillas viejas compiten con las nuevas y se
pierden lecturas (en `teach lib list --usage` aparecen como `DANINA`).

---

### Paso 3 — Inferir sobre todo el pool

**Qué hago**

```powershell
python -m spectro read --run <id>
```

**Qué pasa por dentro** — Lee cada fotograma que pasó el QC y escribe `out/readings.csv` con, por
fotograma, el valor, la **confianza** (`confidence`, mínimo de la NCC entre celdas), el **margen**
(`margin`, mínimo de la ventaja sobre otra etiqueta), el texto leído (`chars`) y el estado (`ok`,
`low_confidence`, `spike`, `roi_outside`). Deja también `out/read_meta.json` con la huella de la
biblioteca que usó.

**El fundamento** — Esto es la **inferencia**: aplicar el modelo a datos sin etiquetar, como medir
las muestras desconocidas con la curva. Las lecturas sirven a la vez como producto y como **señal de
incertidumbre**: el modelo duda donde confianza y margen están cerca de los umbrales. Esa señal es la
que usa el muestreo del paso 5.

**Qué mirar** — El porcentaje de lecturas válidas y los descartes por baja confianza. Un descarte
alto no es necesariamente malo: puede ser el último dígito redibujándose (ver el paso 5). Si la
geometría tiene signo y falta la plantilla `-`, `read` lo avisa: todas las lecturas negativas se van a
descartar.

**Errores comunes** — Usar un `readings.csv` **viejo**. Si cambiaste la biblioteca o la config después
de correr `read`, sus confianzas ya no valen; `teach status` lo marca `stale` y `samples suggest` cae a
muestreo al azar con un aviso. Volvé a correr `read`.

---

### Paso 4 — Evaluar en la prueba

**Qué hago**

```powershell
python -m spectro teach test eval <id>
python -m spectro teach test eval          # tabla de todas las corridas que tengan test.csv
```

En la ventana: el botón `Evaluar prueba`.

**Qué pasa por dentro** — Lee cada fotograma de `test.csv` con la biblioteca vigente (el mismo
`read_frame` del pipeline) y lo clasifica; con una corrida, escribe `out/test_report.csv` y agrega una
fila a `out/teach_history.csv` (con la huella de la biblioteca). Sin corrida imprime una tabla y no
escribe nada.

**El fundamento** — Un solo porcentaje de "exactitud" esconde lo que más importa, así que el
resultado se separa en tres:

| resultado | en `test_report.csv` | significa | por qué importa |
|---|---|---|---|
| **correcta** | `correct` | el lector aceptó la lectura y coincide con tu valor | lo que querés |
| **errónea aceptada** | `wrong` | el lector aceptó la lectura y **no** coincide | **lo grave**: un dato falso en el CSV |
| **descartada** | `discarded` | el lector se abstuvo | un hueco honesto, no un error |

De ahí salen la **tasa de error entre las aceptadas** (erróneas / aceptadas) y la **cobertura**
(aceptadas / total). Es la _clasificación selectiva_: como un laboratorio que informa "por debajo del
límite de cuantificación" en vez de un número dudoso. El proyecto prefiere subir los descartes antes
que las erróneas.

Cada porcentaje lleva un **intervalo de confianza de Wilson al 95 %**. Con 20 muestras, "19/20 = 95 %"
es compatible con una exactitud real entre 76 % y 99 %: el intervalo dice cuánto ancho tiene tu
incertidumbre. Es mejor que el intervalo "normal" porque no se sale de [0, 1] ni con pocas muestras.
Supone muestras independientes; por eso el informe también cuenta los **valores distintos**.

El informe marca el **tipo** de prueba: `same_run` (_misma corrida_) si esa corrida tiene muestras de
entrenamiento propias (mide qué tan bien lee *ese video*; es optimista) u `other_video` si no las tiene
(_hold-out por video_: mide cómo se comporta con un video nuevo, que es el uso real). Para una cifra
final, reservá un video entero como prueba y no lo uses para entrenar (`teach train --exclude <id>`).

**Qué mirar** — (1) Las **erróneas aceptadas**: abrí el fotograma y mirá con tus ojos. Puede ser un
error tuyo al etiquetar, o una confusión real del lector (lo más valioso que podés encontrar).
(2) Las **descartadas**: ¿son fotogramas a medio dibujar? Entonces está bien. (3) Los avisos:
*valores distintos* bajos, *fugas* de entrenamiento, o *caracteres ausentes* de la biblioteca.
`teach test history <id>` muestra la curva completa, con el cambio contra la ronda anterior.

**Errores comunes** — Mover al conjunto de prueba una muestra que ya estaba en entrenamiento: sus
glifos **ya están en la biblioteca**, y eso contamina la prueba. La herramienta lo avisa; para una
prueba limpia, reconstruí la biblioteca (`teach train`) después de moverla.

---

### Paso 5 — Rondas siguientes: dónde etiquetar

**Qué hago**

```powershell
python -m spectro teach samples suggest <id> 20 --strategy mixed     # mitad inciertas, mitad azar
python -m spectro teach samples label <id> --queue 20                # etiquetarlas en la ventana
python -m spectro teach train
python -m spectro read --run <id>
python -m spectro teach test eval <id>
```

**Qué pasa por dentro** — `samples suggest` ordena las lecturas de `readings.csv` por
**incertidumbre** `u`, la distancia a la frontera de aceptación relativa a los umbrales:
`u = min((confidence − min_score)/min_score, (margin − min_margin)/min_margin)`. `u < 0` es una
lectura descartada; cerca de 0, al borde. Un `spike` (salto aislado que pasó el umbral) se trata como
el más incierto. Después aplica dos filtros y reparte con azar (`--strategy mixed`, el valor por
defecto).

**El fundamento** — Es **aprendizaje activo** (_active learning_): en vez de etiquetar fotogramas al
azar, se etiqueta donde el modelo más duda, porque ahí una etiqueta nueva aporta más (como repetir las
mediciones donde la incertidumbre es mayor). Funciona con tres cuidados, cada uno por un riesgo
conocido:

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

**Cuándo parar** — Mirá `teach test history <id>`: una fila por evaluación. Parás cuando
(a) la curva **se aplana** (dos rondas seguidas sin mejorar), o (b) el error entre aceptadas está
por debajo de lo que tu experimento tolera, con el extremo superior del intervalo a la vista.

**Errores comunes** — Esperar que el aprendizaje activo arregle todo: depende de que el modelo dude
donde se equivoca. Y repetir rondas sin volver a correr `read`: las incertidumbres serían de la
biblioteca anterior (`teach status` lo marca `stale`).

---

### Paso 6 — Aplicar al resto

**Qué hago**

```powershell
python -m spectro read --run <id>
python -m spectro report --run <id>
# o, para todos los videos de punta a punta, con el reporte del lote:
python -m spectro batch videos/*.MOV --fps 4 --no-skip-existing
```

**Qué pasa por dentro** — `read` lee todo el pool con la biblioteca final; `report` escribe
`absorbance.csv`, el gráfico y el **cuadre de conteos** (válidas + descartadas = extraídas). `batch`
hace eso por cada video y además escribe `runs/batch_report.csv`: una fila por corrida con sus
descartes por motivo, su cobertura y la evaluación de su prueba con la biblioteca vigente.

**El fundamento** — Con el modelo ya "entrenado" y evaluado, la lectura del resto es **inferencia**
pura. Lo que reportaste en el paso 4 es tu estimación de cuánto confiar en ella: la tasa de error entre
aceptadas y la cobertura de la prueba predicen la de todo el video, **si la prueba es representativa**.

**Qué mirar** — Cobertura, descartes y el rango de la serie. Los saltos aislados los marca el filtro
`spike` de `read` (`read.max_rate`). En el reporte del lote, la columna `outputs` tiene que decir
`up_to_date` en todas las corridas.

**Errores comunes** — Aplicar la biblioteca a un video con otro encuadre sin recalibrar la ROI
(`calibrate --auto`), o con otro zoom: es un video nuevo para el modelo; evaluá con una prueba de
*ese* video. Y `batch` sin `--no-skip-existing` después de cambiar la biblioteca: saltea las corridas
que ya tienen salida, que quedan leídas con la biblioteca anterior.

---

### Los pasos sobre datos reales

El [ejemplo resuelto sobre `img_8102`](ejemplo-img_8102.md) recorre los pasos 1, 2, 4 y 5 con las
salidas reales de una corrida (8-oct-2026), incluido un error confiado que solo encontró la prueba.

---

## 4. La ronda final

Es la última vuelta del ciclo, la que deja la biblioteca con la que se procesan todos los videos y
el criterio con el que se acepta cada uno.

**Qué hago**

```powershell
python -m spectro teach status                          # línea de base y avisos
python -m spectro teach lib list --usage                # plantillas que confunden caracteres
python -m spectro teach samples label img_8102          # cubrir lo que falte (p. ej. el signo '-'; también img_8110)
python -m spectro teach test suggest img_8110 20        # ampliar la prueba donde sea chica
python -m spectro teach train --exclude img_8112        # entrenar; img_8112 queda como video nuevo
python -m spectro teach test eval                       # medir todas las corridas
python -m spectro batch videos/*.MOV --fps 4 --no-skip-existing
```

Entre `test eval` y `batch`, fijá los umbrales en la sección `acceptance` de `calib/config.json`
([config](../referencia/config.md#acceptance--criterio-del-lote--solo-en-calib)) con lo que mediste.

**Qué pasa por dentro** — `status` y `lib list --usage` solo leen. `samples label` y `test label`
escriben `truth.csv` y `test.csv`. `train` respalda y reescribe `calib/templates/`. `test eval` sin
corrida mide cada `test.csv` con la biblioteca nueva y no escribe nada. `batch` relee todos los
videos con la biblioteca final, escribe un `absorbance.csv` por corrida y `runs/batch_report.csv`
con el veredicto `accept` / `review` de cada una.

**El fundamento** — Los umbrales se fijan **después** de medir, nunca antes: con 20-40 muestras de
prueba por corrida, una exactitud del 95 % tiene un intervalo de Wilson de entre 15 y 23 puntos de
ancho (de 83,5 % a 98,6 % con 38/40; de 76,4 % a 99,1 % con 19/20), así que conviene ampliar la prueba
antes de decidir. Reservar un video entero sin entrenamiento propio
(`--exclude img_8112`) da la única medida honesta de cómo le va al lector con un video que no vio;
las pruebas `same_run` son optimistas. Por eso `batch` **no tiene umbrales por defecto**: un
veredicto con un criterio inventado daría una confianza que nadie midió.

**Qué mirar** — El punto de partida medido el 11 de octubre de 2026, con la biblioteca de 53
plantillas sin `-` (`teach test eval`):

```
  corrida                fotog. desc.qc roi_outside     ok  baja spike  cobert.     prueba  exact.  error plant.       huella         salidas  veredicto
  img_8102                10817      21           0  10196   600     0    94.3%   20 misma   10.0%   0.0%     53 dc430831a1d7           stale
  img_8106                17944     584           0  15575  1785     0    86.8%   40 misma   12.5%  28.6%     53 dc430831a1d7           stale
  img_8110                 3824      42           0   2265  1517     0    59.2%   43 misma   86.0%   5.1%     53 dc430831a1d7           stale
  img_8112                10176     254           0   6989  2933     0    68.7%    20 otro   80.0%   5.9%     53 dc430831a1d7           stale
```

Se lee así. Las columnas `ok`, `baja` y `cobert.` vienen de `readings.csv`, que es de una biblioteca
anterior (`stale`): no describen a la biblioteca de hoy. `exact.` y `error` sí: se midieron recién.
En `img_8102` la exactitud cae al 10 % (2 de 20) con un error entre aceptadas del 0 %: las 18 que
faltan son **descartadas**, no erróneas, porque casi todos sus valores son negativos y sin plantilla
`-` el lector se abstiene. Es el "descartar antes que adivinar" funcionando, y dice exactamente qué
falta. En `img_8106` el 12,5 % convive con un error del 28,6 % (2 erróneas entre 7 aceptadas): ahí hay
también confusiones seguras de sí mismas que mirar en `test_report.csv`. Ninguna corrida tiene
veredicto porque todavía no hay umbrales. El mismo día, `teach lib list --usage` (sobre 482 celdas
de 86 muestras de 3 corridas) marcaba 5 plantillas `DANINA`; las dos peores eran:

```
      5_2      gana bien    4   gana mal  25  DANINA: gana celdas de otro caracter
      8_2      gana bien    2   gana mal  24  DANINA: gana celdas de otro caracter
```

Una plantilla que gana más celdas mal que bien confunde caracteres. Como `teach train` (sin
`--keep`) reconstruye la biblioteca desde las muestras, borrarla no alcanza si sale de una muestra
mal etiquetada: volvería en el próximo entrenamiento. Mirala en `Gestionar biblioteca` y revisá las
muestras de ese carácter antes de entrenar.

> **Pendiente:** el resultado de esta ronda (exactitud, error entre aceptadas y cobertura por
> corrida, y los umbrales elegidos) se agrega cuando termine el entrenamiento final.

Al terminar, en `batch_report.csv` todas las corridas tienen que decir `up_to_date` en `outputs`.
Las que queden en `review` vuelven al paso 5; el motivo está en la columna `detail`.

**Errores comunes** — Ajustar los umbrales para que todas las corridas den `accept`: el criterio pasa
a describir los datos en vez de juzgarlos. Etiquetar entrenamiento en `img_8112` "para mejorarla":
deja de ser un video nuevo y se pierde la única medida de generalización. Y olvidar
`--no-skip-existing` en `batch`: las corridas con salida quedan leídas con la biblioteca vieja y su
`outputs` dice `stale`.

---

## 5. Cuando algo no sale como se espera

La tabla de síntomas de la calibración (biblioteca que no lee, signo faltante, fugas, avisos de
`suggest`, salidas `stale`…) vive en el
[diagnóstico](../diagnosticar/problemas.md#calibración-del-lector), junto con los problemas del
resto del pipeline.

---

**Siguiente paso:** el ciclo completo sobre un video real, en el
[ejemplo resuelto de `img_8102`](ejemplo-img_8102.md).
