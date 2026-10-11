"""``ui_common``: botones, layout base, colores y helpers de dibujo, sin abrir ventanas.

Cada test dice en su docstring que cambio en ``src/`` lo haria fallar.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from spectro import calib_ui, teach_ui, ui_common
from spectro.config import DigitsConfig
from spectro.ui_common import (
    BAD_SCORE_C,
    BG,
    BTN,
    BTN_ON,
    FG,
    GOOD_SCORE_C,
    GREEN,
    ORANGE,
    PANEL_W,
    YELLOW,
    BaseLayout,
    Button,
    draw_button,
    draw_char,
    draw_text,
    draw_titles,
    hit_test,
    open_window,
    panel_geometry,
    score_color,
    slot_color,
    window_closed,
)


def canvas(w=400, h=200):
    return np.full((h, w, 3), BG, np.uint8)


# ==========================================================================
# Button
# ==========================================================================
def test_button_contains_incluye_el_borde_superior_izquierdo_y_excluye_el_inferior_derecho():
    """Rompe: cambiar ``<`` por ``<=`` en ``contains`` (botones contiguos se solaparian)."""
    b = Button("a", 10, 20, 30, 40, "A")
    assert b.contains(10, 20) and b.contains(39, 59)
    assert not b.contains(40, 59) and not b.contains(39, 60)
    assert not b.contains(9, 20) and not b.contains(10, 19)


def test_button_center_es_el_medio_y_cae_dentro():
    """Rompe: ``center`` con el ancho y el alto cruzados, o sin la mitad."""
    b = Button("a", 10, 20, 31, 41, "A")
    assert b.center == (25, 40) and b.contains(*b.center)
    assert Button("b", 0, 0, 1, 1, "").center == (0, 0)


def test_button_es_inmutable():
    """Rompe: sacar ``frozen=True`` (los layouts se comparten entre cuadros)."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        Button("a", 0, 0, 1, 1, "A").x = 5


# ==========================================================================
# BaseLayout / hit_test / panel_geometry
# ==========================================================================
def _layout():
    return BaseLayout(x0=100, height=300, buttons=[
        Button("uno", 110, 10, 50, 20, "1"), Button("dos", 170, 10, 50, 20, "2"),
    ])


def test_hit_test_devuelve_la_accion_del_boton_bajo_el_punto():
    """Rompe: ``hit_test`` que devuelva siempre el primer boton o el ultimo."""
    lay = _layout()
    assert hit_test(lay, 120, 15) == "uno" and hit_test(lay, 175, 15) == "dos"
    assert hit_test(lay, *lay.buttons[1].center) == "dos"


def test_hit_test_fuera_de_todo_devuelve_none():
    """Rompe: devolver una accion por defecto fuera de los botones."""
    lay = _layout()
    assert hit_test(lay, 0, 0) is None and hit_test(lay, 165, 15) is None  # el hueco entre botones
    assert hit_test(BaseLayout(0, 10, []), 1, 1) is None


def test_hit_test_con_botones_solapados_gana_el_primero():
    """Rompe: recorrer los botones en orden inverso."""
    lay = BaseLayout(0, 10, [Button("a", 0, 0, 10, 10, ""), Button("b", 5, 5, 10, 10, "")])
    assert hit_test(lay, 6, 6) == "a"


def test_base_layout_titles_es_opcional_y_solo_por_nombre():
    """Rompe: volver ``titles`` posicional (las subclases con campos obligatorios no podrian heredarlo)."""
    assert _layout().titles == {}
    assert BaseLayout(0, 1, [], titles={"X": 3}).titles == {"X": 3}
    with pytest.raises(TypeError):
        BaseLayout(0, 1, [], {"X": 3})  # type: ignore[misc]


def test_los_titles_por_defecto_no_se_comparten_entre_layouts():
    """Rompe: ``titles`` con un dict mutable compartido en vez de ``default_factory``."""
    a, b = _layout(), _layout()
    a.titles["X"] = 1
    assert b.titles == {}


def test_panel_geometry():
    """Rompe: el margen de 10 px o el ancho util (``PANEL_W - 20``)."""
    assert panel_geometry(700) == (710, PANEL_W - 20)
    assert panel_geometry(0) == (10, 340)


# ==========================================================================
# colores
# ==========================================================================
def digits(sign=0, seps=(2,)):
    return DigitsConfig(n_digits=6, separator_slots=list(seps), decimal_after=1,
                        polarity="light_on_dark", sign_slot=sign)


def test_slot_color_el_signo_es_verde():
    """Rompe: no distinguir el slot del signo."""
    assert slot_color(0, digits()) == GREEN


def test_slot_color_el_signo_gana_al_separador():
    """Rompe: preguntar por el separador antes que por el signo."""
    assert slot_color(0, digits(sign=0, seps=(0,)), with_separators=True) == GREEN


def test_slot_color_separador_solo_con_separadores_activados():
    """Rompe: pintar el separador sin ``with_separators`` (la ventana de calibracion no los marca)."""
    d = digits()
    assert slot_color(2, d, with_separators=True) == ORANGE
    assert slot_color(2, d) == YELLOW and slot_color(2, d, False) == YELLOW


def test_slot_color_el_resto_es_amarillo():
    """Rompe: un color distinto para los digitos."""
    d = digits()
    assert {slot_color(i, d, True) for i in (1, 3, 4, 5)} == {YELLOW}


def test_slot_color_sin_celda_de_signo_ni_separadores():
    """Rompe: comparar ``i == None``/iterar ``None`` (``sign_slot=None``, ``separator_slots=None``)."""
    d = digits(sign=None)
    d.separator_slots = None
    assert slot_color(0, d, True) == YELLOW


def test_score_color():
    """Rompe: invertir verde/rojo."""
    assert score_color(True) == GOOD_SCORE_C and score_color(False) == BAD_SCORE_C
    assert GOOD_SCORE_C != BAD_SCORE_C


# ==========================================================================
# dibujo (sobre un canvas numpy)
# ==========================================================================
def test_draw_text_cambia_pixeles_y_respeta_el_color():
    """Rompe: ``draw_text`` que no dibuje o que ignore ``color``."""
    c = canvas()
    draw_text(c, "Hola", 10, 50)
    assert (c != np.array(BG)).any()
    c2 = canvas()
    draw_text(c2, "Hola", 10, 50, color=(0, 0, 255))
    assert not np.array_equal(c, c2)


def test_draw_text_bold_pinta_mas_pixeles():
    """Rompe: ``bold`` que no cambie el grosor."""
    a, b = canvas(), canvas()
    draw_text(a, "Hola", 10, 50)
    draw_text(b, "Hola", 10, 50, bold=True)
    assert (b != np.array(BG)).any(axis=2).sum() > (a != np.array(BG)).any(axis=2).sum()


def test_draw_text_fuera_del_canvas_no_rompe():
    """Rompe: indexar a mano en vez de dejar que OpenCV recorte."""
    draw_text(canvas(), "Hola", 10_000, 10_000)
    draw_text(canvas(), "Hola", -50, -50)


def test_draw_button_rellena_el_rectangulo_con_el_color_de_reposo():
    """Rompe: ``draw_button`` que no rellene o que use ``BTN_ON`` en reposo."""
    c = canvas()
    b = Button("a", 20, 20, 100, 30, "Ok")
    draw_button(c, b)
    assert tuple(c[25, 25]) == BTN and tuple(c[5, 5]) == BG
    assert (c[20:51, 20:121] != np.array(BTN)).any()  # borde y rotulo


def test_draw_button_activo_y_con_color_propio():
    """Rompe: ignorar ``active`` o ``color`` (``active`` gana sobre ``color``)."""
    b = Button("a", 20, 20, 100, 30, "Ok")
    on, rojo, ambos = canvas(), canvas(), canvas()
    draw_button(on, b, active=True)
    draw_button(rojo, b, color=(0, 0, 200))
    draw_button(ambos, b, active=True, color=(0, 0, 200))
    assert tuple(on[25, 25]) == BTN_ON and tuple(rojo[25, 25]) == (0, 0, 200)
    assert np.array_equal(on, ambos)


def test_draw_button_sin_rotulo_no_rompe():
    """Rompe: ``getTextSize`` sobre texto vacio sin guarda."""
    draw_button(canvas(), Button("a", 5, 5, 40, 20, ""))


def test_draw_button_centra_el_rotulo():
    """Rompe: dibujar el rotulo en la esquina del boton."""
    c = canvas(300, 100)
    b = Button("a", 50, 20, 200, 50, "I")
    draw_button(c, b, active=True)
    zona = c[21:70, 51:249]
    ys, xs = np.where((zona != np.array(BTN_ON)).any(axis=2) & (zona.sum(axis=2) < 50))  # tinta negra
    assert len(xs) and abs(xs.mean() + 51 - (b.x + b.w / 2)) < 12


def test_draw_titles_dibuja_texto_y_linea_para_cada_titulo():
    """Rompe: no dibujar la linea separadora o ignorar la posicion ``ty``."""
    lay = BaseLayout(x0=0, height=200, buttons=[], titles={"UNO": 10, "DOS": 80})
    c = canvas()
    draw_titles(c, lay)
    px, inner = panel_geometry(0)
    assert tuple(c[10 + 20, px + 5]) == (90, 90, 90) and tuple(c[80 + 20, px + inner - 1]) == (90, 90, 90)
    assert (c[10:30] != np.array(BG)).any() and (c[80:100] != np.array(BG)).any()
    assert tuple(c[50, px + 5]) == BG  # entre un titulo y otro no hay nada


def test_draw_titles_sin_titulos_no_toca_el_canvas():
    """Rompe: dibujar algo cuando ``titles`` esta vacio."""
    c = canvas()
    antes = c.copy()
    draw_titles(c, BaseLayout(0, 100, []))
    assert np.array_equal(c, antes)


def test_draw_char_dibuja_y_el_espacio_se_ve_como_guion_bajo():
    """Rompe: dibujar el espacio como espacio (la celda del signo vacia no se veria)."""
    sp, gb, vacio = canvas(), canvas(), canvas()
    draw_char(sp, " ", 20, 60, 0.7)
    draw_text(gb, "_", 20, 60, 0.7, FG, False)
    assert np.array_equal(sp, gb) and not np.array_equal(sp, vacio)
    uno = canvas()
    draw_char(uno, "1", 20, 60, 0.7)
    assert not np.array_equal(uno, sp)


def test_draw_char_respeta_color_y_bold():
    """Rompe: perder ``color`` o ``bold`` al delegar en ``draw_text``."""
    a, b, c = canvas(), canvas(), canvas()
    draw_char(a, "5", 20, 60, 0.7, FG)
    draw_char(b, "5", 20, 60, 0.7, (0, 0, 255))
    draw_char(c, "5", 20, 60, 0.7, FG, True)
    assert not np.array_equal(a, b) and not np.array_equal(a, c)


# ==========================================================================
# ventana (con OpenCV espiado: nunca se abre una)
# ==========================================================================
def test_open_window_crea_la_ventana_y_engancha_el_mouse(monkeypatch):
    """Rompe: no registrar el callback del mouse."""
    llamadas = []
    monkeypatch.setattr(ui_common.cv2, "namedWindow", lambda *a: llamadas.append(("win", a)))
    monkeypatch.setattr(ui_common.cv2, "setMouseCallback", lambda *a: llamadas.append(("mouse", a)))
    cb = object()
    open_window("titulo", cb)
    assert llamadas == [("win", ("titulo", ui_common.cv2.WINDOW_AUTOSIZE)), ("mouse", ("titulo", cb))]


@pytest.mark.parametrize("visible, cerrada", [(1.0, False), (0.0, True), (-1.0, True)])
def test_window_closed_segun_la_propiedad_visible(monkeypatch, visible, cerrada):
    """Rompe: invertir la comparacion ``< 1``."""
    monkeypatch.setattr(ui_common.cv2, "getWindowProperty", lambda t, p: visible)
    assert window_closed("titulo") is cerrada


def test_constantes_de_teclas_y_panel():
    """Rompe: cambiar los codigos de ENTER/ESC que las dos UI comparten."""
    assert (ui_common.KEY_ENTER, ui_common.KEY_ESC) == (13, 27) and PANEL_W == 360


# ==========================================================================
# las UI usan la base comun
# ==========================================================================
def test_los_layouts_de_las_ui_heredan_de_base_layout():
    """Rompe: que ``Layout``/``TLayout`` dejen de heredar de ``BaseLayout``."""
    assert issubclass(calib_ui.Layout, BaseLayout) and issubclass(teach_ui.TLayout, BaseLayout)


def test_layout_de_calibracion_es_un_base_layout_con_titulos_y_hit_test():
    """Rompe: que ``layout_panel`` no llene ``titles`` o que ``hit_test`` no sirva con el layout derivado."""
    lay = calib_ui.layout_panel(700, 800)
    assert isinstance(lay, BaseLayout) and lay.x0 == 700 and lay.height == 800
    assert lay.titles and lay.buttons
    for b in lay.buttons:
        assert hit_test(lay, *b.center) == b.action


def test_layout_de_teach_es_un_base_layout_en_los_dos_modos():
    """Rompe: que ``layout_teach`` no llene ``titles`` en algun modo."""
    for modo in ("muestras", "biblioteca"):
        lay = teach_ui.layout_teach(mode=modo, n_tiles=5, sel_label="3")
        assert isinstance(lay, BaseLayout) and lay.titles and lay.buttons
        for b in lay.buttons:
            assert hit_test(lay, *b.center) == b.action


def test_los_layouts_derivados_agregan_sus_campos_obligatorios():
    """Rompe: perder ``kw_only`` en ``titles`` (los campos obligatorios de la subclase irian despues de uno con default)."""
    nombres = {f.name for f in dataclasses.fields(calib_ui.Layout)}
    assert {"x0", "height", "buttons", "titles", "slider", "zoom", "chars_y"} <= nombres
    assert {"field", "chips_y", "result_y"} <= {f.name for f in dataclasses.fields(teach_ui.TLayout)}


def test_las_dos_ui_comparten_las_mismas_funciones_de_ui_common():
    """Rompe: volver a copiar ``Button``/``hit_test`` en una de las UI."""
    assert calib_ui.Button is ui_common.Button is teach_ui.Button
    assert calib_ui.hit_test is ui_common.hit_test is teach_ui.hit_test
    assert calib_ui.slot_color is ui_common.slot_color is teach_ui.slot_color


def test_draw_titles_sobre_los_layouts_reales_no_rompe():
    """Rompe: que ``draw_titles`` use un campo que solo tenga una de las subclases."""
    c = np.zeros((900, 1100, 3), np.uint8)
    draw_titles(c, calib_ui.layout_panel(700, 800))
    draw_titles(c, teach_ui.layout_teach(mode="library", n_tiles=3, sel_label="1"))
    assert c.any()
