"""Fixtures sinteticas: los tests no dependen del video ni de datos reales.

Se fabrica un "display" de mentira con la misma estructura que el del equipo
(numero monoespaciado, punto en su propia celda, texto claro sobre fondo
oscuro) para poder ejercitar el pipeline entero de forma determinista.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from spectro.config import ROI, Config, DigitsConfig

#: Geometria del display sintetico.
CELL_W, CELL_H = 26, 44
ROI_X, ROI_Y = 40, 30
FRAME_W, FRAME_H = 320, 140


def render_display(
    text: str = "0.245", brightness: int = 200, blur: int = 0, angle: float = 0.0
) -> np.ndarray:
    """Dibuja un fotograma sintetico con ``text`` en celdas monoespaciadas."""
    frame = np.full((FRAME_H, FRAME_W), 30, dtype=np.uint8)
    # Estructura fija fuera de la ROI: hace las veces de ancla de registro.
    cv2.putText(frame, "SPECTRO", (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 230, 2)
    cv2.rectangle(frame, (10, 100), (300, 130), 180, 2)
    for i, char in enumerate(text):
        x = ROI_X + i * CELL_W
        cv2.putText(
            frame,
            char,
            (x + 3, ROI_Y + CELL_H - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            brightness,
            2,
            cv2.LINE_AA,
        )
    if blur:
        frame = cv2.GaussianBlur(frame, (blur | 1, blur | 1), 0)
    if angle:
        from spectro.imaging import rotate

        frame = rotate(frame, angle)
    return frame


def make_config(n_digits: int = 5, sign: bool = False) -> Config:
    """Con ``sign`` el display tiene una celda de signo a la izquierda (6 celdas)."""
    cfg = Config.default()
    if sign:
        n_digits += 1
    cfg.roi = ROI(x=ROI_X, y=ROI_Y, w=CELL_W * n_digits, h=CELL_H)
    cfg.digits = DigitsConfig(
        n_digits=n_digits,
        separator_slots=[2 if sign else 1],
        decimal_after=1,
        polarity="light_on_dark",
        sign_slot=0 if sign else None,
    )
    cfg.qc.anchor = ROI(x=10, y=0, w=140, h=28)
    return cfg


@pytest.fixture
def cfg() -> Config:
    return make_config()


@pytest.fixture
def library(cfg, tmp_path):
    """Biblioteca de plantillas construida desde el display sintetico."""
    from spectro.imaging import binarize, normalize_glyph, slot_boxes
    from spectro.library import Template

    templates: list[Template] = []
    seen: set[str] = set()
    for text in ("0.245", "1.789", "3.056"):
        img = render_display(text)
        roi = cfg.roi.crop(img)
        binary = binarize(roi, cfg.digits.polarity)
        for i, (x0, x1) in enumerate(slot_boxes(roi.shape[1], cfg.digits)):
            label = text[i]
            if label in seen:
                continue
            seen.add(label)
            glyph = normalize_glyph(binary[:, x0:x1], cfg.templates.size)
            path = tmp_path / f"{label}_0.png"
            cv2.imwrite(str(path), glyph)
            templates.append(Template(label=label, image=glyph, path=path))
    return templates


@pytest.fixture
def cfg_sign() -> Config:
    return make_config(sign=True)


@pytest.fixture
def library_sign(cfg_sign):
    """Biblioteca con digitos, punto y el signo '-' (celdas de 6 slots)."""
    from spectro.imaging import binarize, normalize_glyph, slot_boxes
    from spectro.library import Template

    templates: list[Template] = []
    seen: set[str] = set()
    for text in ("-0.245", " 1.789", "-3.056"):
        img = render_display(text)
        roi = cfg_sign.roi.crop(img)
        binary = binarize(roi, cfg_sign.digits.polarity)
        for i, (x0, x1) in enumerate(slot_boxes(roi.shape[1], cfg_sign.digits)):
            label = text[i]
            if label == " " or label in seen:
                continue
            seen.add(label)
            glyph = normalize_glyph(binary[:, x0:x1], cfg_sign.templates.size)
            templates.append(Template(label=label, image=glyph, path=None))
    return templates
