"""Decodificacion: recortes de digitos conocidos -> el digito correcto via NCC."""

import pytest

from conftest import render_display
from spectro.imaging import binarize, normalize_glyph, slot_boxes
from spectro.read import match_slot, read_frame


@pytest.mark.parametrize("texto", ["0.245", "1.789", "3.056"])
def test_lee_el_numero_completo(cfg, library, texto):
    reading = read_frame(render_display(texto), cfg, library)
    assert reading.estado == "ok"
    assert reading.valor == pytest.approx(float(texto))


def test_cada_slot_matchea_su_caracter(cfg, library):
    img = render_display("0.245")
    roi = cfg.roi.crop(img)
    binary = binarize(roi, cfg.digits.polarity)
    for i, (x0, x1) in enumerate(slot_boxes(roi.shape[1], cfg.digits)):
        glyph = normalize_glyph(binary[:, x0:x1], cfg.templates.size)
        label, score, margin = match_slot(glyph, library)
        assert label == "0.245"[i]
        assert score > cfg.templates.min_score


def test_el_punto_no_aporta_digito(cfg, library):
    """El valor sale del punto decimal fijo, no del glifo leido."""
    reading = read_frame(render_display("0.245"), cfg, library)
    assert reading.caracteres == "0.245"
    assert reading.valor == pytest.approx(0.245)


def test_brillo_distinto_sigue_leyendo_igual(cfg, library):
    """La binarizacion normaliza el contraste: el brillo absoluto no debe importar."""
    tenue = read_frame(render_display("0.245", brightness=110), cfg, library)
    fuerte = read_frame(render_display("0.245", brightness=255), cfg, library)
    assert tenue.valor == fuerte.valor == pytest.approx(0.245)


def test_registro_compensa_el_corrimiento(cfg, library):
    """Con la escena corrida, la ROI se mueve con ella y la lectura no cambia."""
    import numpy as np

    img = render_display("0.245")
    corrido = np.roll(np.roll(img, 3, axis=0), 2, axis=1)
    sin_offset = read_frame(corrido, cfg, library)
    con_offset = read_frame(corrido, cfg, library, offset=(2, 3))
    assert con_offset.valor == pytest.approx(0.245)
    assert con_offset.confianza > sin_offset.confianza
