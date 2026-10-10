---
name: docs-style
description: Como se escribe la documentacion de spectro, de forma pedagogica. Usar al redactar o revisar README, guias, arquitectura o planes: audiencia, voz, estructura de cada procedimiento (Que hago / Que pasa por dentro / El fundamento / Que mirar / Errores comunes), reglas para explicar conceptos y no inventar cifras, y donde va cada cosa.
---

# Estilo de la documentación de spectro

## Para quién se escribe

Una persona de laboratorio que **sabe espectrofotometría y absorbancia** y que **no sabe ciencia de datos ni Python**. Tiene que poder:

1. **usar** el software siguiendo los pasos sin entender el código, y
2. **entender por qué** cada paso se hace así, para decidir bien cuando algo sale distinto de lo esperado.

Los fundamentos no son un adorno: sin ellos no sabe cuándo confiar en un número ni cuándo parar de etiquetar.

## Voz

- **Español, con tildes**, voseo (`corré`, `mirá`, `abrí`, `tenés`). Directo y cálido, sin solemnidad ni jerga innecesaria.
- Frases cortas. Un párrafo, una idea. Primero el **para qué**, después el cómo.
- Los nombres técnicos van **entre paréntesis la primera vez**, después de la explicación en llano: «un conjunto aparte con respuestas conocidas que el modelo nunca vio (_hold-out_)».
- Las salidas del programa y el código **no llevan tildes** (es como las imprime el CLI): no las "corrijas" al citarlas.

## Estructura de cada procedimiento

Todo paso de un proceso se escribe con los mismos cinco bloques, en este orden:

| bloque | qué contiene |
|---|---|
| **Qué hago** | el comando exacto (en un bloque de código que se pueda copiar y ejecutar) y, si existe, el botón equivalente de la UI |
| **Qué pasa por dentro** | qué función o etapa corre, qué archivos lee y cuáles escribe (con su ruta) |
| **El fundamento** | el concepto detrás, en lenguaje llano, con su nombre técnico y, si aclara, una analogía de laboratorio |
| **Qué mirar** | cómo leer la salida y **cuándo pasar al paso siguiente** |
| **Errores comunes** | la trampa específica de ese paso, con la señal para reconocerla |

Cerrá los procesos largos con un **ejemplo resuelto** sobre datos reales y una **tabla de diagnóstico** (síntoma → causa probable → qué hacer).

## Cómo explicar un concepto

1. **Una frase de definición**, sin fórmulas. Las fórmulas, solo si la persona va a tener que calcular algo, y después de la idea.
2. **Dónde aparece en el proyecto**: el comando, el archivo, el número que va a ver.
3. **Una analogía de laboratorio solo si aclara** (el conjunto de prueba como muestra ciega; la fuga de datos como recalibrar con el mismo estándar que después medís). Si la analogía no suma, no va.
4. **El error típico** que ese concepto previene.
5. Los conceptos viven en `ds-fundamentals` (`references/conceptos.md` y `glosario.md`): usá sus definiciones y su vocabulario, no inventes sinónimos.

## Reglas de honestidad

- **Nunca inventes una cifra.** Todo número viene de una corrida real y lleva su origen («en `img_8102`, el 8-oct-2026»). Si no podés reproducirlo, lo decís o lo quitás.
- **Decí el límite de cada afirmación.** «19/20 correctas» no es «95 % de exactitud»: es 19 de 20, con un intervalo de 76 % a 99 %. «Mide ese video, no videos nuevos».
- **Distinguí lo que se midió de lo que se supone.** Una recomendación sin medición se presenta como recomendación.
- Un ejemplo de salida es una salida **real** copiada, no una que "se parece".
- Si algo falla o está sin verificar, se escribe. Un documento que oculta límites enseña a confiar de más.

## Dónde va cada cosa

| documento | contiene | no contiene |
|---|---|---|
| `README.md` | uso y **referencia**: instalación, carpetas, comandos y flags, formatos de salida | el porqué extenso de las decisiones |
| `docs/GUIA_CALIBRACION.md` | el **proceso** de calibración paso a paso, con fundamentos, ejemplo resuelto y diagnóstico | la lista completa de flags |
| `docs/ARQUITECTURA.md` | **decisiones de diseño**: qué se decidió, por qué y qué riesgo cubre; tabla de módulos | pasos de uso |
| `docs/CONFIG.md` | cada campo de `config.json` | procesos |
| `CLAUDE.md` | memoria para quien trabaja en el código (agentes, convenciones, seguridad) | explicaciones para usuarios |
| `PLAN*.md` | planes de trabajo; son historia | documentación vigente |

**No dupliques:** una explicación vive en un solo documento y los demás la **enlazan** (`[guía](docs/GUIA_CALIBRACION.md)`). Un resumen de dos líneas con enlace sí; copiar la sección, no.

## Formato

- Tablas para **comparar**; listas para **enumerar**; prosa para **razonar**.
- Encabezados que el lector pueda ubicar al leer el índice; los enlaces internos llevan ancla (`#referencia-de-comandos`).
- Comandos en bloques ` ```powershell `, con comentarios `#` al costado cuando ayuden. Cada comando tiene que ser ejecutable tal cual; si es una plantilla, que se note (`<id>`, `…`).
- Diagramas ASCII para flujos cortos (se ven en la terminal y en GitHub).
- Los números de tests, plantillas, etc., salen de ejecutar el comando, no de la memoria.

## Antes de entregar (lista de control)

- [ ] Cada procedimiento tiene los cinco bloques.
- [ ] Cada concepto nuevo está definido, con su nombre técnico y su error típico.
- [ ] Ninguna cifra sin origen; ningún límite omitido.
- [ ] Nada duplicado: lo repetido es un enlace.
- [ ] `docs-sync`: `check_docs.py` da 0 y los flags coinciden con `--help`.
- [ ] Voseo, tildes en el texto, sin tildes en el código citado.
