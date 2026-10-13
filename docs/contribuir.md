# Contribuir

**Para quién y cuándo leerlo:** cuando vas a cambiar el código, los tests o la documentación de
spectro. La memoria completa del proyecto para quien trabaja en el código (invariantes de diseño,
seguridad de datos, agentes) está en [`CLAUDE.md`](../CLAUDE.md); acá está el resumen para empezar.

## Tests

```powershell
python -m pytest -q
```

La cantidad de tests cambia con cada función nueva: el número vigente es el que imprime ese
comando, no el de un documento. Como referencia, el 13-oct-2026 la suite tenía 1010 tests y tardó
74 s.

Usan fixtures sintéticas — un "display" de mentira dibujado con OpenCV — así que no dependen del
video ni de datos reales: convención de nombres, decodificación de dígitos, armado del número,
filtro de QC, umbrales de confianza, contratos entre etapas, derivación de rutas por corrida,
calibración automática, biblioteca y respaldos, entrenamiento y evaluación, el árbol de `teach`,
la lógica de las ventanas sin ventana, la compatibilidad con archivos viejos y esta misma
documentación (`tests/test_docs.py` comprueba que cada comando citado exista en el CLI y que cada
enlace apunte a algo real).

Los tests con fixtures no alcanzan solos: varios errores del proyecto se vieron recién sobre datos
reales. Verificá también sobre los videos, con comandos de solo lectura o sobre una copia
(`--calib-dir` y `--runs-dir` apuntando a una carpeta temporal).

## Verificar la documentación

```powershell
.venv/Scripts/python .claude/skills/docs-sync/scripts/check_docs.py
```

Parsea en seco cada `python -m spectro …` citado en `README.md`, `CLAUDE.md` y `docs/` (salvo
`docs/plans/` y `docs/historia/`) y revisa que cada enlace relativo apunte a un archivo y a un
encabezado que existan. Tiene que terminar sin problemas. Una explicación vive en **un solo**
documento y los demás la enlazan: el mapa de qué va dónde es el
[índice del README](../README.md#mapa-de-la-documentación).

## Flujo de trabajo y agentes

Una función nueva sigue este orden: **plan → implementar y correr la suite → agregar tests y
comprobar por mutación que fallan → (reestructurar si el código quedó torcido) → actualizar la
documentación y verificar los comandos → commit**. En Claude Code cada etapa la hace un agente
distinto (`developer`, `test`, `refactor`, `writer`), y cada uno solo puede escribir en su zona;
la tabla de agentes y sus zonas está en
[`CLAUDE.md`](../CLAUDE.md#agentes-claudeagents). Los agentes no hacen commits: los hace la
persona, con `/commit`.

## Convenciones, en resumen

- **Interfaz en inglés, prosa en español.** Identificadores, columnas de CSV, claves de
  `config.json`, flags y valores de estado van en inglés; comentarios, mensajes y documentos, en
  español (con voseo en la documentación). Los textos de pantalla del CLI y de la UI quedan en
  español.
- **Sin tildes ni eñes en el código ni en las salidas del CLI**; con tildes en los `.md`.
- **Errores esperados** como `ValueError`, `FileNotFoundError` o `RuntimeError`: el CLI los
  imprime como `ERROR: ...` y sale con código 1.
- **Los archivos que ya existen siguen cargando**: los nombres viejos se traducen en un solo
  lugar, `compat.py`.

Los invariantes de diseño que no se pueden romper (descartar antes que adivinar, un solo
recorte de celda, un solo evaluador, la biblioteca solo por `library.py`…) están en
[`CLAUDE.md`](../CLAUDE.md#invariantes-de-diseño-no-romperlos), y el porqué de cada uno, en
[decisiones](diseno/decisiones.md).

## Datos reales: qué no tocar

No se editan a mano `calib/templates/`, `runs/*/teach/truth.csv` ni `runs/*/test/test.csv`: los cambios van
por los comandos `teach`, que respaldan solos antes de borrar. El detalle está en
[`CLAUDE.md`](../CLAUDE.md#seguridad-de-datos).

## Trampas del entorno (Windows + Git Bash)

- Usá `.venv/Scripts/python` como intérprete.
- Los heredocs de Python con barras invertidas (`\n`, `\\`) se corrompen en Git Bash: escribí el
  script a un archivo y ejecutalo.
- Listar las carpetas de fotogramas es muy lento: contá con `frames_index.csv`.

---

**Siguiente paso:** fin del recorrido. Para volver al mapa de todos los documentos, el
[README](../README.md#mapa-de-la-documentación).
