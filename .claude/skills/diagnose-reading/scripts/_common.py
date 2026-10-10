"""Utilidades comunes de los scripts de diagnostico (solo lectura).

Ninguno de estos scripts escribe en ``calib/`` ni en ``runs/``: leen la config de la
corrida, el reporte de QC y la biblioteca, y imprimen (o guardan una imagen en la
ruta que se les pase con ``--out``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace


def argumentos(descripcion: str, run: bool = True) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=descripcion)
    if run:
        p.add_argument("--run", required=True, help="id de la corrida, p. ej. img_8110")
    p.add_argument("--runs-dir", default="runs", help="carpeta de corridas (default: runs)")
    p.add_argument("--calib-dir", default="calib",
                   help="carpeta de calibracion con templates/ (default: calib); "
                        "apuntala a una copia para probar una biblioteca distinta")
    return p


def contexto(args) -> SimpleNamespace:
    """Config, offsets de QC, biblioteca y rutas de la corrida."""
    from spectro.config import Config
    from spectro.project import CalibPaths, RunPaths
    from spectro.qc import load_qc_report
    from spectro.templates import load_templates

    run = RunPaths.for_run(args.run, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
    if not run.config.exists():
        sys.exit(f"No existe {run.config}. Corridas: ver la carpeta {args.runs_dir}/")
    cfg = Config.load(run.config)
    qc = load_qc_report(run.qc_report) if run.qc_report.exists() else []
    calib = CalibPaths.at(args.calib_dir)
    try:
        library = load_templates(calib.templates)
    except FileNotFoundError:
        library = []
    return SimpleNamespace(
        run=run, cfg=cfg, qc=qc, library=library, templates_dir=calib.templates,
        offsets={r.archivo: r.offset for r in qc}, estados={r.archivo: r.estado for r in qc},
        frames_dir=Path(run.frames),
    )


def cortar_celdas(ctx, archivo: str):
    """``(roi_binaria, [(i, x0, x1)])`` del fotograma, con rotacion y corrimiento de QC."""
    from spectro.imaging import binarize, crop_for_reading, load_frame, slot_boxes

    gray = load_frame(ctx.frames_dir / archivo, ctx.cfg)
    roi = crop_for_reading(gray, ctx.cfg, None, ctx.offsets.get(archivo, (0, 0)))
    binaria = binarize(roi, ctx.cfg.digits.polarity)
    cajas = [(i, x0, x1) for i, (x0, x1) in enumerate(slot_boxes(roi.shape[1], ctx.cfg.digits))]
    return binaria, cajas


def ranking_por_etiqueta(glyph, library) -> list[tuple[str, float]]:
    """Mejor NCC de cada etiqueta contra ``glyph``, de mayor a menor."""
    from spectro.imaging import ncc

    mejor: dict[str, float] = {}
    for t in library:
        s = ncc(glyph, t.image)
        if s > mejor.get(t.label, -2.0):
            mejor[t.label] = s
    return sorted(mejor.items(), key=lambda kv: -kv[1])
