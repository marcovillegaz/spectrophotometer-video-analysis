---
name: testing-patterns
description: Como se testea el proyecto spectro (pytest). Usar al escribir, ampliar o depurar tests del pipeline, del CLI o de las UI; al agregar tests para una funcion nueva; o al comprobar que un test realmente puede fallar (mutacion). Cubre las fixtures sinteticas, el proyecto de juguete en tmp_path para el CLI, las UI sin ventana y como reportar un bug al developer.
---

# Patrones de testing de spectro

Se corre con `.venv/Scripts/python -m pytest -q` (la suite tarda segundos). Las reglas generales de `tests/` están en `.claude/rules/tests.md`; esta skill es el **cómo**.

## Reglas de trabajo del agente `test`

- Escribís solo en `tests/**`. **Nunca editás `src/`**: si un test revela un bug, lo reportás (ver el final) y seguís.
- Partí siempre de la suite en verde: corré la suite antes de escribir y anotá el recuento. Terminá con la suite entera en verde, o con los fallos explicados.
- Un test nuevo tiene que **poder fallar**: hacé la mutación (abajo) antes de darlo por bueno.

## Datos sintéticos (`tests/conftest.py`)

| pieza | para qué |
|---|---|
| `render_display("-0.245", brightness, blur, angle)` | un fotograma de mentira con celdas monoespaciadas, igual que el display real |
| `make_config(sign=False)` | `Config` con la ROI exacta del display sintético; `sign=True` agrega la celda del signo (6 celdas) |
| `cfg`, `cfg_sign` | esas configs como fixtures |
| `library`, `library_sign` | bibliotecas de plantillas armadas desde el display sintético (`library_sign` incluye `-`) |

Reutilizalas antes de crear otras. Si hace falta un helper compartido, va a `conftest.py`; si es de un solo archivo, queda en ese archivo.

**Ojo con la ROI:** las bibliotecas sintéticas se arman con la ROI **exacta**; si un test usa `refine=True` o una ROI dibujada a mano, los slots no caen igual y la lectura falla por razones que no son el invariante que querés probar.

## Probar el CLI con un proyecto de juguete

1. En `tmp_path` armá `runs/<id>/frames/…` (con `cv2.imwrite` de `render_display`), `runs/<id>/config.json` (`make_config(...).save(...)`) y, si hace falta, `truth.csv` (`teach.save_truth`) y un `qc_report.csv`.
2. Llamá `main([...])` con las **globales antes del subcomando**: `["--runs-dir", str(tmp/"runs"), "--calib-dir", str(tmp/"calib"), "teach", ...]`.
3. Comprobá el código de salida, la salida con `capsys.readouterr().out` y los mensajes de error en `.err`; después, los archivos que quedaron (o que **no** quedaron) en disco.
4. Los videos repiten nombres de fotograma (`t_0000000.000.jpg`): armá dos corridas con **los mismos nombres** para cazar colisiones.

## UI sin ventana

- **Estado y acciones:** funciones puras (`apply_action`, `apply_key`): estado + acción → estado nuevo. Probá cada acción, los límites y las confirmaciones de dos pasos.
- **Layout:** el centro de cada botón devuelve su acción (`hit_test`), nada se sale del panel y no hay solapamientos.
- **Render:** un *smoke test* que dibuja varios estados (con y sin datos, con y sin ROI) y comprueba solo la forma del resultado.
- Nunca abras `cv2.imshow` ni `waitKey` en un test.

## Mutación: probar que el test puede fallar

Para cada invariante nuevo:
1. Copiá el archivo a probar a una carpeta temporal (`$TEMP`).
2. Rompé el invariante en `src/` **de forma temporal** (por ejemplo, validar por nombre de fotograma en vez de por identificador `corrida/archivo`).
3. Corré el test: tiene que ponerse rojo.
4. **Restaurá** el archivo desde la copia y confirmá que vuelve a verde.

Como no podés editar `src/`, la mutación se hace con `monkeypatch` sobre la función o el atributo, o pidiéndosela al developer. Dejá escrito en el test (docstring) **qué rompería** el invariante.

Para "X nunca llega a Y" usá un espía:

```python
vistos = []
original = modulo.funcion
monkeypatch.setattr(modulo, "funcion", lambda datos, *a, **k: (vistos.extend(datos), original(datos, *a, **k))[1])
```

y comprobá que lo que no debía pasar no está en `vistos`.

## Determinismo

- Semillas fijas (`random.Random(0)`, `np.random.default_rng(0)`); nada que dependa del reloj ni del orden de `glob`.
- Los JPEG pierden información: comparar con tolerancia o escribir PNG.
- Un test = una conducta, con nombre en español que la describa. Cubrí también los errores: mensaje claro, código 1, nada a medias.

## Qué cubrir en una función nueva

Camino feliz · cada rama de error con su mensaje · datos vacíos / un solo elemento · compatibilidad con archivos viejos (campos ausentes) · idempotencia si repetirlo no debería cambiar nada · que lo prohibido siga prohibido (la prueba no entra a la biblioteca, no se pisan archivos).

## Reportar un bug al developer

Entregá: (1) el comportamiento esperado y el obtenido, (2) un **caso mínimo** que lo reproduce (el test que falla, aislado, o 5–10 líneas), (3) la ruta y la función donde creés que está, (4) si hay riesgo para los datos. No lo arregles.
