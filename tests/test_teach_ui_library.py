"""UI de ``teach``, modo biblioteca y botones nuevos: sin abrir ventanas."""

from __future__ import annotations

import cv2

from spectro import library, teach as T
from spectro.calib_ui import hit_test
from spectro.library import template_path
from spectro.teach_session import PER_PAGE, TeachState, apply_action
from spectro.teach_ui import (
    HEIGHT,
    PANEL_W,
    VIEW_W,
    TeachView,
    layout_teach,
    render_teach,
    tile_rect,
)


def test_reemplazar_pide_confirmacion_de_dos_pasos():
    s = apply_action(TeachState(), "replace", 3)
    assert s.confirm == "replace" and s.request == ""
    s2 = apply_action(s, "replace", 3)
    assert s2.request == "replace" and s2.confirm == ""


def test_otra_accion_cancela_la_confirmacion():
    s = apply_action(TeachState(), "replace", 3)
    assert apply_action(s, "next", 3).confirm == ""
    assert apply_action(s, "color", 3).confirm == ""


def test_borrar_necesita_biblioteca_y_confirmacion():
    s = TeachState(mode="library")
    assert apply_action(s, "del_one", 3, n_lib=0) == s  # nada que borrar
    armado = apply_action(s, "del_one", 3, n_lib=5)
    assert armado.confirm == "del_one" and armado.request == ""
    assert apply_action(armado, "del_one", 3, n_lib=5).request == "del_one"
    otro = apply_action(armado, "del_label", 3, n_lib=5)  # confirmar otra no ejecuta la anterior
    assert otro.confirm == "del_label" and otro.request == ""


def test_alternar_modo_paginas_y_seleccion():
    s = apply_action(TeachState(), "lib", 3)
    assert s.mode == "library" and s.request == "refresh_lib"
    assert apply_action(s, "samples", 3).mode == "samples"
    n = PER_PAGE * 2 + 3
    p = apply_action(s, "page+", 3, n_lib=n)
    assert p.page == 1
    p2 = apply_action(apply_action(p, "page+", 3, n_lib=n), "page+", 3, n_lib=n)
    assert p2.page == 2  # tope en la ultima pagina
    assert apply_action(p, "page-", 3, n_lib=n).page == 0
    assert apply_action(s, "page-", 3, n_lib=n).page == 0
    assert apply_action(p, "tile:2", 3, n_lib=n).sel == PER_PAGE + 2
    assert apply_action(s, "tile:50", 3, n_lib=5) == s  # mas alla de lo que hay
    assert apply_action(s, "relabel:7", 3, n_lib=5).request == "relabel:7"
    vacio = TeachState(mode="library")
    assert apply_action(vacio, "relabel:7", 3, n_lib=0).request == ""


def test_layout_biblioteca_sin_solapamientos():
    lay = layout_teach(mode="library", n_tiles=PER_PAGE, sel_label="7")
    for b in lay.buttons:
        assert hit_test(lay, *b.center) == b.action
        assert b.x + b.w <= VIEW_W + PANEL_W and b.y + b.h <= HEIGHT
    for i, a in enumerate(lay.buttons):
        for b in lay.buttons[i + 1:]:
            assert not (a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h)
    acciones = {b.action for b in lay.buttons}
    assert {f"relabel:{c}" for c in "0123456789.-"} <= acciones
    assert {"del_one", "del_label", "undo", "samples", "page+", "page-"} <= acciones
    x, y, _, _ = tile_rect(3)
    assert hit_test(lay, x + 5, y + 5) == "tile:3"
    assert "7" in next(b.label for b in lay.buttons if b.action == "del_label")


def test_layout_muestras_tiene_los_botones_de_biblioteca():
    lay = layout_teach(confirm="replace", lib_size=19)
    acciones = {b.action for b in lay.buttons}
    assert {"add_lib", "replace", "validate", "lib"} <= acciones
    assert "19" in next(b.label for b in lay.buttons if b.action == "replace")


def test_render_biblioteca_smoke(cfg_sign, library_sign, tmp_path):
    for t in library_sign:
        cv2.imwrite(str(template_path(t.label, 0, tmp_path)), t.image)
    entries = library.list_entries(tmp_path)
    entries[0].errors = 2
    entries[1].uses = 3
    names = ["t_0000001.000.jpg"]
    estados = (
        TeachState(mode="library"),
        TeachState(mode="library", sel=2, confirm="del_one"),
        TeachState(mode="library", page=3),
    )
    for state in estados:
        view = TeachView(state, cfg_sign, names, None, None, (0, 0), [], None, len(entries),
                         ["biblioteca vigente: 1/1 lecturas exactas"], entries, True)
        canvas, _ = render_teach(view)
        assert canvas.shape == (HEIGHT, VIEW_W + PANEL_W, 3)
    vacia = TeachView(TeachState(mode="library"), cfg_sign, names, None, None, (0, 0), [], None, 0)
    render_teach(vacia)
