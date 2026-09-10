"""Fotogramas sinteticos oscuro / borroso / ocluido -> el estado esperado."""

import numpy as np
import pytest

from conftest import render_display
from spectro.config import QCConfig
from spectro.imaging import estimate_shift
from spectro.qc import QCRow, classify, measure, suggest_thresholds


def fila(cfg, frame, qc: QCConfig | None = None) -> QCRow:
    row = QCRow(archivo="t_0000000.000.jpg", t_s=0.0, indice=1)
    for k, v in measure(frame, cfg).items():
        setattr(row, k, v)
    row.estado = classify(row, qc or QCConfig())
    return row


def test_fotograma_bueno_pasa(cfg):
    assert fila(cfg, render_display("0.245")).estado == "ok"


def test_fotograma_oscuro(cfg):
    oscuro = (render_display("0.245") * 0.1).astype(np.uint8)
    assert fila(cfg, oscuro).estado == "dark"


def test_fotograma_quemado(cfg):
    quemado = np.full_like(render_display("0.245"), 252)
    assert fila(cfg, quemado).estado in ("blown", "low_contrast")


def test_fotograma_borroso(cfg):
    borroso = render_display("0.245", blur=31)
    qc = QCConfig(min_blur_var=200.0)
    assert fila(cfg, borroso, qc).estado == "blur"


def test_pantalla_vacia(cfg):
    vacio = np.full_like(render_display("0.245"), 30)
    assert fila(cfg, vacio).estado in ("blank", "low_contrast")


def test_ocluido(cfg):
    """Una mano delante deja la ROI casi toda "tinta"."""
    ocluido = render_display("0.245")
    ocluido[:, :] = 30
    ocluido[cfg.roi.y : cfg.roi.y + cfg.roi.h, cfg.roi.x : cfg.roi.x + cfg.roi.w] = 240
    assert fila(cfg, ocluido).estado in ("occluded", "blown", "low_contrast")


def test_metricas_se_calculan_sobre_la_roi(cfg):
    """Oscurecer todo *menos* la ROI no debe cambiar las metricas."""
    limpio = render_display("0.245")
    con_penumbra = limpio.copy()
    con_penumbra[100:, :] = 0
    assert measure(limpio, cfg)["mean_luma"] == pytest.approx(
        measure(con_penumbra, cfg)["mean_luma"]
    )


def test_umbrales_auto_no_rechazan_la_poblacion_normal(cfg):
    rows = []
    for i in range(30):
        row = QCRow(archivo=f"f{i}", t_s=float(i), indice=i)
        for k, v in measure(render_display("0.245", brightness=190 + i % 10), cfg).items():
            setattr(row, k, v)
        rows.append(row)
    qc = suggest_thresholds(rows, QCConfig())
    assert all(classify(r, qc) == "ok" for r in rows)


def test_registro_mide_el_corrimiento(cfg):
    frame = render_display("0.245")
    corrido = np.roll(np.roll(frame, 3, axis=0), 2, axis=1)
    dx, dy, score = estimate_shift(cfg.qc.anchor.crop(frame), corrido, cfg.qc.anchor, margin=20)
    assert (dx, dy) == (2, 3)
    assert score > 0.9


def test_corrimiento_excesivo_es_camera_moved(cfg):
    row = QCRow(archivo="f", t_s=0.0, indice=1, mean_luma=100, contraste=100,
                blur_var=1000, ink_fraction=0.2, anchor_ncc=1.0, dx=0, dy=99)
    assert classify(row, QCConfig(max_shift_px=40)) == "camera_moved"
