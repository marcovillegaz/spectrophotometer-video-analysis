"""Signo negativo, rotacion, calibracion con signo y UI (logica pura)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from conftest import make_config, render_display
from spectro.calibrate import _infer_separator_slots, refine_roi
from spectro.config import ROI, Config
from spectro.imaging import binarize, load_frame, normalize_glyph, slot_boxes
from spectro.read import assemble, read_frame
from spectro.library import Template


def test_assemble_negativo():
    assert assemble("0018", 1, negative=True) == pytest.approx(-0.018)
    assert assemble("0018", 1) == pytest.approx(0.018)


def test_assemble_cero_negativo_es_cero():
    v = assemble("0000", 1, negative=True)
    assert v == 0.0 and str(v) == "0.0"


@pytest.mark.parametrize("text,esperado", [("-0.245", -0.245), (" 0.245", 0.245), ("-1.789", -1.789)])
def test_lee_signo(cfg_sign, library_sign, text, esperado):
    r = read_frame(render_display(text), cfg_sign, library_sign)
    assert r.estado == "ok", r.caracteres
    assert r.valor == pytest.approx(esperado)
    assert r.caracteres == text


def test_celda_vacia_con_ruido_es_positivo(cfg_sign, library_sign):
    img = render_display(" 0.245")
    rng = np.random.default_rng(0)
    x0 = cfg_sign.roi.x
    patch = img[cfg_sign.roi.y : cfg_sign.roi.y + 44, x0 : x0 + 26]
    patch += rng.integers(0, 3, patch.shape, dtype=np.uint8)
    r = read_frame(img, cfg_sign, library_sign)
    assert r.valor == pytest.approx(0.245)


def test_sin_plantilla_menos_se_descarta(cfg_sign, library_sign):
    lib = [t for t in library_sign if t.label != "-"]
    r = read_frame(render_display("-0.245"), cfg_sign, lib)
    assert r.estado == "low_confidence" and r.valor is None


def test_digito_en_celda_de_signo_se_descarta(cfg_sign, library_sign):
    r = read_frame(render_display("30.245"), cfg_sign, library_sign)
    assert r.estado == "low_confidence"


def test_config_sin_signo_no_cambia(cfg, library):
    r = read_frame(render_display("0.245"), cfg, library)
    assert r.valor == pytest.approx(0.245)


def test_config_vieja_carga_con_defaults():
    cfg = Config.from_dict({"digits": {"n_digits": 5}})
    assert cfg.digits.sign_slot is None and cfg.rotation_deg == 0.0


def test_digit_slots_excluye_signo(cfg_sign):
    assert cfg_sign.digits.digit_slots() == [1, 3, 4, 5]


def test_refine_roi_igual_con_positivo_y_negativo(cfg_sign):
    big = ROI(x=cfg_sign.roi.x - 15, y=cfg_sign.roi.y - 10, w=cfg_sign.roi.w + 30, h=60)
    rois = []
    for text in ("-0.245", " 0.245"):
        gray = render_display(text)
        rois.append(refine_roi(gray, big, "light_on_dark", n_digits=6, sign=True))
    a, b = rois
    assert abs(a.x - b.x) <= 1 and abs(a.w - b.w) <= 2
    # la ROI refinada contiene la celda del signo
    assert a.x <= cfg_sign.roi.x + 4


def test_separador_ignora_celda_de_signo(cfg_sign):
    gray = render_display(" 0.245")
    assert _infer_separator_slots(gray, cfg_sign.roi, cfg_sign.digits) == [2]


def test_rotacion_se_compensa(cfg_sign, library_sign, tmp_path):
    img = render_display("-0.245", angle=3.0)
    p = tmp_path / "t_0000001.000.jpg"
    cv2.imwrite(str(p), img)
    cfg_sign.rotation_deg = -3.0
    r = read_frame(load_frame(p, cfg_sign), cfg_sign, library_sign)
    assert r.valor == pytest.approx(-0.245)


def test_roi_only_con_rotacion_falla(tmp_path):
    from spectro import cli

    cfg = make_config()
    cfg.rotation_deg = 2.0
    path = cfg.save(tmp_path / "config.json")
    args = cli.build_parser().parse_args(
        ["--config", str(path), "extract", "--roi-only", "--video", "x.mov"]
    )
    assert args.func(args) == 2
