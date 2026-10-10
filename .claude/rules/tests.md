---
paths:
  - "tests/**/*.py"
---

# Convenciones de tests (`tests/`)

- Se corre con `.venv/Scripts/python -m pytest -q`. La suite entera tiene que tardar segundos: **sin videos reales, sin red, sin leer `runs/` ni `calib/` reales**.
- **Datos sintéticos.** `conftest.py` ofrece `render_display(texto, angle=…)` (un display de mentira dibujado con OpenCV), `make_config(sign=…)` y las fixtures `cfg`, `cfg_sign`, `library`, `library_sign`. Reutilizalas antes de crear otras.
- Todo lo que escribe va a `tmp_path`. Para probar el CLI se arma un proyecto de juguete (`runs/<id>/…`, `calib/`) en `tmp_path` y se llama `main([...])` con `--runs-dir` y `--calib-dir`; se comprueba el código de salida y, con `capsys`, la salida y `err`.
- **Lo determinista:** semillas fijas, nada que dependa del reloj o del orden del sistema de archivos. Los JPEG de prueba pierden información: comparar con tolerancia o usar PNG.
- **Un test = una conducta**, con nombre en español que la describa (`test_la_prueba_nunca_entra_a_la_biblioteca`). Cubrí también los errores: mensaje claro, código 1, nada escrito a medias.
- **Probá que el test puede fallar.** Para un invariante nuevo, rompé la implementación a propósito (mutación) y comprobá que el test se pone rojo; después restaurá. Para "X nunca llega a Y", usá un espía (`monkeypatch`) que registre lo que pasa por Y.
- Las UI se testean sin ventana: reducer puro, layout (que cada botón se pueda alcanzar y no haya solapamientos) y un *smoke* de `render` que no lance excepciones.
- Las clases de `src/` cuyo nombre empieza con `Test` (por ejemplo `TestReport`) llevan `__test__ = False`; no uses ese prefijo para clases propias de tests.
- No edites `src/` desde un test: si encontrás un bug, reportalo con un caso mínimo que lo reproduzca.
