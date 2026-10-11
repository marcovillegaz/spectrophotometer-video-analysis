"""Fase 1 del plan v5: correcciones tras la revision de codigo (un test minimo por punto)."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from conftest import make_config, render_display
from spectro import library as lib
from spectro.evaluation import evaluate
from spectro.imaging import crop_for_reading
from spectro.qc import run_qc
from spectro.read import run_read
from spectro.teach import Sample, build_pool


def test_evaluate_usa_el_sidecar_roi(cfg, library, tmp_path):
    """Punto 1: una corrida extraida con --roi-only se evalua sin recortar de nuevo."""
    recorte = cfg.roi.crop(render_display("0.245"))
    cv2.imwrite(str(tmp_path / "t_0000001.000.jpg"), recorte)
    r = cfg.roi
    (tmp_path / ".roi.json").write_text(
        json.dumps({"x": r.x, "y": r.y, "w": r.w, "h": r.h}), encoding="utf-8")
    _, datas, errores = build_pool([Sample("t_0000001.000.jpg", "0.245")], cfg, tmp_path)
    assert not errores and datas[0].frames_roi == r
    lectura = evaluate(datas, library, cfg)[0].reading
    assert lectura.chars == "0.245" and lectura.status == "ok"


def test_guarda_de_roi_solo_salta_si_no_cabe(cfg):
    """Punto 2: un exceso de pocos pixeles en el borde se recorta; si no cabe, ValueError."""
    cfg.roi.x = 200  # x + w se pasa del ancho (320), pero w cabe
    assert crop_for_reading(render_display("0.245"), cfg).shape[1] > 0
    chico = np.zeros((cfg.roi.h - 1, 400), dtype=np.uint8)
    with pytest.raises(ValueError):
        crop_for_reading(chico, cfg)


def test_qc_y_read_descartan_un_fotograma_que_no_cabe(cfg, library, tmp_path):
    """Punto 2: el fotograma chico se descarta con motivo, no aborta la corrida."""
    cfg.qc.register = False
    frames = tmp_path / "frames"
    frames.mkdir()
    cv2.imwrite(str(frames / "t_0000001.000.jpg"), render_display("0.245"))
    cv2.imwrite(str(frames / "t_0000002.000.jpg"), np.full((10, 10), 90, np.uint8))
    qc_csv = tmp_path / "qc.csv"
    rows = run_qc(cfg, frames, tmp_path / "no_hay.csv", qc_csv, verbose=False)
    assert {r.file: r.status for r in rows}["t_0000002.000.jpg"] == "roi_outside"
    assert rows[0].status != "roi_outside"
    # Aun si un fotograma chico llegara marcado como ok, read lo descarta sin abortar.
    for r in rows:
        r.status = "ok"
    from spectro.qc import write_qc_report
    write_qc_report(rows, qc_csv)
    tdir = tmp_path / "tpl"
    tdir.mkdir()
    for t in library:
        cv2.imwrite(str(tdir / f"{t.label}_0.png"), t.image)
    lecturas = run_read(cfg, frames, qc_csv, tdir, tmp_path / "r.csv", verbose=False)
    assert {r.file: r.status for r in lecturas}["t_0000002.000.jpg"] == "roi_outside"


def test_list_backups_orden_natural(tmp_path):
    """Punto 3: ``_10`` va despues de ``_2``."""
    tpl = tmp_path / "templates"
    tpl.mkdir()
    root = lib.backups_root(tpl)
    nombres = ["20260101_120000", "20260101_120000_2", "20260101_120000_10", "20260101_120001"]
    for n in nombres:
        (root / n).mkdir(parents=True)
    assert lib.list_backups(tpl) == nombres


def test_train_avisa_signo_si_alguna_corrida_lo_necesita(monkeypatch, tmp_path):
    """Punto 4: el aviso de signo mira todas las corridas, no solo la primera."""
    from types import SimpleNamespace
    from spectro import teach
    sin, con = make_config(), make_config(sign=True)
    dato = SimpleNamespace(cells=["0"])
    monkeypatch.setattr(teach, "build_pool_runs", lambda runs, prefixed=True: ([], [dato], []))
    monkeypatch.setattr(teach, "validate", lambda *a: None)
    monkeypatch.setattr(teach, "evaluate_library", lambda *a: None)
    monkeypatch.setattr(lib, "load", lambda d: [])
    monkeypatch.setattr(lib, "warn_missing_sign",
                        lambda c, v: "falta '-'" if c.digits.sign_slot is not None else None)
    corridas = [SimpleNamespace(cfg=sin), SimpleNamespace(cfg=con)]
    res = teach.train(corridas, tmp_path, build=False)
    assert res.sign_warning == "falta '-'"


def test_read_importa_template():
    """Punto 5: las anotaciones de read.py resuelven ``Template``."""
    from spectro import read
    assert read.Template is lib.Template
