"""UI de ``teach``: conjunto activo (entrenamiento / prueba), evaluar y cola con motivos."""

from __future__ import annotations

import cv2

from spectro import teach as T
from spectro.calib_ui import hit_test
from spectro.read import read_frame
from spectro.teach_ui import (
    HEIGHT,
    PANEL_W,
    VIEW_W,
    TeachState,
    TeachView,
    add_to_set,
    apply_action,
    layout_teach,
    render_teach,
)
from conftest import render_display


def test_alternar_conjunto_y_pedir_evaluacion():
    s = TeachState()
    assert s.target == "train"
    t = apply_action(s, "target", 5)
    assert t.target == "test" and apply_action(t, "target", 5).target == "train"
    assert apply_action(s, "eval", 5).request == "eval"


def test_botones_de_conjunto_y_evaluar_en_el_panel():
    lay = layout_teach(target="test")
    acciones = {b.action: b for b in lay.buttons}
    assert "Prueba" in acciones["target"].label and acciones["eval"].label == "Evaluar prueba"
    assert "Entrenam" in next(b.label for b in layout_teach().buttons if b.action == "target")
    for b in lay.buttons:
        assert hit_test(lay, *b.center) == b.action
        assert b.x + b.w <= VIEW_W + PANEL_W and b.y + b.h <= HEIGHT
    for i, a in enumerate(lay.buttons):
        for b in lay.buttons[i + 1:]:
            assert not (a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h)


def test_add_to_set_mantiene_un_solo_conjunto(cfg_sign):
    d = cfg_sign.digits
    train, test, msg = add_to_set([], [], "t_0000001.000.jpg", "-0.245", d, "train")
    assert msg == "muestra agregada" and len(train) == 1 and test == []
    train, test, msg = add_to_set(train, test, "t_0000050.000.jpg", "0.100", d, "test")
    assert msg == "muestra de prueba agregada" and len(train) == 1 and len(test) == 1
    # mover una de entrenamiento a prueba avisa que ya aporto glifos
    train, test, msg = add_to_set(train, test, "t_0000001.000.jpg", "-0.245", d, "test")
    assert "ya habia aportado" in msg and train == [] and len(test) == 2
    # y a la inversa
    train, test, _ = add_to_set(train, test, "t_0000050.000.jpg", "0.100", d, "train")
    assert [s.archivo for s in train] == ["t_0000050.000.jpg"] and len(test) == 1


def test_add_to_set_rechaza_un_formato_invalido(cfg_sign):
    train, test, msg = add_to_set([], [], "t_0000001.000.jpg", "12.5", cfg_sign.digits, "test")
    assert train == [] and test == [] and "formato" in msg


def test_render_con_prueba_cola_y_resultado(cfg_sign, library_sign):
    gray = render_display("-0.245")
    color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    reading = read_frame(gray, cfg_sign, library_sign)
    names = ["t_0000001.000.jpg", "t_0000050.000.jpg"]
    train = [T.Sample(names[0], "-0.245")]
    test = [T.Sample(names[1], "0.100")]
    motivos = {names[0]: "incierta u=-0.12", names[1]: "azar"}
    resultado = ["prueba (otro video): 1 muestras, 1 valores", "1 correctas · 0 erroneas · 0 descartadas",
                 "exactitud 100% [21%-100%]  error aceptadas 0.0%"]
    for idx in (0, 1):
        for target in ("train", "test"):
            view = TeachView(TeachState(index=idx, text="-0.245", target=target), cfg_sign, names,
                             gray, color, (0, 0), train, reading, len(library_sign), resultado,
                             test=test, motivos=motivos)
            canvas, _ = render_teach(view)
            assert canvas.shape == (HEIGHT, VIEW_W + PANEL_W, 3)
