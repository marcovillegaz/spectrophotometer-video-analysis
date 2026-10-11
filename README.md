# spectro — absorbancia desde el video del espectrofotómetro

El espectrofotómetro UV/VIS con celda de flujo continuo del laboratorio no tiene software de
adquisición. El experimento se registró **filmando la pantalla del equipo** con un teléfono en
soporte fijo. Este proyecto convierte ese video en una **serie temporal de absorbancia vs
tiempo en CSV**, lista para Excel o para otros scripts.

```
video de la pantalla  ->  extract  ->  qc  ->  read  ->  report  ->  absorbance.csv
                                               ^
                  teach (etiquetar, armar la biblioteca y medirla)
```

| etapa | qué hace |
|---|---|
| `extract` | saca fotogramas del video a una frecuencia fija, con el tiempo en el nombre |
| `qc` | descarta los fotogramas donde el número no se ve bien y mide cuánto se movió la cámara |
| `read` | lee el número de cada fotograma comparándolo con la biblioteca de plantillas |
| `report` | escribe `absorbance.csv`, la curva y el cuadre de conteos |
| `teach` | arma la biblioteca a partir de fotogramas que etiquetás vos, y mide cuánto acierta |

La lectura del número es **comparación contra plantillas** (_template matching_) por carácter:
100 % local, sin API, sin Tesseract y determinista — el mismo fotograma da siempre el mismo
resultado. Cada lectura lleva un puntaje de confianza, y **los fotogramas dudosos se descartan en
vez de inventar un valor**: un hueco en la serie es información honesta; un valor inventado, no.

## Cómo se ve en uso

```powershell
python -m spectro doctor                          # ¿está todo instalado? estado de cada corrida
python -m spectro batch videos/*.MOV --fps 4      # de los videos a un absorbance.csv por corrida
python -m spectro teach status                    # ¿cuánto sabe leer el lector y qué falta?
```

`doctor` y `teach status` solo leen; `batch` crea las corridas en `runs/` y escribe sus salidas.
Antes de procesar videos de verdad, seguí la [instalación](docs/empezar/instalar.md) y la
[primera corrida](docs/empezar/primera-corrida.md).

## Mapa de la documentación

Esta es la lista de todos los documentos del proyecto. Si es la primera vez, leelos en este orden
hasta donde lo necesites; cada uno termina con un enlace al siguiente.

| quiero… | leé esto | para qué sirve |
|---|---|---|
| instalar spectro y comprobar que anda | [empezar/instalar](docs/empezar/instalar.md) | requisitos, instalación y `doctor` |
| convertir mi primer video en un CSV | [empezar/primera-corrida](docs/empezar/primera-corrida.md) | Quickstart, re-calibrar una corrida y abrir el CSV en Excel |
| enseñarle al lector a leer mi display y saber cuánto confiar | [calibrar/guía](docs/calibrar/guia.md) | el ciclo de calibración por rondas, paso a paso y con fundamentos |
| ver ese ciclo sobre un video real | [calibrar/ejemplo-img_8102](docs/calibrar/ejemplo-img_8102.md) | el ejemplo resuelto, con salidas reales |
| resolver un error o un resultado raro | [diagnosticar/problemas](docs/diagnosticar/problemas.md) | síntoma → causa → qué hacer, de todo el pipeline |
| el comando exacto y sus flags | [referencia/comandos](docs/referencia/comandos.md) | todos los subcomandos, incluido `teach` y sus ventanas |
| entender una columna o un estado de un CSV | [referencia/salidas](docs/referencia/salidas.md) | formato de cada archivo de salida |
| saber dónde vive un dato | [referencia/carpetas](docs/referencia/carpetas.md) | qué es compartido y qué es de cada corrida |
| editar un `config.json` | [referencia/config](docs/referencia/config.md) | cada campo, incluido `acceptance` |
| entender cómo está armado el código | [diseño/arquitectura](docs/diseno/arquitectura.md) | pipeline, módulos, contratos y cómo extenderlo |
| saber por qué se decidió algo | [diseño/decisiones](docs/diseno/decisiones.md) | cada decisión, su porqué y el riesgo que cubre |
| cambiar el código o los documentos | [contribuir](docs/contribuir.md) | tests, flujo de agentes, convenciones y trampas del entorno |
| trabajar en el código con Claude Code | [CLAUDE.md](CLAUDE.md) | invariantes, seguridad de datos y agentes |
| saber en qué está el plan de trabajo | [plans/PLAN_CONTINUACION](docs/plans/PLAN_CONTINUACION.md) | el plan vigente; los cerrados están en [`docs/plans/`](docs/plans/) |
| ver cómo estaba el proyecto antes del plan v5 | [historia/AUDITORIA_v5](docs/historia/AUDITORIA_v5.md) | la auditoría de partida (documento histórico) |

Los planes y la historia describen comandos y rutas de su momento: para el uso vigente, valen los
demás documentos.

---

**Siguiente paso:** [instalar spectro](docs/empezar/instalar.md).
