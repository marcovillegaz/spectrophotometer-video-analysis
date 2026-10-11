"""Plantillas danadas de la biblioteca y la muestra de la que salieron (solo lectura).

Revisa la biblioteca contra las muestras etiquetadas y senala:

1. plantillas que **ganan mal** (son la mejor coincidencia de una celda de OTRO caracter);
2. pares de plantillas de **distinto caracter** casi iguales (NCC alta): una etiqueta equivocada;
3. plantillas **casi vacias** (poca tinta frente a las de su caracter): fotograma a medio dibujar;
4. para cada sospechosa, la muestra de la que salio y el valor que se escribio.

    python .claude/skills/diagnose-reading/scripts/culprits.py --run img_8110
    python .claude/skills/diagnose-reading/scripts/culprits.py --all-runs

Con ``--all-runs`` junta las muestras de entrenamiento de todas las corridas (es lo que
usa ``teach train`` sin corridas). La biblioteca es global, asi que una etiqueta mala en
cualquier video contamina a todos.
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import argumentos  # noqa: E402


def main() -> int:
    p = argumentos(__doc__.splitlines()[0], run=False)
    p.add_argument("--run", help="una corrida (su truth.csv; con --with-test tambien su test.csv)")
    p.add_argument("--all-runs", action="store_true", help="las muestras de entrenamiento de todas las corridas")
    p.add_argument("--with-test", action="store_true", help="sumar test.csv al conteo de usos")
    p.add_argument("--thr", type=float, default=0.9, help="NCC desde la cual dos plantillas se consideran casi iguales")
    args = p.parse_args()
    if not (args.run or args.all_runs):
        sys.exit("Indica --run <id> o --all-runs.")

    import numpy as np

    from spectro import library as L
    from spectro import teach as T
    from spectro.config import Config
    from spectro.imaging import ncc
    from spectro.project import CalibPaths, RunPaths
    from spectro.qc import load_qc_report

    templates_dir = CalibPaths.at(args.calib_dir).templates
    entradas = L.list_entries(templates_dir)
    if not entradas:
        sys.exit(f"No hay plantillas en {templates_dir}.")

    if args.all_runs:
        corridas = T.gather_runs(args.runs_dir, args.calib_dir)
        if not corridas:
            sys.exit("Ninguna corrida tiene truth.csv con muestras.")
        pool, datas, errores = T.build_pool_runs(corridas)
        origen = {f"{r.run_id}/": r for r in corridas}
    else:
        run = RunPaths.for_run(args.run, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        cfg = Config.load(run.config)
        offsets = {x.file: x.offset for x in load_qc_report(run.qc_report)} if run.qc_report.exists() else {}
        muestras = T.load_truth(run.truth) + (T.load_truth(run.test) if args.with_test else [])
        pool, datas, errores = T.build_pool(muestras, cfg, run.frames, offsets)
        origen = {}
    for e in errores:
        print(f"muestra descartada: {e}")
    L.usage(entradas, datas)
    valor = {d.ident: d.sample.value for d in datas}
    print(f"{len(entradas)} plantillas, {len(datas)} muestras, {len(pool)} glifos\n")

    def de_donde(e) -> str:
        if not pool:
            return "?"
        mejor = max(((ncc(g.image, e.image), g) for g in pool if g.label == e.label), key=lambda x: x[0],
                    default=(0.0, None))
        s, g = mejor
        return f"{g.source} (escribiste {valor.get(g.source, '?')!r}, NCC {s:.3f})" if g and s >= 0.99 else "no sale de estas muestras"

    print("1. plantillas que ganan mal:")
    malas = [e for e in entradas if e.errors]
    for e in malas:
        print(f"   {e.path.name:10s} usos {e.uses:3d}  gana_mal {e.errors:3d}   sale de {de_donde(e)}")
    if not malas:
        print("   ninguna")

    print(f"\n2. pares de distinto caracter con NCC >= {args.thr}:")
    hay = False
    for i, a in enumerate(entradas):
        for b in entradas[i + 1:]:
            if a.label != b.label:
                s = ncc(a.image, b.image)
                if s >= args.thr:
                    hay = True
                    print(f"   {a.path.name:10s} ~ {b.path.name:10s} NCC {s:.3f}   "
                          f"(una de las dos tiene la etiqueta equivocada)")
    if not hay:
        print("   ninguno")

    print("\n3. plantillas casi vacias (tinta < 60 % de la mediana de su caracter):")
    tinta = defaultdict(list)
    for e in entradas:
        tinta[e.label].append(float(np.count_nonzero(e.image)) / e.image.size)
    vacias = []
    for e in entradas:
        t = float(np.count_nonzero(e.image)) / e.image.size
        mediana = statistics.median(tinta[e.label])
        if len(tinta[e.label]) > 1 and t < 0.6 * mediana:
            vacias.append(e)
            print(f"   {e.path.name:10s} tinta {t:.3f} (mediana {mediana:.3f})   sale de {de_donde(e)}")
    if not vacias:
        print("   ninguna")
    return 0


if __name__ == "__main__":
    sys.exit(main())
