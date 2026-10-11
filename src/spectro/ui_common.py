"""Piezas comunes de las UI de OpenCV (``calib_ui`` y ``teach_ui``).

Las dos ventanas comparten el mismo estilo: un panel lateral de 360 px con
titulos, botones rectangulares y texto chico. Este modulo reune lo que antes se
copiaba o se importaba de una UI a la otra: colores, ``Button``, ``BaseLayout``,
``hit_test``, los helpers de dibujo de texto y botones, los titulos del panel,
el color de los cortes de slot, la etiqueta de caracter y la apertura/cierre de
la ventana.

Todo es puro salvo las funciones ``draw_*``/``open_window``/``window_closed``,
que solo llaman a OpenCV sobre un canvas ya armado. No hay estado ni logica de
cada UI aca: eso sigue en ``calib_ui`` y ``teach_ui``.

Interfaz publica:
    colores: BG, FG, BTN, BTN_ON, OK_C, BAD_C, DIM, YELLOW, GREEN, ORANGE, GOOD_SCORE_C, BAD_SCORE_C
    PANEL_W, KEY_ENTER, KEY_ESC
    Button, BaseLayout                  hit_test(layout, x, y) -> str | None
    panel_geometry(x0) -> (px, inner)   slot_color(i, digits, with_separators) -> BGR
    score_color(good) -> BGR
    draw_text(canvas, txt, x, y, scale, color, bold)
    draw_button(canvas, b, active, color)
    draw_titles(canvas, layout)         draw_char(canvas, ch, x, y, scale, color, bold)
    open_window(title, on_mouse)        window_closed(title) -> bool
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2

from .config import DigitsConfig

YELLOW = (0, 255, 255)  # BGR: contrasta con el fondo azul del display
GREEN = (0, 255, 0)
ORANGE = (0, 128, 255)

BG = (38, 38, 38)
FG = (230, 230, 230)
BTN = (80, 80, 80)
BTN_ON = (0, 200, 255)
OK_C = (70, 170, 70)
BAD_C = (60, 60, 190)
DIM = (150, 150, 150)
GOOD_SCORE_C = (80, 220, 80)
BAD_SCORE_C = (80, 80, 240)

PANEL_W = 360
KEY_ENTER, KEY_ESC = 13, 27


# --------------------------------------------------------------------------
# Botones y layout
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Button:
    action: str
    x: int
    y: int
    w: int
    h: int
    label: str

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass(frozen=True)
class BaseLayout:
    """Lo que tiene todo layout de panel: origen, alto, botones y titulos."""

    x0: int
    height: int
    buttons: list[Button]
    #: Solo por nombre: asi las subclases pueden sumar campos obligatorios despues.
    titles: dict[str, int] = field(default_factory=dict, kw_only=True)


def hit_test(layout: BaseLayout, x: int, y: int) -> str | None:
    """La accion del boton bajo ``(x, y)``, o ``None``."""
    for btn in layout.buttons:
        if btn.contains(x, y):
            return btn.action
    return None


def panel_geometry(x0: int) -> tuple[int, int]:
    """``(px, inner)``: x donde empieza el contenido del panel y su ancho util."""
    return x0 + 10, PANEL_W - 20


# --------------------------------------------------------------------------
# Dibujo
# --------------------------------------------------------------------------
def draw_text(canvas, txt, x, y, scale=0.46, color=FG, bold=False):
    cv2.putText(canvas, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color,
                2 if bold else 1, cv2.LINE_AA)


def draw_button(canvas, b: Button, active: bool = False, color=None):
    bg = BTN_ON if active else (color or BTN)
    cv2.rectangle(canvas, (b.x, b.y), (b.x + b.w, b.y + b.h), bg, -1)
    cv2.rectangle(canvas, (b.x, b.y), (b.x + b.w, b.y + b.h), (20, 20, 20), 1)
    (tw, th), _ = cv2.getTextSize(b.label, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1)
    draw_text(canvas, b.label, b.x + (b.w - tw) // 2, b.y + (b.h + th) // 2,
              color=(0, 0, 0) if active else FG)


def draw_titles(canvas, layout: BaseLayout) -> None:
    """Los titulos de seccion del panel, cada uno con su linea separadora."""
    px, inner = panel_geometry(layout.x0)
    for title, ty in layout.titles.items():
        draw_text(canvas, title, px, ty + 14, 0.5, YELLOW, bold=True)
        cv2.line(canvas, (px, ty + 20), (px + inner, ty + 20), (90, 90, 90), 1)


def slot_color(i: int, digits: DigitsConfig, with_separators: bool = False):
    """Color del corte de slot ``i``: verde el signo, naranja el separador, amarillo el resto."""
    if i == digits.sign_slot:
        return GREEN
    if with_separators and i in (digits.separator_slots or []):
        return ORANGE
    return YELLOW


def score_color(good: bool):
    """Verde si el score llega al minimo, rojo si no."""
    return GOOD_SCORE_C if good else BAD_SCORE_C


def draw_char(canvas, ch: str, x: int, y: int, scale: float, color=FG, bold: bool = False) -> None:
    """Dibuja el caracter de una celda; el espacio se muestra como ``_``."""
    draw_text(canvas, ch if ch != " " else "_", x, y, scale, color, bold)


# --------------------------------------------------------------------------
# Ventana
# --------------------------------------------------------------------------
def open_window(title: str, on_mouse) -> None:
    """Crea la ventana de OpenCV y le engancha el callback del mouse."""
    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, on_mouse)


def window_closed(title: str) -> bool:
    """``True`` si el usuario cerro la ventana con la X."""
    return cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1
