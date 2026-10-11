"""Diagnostico celda por celda de uno o varios fotogramas (solo lectura).

Para cada celda muestra la tinta, la mejor etiqueta, su puntaje y el margen contra la
mejor etiqueta *distinta*, y marca cuales celdas hacen que el lector rechace el fotograma:

    python .claude/skills/diagnose-reading/scripts/cells.py --run img_8110 t_0000205.000.jpg

Un margen chico con puntaje alto (``RECHAZA`` con puntaje 0.9+) es la firma de dos
plantillas de caracteres distintos casi iguales: mirar ``culprits.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import argumentos, contexto, cortar_celdas, ranking_por_etiqueta  # noqa: E402


def main() -> int:
    p = argumentos(__doc__.splitlines()[0])
    p.add_argument("frames", nargs="+", help="nombres de fotograma, p. ej. t_0000205.000.jpg")
    args = p.parse_args()
    ctx = contexto(args)
    if not ctx.library:
        sys.exit(f"No hay plantillas en {ctx.templates_dir}.")
    from spectro.imaging import normalize_glyph
    from spectro.read import read_frame
    from spectro.imaging import load_frame

    t = ctx.cfg.templates
    for nombre in args.frames:
        binaria, cajas = cortar_celdas(ctx, nombre)
        r = read_frame(load_frame(ctx.frames_dir / nombre, ctx.cfg), ctx.cfg, ctx.library, None,
                       ctx.offsets.get(nombre, (0, 0)))
        print(f"\n{nombre}  qc={ctx.statuses.get(nombre, '?')}  offset={ctx.offsets.get(nombre, (0, 0))}  "
              f"lee {r.chars!r}  estado={r.status}  confianza={r.confidence:.2f}  margen={r.margin:.3f}")
        for i, x0, x1 in cajas:
            celda = binaria[:, x0:x1]
            tinta = float((celda > 0).sum()) / max(celda.size, 1)
            if i == ctx.cfg.digits.sign_slot:
                marca = f"  <- SIGNO (tinta {tinta:.3f}, umbral {ctx.cfg.digits.sign_max_ink})"
                print(f"  celda {i}: tinta {tinta:.3f}{marca}")
                continue
            rk = ranking_por_etiqueta(normalize_glyph(celda, t.size), ctx.library)
            (lab, best), (otra, seg) = rk[0], (rk[1] if len(rk) > 1 else ("-", -1.0))
            margen = best - seg
            marca = ""
            if best < t.min_score:
                marca = "  <- RECHAZA (puntaje bajo)"
            elif margen < t.min_margin:
                marca = f"  <- RECHAZA (margen bajo contra {otra!r})"
            print(f"  celda {i}: tinta {tinta:.3f}  mejor {lab!r} {best:.2f}  "
                  f"segunda {otra!r} {seg:.2f}  margen {margen:.3f}{marca}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
