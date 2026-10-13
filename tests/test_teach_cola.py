"""Contador de la cola de ``teach``: cuantos fotogramas de la cola tienen muestra."""

from __future__ import annotations

import cv2

from conftest import render_display
from test_teach_session import _ir_a, _sesion
from spectro import teach as T
from spectro import teach_ui
from spectro.ui_common import PANEL_W
from spectro.teach_session import TeachState, labeled_in_queue
from spectro.teach_ui import HEIGHT, VIEW_W, TeachView, render_teach


def _m(*files):
    return [T.Sample(f, "-0.245") for f in files]


def test_cola_vacia_da_cero():
    """Rompe: dividir/indexar sobre una cola vacia."""
    assert labeled_in_queue([], _m("a"), _m("b")) == 0


def test_sin_muestras_da_cero():
    """Rompe: devolver len(names)."""
    assert labeled_in_queue(["a", "b"], [], []) == 0


def test_fotograma_solo_en_entrenamiento_cuenta_uno():
    """Rompe: ignorar ``samples``."""
    assert labeled_in_queue(["a", "b"], _m("a"), []) == 1


def test_fotograma_solo_en_prueba_cuenta_uno():
    """Rompe: contar solo ``samples`` (olvidar ``test``)."""
    assert labeled_in_queue(["a", "b"], [], _m("b")) == 1


def test_fotograma_en_ambos_conjuntos_cuenta_una_sola_vez():
    """Rompe: sumar ``samples`` y ``test`` por separado (doble conteo)."""
    assert labeled_in_queue(["a", "b"], _m("a"), _m("a")) == 1


def test_muestras_fuera_de_la_cola_no_cuentan():
    """Rompe: usar len(samples)+len(test) en vez de la interseccion con names."""
    assert labeled_in_queue(["a"], _m("x", "y", "a"), _m("z")) == 1
    assert labeled_in_queue(["a"], _m("x"), _m("z")) == 0


def test_nombre_repetido_en_la_cola_se_cuenta_por_posicion():
    """Fija la conducta actual: cuenta fotogramas de la cola, no nombres unicos."""
    assert labeled_in_queue(["a", "a", "b"], _m("a"), []) == 2


def test_descartar_baja_el_conteo_y_la_cola_sin_repuesto(tmp_path):
    """Rompe: que ``_discard`` deje la muestra, o que sin ``refill`` no saque el nombre de la cola."""
    s = _sesion(tmp_path, n_train=3, n_test=2)
    n = len(s.names)
    antes = labeled_in_queue(s.names, s.samples, s.test)
    assert antes == 5
    _ir_a(s, 1)
    s.act("discard")
    assert labeled_in_queue(s.names, s.samples, s.test) == antes - 1
    assert len(s.names) == n - 1


def _textos_dibujados(monkeypatch):
    vistos = []
    original = teach_ui.draw_text

    def espia(canvas, txt, x, y, *a, **k):
        vistos.append((txt, x, y, a))
        return original(canvas, txt, x, y, *a, **k)

    monkeypatch.setattr(teach_ui, "draw_text", espia)
    return vistos


def _vista(cfg_sign, n=20, con=16, index=3):
    gray = render_display("-0.245")
    color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    names = [f"t_{i:07d}.000.jpg" for i in range(n)]
    samples = _m(*names[:con])
    return TeachView(TeachState(index=index), cfg_sign, names, gray, color, (0, 0), samples)


def test_render_muestra_ambos_numeros_del_contador(cfg_sign, monkeypatch):
    """Rompe: volver a mostrar solo ``i/N`` o pasar otro K al texto."""
    vistos = _textos_dibujados(monkeypatch)
    canvas, _ = render_teach(_vista(cfg_sign))
    assert canvas.shape == (HEIGHT, VIEW_W + PANEL_W, 3)
    linea = [t for t in vistos if "en cola" in t[0]]
    assert len(linea) == 1
    assert linea[0][0].startswith("4/20 en cola") and "16 con muestra" in linea[0][0]


def test_contador_y_estado_no_comparten_linea(cfg_sign, monkeypatch):
    """Rompe: dibujar el estado en la misma y que el contador."""
    vistos = _textos_dibujados(monkeypatch)
    render_teach(_vista(cfg_sign))
    y_cont = [y for t, x, y, a in vistos if "en cola" in t][0]
    y_est = [y for t, x, y, a in vistos if t in ("CON muestra (entrenamiento)", "sin muestra")][0]
    assert y_cont != y_est


def test_contador_cabe_en_el_ancho_del_panel(cfg_sign, monkeypatch):
    """Rompe: texto del contador mas ancho que el panel (peor caso: 4 digitos y t grande)."""
    vistos = _textos_dibujados(monkeypatch)
    view = _vista(cfg_sign, n=9999, con=9999, index=9998)
    view.names[9998] = "t_0099999.000.jpg"
    render_teach(view)
    txt, x, y, a = [t for t in vistos if "en cola" in t[0]][0]
    escala = a[0]
    ancho = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)[0][0]
    assert x + ancho <= VIEW_W + PANEL_W, f"{txt!r} mide {ancho}px desde x={x}"


def test_render_con_cola_vacia_no_falla(cfg_sign):
    """Rompe: indexar names vacio al armar el contador."""
    canvas, _ = render_teach(TeachView(TeachState(), cfg_sign, [], None, None, (0, 0), []))
    assert canvas.shape[0] == HEIGHT
