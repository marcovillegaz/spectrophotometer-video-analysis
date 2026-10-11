---
name: docs-sync
description: Mantiene la documentacion de spectro alineada con el codigo. Usar despues de que cambien comandos, flags, salidas o la estructura de carpetas, y antes de entregar cualquier documentacion. Verifica que cada comando documentado sea valido contra el parser real, que los enlaces y anclas existan, y que las cifras y salidas citadas salgan de datos reales.
---

# Sincronizar la documentación con el código

La documentación se desactualiza cada vez que cambia el código: un flag que ya no existe, un recuento de tests viejo, una salida que ya no se parece. Esta skill es el procedimiento para cazarlo **antes** de entregar.

## 1. Averiguar qué cambió y qué documento toca

`git status` y `git diff --stat` (solo lectura). Cruzalo con esta tabla:

| lo que cambió | documento y sección a revisar |
|---|---|
| `cli.py`, `teach_cli.py` (comandos, flags, mensajes) | `docs/referencia/comandos.md`; `docs/calibrar/guia.md` y `docs/empezar/primera-corrida.md` → bloques de comandos |
| `config.py` (campos de `config.json`) | `docs/referencia/config.md` |
| `project.py` (rutas, layout de carpetas) | `docs/referencia/carpetas.md` |
| `teach.py`, `sampling.py`, `evaluation.py` (entrenamiento, muestreo, prueba) | `docs/calibrar/guia.md` (pasos y fundamentos); `docs/diseno/decisiones.md` y `docs/diseno/arquitectura.md` (decisiones y tabla de módulos) |
| `read.py`, `qc.py`, `report.py` (columnas de CSV, estados) | `docs/referencia/salidas.md` |
| módulos nuevos o renombrados | `docs/diseno/arquitectura.md` → tabla de módulos; `CLAUDE.md` si cambia el mapa |
| cantidad de tests | `docs/contribuir.md` → sección *Tests* |
| agentes o skills | `CLAUDE.md` → *Agentes* |

## 2. Correr el verificador

```
.venv/Scripts/python .claude/skills/docs-sync/scripts/check_docs.py
.venv/Scripts/python .claude/skills/docs-sync/scripts/check_docs.py --list     # qué comandos ve
```

- **Comandos:** cada línea `python -m spectro …` de un bloque de código se **parsea en seco** con `build_parser()` (no se ejecuta). Un flag eliminado o mal escrito falla con el mensaje del parser.
- **Enlaces:** archivo y ancla de cada enlace relativo entre los `.md`.
- Los ejemplos con `...`, `…`, `[` o `|` se **omiten** (son plantillas); el resumen dice cuántos. Si un ejemplo real se está omitiendo por error, reescribilo sin esas marcas.
- Los `PLAN*.md` no se revisan: describen comandos futuros o ya reemplazados.

Un problema del verificador significa que **la documentación está mal o el código cambió**: arreglá el documento. Si el comando en el documento es correcto y el parser lo rechaza, es un bug del código: avisale al developer, no lo "arregles" en el texto.

## 3. Comparar flags con las tablas

El verificador comprueba que los comandos *se pueden parsear*, no que las tablas de flags estén completas. Para cada comando que cambió, ejecutá `--help` (está permitido) y confrontalo con la tabla del README: ¿falta un flag nuevo?, ¿sobra uno viejo?, ¿cambió un valor por defecto?

```
.venv/Scripts/python -m spectro teach --help
.venv/Scripts/python -m spectro teach test --help
```

## 4. Ejecutar los ejemplos que se pueden (solo lectura)

Tenés permitido: `--help`, `doctor`, `teach status`, `teach lib list`, `teach samples list`, `teach test list|history`, `teach test eval` (sin corrida), `pytest`, `git status|diff|log`. Si un ejemplo cita una **salida**, volvé a producirla con uno de esos comandos o, si hace falta un comando que escribe (`train`, `read`, `report`, `teach … eval <corrida>`), **pedísela al developer** con el comando exacto. Nunca completes una salida de memoria.

## 5. Cifras y salidas citadas

- Recuento de tests: `.venv/Scripts/python -m pytest -q` → el "N passed" va en el README.
- Una cifra de un experimento (porcentajes, plantillas, intervalos) lleva su **origen**: la corrida y la fecha. Si no podés reproducirla, se dice ("medido el 8-oct-2026 en `img_8102`") o se quita.
- Una salida de ejemplo que ya no coincide con la real se reemplaza por la real, no se "parece".

## 6. Cerrar

Volvé a correr `check_docs.py` (tiene que dar 0). Informá al final: documentos modificados, qué problema resolvió cada cambio, qué omitió el verificador y por qué, y qué le pedís al developer (si algo).

## Qué no hacer

- No edites código, tests ni `.claude/` (hay un hook que lo bloquea): si el documento exige un cambio de código, describilo.
- No ejecutes comandos que escriben (el hook de Bash también lo bloquea).
- No dupliques contenido entre documentos: una explicación vive en un solo lugar y el resto la enlaza (ver `docs-style`).
