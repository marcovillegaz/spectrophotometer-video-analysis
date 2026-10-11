"""La logica del verificador de piso de cobertura (``tests/check_cobertura.py``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_cobertura as C  # noqa: E402


def _rep(**pcts):
    return {"files": {f"src/spectro/{m}.py": {"summary": {"percent_covered": v}} for m, v in pcts.items()}}


def _todos(v):
    return _rep(library=v, teach_cli=v, evaluation=v, teach_session=v)


def test_el_piso_acepta_el_borde_y_rechaza_por_debajo():
    """Rompe: cambiar ``<`` por ``<=`` o mover el piso."""
    assert C.PISO == 85.0 and C.verificar(_todos(85.0)) == []
    (p,) = C.verificar(_rep(library=84.9, teach_cli=90, evaluation=90, teach_session=90))
    assert p.startswith("library.py")


def test_un_modulo_ausente_del_reporte_es_un_problema():
    """Rompe: tratar la ausencia como cumplimiento (un modulo sin medir pasaria el piso)."""
    (p,) = C.verificar(_rep(library=99, teach_cli=99, evaluation=99))
    assert "teach_session.py" in p and "no aparece" in p


def test_main_devuelve_codigo_segun_el_reporte(tmp_path, capsys):
    """Rompe: que ``main`` salga con 0 aunque haya modulos bajo el piso."""
    ok, mal = tmp_path / "ok.json", tmp_path / "mal.json"
    ok.write_text(json.dumps(_todos(97)), encoding="utf-8")
    mal.write_text(json.dumps(_todos(50)), encoding="utf-8")
    assert C.main(["x", str(ok)]) == 0
    assert C.main(["x", str(mal)]) == 1 and "PISO NO CUMPLIDO" in capsys.readouterr().out
    assert C.main(["x"]) == 2
