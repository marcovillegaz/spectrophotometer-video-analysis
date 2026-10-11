# Primera corrida — de un video al CSV

**Para quién y cuándo leerlo:** cuando ya [instalaste](instalar.md) spectro y querés convertir un
video en `absorbance.csv`; también cuando tenés que volver a calibrar el encuadre de una corrida o
abrir el resultado en Excel.

## Quickstart

Ninguna etapa lleva rutas a mano: **`--run <id>` las deriva todas** desde el layout de
[carpetas](../referencia/carpetas.md). El ejemplo usa el video `videos/IMG_8102.MOV`, cuya corrida
es `img_8102`.

```powershell
# 1. Dar de alta la corrida (crea runs/img_8102/ y hereda la receta de calib/)
python -m spectro new videos/IMG_8102.MOV --fps 4

# 2. Extraer los fotogramas -> runs/img_8102/frames/ + frames_index.csv
python -m spectro extract --run img_8102

# 3. Calibrar el encuadre de ESTA sesión contra la referencia compartida
python -m spectro calibrate --run img_8102 --auto
#    Si el encuadre cambió demasiado, avisa y no inventa nada: calibrá a mano
#    sin --auto (ver calibrate en la referencia de comandos)

# 4. qc -> read -> report sobre los fotogramas ya extraídos
python -m spectro run --run img_8102 --skip-extract
#    -> runs/img_8102/out/absorbance.csv, preview.png, qc_report.csv…
```

Si la corrida ya existe, `new` no la pisa (avisa y sale); `--force` la vuelve a sembrar desde
`calib/`. Todos los flags de cada paso están en la [referencia de comandos](../referencia/comandos.md).

Los pasos 1–4 en uno, para uno o varios videos:

```powershell
python -m spectro batch videos/*.MOV --fps 4
```

**Qué mirar.** `report` cierra con el **cuadre de conteos** (válidas + descartadas = extraídas) y
`[ok]`; si dice `[NO CUADRA]`, se perdió un fotograma y es un bug. `doctor` muestra una línea por
corrida con la salida que tiene:

```
Corridas (runs/): 4
  img_8102               calibrada      10817 fotogramas  absorbancia.csv video=IMG_8102.MOV
  img_8106               calibrada      17944 fotogramas  absorbancia.csv video=IMG_8106.MOV
  img_8110               calibrada       3824 fotogramas  absorbancia.csv video=IMG_8110.MOV
  img_8112               calibrada      10176 fotogramas  absorbancia.csv video=IMG_8112.MOV
```

(`doctor`, 11-oct-2026. Dice `absorbancia.csv` porque esas salidas son anteriores al cambio de
nombre a `absorbance.csv`; ver [archivos de versiones anteriores](../referencia/salidas.md#archivos-de-versiones-anteriores).)

> **Pendiente:** la salida completa del paso 4 sobre `img_8102` (fotogramas que pasan QC, lecturas
> válidas, cobertura) se copia acá **después del entrenamiento final** de la biblioteca. Hoy a la
> biblioteca le falta la plantilla `-` y cualquier cifra de lectura de `img_8102`, que es casi toda
> negativa, no sería representativa.

## La primera vez: sembrar `calib/`

**La primera vez** hay que sembrar `calib/`, porque todavía no hay receta que heredar: calibrá a
mano la primera corrida, etiquetá unos fotogramas, armá la biblioteca y promové el resultado.

```powershell
python -m spectro new videos/mi_primer_video.MOV --fps 4
python -m spectro extract --run <id>
python -m spectro calibrate --run <id>                 # UI: arrastrá el rectángulo (con lupa)
python -m spectro qc --run <id>                        # mide la deriva de cámara
python -m spectro teach samples label <id>             # escribí el valor de ~30 fotogramas
python -m spectro teach train <id>                     # arma calib/templates con esas muestras
python -m spectro calibrate --run <id> --promote       # sube ROI, ancla y fotograma a calib/
python -m spectro run --run <id> --skip-extract
```

Para re-procesar la misma corrida con otro `--fps` alcanza con repetir los pasos 2 y 4: la
calibración y las plantillas se reusan.

Enseñarle al lector a leer bien (etiquetar, entrenar, medir con una prueba y repetir) es un proceso
propio, con sus fundamentos: está en la [guía de calibración](../calibrar/guia.md).

## Cómo re-calibrar una sola corrida

Re-calibrar **no toca las demás corridas**: la ROI vive en `runs/<id>/config.json`.

```powershell
# el camino normal: registrar contra la referencia compartida
python -m spectro calibrate --run <id> --auto

# si --auto no engancha (el encuadre cambió demasiado), a mano
python -m spectro calibrate --run <id>

# y volver a correr de qc en adelante; los fotogramas ya están extraídos
python -m spectro run --run <id> --skip-extract
```

Si sólo cambió la iluminación, alcanza con `qc --run <id>` para que se re-sugieran los umbrales:
la ROI sigue siendo válida.

**Cuando cambia el equipo o el formato del número** hay que rehacer la receta compartida, no una
corrida: calibrá a mano una corrida representativa, rearmá la biblioteca con sus muestras y
promové el resultado. La receta actual de `calib/` viene de `img_8102` (6 celdas: signo + `0.000`).

```powershell
python -m spectro calibrate --run <id>                  # nueva ROI y nuevos slots
python -m spectro qc --run <id>                         # offsets de cámara
python -m spectro teach samples label <id>              # muestras con valores reales
python -m spectro teach train <id>                      # biblioteca nueva (respalda la anterior)
python -m spectro calibrate --run <id> --promote        # sube ROI, ancla y fotograma a calib/
```

**Cuando el montaje nuevo es mejor que el viejo** —mejor foco, mejor encuadre— también conviene
`--promote`: las corridas siguientes van a registrar contra esa referencia, así que cuanto mejor
sea, más veces va a enganchar `--auto`.

## Abrirlo y graficarlo en Excel

1. **Datos → Obtener datos → Desde texto/CSV**, elegir `absorbance.csv`, origen **UTF-8** y
   delimitador **coma**. (Abrirlo con doble clic también funciona, pero si tu Excel usa la coma
   como separador decimal conviene el importador para que no rompa los números.)
2. Seleccionar las columnas `t_exp` y `absorbance` → **Insertar → Gráfico de dispersión con
   líneas suavizadas**.
3. Para filtrar lecturas dudosas: agregar un filtro sobre `confidence` y quedarse con `> 0,8`.

Qué significa cada columna, y cómo alinear `t_exp` con el log del laboratorio, está en
[salidas](../referencia/salidas.md).

---

**Siguiente paso:** enseñarle al lector a leer tu display y medir cuánto confiar en él, en la
[guía de calibración](../calibrar/guia.md).
