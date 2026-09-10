"""Un glifo ambiguo debe caer por debajo del umbral, no adivinar.

Es la propiedad central del enfoque: preferimos un hueco en la serie antes que
un valor inventado.
"""

import numpy as np
import pytest

from conftest import render_display
from spectro.read import Reading, flag_spikes, read_frame


def test_glifo_de_ruido_no_se_lee(cfg, library):
    """Ruido en el ultimo slot: la lectura entera se descarta."""
    rng = np.random.default_rng(0)
    frame = render_display("0.245")
    x0 = cfg.roi.x + 4 * (cfg.roi.w // 5)
    frame[cfg.roi.y : cfg.roi.y + cfg.roi.h, x0 : cfg.roi.x + cfg.roi.w] = rng.integers(
        0, 255, size=(cfg.roi.h, cfg.roi.x + cfg.roi.w - x0), dtype=np.uint8
    )
    reading = read_frame(frame, cfg, library)
    assert reading.estado == "low_confidence"
    assert reading.valor is None


def test_slot_vacio_no_se_lee(cfg, library):
    """Un digito a medio refrescar deja el slot casi vacio: no se inventa nada."""
    frame = render_display("0.245")
    x0 = cfg.roi.x + 4 * (cfg.roi.w // 5)
    frame[cfg.roi.y : cfg.roi.y + cfg.roi.h, x0 : cfg.roi.x + cfg.roi.w] = 30
    assert read_frame(frame, cfg, library).valor is None


def test_separador_desalineado_descarta(cfg, library):
    """Si el slot del punto no matchea un punto, la ROI se corrio: no se lee."""
    frame = render_display("02455")  # sin punto: el slot 1 trae un digito
    reading = read_frame(frame, cfg, library)
    assert reading.estado == "low_confidence"


def test_margen_exigente_descarta_todo(cfg, library):
    """Con un margen inalcanzable, ni un glifo perfecto se acepta."""
    cfg.templates.min_margin = 0.99
    assert read_frame(render_display("0.245"), cfg, library).valor is None


def test_umbral_de_score_inalcanzable_descarta_todo(cfg, library):
    cfg.templates.min_score = 1.001
    assert read_frame(render_display("0.245"), cfg, library).valor is None


def test_spike_aislado_se_marca():
    base = [Reading(archivo=f"f{i}", t_s=float(i), indice=i, valor=0.500) for i in range(5)]
    base[2].valor = 0.900  # un digito mal leido
    assert flag_spikes(base, max_rate=0.1) == 1
    assert base[2].estado == "spike"
    assert [r.estado for r in base if r is not base[2]] == ["ok"] * 4


def test_escalon_real_no_se_marca():
    """Una transicion real del experimento se sostiene en el tiempo: no es spike."""
    valores = [0.5, 0.5, 0.9, 0.9, 0.9]
    rows = [
        Reading(archivo=f"f{i}", t_s=float(i), indice=i, valor=v)
        for i, v in enumerate(valores)
    ]
    assert flag_spikes(rows, max_rate=0.1) == 0


def test_confianza_es_el_minimo_de_los_slots(cfg, library):
    reading = read_frame(render_display("0.245"), cfg, library)
    assert reading.confianza == pytest.approx(min(reading.scores))
