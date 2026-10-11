"""UI de calibracion: acciones, layout, vista previa y prueba. Sin abrir ventanas."""

from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np
import pytest

from conftest import render_display
from spectro.calib_ui import (
    PANEL_W,
    UIState,
    apply_action,
    apply_key,
    build_config,
    data_lines,
    final_roi,
    fit_scale,
    hit_test,
    layout_panel,
    preview_reading,
    probe_frames,
    render,
    slider_value,
    to_frame_coords,
)
from spectro.config import ROI


def test_teclas_son_atajos_de_acciones():
    s = UIState()
    s = apply_key(s, ord("e"))
    s = apply_key(s, ord("d"))
    assert s.rotation == pytest.approx(1.1)
    assert apply_key(s, 13).done and apply_key(s, 27).cancelled
    assert apply_key(s, ord("r")) == UIState()
    assert apply_key(s, ord("g")).guides


def test_signo_suma_y_quita_la_celda():
    s = apply_action(UIState(), "sign")
    assert s.sign and s.n_digits == 6
    s = apply_action(s, "sign")
    assert not s.sign and s.n_digits == 5


@pytest.mark.parametrize("action,campo,esperado", [
    ("cells+", "n_digits", 6), ("cells-", "n_digits", 4),
    ("dec+", "decimal_after", 2), ("dec-", "decimal_after", 0),
    ("rot+1", "rotation", 1.0), ("rot-0.1", "rotation", -0.1),
])
def test_acciones(action, campo, esperado):
    assert getattr(apply_action(UIState(), action), campo) == pytest.approx(esperado)


def test_toggles_y_limites():
    assert not apply_action(UIState(), "refine").refine
    assert apply_action(UIState(), "probe").probe_requested
    s = UIState(n_digits=2, decimal_after=2)
    assert apply_action(s, "cells-").n_digits == 2
    s = UIState(rotation=44.9)
    for _ in range(5):
        s = apply_action(s, "rot+1")
    assert s.rotation == 45.0


def test_coordenadas():
    assert to_frame_coords(100, 50, 0.5) == (200, 100)


def test_hit_test_y_slider():
    lay = layout_panel(1000, 800)
    for b in lay.buttons:
        assert hit_test(lay, *b.center) == b.action
    assert hit_test(lay, 100, 100) is None  # sobre la imagen
    assert slider_value(lay.slider[0], lay.slider) == -45.0
    assert slider_value(lay.slider[0] + lay.slider[2], lay.slider) == 45.0
    assert slider_value(lay.slider[0] + lay.slider[2] // 2, lay.slider) == pytest.approx(0.0, abs=0.5)


def test_botones_no_se_pisan_ni_salen_del_panel():
    lay = layout_panel(1000, 800)
    for i, a in enumerate(lay.buttons):
        assert a.x >= 1000 and a.x + a.w <= 1000 + PANEL_W and a.y + a.h <= 800
        for b in lay.buttons[i + 1:]:
            assert not (a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h)


def _estado_signo(refine: bool = False):
    # ROI exacta de la fixture: la biblioteca sintetica se armo con ella, asi que
    # sin ajustar a la tinta los slots caen igual que al construir las plantillas.
    return UIState(n_digits=6, sign=True, roi=ROI(x=40, y=30, w=156, h=44), refine=refine)


def test_preview_lee_el_valor_con_el_lector_real(cfg_sign, library_sign):
    gray = render_display("-0.245")
    p = preview_reading(gray, _estado_signo(), "light_on_dark", library_sign)
    assert p.enabled and p.value == pytest.approx(-0.245) and p.status == "ok"
    assert p.chars == "-0.245"


def test_preview_sin_biblioteca_o_sin_roi(library_sign):
    gray = render_display("-0.245")
    assert not preview_reading(gray, _estado_signo(), "light_on_dark", None).enabled
    assert not preview_reading(gray, UIState(), "light_on_dark", library_sign).enabled


def test_final_roi_respeta_refine():
    gray = render_display("-0.245")
    st = replace(_estado_signo(), roi=ROI(x=20, y=20, w=190, h=70))
    assert final_roi(gray, st, "light_on_dark") == st.roi
    assert final_roi(gray, replace(st, refine=True), "light_on_dark") != st.roi


def test_probe_cuenta_validas_y_rango(library_sign, tmp_path):
    gray = render_display("-0.245")
    paths = []
    for i, text in enumerate(("-0.245", " 1.789", "-3.056")):
        p = tmp_path / f"t_{i:07d}.000.jpg"
        cv2.imwrite(str(p), render_display(text))
        paths.append(p)
    cfg = build_config(gray, _estado_signo(), "light_on_dark")
    res = probe_frames(paths, cfg, library_sign)
    assert res.total == 3 and res.valid == 3 and res.negatives == 2
    assert res.vmin == pytest.approx(-3.056, abs=1e-3) and res.vmax == pytest.approx(1.789, abs=1e-3)


def test_probe_motivo_de_descarte(library_sign, tmp_path):
    gray = render_display("-0.245")
    p = tmp_path / "t_0000000.000.jpg"
    cv2.imwrite(str(p), np.full_like(gray, 30))
    res = probe_frames([p], build_config(gray, _estado_signo(), "light_on_dark"), library_sign)
    assert res.valid == 0 and res.top_reason


def test_render_smoke(library_sign):
    gray = render_display("-0.245")
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    st = _estado_signo()
    sc = fit_scale(img.shape)
    pv = preview_reading(gray, st, "light_on_dark", library_sign)
    canvas, lay = render(img, st, sc, "light_on_dark", pv, None, False, library_sign)
    assert canvas.shape[1] == int(img.shape[1] * sc) + PANEL_W
    assert lay.x0 == int(img.shape[1] * sc)
    # sin vista previa ni ROI tampoco falla
    render(img, UIState(), sc, "light_on_dark", None, None, False, None)
    assert any("ROI final" in l for l in data_lines(st, pv, "light_on_dark", img.shape, library_sign))


# -- lupa ---------------------------------------------------------------
from spectro.calib_ui import LENS_H, LENS_W, ZOOM_LEVELS, lens_corner, lens_patch  # noqa: E402


def test_lens_patch_centrada_y_ampliada():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    img[50, 100] = (0, 0, 255)
    patch, (ox, oy) = lens_patch(img, 100, 50, 8)
    assert patch.shape == ((LENS_H // 8) * 8, (LENS_W // 8) * 8, 3)
    cx, cy = (100 - ox) * 8, (50 - oy) * 8
    assert tuple(patch[cy + 3, cx + 3]) == (0, 0, 255)  # el pixel quedo ampliado 8x8
    assert tuple(patch[cy + 3, cx + 11]) == (0, 0, 0)


def test_lens_patch_en_el_borde_rellena_sin_correrse():
    img = np.full((50, 50, 3), 200, dtype=np.uint8)
    patch, (ox, oy) = lens_patch(img, 0, 0, 8)
    assert ox < 0 and oy < 0                     # el centro sigue siendo el cursor
    assert tuple(patch[0, 0]) == (0, 0, 0)       # fuera del fotograma: negro
    assert tuple(patch[-oy * 8 + 2, -ox * 8 + 2]) == (200, 200, 200)
    lens_patch(img, 500, 500, 4)                 # totalmente afuera: no falla


def test_lens_corner_se_aparta_del_cursor():
    size = (LENS_W, LENS_H)
    assert lens_corner((600, 400), size, 1100) == (8, 8)
    izq = lens_corner((50, 50), size, 1100)
    assert izq[0] > 500                          # cursor cerca de la esquina: pasa a la derecha


def test_acciones_de_zoom():
    s = UIState()
    assert s.zoom == 8
    assert apply_action(s, "zoom+").zoom == 12
    assert apply_action(apply_action(s, "zoom+"), "zoom+").zoom == 16
    z = UIState(zoom=ZOOM_LEVELS[-1])
    assert apply_action(z, "zoom+").zoom == ZOOM_LEVELS[-1]
    assert apply_action(UIState(zoom=4), "zoom-").zoom == 4
    assert apply_key(s, ord("x")).zoom == 12 and apply_key(s, ord("z")).zoom == 4


def test_render_con_cursor_dibuja_la_lupa(library_sign):
    gray = render_display("-0.245")
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    st = _estado_signo()
    sc = fit_scale(img.shape)
    sin, _ = render(img, st, sc, "light_on_dark", None, None, False, library_sign, None)
    con, _ = render(img, st, sc, "light_on_dark", None, None, False, library_sign,
                    (int(60 * sc), int(50 * sc)))
    assert con.shape == sin.shape and (con != sin).any()
    # cursor fuera de la imagen: no hay lupa
    fuera, _ = render(img, st, sc, "light_on_dark", None, None, False, library_sign,
                      (con.shape[1] - 5, 10))
    assert (fuera == sin).all()
