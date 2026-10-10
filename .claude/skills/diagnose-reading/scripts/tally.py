"""Por que se rechazan los fotogramas de una corrida (solo lectura).

Lee una muestra de los fotogramas que pasaron QC (``--every N``), aplica el mismo criterio
que ``read`` (puntaje minimo y margen minimo contra otra etiqueta) y cuenta:

* los motivos de rechazo por celda (puntaje, margen, signo con tinta);
* cuantos fotogramas se rechazan *solo* por margen;
* la fraccion rechazada por tramo de tiempo;
* los pares de caracteres que se estorban (mejor etiqueta vs. segunda etiqueta).

    python .claude/skills/diagnose-reading/scripts/tally.py --run img_8110 --every 3
    python .claude/skills/diagnose-reading/scripts/tally.py --run img_8110 --sin 0_3 1_3

``--sin`` quita plantillas **en memoria** (no en disco) y recalcula: sirve para cuantificar
cuanto mejoraria la lectura al borrarlas, antes de tocar nada.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import argumentos, contexto, cortar_celdas, ranking_por_etiqueta  # noqa: E402


def main() -> int:
    p = argumentos(__doc__.splitlines()[0])
    p.add_argument("--every", type=int, default=3, help="usar 1 de cada N fotogramas (default 3)")
    p.add_argument("--bin", type=int, default=200, help="segundos por tramo de tiempo (default 200)")
    p.add_argument("--sin", nargs="*", default=[], metavar="PLANTILLA",
                   help="quitar estas plantillas en memoria, p. ej. 0_3 1_3")
    args = p.parse_args()
    ctx = contexto(args)
    if not ctx.library:
        sys.exit(f"No hay plantillas en {ctx.templates_dir}.")

    from spectro.imaging import normalize_glyph

    quitar = {s.removesuffix(".png") for s in args.sin}
    library = [t for t in ctx.library if t.path.stem not in quitar]
    if quitar:
        print(f"plantillas quitadas en memoria: {sorted(quitar)} "
              f"({len(ctx.library)} -> {len(library)})")
    t = ctx.cfg.templates
    d = ctx.cfg.digits
    filas = [r for r in ctx.qc if r.passed_qc][:: max(args.every, 1)]
    print(f"corrida {args.run}: {len(filas)} fotogramas (1 de cada {args.every}); "
          f"biblioteca: {dict(sorted(Counter(x.label for x in library).items()))}")

    motivos: Counter = Counter()
    pares: Counter = Counter()
    por_tramo: dict[int, list[int]] = {}
    rechazados = solo_margen = 0
    for r in filas:
        binaria, cajas = cortar_celdas(ctx, r.archivo)
        malos: list[str] = []
        for i, x0, x1 in cajas:
            celda = binaria[:, x0:x1]
            if i == d.sign_slot:
                if (celda > 0).sum() / max(celda.size, 1) >= d.sign_max_ink:
                    malos.append("signo con tinta")
                continue
            rk = ranking_por_etiqueta(normalize_glyph(celda, t.size), library)
            (lab, best), (otra, seg) = rk[0], (rk[1] if len(rk) > 1 else ("-", -1.0))
            if best < t.min_score:
                malos.append("puntaje")
            elif best - seg < t.min_margin:
                malos.append("margen")
                pares[tuple(sorted((lab, otra)))] += 1
            elif i in (d.separator_slots or []) and lab != ".":
                malos.append("separador")
            elif i not in (d.separator_slots or []) and not lab.isdigit():
                malos.append("no digito")
        tramo = int(r.t_s // args.bin)
        por_tramo.setdefault(tramo, [0, 0])[1] += 1
        if malos:
            rechazados += 1
            por_tramo[tramo][0] += 1
            motivos.update(malos)
            solo_margen += all(m == "margen" for m in malos)

    n = max(len(filas), 1)
    print(f"\naceptados {len(filas) - rechazados}/{len(filas)} = {100 * (len(filas) - rechazados) / n:.1f}%"
          f"   rechazados {rechazados} (solo por margen: {solo_margen})")
    print("motivos de rechazo (celdas):", dict(motivos))
    print("pares que se estorban (margen < minimo):", pares.most_common(8))
    print(f"\nrechazo por tramo de {args.bin} s:")
    for k in sorted(por_tramo):
        rech, tot = por_tramo[k]
        print(f"  {k * args.bin:6d}-{(k + 1) * args.bin:6d} s: {rech:4d}/{tot:4d} = {100 * rech / max(tot, 1):5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
