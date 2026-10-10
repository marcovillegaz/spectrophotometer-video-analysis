---
name: ds-fundamentals
description: Los fundamentos de ciencia de datos detras de spectro, explicados para gente de laboratorio. Usar al escribir o revisar documentacion que explique por que se entrena con unas muestras y se evalua con otras, que es la prueba (hold-out), la fuga de datos, el leave-one-out, el aprendizaje activo, el arranque en frio, la abstencion del lector o los intervalos de confianza. Incluye un glosario y una entrada por concepto.
---

# Fundamentos de ciencia de datos de spectro

Esta skill es la **base conceptual** de la documentación. El estilo de redacción está en `docs-style`; acá está **qué hay que explicar y cómo se llama cada cosa**.

## Dónde mirar

| archivo | para qué | cuándo leerlo |
|---|---|---|
| [`references/glosario.md`](references/glosario.md) | la tabla *término técnico ↔ cómo aparece en spectro ↔ analogía de laboratorio* | siempre que uses un término técnico: tomá el nombre de ahí, no inventes sinónimos |
| [`references/conceptos.md`](references/conceptos.md) | una entrada por concepto: definición en llano, dónde aparece, ejemplo real, error típico y qué decir | al explicar un concepto por primera vez en un documento |

Leé solo lo que necesitás: el glosario para vocabulario, y la entrada del concepto que vas a explicar.

## Cómo se explica un concepto en este proyecto

1. **Anclalo a algo que la persona ya conoce del laboratorio.** Todo el modelo se parece a una *búsqueda en una biblioteca de espectros de referencia*; la prueba, a una *muestra ciega*; la fuga de datos, a *verificar una calibración con el mismo estándar con el que se calibró*. Esas analogías están en el glosario; usalas si aclaran.
2. **Definición en una frase, sin fórmulas.** La fórmula (por ejemplo la de la incertidumbre) va después y solo si hace falta.
3. **Mostralo en el proyecto:** el archivo (`truth.csv`), el comando, la columna de un CSV, el mensaje de la consola que va a ver.
4. **Dá un ejemplo con números reales y su origen.** Los ejemplos reales de cada concepto están en `conceptos.md` con corrida y fecha. Si usás otro, medilo.
5. **Cerrá con el error típico** y la señal para reconocerlo.

## Límites que hay que decir siempre

- Una exactitud sin intervalo ni tamaño de muestra engaña: con 20 muestras, «19/20» es compatible con una exactitud real entre el 76 % y el 99 %.
- Una prueba de **la misma corrida** mide ese video, no un video nuevo.
- El leave-one-out **no reemplaza** a la prueba: evalúa muestras con las que se entrena (menos una).
- La biblioteca es **compartida**: una etiqueta mala afecta a todos los videos, no solo al que se etiquetó.
- Elegir las muestras por incertidumbre no encuentra los errores **seguros de sí mismos**; esos los encuentra la prueba.

## Qué no hacer

- No uses términos en inglés sin su explicación en español la primera vez.
- No presentes una analogía como si fuera exacta: es una ayuda para entender, no una equivalencia.
- No expliques más de lo que el paso necesita: un fundamento por bloque «El fundamento», con enlace a la guía si hay más.
