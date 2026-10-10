"""UI de ``teach``: estado, layout y render, sin abrir ventanas."""

from __future__ import annotations

import pytest

from conftest import render_display
from spectro import teach as T
from spectro.read import read_frame
from spectro.teach_ui import (
    HEIGHT,
    PANEL_W,
    VIEW_W,
    TeachState,
    TeachView,
    apply_action,
    go_to,
    layout_teach,
    remove_sample,
    render_teach,
)
from spectro.calib_ui import hit_test


def test_tipeo_y_borrado():
    s = TeachState()
    for ch in "-0.245":
        s = apply_action(s, f"key:{ch}", 10)
    assert s.text == "-0.245"
    assert apply_action(s, "back", 10).text == "-0.24"
    assert apply_action(s, "clear", 10).text == ""
    assert apply_action(s, "key:x", 10) == s  # solo 0-9 . -


def test_largo_maximo():
    s = TeachState(text="1" * 12)
    assert apply_action(s, "key:1", 10).text == "1" * 12


def test_navegacion_acotada():
    s = TeachState(index=3)
    assert apply_action(s, "next", 5).index == 4
    assert apply_action(s, "jump+10", 5).index == 4
    assert apply_action(s, "jump-10", 5).index == 0
    assert apply_action(TeachState(index=0), "prev", 5).index == 0


def test_go_to_precarga_el_valor_existente():
    names = ["a", "b", "c"]
    samples = [T.Sample("b", "-0.245")]
    assert go_to(TeachState(text="zzz"), samples, names, 1).text == "-0.245"
    assert go_to(TeachState(text="zzz"), samples, names, 2).text == ""
    assert go_to(TeachState(), samples, names, 99).index == 2


def test_toggles_y_pedidos():
    s = TeachState()
    assert apply_action(s, "color", 3).color
    assert apply_action(s, "add_lib", 3).request == "add_lib"
    assert apply_action(s, "validate", 3).request == "validate"
    assert apply_action(s, "save", 3).done


def test_remove_sample():
    samples = [T.Sample("a.jpg", "-0.245")]
    assert remove_sample(samples, "a.jpg") == []


def test_layout_botones():
    lay = layout_teach()
    for b in lay.buttons:
        assert hit_test(lay, *b.center) == b.action
        assert b.x >= VIEW_W and b.x + b.w <= VIEW_W + PANEL_W and b.y + b.h <= HEIGHT
    assert hit_test(lay, 100, 100) is None
    for i, a in enumerate(lay.buttons):
        for b in lay.buttons[i + 1:]:
            assert not (a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h)
    # teclado numerico completo
    acciones = {b.action for b in lay.buttons}
    assert {f"key:{c}" for c in "0123456789.-"} <= acciones


def test_render_smoke(cfg_sign, library_sign):
    gray = render_display("-0.245")
    import cv2

    color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    reading = read_frame(gray, cfg_sign, library_sign)
    names = ["t_0000001.000.jpg", "t_0000002.000.jpg"]
    samples = [T.Sample(names[0], "-0.245")]
    for text in ("-0.245", "0.245", "zz", ""):
        view = TeachView(TeachState(text=text), cfg_sign, names, gray, color, (0, 0), samples,
                         reading, len(library_sign), ["leave-one-out: 1/1 lecturas exactas"])
        canvas, lay = render_teach(view)
        assert canvas.shape == (HEIGHT, VIEW_W + PANEL_W, 3)
    # sin fotograma (ROI invalida) tampoco falla
    cfg_sign.roi.w = 0
    render_teach(TeachView(TeachState(), cfg_sign, names, None, None, (0, 0), []))
