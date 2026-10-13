"""Migracion del layout viejo de la corrida a ``teach/`` y ``test/`` (``compat.migrate_run_layout``).

Los archivos viejos se escriben a mano (el formato de antes). Todo sobre ``tmp_path``.
Mutaciones hechas (con monkeypatch): vaciar ``LEGACY_RUN_FILES`` o anular
``RunPaths.migrate_layout`` deja rojos los tests de cada punto de entrada (ver el ultimo test).
"""

from __future__ import annotations

import argparse

import pytest

from conftest import make_config
from spectro.cli import main
from spectro.compat import LEGACY_RUN_FILES, migrate_run_layout
from spectro.project import RunContext, RunPaths, require_run
from spectro.teach_cli import _run_ids

VIEJOS = {
    "truth.csv": "file,value\na.jpg,1.000\n",
    "rejected.csv": "file,set,date\nb.jpg,train,2026-01-01\n",
    "out/teach_report.csv": "file,x\na.jpg,1\n",
    "test.csv": "file,value\nc.jpg,2.000\n",
    "out/test_report.csv": "file,y\nc.jpg,2\n",
    "out/teach_history.csv": (
        "fecha,tipo,plantillas,entrenamiento,prueba,valores_distintos,correctas,erroneas,"
        "descartadas,exactitud,error_aceptadas,cobertura\n"
        "2026-01-01 10:00:00,misma_corrida,30,8,2,2,2,0,0,1.0000,0.0000,1.0000\n"),
}


def _layout_viejo(root):
    for rel, texto in VIEJOS.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(texto, encoding="utf-8", newline="")
    return root


def _corrida_vieja(base, run_id="r1"):
    root = base / "runs" / run_id
    (root / "frames").mkdir(parents=True)
    make_config().save(root / "config.json")
    return _layout_viejo(root)


def _globales(base):
    return ["--runs-dir", str(base / "runs"), "--calib-dir", str(base / "calib")]


def _conflicto(root):
    (root / "teach").mkdir(exist_ok=True)
    (root / "teach" / "truth.csv").write_text("NUEVO", encoding="utf-8")


def test_la_tabla_de_migracion_cubre_los_seis_archivos():
    """Rompe: perder un archivo de ``LEGACY_RUN_FILES`` (queda en el layout viejo)."""
    assert len(LEGACY_RUN_FILES) == 6
    assert {new for _, new in LEGACY_RUN_FILES} == {
        "teach/truth.csv", "teach/rejected.csv", "teach/teach_report.csv",
        "test/test.csv", "test/test_report.csv", "test/teach_history.csv"}


def test_mueve_los_seis_archivos_con_su_contenido(tmp_path, capsys):
    """Rompe: no mover alguno, moverlo a la carpeta equivocada o alterar el contenido."""
    root = _layout_viejo(tmp_path / "r")
    movidos = migrate_run_layout(root)
    assert len(movidos) == 6
    for old, new in LEGACY_RUN_FILES:
        assert not (root / old).exists()
        assert (root / new).read_text(encoding="utf-8") == VIEJOS[old]
    assert capsys.readouterr().out.count("aviso: se movio") == 6


def test_es_idempotente_y_la_segunda_vez_no_mueve_nada(tmp_path, capsys):
    """Rompe: fallar o avisar de nuevo cuando todo ya esta en su lugar."""
    root = _layout_viejo(tmp_path / "r")
    migrate_run_layout(root)
    capsys.readouterr()
    assert migrate_run_layout(root) == []
    assert capsys.readouterr().out == ""
    for old, new in LEGACY_RUN_FILES:
        assert (root / new).read_text(encoding="utf-8") == VIEJOS[old]


def test_corrida_nueva_o_inexistente_no_cambia_nada(tmp_path):
    """Rompe: crear ``teach/`` o ``test/`` vacias, o fallar si falta la carpeta."""
    root = tmp_path / "r"
    root.mkdir()
    assert migrate_run_layout(root) == []
    assert list(root.iterdir()) == []
    assert migrate_run_layout(tmp_path / "no_existe") == []


def test_migra_solo_lo_que_existe(tmp_path):
    """Rompe: exigir los seis archivos o crear destinos vacios de los que faltan."""
    root = tmp_path / "r"
    root.mkdir()
    (root / "truth.csv").write_text(VIEJOS["truth.csv"], encoding="utf-8")
    movidos = migrate_run_layout(root)
    assert [d for _, d in movidos] == [root / "teach" / "truth.csv"]
    assert not (root / "test").exists()


def test_origen_y_destino_juntos_dan_error_y_no_mueven_nada(tmp_path):
    """Rompe: mover antes de detectar el conflicto (queda a medias) o pisar el destino."""
    root = _layout_viejo(tmp_path / "r")
    (root / "test").mkdir()
    (root / "test" / "teach_history.csv").write_text("NUEVO", encoding="utf-8")   # conflicto en el ultimo
    with pytest.raises(RuntimeError, match="viejo .*nuevo"):
        migrate_run_layout(root)
    for rel, texto in VIEJOS.items():                      # ninguno de los viejos se movio
        assert (root / rel).read_text(encoding="utf-8") == texto
    assert not (root / "teach").exists()
    assert (root / "test" / "teach_history.csv").read_text(encoding="utf-8") == "NUEVO"


def test_conflicto_en_el_primer_archivo_tambien_es_atomico(tmp_path):
    """Rompe: validar archivo por archivo mientras se mueve (los siguientes quedan a medias)."""
    root = _layout_viejo(tmp_path / "r")
    _conflicto(root)
    with pytest.raises(RuntimeError):
        migrate_run_layout(root)
    assert (root / "truth.csv").exists() and (root / "test.csv").exists()
    assert not (root / "test").exists()


def test_acepta_ruta_como_texto(tmp_path):
    """Rompe: asumir ``Path`` en vez de aceptar ``str``."""
    root = _layout_viejo(tmp_path / "r")
    assert len(migrate_run_layout(str(root))) == 6


def test_require_run_migra_la_corrida_vieja(tmp_path):
    """Rompe: que ``require_run`` no llame a ``migrate_layout``."""
    root = _corrida_vieja(tmp_path)
    run = require_run("r1", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    assert run.truth.read_text(encoding="utf-8") == VIEJOS["truth.csv"]
    assert run.test.exists() and run.history.exists() and run.rejected.exists()
    assert run.teach_report.exists() and run.test_report.exists()
    assert not (root / "truth.csv").exists()


def test_require_run_de_corrida_inexistente_no_crea_nada(tmp_path):
    """Rompe: migrar o crear carpetas antes de comprobar que la corrida existe."""
    (tmp_path / "runs").mkdir()
    with pytest.raises(ValueError, match="No existe la corrida"):
        require_run("zzz", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    assert list((tmp_path / "runs").iterdir()) == []


def test_require_run_con_conflicto_falla_con_runtime_error(tmp_path):
    """Rompe: tragarse el conflicto en vez de dejar que ``cli.main`` lo imprima."""
    root = _corrida_vieja(tmp_path)
    _conflicto(root)
    with pytest.raises(RuntimeError):
        require_run("r1", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")


def test_run_context_load_migra_y_lee_las_muestras_viejas(tmp_path):
    """Rompe: que ``RunContext.load`` no migre antes de leer (las muestras salen vacias)."""
    _corrida_vieja(tmp_path)
    run = RunPaths.for_run("r1", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    ctx = RunContext.load(run)
    assert [s.file for s in ctx.train] == ["a.jpg"]
    assert [s.file for s in ctx.test] == ["c.jpg"]
    assert run.truth.exists() and not (run.root / "truth.csv").exists()


def test_run_ids_de_teach_migra_todas_las_corridas(tmp_path):
    """Rompe: que ``_run_ids`` liste sin migrar (las demas areas verian el layout viejo)."""
    r1, r2 = _corrida_vieja(tmp_path, "r1"), _corrida_vieja(tmp_path, "r2")
    (tmp_path / "runs" / "sin_config").mkdir()
    args = argparse.Namespace(runs_dir=str(tmp_path / "runs"), calib_dir=str(tmp_path / "calib"))
    assert _run_ids(args) == ["r1", "r2"]
    for r in (r1, r2):
        assert (r / "teach" / "truth.csv").exists() and (r / "test" / "test.csv").exists()
        assert not (r / "truth.csv").exists()
    assert not (tmp_path / "runs" / "sin_config" / "teach").exists()   # sin config no es corrida


def test_teach_status_por_cli_migra_una_corrida_vieja(tmp_path):
    """Rompe: que el camino real (``teach status``) no migre."""
    root = _corrida_vieja(tmp_path)
    assert main(_globales(tmp_path) + ["teach", "status"]) == 0
    assert (root / "teach" / "truth.csv").exists() and not (root / "truth.csv").exists()


def test_teach_con_conflicto_sale_con_error_y_codigo_1(tmp_path, capsys):
    """Rompe: que el conflicto salga como traza en vez de ``ERROR: ...`` con codigo 1."""
    root = _corrida_vieja(tmp_path)
    _conflicto(root)
    assert main(_globales(tmp_path) + ["teach", "status"]) == 1
    assert "ERROR:" in capsys.readouterr().err
    assert (root / "truth.csv").read_text(encoding="utf-8") == VIEJOS["truth.csv"]   # no se perdio nada


def test_sin_migrar_la_corrida_vieja_queda_sin_muestras(tmp_path, monkeypatch):
    """Mutacion dejada escrita: con ``migrate_layout`` anulado el layout viejo sigue y
    ``require_run`` no deja ``teach/truth.csv``; los tests de arriba fallarian."""
    _corrida_vieja(tmp_path)
    monkeypatch.setattr(RunPaths, "migrate_layout", lambda self: [])
    run = require_run("r1", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    assert not run.truth.exists()
