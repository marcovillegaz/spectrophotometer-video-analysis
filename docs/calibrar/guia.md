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
| conjunto de **entrenamiento** | `runs/<id>/teach/truth.csv`; sus glifos forman la biblioteca |
| conjunto de **prueba** (_hold-out_, _test set_) | `runs/<id>/test/test.csv`; **nunca** entra a la biblioteca |
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
   (1) armar la PRUEBA, una vez  ──►  runs/<id>/test/test.csv (nunca entrena)
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
entonces decidir qué etiquetar. Cada evaluación deja una fila en `runs/<id>/test/teach_history.csv`,
que es tu **curva de aprendizaje**. En cualquier momento, `teach status` te dice dónde estás, y
`summary` te da el panorama de todas las corridas juntas
([paso 4](#todas-las-corridas-a-la-vez--summary)).

### Las tres piezas y qué toca cada comando

El diagrama de arriba es el ciclo en el tiempo. Este es el mismo ciclo visto por **archivos**: hay
tres piezas, y cada comando de `teach` lee unas y escribe otras. Si te perdés entre
`samples label`, `train`, `check`, `test label` y `test eval`, ubicalos acá.

```
  teach samples label <id>                               teach test label <id>
             │ escribe                                              │ escribe
             ▼                                                      ▼
  ┌─────────────────────┐                                ┌─────────────────────┐
  │ ENTRENAMIENTO       │                                │ PRUEBA              │
  │ runs/<id>/teach/    │                                │ runs/<id>/test/     │
  │   truth.csv         │                                │   test.csv          │
  │ uno por video       │                                │ uno por video       │
  └─────────────────────┘                                └─────────────────────┘
       │           │                                                │
       │ lee       │ lee                                            │ lee
       ▼           ▼                                                │
  teach check    teach train ────── reescribe ─────┐                │
  leave-one-out  (antes respalda                   ▼                │
  no toca la     la anterior;          ┌─────────────────────┐      │
  biblioteca     es el único           │ BIBLIOTECA          │      │
                 que la escribe)       │ calib/templates/    │      │
                                       │ una para todos      │      │
                                       └─────────────────────┘      │
                                                   │ lee            │
                                                   ▼                │
                                         teach test eval <id> ◄─────┘
                                         (mide; no cambia la biblioteca
                                          ni las muestras)

  El ciclo:  samples label ──► train ──► test eval ──► ¿dónde falla? ──┐
                   ▲                                                   │
                   └──── más entrenamiento de eso, nunca la prueba ────┘
```

Ninguna flecha va de la PRUEBA a `teach train`: esa es la regla de oro.

| comando | lee | escribe | ¿cambia la biblioteca? |
|---|---|---|---|
| `teach samples label <id>` | los fotogramas de la corrida | `runs/<id>/teach/truth.csv` (y `teach/rejected.csv` si descartás un fotograma) | no (salvo los botones de biblioteca de la ventana, que hacen lo mismo que `teach train`) |
| `teach train` | los `truth.csv` de todas las corridas, menos las de `--exclude` | `calib/templates/` (antes copia la anterior a `calib/.backups/`) y `teach/teach_report.csv` de cada corrida | **sí: es el único comando que la escribe** |
| `teach check` | lo mismo que `train`, y la biblioteca vigente para comparar | solo `teach/teach_report.csv` de cada corrida | no |
| `teach test label <id>` | los fotogramas de la corrida | `runs/<id>/test/test.csv` | no |
| `teach test eval <id>` | `test.csv` y la biblioteca vigente | `test/test_report.csv` y una fila de `test/teach_history.csv` (sin `<id>`, solo imprime la tabla) | no |
| `summary` | todo lo anterior, de todas las corridas | solo `runs/summary.csv`, `runs/summary_chars.csv` y `runs/summary.html` | no |

**El fundamento** — Dos reglas sostienen todo lo demás.

* **La prueba nunca se usa para entrenar.** Si un fotograma de `test.csv` aportara glifos a la
  biblioteca, la prueba lo "acertaría" por haberlo visto (fuga de datos, _data leakage_): es verificar
  la calibración con el mismo estándar con el que calibraste. Lo que falla en la prueba se corrige
  etiquetando **otros** fotogramas parecidos como entrenamiento; el fotograma de prueba se queda donde
  está ([paso 5](#paso-5--rondas-siguientes-dónde-etiquetar)).
* **`check` no reemplaza a `test eval`.** El leave-one-out de `check` lee cada muestra de
  entrenamiento sin sus propios glifos, pero con los de las demás muestras de ese mismo video: sirve
  para cazar etiquetas mal tipeadas y es optimista frente a un video nuevo (con un carácter de un solo
  ejemplo es al revés, más exigente). La cifra que vale es la de la prueba
  ([paso 4](#paso-4--evaluar-en-la-prueba)).

La prueba de un video que también entrena (tipo `same_run`, "misma" en la tabla) mide *ese* video.
Para saber cómo le va al lector con un video que no vio, reservá un video entero: no le etiquetes
entrenamiento y dejalo fuera de la biblioteca con `teach train --exclude <id>`. Su prueba sale como
`other_video` ("otro"), el _hold-out_ por video, que es la cifra honesta.

**Ejemplo: tres videos entrenan, uno queda de prueba.** Es el plan de la
[ronda final](#4-la-ronda-final): `img_8102`, `img_8106` e `img_8110` entrenan (incluidos tramos con
valores negativos, para que la biblioteca tenga plantillas `-`) e `img_8112` queda reservado como
video nuevo.

```powershell
python -m spectro teach samples label img_8102 --queue 20     # entrenamiento, con valores negativos
python -m spectro teach samples label img_8106 --queue 20
python -m spectro teach samples label img_8110 --queue 20
python -m spectro teach test suggest img_8112 20              # img_8112: solo prueba
python -m spectro teach test label img_8112 --queue 20
python -m spectro teach check --exclude img_8112              # leave-one-out, sin escribir la biblioteca
python -m spectro teach train --exclude img_8112              # reescribe calib/templates/
python -m spectro teach test eval img_8112                    # tiene que decir "otro video"
```

**Qué mirar** — Antes de entrenar, `teach samples list` tiene que mostrar **0** muestras de
entrenamiento en el video reservado, y en la columna `caracteres sin cubrir` el `-` tiene que estar
cubierto en al menos uno de los videos que entrenan (mejor en varios). Así se veía el 11 de octubre de 2026: `img_8110` todavía no tenía
ningún `-`, e `img_8112` ya tenía 26 muestras de entrenamiento, así que todavía no servía como video
nuevo.

```
== muestras de entrenamiento por corrida ==
  corrida                muestras  valores  caracteres sin cubrir
  img_8102                     29       20  ninguno
  img_8106                     25       11  '1' '9'
  img_8110                     28       26  '-'
  img_8112                     26       21  ninguno
```

Después de `test eval img_8112`, el informe tiene que decir `otro video (hold-out por video)`. Si
dice `misma corrida`, ese video tiene entrenamiento propio.

**Errores comunes** — (1) Pasar a entrenamiento un fotograma de prueba que falló "para que aprenda":
la prueba deja de medir. (2) Creer que `--exclude` alcanza: deja ese video fuera de la biblioteca,
pero si su `truth.csv` tiene muestras, el informe lo sigue marcando `misma corrida`, porque mira si
la corrida tiene entrenamiento propio. Para un _hold-out_ por video limpio, el video reservado no
lleva muestras de entrenamiento. (3) Tomar el resultado de `teach check` como la exactitud del lector.

---

## 3. Paso a paso

### En cualquier momento — `teach status`

**Qué hago**

```powershell
python -m spectro teach status
```

**Qué pasa por dentro** — Lee la biblioteca (`calib/templates/`) y, de cada corrida, sus
`teach/truth.csv`, `teach/rejected.csv`, `test/test.csv` y `test/teach_history.csv`, y sus
`out/qc_report.csv`, `out/readings.csv` y `out/read_meta.json`. No escribe nada (salvo, una sola
vez, mudar al layout nuevo los archivos de una corrida vieja; ver
[carpetas](../referencia/carpetas.md#corridas-con-el-layout-anterior)).

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
repetir el comando da la misma lista. Lo que etiquetás se guarda en `runs/<id>/test/test.csv`.

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
bien, el modelo generaliza; si falló, el informe (`runs/<id>/teach/teach_report.csv`) dice cuál y por
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
`read_frame` del pipeline) y lo clasifica; con una corrida, escribe `test/test_report.csv` y agrega una
fila a `test/teach_history.csv` (con la huella de la biblioteca). Sin corrida imprime una tabla y no
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

#### Todas las corridas a la vez — `summary`

`teach test eval <id>` mide una corrida. Cuando tenés varias, la pregunta pasa a ser otra: ¿cuánto
acierta el lector **en total**, en qué caracteres se equivoca, cuánta serie se pierde y si está
mejorando? `summary` lo contesta en un solo reporte.

**Qué hago**

```powershell
python -m spectro summary                      # todas las corridas; veredicto con los umbrales de calib/config.json
python -m spectro summary --min-accuracy 0.95  # un flag le gana a ese umbral, solo en esta ejecución
```

Los flags están en la [referencia](../referencia/comandos.md#summary--cuánto-acierta-el-lector-en-todas-las-corridas).
Los umbrales del veredicto se fijan en la sección `acceptance` de `calib/config.json`
([config](../referencia/config.md#acceptance--criterio-del-lote--solo-en-calib)).

**Qué pasa por dentro** — Por cada corrida, evalúa su `test/test.csv` con la biblioteca vigente
(el mismo evaluador que `teach test eval`), lee `out/readings.csv` y `test/teach_history.csv`, y
hace un leave-one-out conjunto con las muestras de entrenamiento de todas, **sin escribir la
biblioteca**. No toca `calib/`, `teach/`, `test/` ni `out/`: lo único que escribe es
`runs/summary.csv`, `runs/summary_chars.csv` y `runs/summary.html` (sus columnas, en
[salidas](../referencia/salidas.md#runssummarycsv-runssummary_charscsv-y-runssummaryhtml--la-efectividad-de-todas-las-corridas)).

**El fundamento** — Dos ideas para leer la sección 1, la de la exactitud.

* **Cómo leer el intervalo.** Cada exactitud va con su intervalo de Wilson al 95 %
  (`[IC95 a% a b%]`): el rango de exactitudes reales compatibles con lo que mediste. Leelo así: el
  **extremo inferior** es lo que podés defender; el ancho, cuánto te falta medir. Con 19 correctas
  de 20 (`img_8102`, 8-oct-2026) la exactitud es 95 %, pero el intervalo va del 76,4 % al 99,1 %: no
  podés prometer más que "por encima de tres de cada cuatro". Dos cifras cuyos intervalos se
  superponen **no se distinguen**: el 10-oct-2026 la prueba de `img_8112` como video nuevo dio 17 de
  20 (85 %, intervalo de 64 % a 95 %); el 11-oct, ya con entrenamiento propio y con otra prueba de 16
  fotogramas, dio 14 de 16 (87,5 %), que cae dentro de ese intervalo. Con estos tamaños no se puede
  decir que una sea mejor que la otra. Juntar las pruebas de todas las corridas suma muestras y
  achica el intervalo, pero el intervalo supone fotogramas **independientes**: dos fotogramas vecinos
  del mismo valor cuentan como dos y valen casi como uno, así que con muchos repetidos el intervalo
  real es más ancho que el impreso (por eso el informe cuenta los *valores distintos*).
* **Por qué `same_run` es optimista.** En una prueba `same_run`, la biblioteca ya tiene glifos de
  *ese mismo video*: la misma luz, el mismo enfoque, el mismo encuadre, el mismo día. Aunque cada
  fotograma de prueba esté a más de `--gap` segundos del entrenamiento, se parece a algo que el
  lector ya vio. Es validar un método con el mismo lote de reactivo con el que lo calibraste: mide
  bien *ese* lote, no el próximo. Un video sin entrenamiento propio (`other_video`) trae otra luz y
  otro montaje, que es lo que va a pasar con el próximo experimento. Por eso la fila `TOTAL` usa la
  prueba `other_video` si alguna corrida la tiene, y solo si no hay ninguna cae a `same_run`.

**Qué mirar** — Las cinco secciones, en orden.

1. **Exactitud en la prueba.** Si aparecen las dos, `other_video` y `same_run`, la que responde
   "¿leerá bien el próximo video?" es `other_video`. Mirá `k/n` y el extremo inferior del intervalo,
   no solo el porcentaje.
2. **Errores por carácter.** Un carácter con muchas celdas y errores concentrados (`'6'->'5'`) es
   dónde etiquetar en la próxima ronda ([paso 5](#paso-5--rondas-siguientes-dónde-etiquetar)). El
   aviso `ninguna prueba incluye ...` dice qué caracteres nunca se midieron: su exactitud es
   desconocida, no buena.
3. **Cobertura de la serie.** La cobertura dice cuánto se leyó; los **huecos** dicen dónde se
   perdió. Un hueco es una pausa de más de `--hole` segundos (10 por defecto) entre lecturas
   válidas: por "descartar antes que adivinar", ahí no hay datos. Un hueco de 15 s en una meseta
   larga importa poco; en una transición rápida, puede perder justo lo que querías medir.
4. **Tendencia.** Si la exactitud de `teach_history.csv` sube de una evaluación a otra, las rondas
   rinden; si se aplanó, es momento de parar ([cuándo parar](#paso-5--rondas-siguientes-dónde-etiquetar)).
   `con otra biblioteca (reevalua)` quiere decir que la última evaluación es de una biblioteca que
   ya no existe: corré `teach test eval <id>` antes de comparar.
5. **Veredicto.** Sin umbrales queda vacío a propósito: el criterio lo fijás vos, después de medir
   ([ronda final](#4-la-ronda-final)). La línea `(la fila TOTAL mide la prueba ...)` dice qué tipo
   de prueba resume el total.

Al final, los avisos dicen qué corridas no tienen prueba o no se leyeron, con el comando que falta.

**Ejemplo real.** Salida de `python -m spectro summary` el 13-oct-2026, con la biblioteca de 34
plantillas (huella `a45faaf4e322`) y los umbrales de `calib/config.json` de ese día
(`acceptance`: `min_accuracy` 0.90, `max_error` 0.02, `min_coverage` 0.80). Copiada sin cambios:

```text
== summary (biblioteca: 34 plantillas, huella a45faaf4e322) ==

-- 1. Exactitud en la prueba --
prueba same_run (todas las corridas) [misma corrida (optimista: mide este video)]: 49 muestras, 26 valores distintos
  correctas 46/49 = 93.9%  [IC95 83.5% a 97.9%]
  erroneas aceptadas 1/47 = 2.1%  [IC95 0.4% a 11.1%]
  descartadas 2/49   cobertura 95.9%
  para medir videos nuevos, reserva un video sin entrenamiento propio como prueba

-- 2. Errores por caracter --
  car.  prueba  err.   loo  err.  confusiones
  -          2     1    47     0  '-'->' ' x1
  .         49     0   108     0
  0        122     0   229     0
  1          9     0    31     0
  2         12     0    37     0
  3          7     0    28     0
  4         18     0    14     0
  5          8     0    28     1  '5'->'6' x1
  6          7     1    26     1  '6'->'5' x2
  7          5     0    13     0
  8          4     0    14     1  '8'->'9' x1
  9          4     0    12     0

-- 3. Cobertura de la serie --
  corrida                fotog. desc.qc roi_outside     ok  baja spike  cobert.     prueba  exact.  error plant.       huella         salidas  veredicto
  img_8102                 5408       5           0   5092   311     0    94.2%          -       -      -     34 a45faaf4e322      up_to_date  review (sin prueba que lo verifique)
  img_8106                 8972     262           0   7998   712     0    89.1%          -       -      -     34 a45faaf4e322      up_to_date  review (sin prueba que lo verifique)
  img_8110                 1912      15           0   1661   236     0    86.9%          -       -      -     34 a45faaf4e322      up_to_date  review (sin prueba que lo verifique)
  img_8112                 5088     222           0   4164   702     0    81.8%   49 misma   93.9%   2.1%     34 a45faaf4e322      up_to_date  review (error 2.1% > 2.0%)
  TOTAL                   21380     504           0  18915  1961     0    88.5%   49 misma   93.9%   2.1%     34 a45faaf4e322      up_to_date  review (error 2.1% > 2.0%)
  huecos (> 10 s entre lecturas validas):
    img_8102               mas largo      2.5 s   huecos 0
    img_8106               mas largo     12.5 s   huecos 2
    img_8110               mas largo      5.0 s   huecos 0
    img_8112               mas largo     14.5 s   huecos 4
    TOTAL                  mas largo     14.5 s   huecos 6
  leave-one-out (entrenamiento):
    img_8102               29/29 = 100.0%
    img_8106               23/25 = 92.0%
    img_8110               27/28 = 96.4%
    img_8112               26/26 = 100.0%
    TOTAL                  105/108 = 97.2%

-- 4. Tendencia --
  img_8102               sin historial de evaluaciones
  img_8106               sin historial de evaluaciones
  img_8110               sin historial de evaluaciones
  img_8112               5 evaluaciones   primera 87.5%  ultima 87.5%  cambio +0.0 pts   con otra biblioteca (reevalua)   salidas up_to_date

-- 5. Veredicto --
  img_8102               review (sin prueba que lo verifique)
  img_8106               review (sin prueba que lo verifique)
  img_8110               review (sin prueba que lo verifique)
  img_8112               review (error 2.1% > 2.0%)
  TOTAL                  review (error 2.1% > 2.0%)
  (la fila TOTAL mide la prueba same_run)
  aviso: img_8102: sin prueba. Arma una con: python -m spectro teach test suggest img_8102 20
  aviso: img_8106: sin prueba. Arma una con: python -m spectro teach test suggest img_8106 20
  aviso: img_8110: sin prueba. Arma una con: python -m spectro teach test suggest img_8110 20

  escrito: runs\summary.csv, runs\summary_chars.csv, runs\summary.html
```

Cómo leerla:

* **La única prueba es `same_run`, y solo de `img_8112`.** Las 49 muestras salen de ese video, que
  también tiene entrenamiento propio: el 93,9 % mide `img_8112`, no un video nuevo, y es optimista.
* **El `review` de `img_8112` (y del `TOTAL`) viene de un solo error.** La exactitud (93,9 %) pasa el
  0,90 y la cobertura (81,8 %) pasa el 0,80, pero hubo 1 lectura errónea entre 47 aceptadas: 2,1 %,
  apenas por encima del 2 %. Su intervalo va del 0,4 % al 11,1 %: 47 lecturas no alcanzan ni para
  decir que el error supera el 2 % ni para certificar que está por debajo. Para respaldar un 2 % hace
  falta mucha más prueba: por la *regla del tres*, con cero errores en *n* lecturas el error real
  puede llegar a ~3/*n*, así que se necesitan unas **150 aceptadas sin ningún error**.
* **Las otras tres corridas dan `review` por no tener prueba**, no por leer mal: su cobertura
  (94,2 %, 89,1 % y 86,9 %) pasa el umbral, pero nada verifica su exactitud. Los avisos del final
  dicen cómo armarla.

**Errores comunes** — (1) Citar la exactitud de `TOTAL` como la de un video nuevo cuando la línea
final dice `mide la prueba same_run`: ninguna corrida es un _hold-out_ por video, y la cifra es
optimista. (2) Leer la cobertura y los huecos con salidas `stale`: salen de `readings.csv`, que es
de la biblioteca con la que se leyó; la exactitud de la prueba, en cambio, se mide con la de hoy.
Si la columna `salidas` no dice `up_to_date`, corré `read` y `report` antes de mirar la cobertura.
(3) Tomar el leave-one-out de la sección 3 como la exactitud del lector: mide las muestras de
entrenamiento, no la prueba.

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
python -m spectro summary                               # el panorama final: prueba, caracteres, huecos
```

Entre `test eval` y `batch`, fijá los umbrales en la sección `acceptance` de `calib/config.json`
([config](../referencia/config.md#acceptance--criterio-del-lote--solo-en-calib)) con lo que mediste.

**Qué pasa por dentro** — `status` y `lib list --usage` solo leen. `samples label` y `test label`
escriben `truth.csv` y `test.csv`. `train` respalda y reescribe `calib/templates/`. `test eval` sin
corrida mide cada `test.csv` con la biblioteca nueva y no escribe nada. `batch` relee todos los
videos con la biblioteca final, escribe un `absorbance.csv` por corrida y `runs/batch_report.csv`
con el veredicto `accept` / `review` de cada una. `summary` no cambia ningún dato: junta todo en
`runs/summary.*` ([cómo leerlo](#todas-las-corridas-a-la-vez--summary)).

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
