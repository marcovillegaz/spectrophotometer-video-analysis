"""Piso de cobertura por modulo (no global): library, teach_cli, evaluation y teach_session >= 85 %.

``pytest-cov`` solo admite ``--cov-fail-under`` global, y el total incluye modulos que este
plan no toca (``extract``, ``calibrate``). Uso:

    .venv/Scripts/python -m pytest -q --cov=spectro --cov-report=json:$TEMP/cov.json
    .venv/Scripts/python tests/check_cobertura.py $TEMP/cov.json

Sale con 1 y lista los modulos bajo el piso (o ausentes del reporte). La logica esta en
``verificar`` y la prueba ``tests/test_piso_cobertura.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PISO = 85.0
MODULOS = ("library.py", "teach_cli.py", "evaluation.py", "teach_session.py")


def porcentajes(reporte: dict) -> dict[str, float]:
    """``{modulo: % cubierto}`` por nombre de archivo, de un reporte JSON de coverage."""
    return {Path(p).name: d["summary"]["percent_covered"] for p, d in reporte["files"].items()}


def verificar(reporte: dict, piso: float = PISO, modulos=MODULOS) -> list[str]:
    """Los problemas encontrados (lista vacia = todo bien)."""
    pct = porcentajes(reporte)
    out = []
    for m in modulos:
        if m not in pct:
            out.append(f"{m}: no aparece en el reporte")
        elif pct[m] < piso:
            out.append(f"{m}: {pct[m]:.1f} % < {piso:.0f} %")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    reporte = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    pct = porcentajes(reporte)
    for m in MODULOS:
        print(f"{m:20s} {pct.get(m, float('nan')):6.1f} %")
    problemas = verificar(reporte)
    for p in problemas:
        print("PISO NO CUMPLIDO:", p)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
