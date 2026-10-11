"""UI de calibracion manual: panel lateral con botones y vista previa de lectura.

Una sola ventana de OpenCV: a la izquierda el fotograma (rotado, con el
rectangulo amarillo de la ROI y la grilla de slots) y a la derecha un panel con
la configuracion, los datos, la lectura preliminar y los botones. Las teclas
siguen funcionando como atajos, pero ya no hace falta memorizarlas.

La logica -estado, acciones, layout, hit-test, vista previa- es pura y se
testea sin abrir una ventana; ``run_calibration_ui`` es solo el loop de OpenCV.

La vista previa llama a ``read.read_frame``, el mismo lector del pipeline, con
la biblioteca de ``calib/templates``: lo que se ve aca es lo que ``read`` va a
hacer con esta calibracion.

Lupa: mientras el cursor esta sobre el fotograma aparece un recorte ampliado
en resolucion completa, con la mira, la ROI y los cortes de slot, para marcar con
precision. Su aumento se cambia con los botones de la lupa (o las teclas z/x).

Atajos: q/e a/d rotar, +/- celdas, [/] punto, s signo, g guias, z/x lupa,
p probar, r resetear, ENTER guardar, ESC cancelar.

Interfaz publica:
    UIState, UIResult
    apply_action(state, action) -> UIState        apply_key(state, key) -> UIState
    layout_panel(x0, height) -> Layout             hit_test (reexportado de ui_common)
    slider_value(x, rect) -> float
    preview_reading(...) -> Preview                probe_frames(...) -> ProbeResult
    render(...) -> ndarray                         run_calibration_ui(...) -> UIResult | None
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

from .calibrate import _infer_separator_slots, refine_roi
from .config import ROI, Config, DigitsConfig, TemplateConfig
from .imaging import binarize, detect_polarity, load_frame, rotate, slot_boxes
from .read import read_frame
from .ui_common import (
    BAD_C,
    BAD_SCORE_C,
    BG,
    BTN_ON,
    DIM,
    FG,
    GOOD_SCORE_C,
    KEY_ENTER,
    KEY_ESC,
    OK_C,
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

MAX_ROT = 45.0
ZOOM_LEVELS = (4, 8, 12, 16)
LENS_W, LENS_H = 320, 200

PANEL_MIN_H = 800
MAX_IMG_W, MAX_IMG_H = 1100, 760
PROBE_N = 20


# --------------------------------------------------------------------------
# Estado y acciones
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class UIState:
    rotation: float = 0.0
    n_digits: int = 5
    decimal_after: int = 1
    sign: bool = False
    roi: ROI | None = None
    #: Ajustar la ROI al bounding box de la tinta al guardar (inverso de --no-refine).
    refine: bool = True
    guides: bool = False
    #: Aumento de la lupa del cursor (uno de ``ZOOM_LEVELS``).
    zoom: int = 8
    probe_requested: bool = False
    done: bool = False
    cancelled: bool = False


@dataclass(frozen=True)
class UIResult:
    """Lo que la UI devuelve: el estado confirmado y la ROI **final** que se vio."""

    state: UIState
    roi: ROI


def to_frame_coords(x: int, y: int, scale: float) -> tuple[int, int]:
    """Pasa una coordenada de la ventana escalada a coordenadas del fotograma."""
    return int(round(x / scale)), int(round(y / scale))


_ROT_STEPS = {"rot-1": -1.0, "rot-0.1": -0.1, "rot+0.1": 0.1, "rot+1": 1.0}


def set_rotation(state: UIState, deg: float) -> UIState:
    return replace(state, rotation=max(-MAX_ROT, min(MAX_ROT, round(float(deg), 1))))


def apply_action(state: UIState, action: str) -> UIState:
    """Transicion pura estado + accion -> estado nuevo. Es el unico reducer."""
    if action in _ROT_STEPS:
        return set_rotation(state, state.rotation + _ROT_STEPS[action])
    if action == "cells+":
        return replace(state, n_digits=min(state.n_digits + 1, 12))
    if action == "cells-":
        n = max(state.n_digits - 1, 2)
        return replace(state, n_digits=n, decimal_after=min(state.decimal_after, n))
    if action == "dec+":
        return replace(state, decimal_after=min(state.decimal_after + 1, state.n_digits))
    if action == "dec-":
        return replace(state, decimal_after=max(state.decimal_after - 1, 0))
    if action == "sign":
        # La celda del signo cuenta dentro de n_digits: se suma o se quita con ella.
        n = state.n_digits - 1 if state.sign else state.n_digits + 1
        n = max(2, min(n, 12))
        return replace(
            state, sign=not state.sign, n_digits=n, decimal_after=min(state.decimal_after, n)
        )
    if action == "refine":
        return replace(state, refine=not state.refine)
    if action == "guides":
        return replace(state, guides=not state.guides)
    if action in ("zoom+", "zoom-"):
        levels = list(ZOOM_LEVELS)
        i = levels.index(state.zoom) if state.zoom in levels else 1
        i = min(i + 1, len(levels) - 1) if action == "zoom+" else max(i - 1, 0)
        return replace(state, zoom=levels[i])
    if action == "probe":
        return replace(state, probe_requested=True)
    if action == "reset":
        return UIState()
    if action == "ok":
        return replace(state, done=True)
    if action == "cancel":
        return replace(state, cancelled=True)
    return state


_KEY_ACTIONS = {
    "q": "rot-0.1", "e": "rot+0.1", "a": "rot-1", "d": "rot+1",
    "+": "cells+", "=": "cells+", "-": "cells-",
    "[": "dec-", "]": "dec+", "s": "sign", "g": "guides", "p": "probe", "r": "reset",
    "z": "zoom-", "x": "zoom+",
}


def apply_key(state: UIState, key: int) -> UIState:
    """Atajos de teclado: cada tecla se traduce a una accion de ``apply_action``."""
    if key == KEY_ENTER:
        return apply_action(state, "ok")
    if key == KEY_ESC:
        return apply_action(state, "cancel")
    ch = chr(key) if 0 <= key < 256 else ""
    action = _KEY_ACTIONS.get(ch)
    return apply_action(state, action) if action else state


def state_digits(state: UIState, polarity: str) -> DigitsConfig:
    """El ``DigitsConfig`` provisorio con el que se dibuja la grilla."""
    return DigitsConfig(
        n_digits=state.n_digits,
        decimal_after=state.decimal_after,
        polarity=polarity,
        sign_slot=0 if state.sign else None,
        separator_slots=[],
    )


# --------------------------------------------------------------------------
# Layout del panel (coordenadas del canvas)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Layout(BaseLayout):
    slider: tuple[int, int, int, int]  # x, y, w, h
    zoom: tuple[int, int, int, int]    # recuadro de la ROI binarizada
    chars_y: int
    scores_y: int
    reading_y: int
    probe_y: int
    data_y: int


def layout_panel(x0: int, height: int) -> Layout:
    """Posiciones de todos los botones y recuadros del panel que arranca en ``x0``."""
    px, inner = panel_geometry(x0)
    b: list[Button] = []
    # -- ENCUADRE
    bw = (inner - 3 * 6) // 4
    for i, (act, lab) in enumerate((("rot-1", "-1"), ("rot-0.1", "-.1"),
                                    ("rot+0.1", "+.1"), ("rot+1", "+1"))):
        b.append(Button(act, px + i * (bw + 6), 52, bw, 26, lab))
    slider = (px, 94, inner, 16)
    b.append(Button("guides", px, 120, 150, 26, "Guias horizontales"))
    b.append(Button("zoom-", px + 250, 120, 40, 26, "-"))
    b.append(Button("zoom+", px + 300, 120, 40, 26, "+"))
    # -- NUMERO
    b.append(Button("cells-", px + 190, 188, 40, 26, "-"))
    b.append(Button("cells+", px + 300, 188, 40, 26, "+"))
    b.append(Button("dec-", px + 190, 222, 40, 26, "-"))
    b.append(Button("dec+", px + 300, 222, 40, 26, "+"))
    half = (inner - 8) // 2
    b.append(Button("sign", px, 258, half, 28, "Signo (celda 0)"))
    b.append(Button("refine", px + half + 8, 258, half, 28, "Ajustar a tinta"))
    # -- VISTA PREVIA
    zoom = (px, 452, inner, 64)
    # -- botones de abajo
    b.append(Button("probe", px, 640, inner, 28, f"Probar en {PROBE_N} fotogramas"))
    third = (inner - 12) // 3
    yb = height - 46
    b.append(Button("reset", px, yb, third, 32, "Resetear"))
    b.append(Button("cancel", px + third + 6, yb, third, 32, "Cancelar"))
    b.append(Button("ok", px + 2 * (third + 6), yb, third, 32, "Guardar"))
    return Layout(
        x0=x0, height=height, buttons=b, slider=slider, zoom=zoom,
        chars_y=540, scores_y=560, reading_y=590, probe_y=690, data_y=330,
        titles={"ENCUADRE": 12, "NUMERO": 160, "DATOS": 304, "VISTA PREVIA": 424,
                "PRUEBA": 616},
    )


def in_slider(layout: Layout, x: int, y: int) -> bool:
    sx, sy, sw, sh = layout.slider
    return sx - 4 <= x <= sx + sw + 4 and sy - 8 <= y <= sy + sh + 8


def slider_value(x: int, rect: tuple[int, int, int, int]) -> float:
    """Grados que corresponden a la posicion ``x`` dentro del slider."""
    sx, _, sw, _ = rect
    frac = min(max((x - sx) / max(sw, 1), 0.0), 1.0)
    return round(-MAX_ROT + frac * 2 * MAX_ROT, 1)


# --------------------------------------------------------------------------
# Lupa del cursor
# --------------------------------------------------------------------------
def lens_patch(
    img: np.ndarray, cx: int, cy: int, zoom: int, size: tuple[int, int] = (LENS_W, LENS_H)
) -> tuple[np.ndarray, tuple[int, int]]:
    """Recorte de ``img`` centrado en ``(cx, cy)``, ampliado ``zoom`` veces sin suavizar.

    Devuelve ``(parche, (x0, y0))`` con el origen del recorte en el fotograma, para
    pasar coordenadas de fotograma a coordenadas de la lupa. Cerca del borde el
    recorte se rellena de negro en vez de correrse: el centro siempre es el cursor.
    """
    w, h = size
    sw, sh = max(w // zoom, 1), max(h // zoom, 1)
    x0, y0 = cx - sw // 2, cy - sh // 2
    H, W = img.shape[:2]
    pad = np.zeros((sh, sw) + img.shape[2:], dtype=img.dtype)
    sx0, sy0, sx1, sy1 = max(x0, 0), max(y0, 0), min(x0 + sw, W), min(y0 + sh, H)
    if sx1 > sx0 and sy1 > sy0:
        pad[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = img[sy0:sy1, sx0:sx1]
    return cv2.resize(pad, (sw * zoom, sh * zoom), interpolation=cv2.INTER_NEAREST), (x0, y0)


def lens_corner(
    cursor: tuple[int, int], lens_size: tuple[int, int], img_w: int, margin: int = 8
) -> tuple[int, int]:
    """Esquina donde dibujar la lupa: arriba a la izquierda, salvo que el cursor este cerca."""
    lw, lh = lens_size
    cx, cy = cursor
    if cx < lw + margin + 30 and cy < lh + margin + 50:
        return max(img_w - lw - margin, margin), margin
    return margin, margin


def _draw_lens(canvas, img, state: UIState, roi: ROI | None, cursor, scale, polarity, iw):
    """Dibuja la lupa del cursor sobre el canvas, en la zona de imagen."""
    fx, fy = to_frame_coords(cursor[0], cursor[1], scale)
    z = state.zoom
    patch, (ox, oy) = lens_patch(img, fx, fy, z)
    ph, pw = patch.shape[:2]
    if roi is not None and roi.is_valid():
        def to_lens(x, y):
            return int((x - ox) * z), int((y - oy) * z)

        a, b = to_lens(roi.x, roi.y), to_lens(roi.x + roi.w, roi.y + roi.h)
        cv2.rectangle(patch, a, b, YELLOW, 1)
        digits = state_digits(state, polarity)
        for i, (x0, _) in enumerate(slot_boxes(roi.w, digits)):
            p0, p1 = to_lens(roi.x + x0, roi.y), to_lens(roi.x + x0, roi.y + roi.h)
            cv2.line(patch, p0, p1, slot_color(i, digits), 1)
    cx, cy = pw // 2, ph // 2
    cv2.line(patch, (cx - 14, cy), (cx - 3, cy), (0, 0, 255), 1)
    cv2.line(patch, (cx + 3, cy), (cx + 14, cy), (0, 0, 255), 1)
    cv2.line(patch, (cx, cy - 14), (cx, cy - 3), (0, 0, 255), 1)
    cv2.line(patch, (cx, cy + 3), (cx, cy + 14), (0, 0, 255), 1)
    lx, ly = lens_corner(cursor, (pw, ph), iw)
    canvas[ly : ly + ph, lx : lx + pw] = patch
    cv2.rectangle(canvas, (lx - 1, ly - 1), (lx + pw, ly + ph + 18), (20, 20, 20), 1)
    cv2.rectangle(canvas, (lx, ly + ph), (lx + pw, ly + ph + 18), (20, 20, 20), -1)
    info = f"x={fx} y={fy}  x{z}"
    if state.roi is not None and state.roi.is_valid():
        info += f"  ROI {state.roi.w}x{state.roi.h}"
    draw_text(canvas, info, lx + 4, ly + ph + 13, 0.4, FG)


# --------------------------------------------------------------------------
# Vista previa de lectura y prueba sobre la corrida
# --------------------------------------------------------------------------
@dataclass
class Preview:
    enabled: bool
    message: str = ""
    roi: ROI | None = None
    chars: str = ""
    scores: list[float] = field(default_factory=list)
    value: float | None = None
    status: str = ""
    confidence: float = 0.0
    separators: list[int] = field(default_factory=list)
    zoom: np.ndarray | None = None
    cuts: list[float] = field(default_factory=list)  # bordes de slot, fraccion del ancho


@dataclass
class ProbeResult:
    total: int = 0
    valid: int = 0
    vmin: float | None = None
    vmax: float | None = None
    negatives: int = 0
    top_reason: str = ""


def final_roi(gray: np.ndarray, state: UIState, polarity: str) -> ROI | None:
    """La ROI que se guardaria: la dibujada, ajustada a la tinta si ``refine``."""
    roi = state.roi
    if roi is None or not roi.is_valid():
        return None
    if state.refine:
        return refine_roi(gray, roi, polarity, n_digits=state.n_digits, sign=state.sign)
    return roi


def build_config(
    gray: np.ndarray, state: UIState, polarity: str, templates_cfg: TemplateConfig | None = None
) -> Config | None:
    """``Config`` provisorio con la ROI final, los slots y la rotacion del estado."""
    roi = final_roi(gray, state, polarity)
    if roi is None:
        return None
    cfg = Config.default()
    cfg.rotation_deg = state.rotation
    cfg.roi = roi
    cfg.digits = state_digits(state, polarity)
    cfg.digits.separator_slots = _infer_separator_slots(gray, roi, cfg.digits)
    if templates_cfg is not None:
        cfg.templates = templates_cfg
    return cfg


def preview_reading(
    gray: np.ndarray,
    state: UIState,
    polarity: str,
    library: list | None,
    templates_cfg: TemplateConfig | None = None,
) -> Preview:
    """Lee la ROI actual con el lector real y la biblioteca de ``calib/``."""
    if not state.roi or not state.roi.is_valid():
        return Preview(False, "Dibuja la ROI sobre el numero")
    if not library:
        return Preview(False, "Sin plantillas en calib/templates")
    try:
        cfg = build_config(gray, state, polarity, templates_cfg)
        if cfg is None:
            return Preview(False, "Dibuja la ROI sobre el numero")
        reading = read_frame(gray, cfg, library)
        crop = cfg.roi.crop(gray)
        zoom = binarize(crop, polarity) if crop.size else None
        cuts = []
        if crop.size:
            boxes = slot_boxes(crop.shape[1], cfg.digits)
            cuts = [b[0] / crop.shape[1] for b in boxes] + [1.0]
    except Exception as exc:  # la vista previa nunca debe tumbar la UI
        return Preview(False, f"Error: {exc}")
    return Preview(
        True, roi=cfg.roi, chars=reading.chars, scores=list(reading.scores),
        value=reading.value, status=reading.status, confidence=reading.confidence,
        separators=list(cfg.digits.separator_slots), zoom=zoom, cuts=cuts,
    )


def probe_frames(
    frame_paths: list[Path], cfg: Config, library: list, n: int = PROBE_N
) -> ProbeResult:
    """Lee ``n`` fotogramas repartidos por la corrida con la calibracion actual.

    Es preliminar: no aplica el re-registro de deriva que hace ``qc``.
    """
    out = ProbeResult()
    if not frame_paths or not library:
        return out
    idx = np.linspace(0, len(frame_paths) - 1, min(n, len(frame_paths))).round().astype(int)
    reasons: dict[str, int] = {}
    values: list[float] = []
    for i in sorted(set(int(v) for v in idx)):
        out.total += 1
        try:
            gray = load_frame(frame_paths[i], cfg)
            r = read_frame(gray, cfg, library)
        except Exception:
            reasons["ilegible"] = reasons.get("ilegible", 0) + 1
            continue
        if r.is_valid:
            values.append(r.value)
        else:
            reasons[r.status] = reasons.get(r.status, 0) + 1
    out.valid = len(values)
    if values:
        out.vmin, out.vmax = min(values), max(values)
        out.negatives = sum(1 for v in values if v < 0)
    if reasons:
        out.top_reason = max(reasons, key=reasons.get)
    return out


def data_lines(
    state: UIState, preview: Preview | None, polarity: str, shape: tuple[int, ...],
    library: list | None,
) -> list[str]:
    """Las lineas de la seccion DATOS."""
    roi = preview.roi if preview and preview.roi else state.roi
    roi_txt = f"{roi.x},{roi.y}  {roi.w}x{roi.h}" if roi and roi.is_valid() else "sin ROI"
    sep = preview.separators if preview and preview.enabled else "?"
    nlib = len({t.label for t in library}) if library else 0
    return [
        f"ROI final: {roi_txt}",
        f"Celdas {state.n_digits}  punto tras {state.decimal_after}  separador {sep}",
        f"Signo: {'celda 0' if state.sign else 'no'}   Polaridad: {polarity}",
        f"Imagen {shape[1]}x{shape[0]}  rotacion {state.rotation:+.1f} deg",
        f"Biblioteca calib: {len(library) if library else 0} plantillas, {nlib} etiquetas",
    ]


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------
def fit_scale(shape: tuple[int, ...]) -> float:
    return min(MAX_IMG_W / shape[1], MAX_IMG_H / shape[0], 1.0)


def render(
    img: np.ndarray,
    state: UIState,
    scale: float,
    polarity: str,
    preview: Preview | None = None,
    probe: ProbeResult | None = None,
    probing: bool = False,
    library: list | None = None,
    cursor: tuple[int, int] | None = None,
) -> tuple[np.ndarray, Layout]:
    """Dibuja un cuadro completo de la UI. ``img`` es el fotograma ya rotado."""
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ih, iw = small.shape[:2]
    height = max(ih, PANEL_MIN_H)
    layout = layout_panel(iw, height)
    canvas = np.full((height, iw + PANEL_W, 3), BG, dtype=np.uint8)
    canvas[:ih, :iw] = small

    # -- imagen: guias, ROI y grilla
    if state.guides:
        over = canvas[:ih, :iw].copy()
        for gy in range(0, ih, 40):
            cv2.line(over, (0, gy), (iw, gy), (255, 255, 255), 1)
        canvas[:ih, :iw] = cv2.addWeighted(over, 0.25, canvas[:ih, :iw], 0.75, 0)
    roi = preview.roi if preview and preview.roi else state.roi
    if roi is not None and roi.is_valid():
        x, y = int(roi.x * scale), int(roi.y * scale)
        rw, rh = int(roi.w * scale), int(roi.h * scale)
        cv2.rectangle(canvas, (x, y), (x + rw, y + rh), YELLOW, 2)
        digits = state_digits(state, polarity)
        for i, (x0, _) in enumerate(slot_boxes(roi.w, digits)):
            cv2.line(canvas, (x + int(x0 * scale), y), (x + int(x0 * scale), y + rh),
                     slot_color(i, digits), 1)
    if state.roi is not None and roi is not state.roi and state.roi.is_valid():
        d = state.roi  # lo que se arrastro, distinto de la ROI final ajustada
        cv2.rectangle(canvas, (int(d.x * scale), int(d.y * scale)),
                      (int((d.x + d.w) * scale), int((d.y + d.h) * scale)), DIM, 1)

    if cursor is not None and 0 <= cursor[0] < iw and 0 <= cursor[1] < ih:
        _draw_lens(canvas, img, state, roi, cursor, scale, polarity, iw)

    # -- panel
    px, _ = panel_geometry(layout.x0)
    draw_titles(canvas, layout)

    draw_text(canvas, f"Rotacion  {state.rotation:+.1f} deg", px, 46, 0.5)
    sx, sy, sw, sh = layout.slider
    cv2.rectangle(canvas, (sx, sy + sh // 2 - 2), (sx + sw, sy + sh // 2 + 2), (110, 110, 110), -1)
    cv2.line(canvas, (sx + sw // 2, sy), (sx + sw // 2, sy + sh), DIM, 1)
    kx = int(sx + (state.rotation + MAX_ROT) / (2 * MAX_ROT) * sw)
    cv2.rectangle(canvas, (kx - 5, sy), (kx + 5, sy + sh), BTN_ON, -1)

    draw_text(canvas, f"Lupa x{state.zoom}", px + 168, 138, 0.46)
    draw_text(canvas, f"Celdas de caracter   {state.n_digits}", px, 206)
    draw_text(canvas, f"Digitos antes del punto   {state.decimal_after}", px, 240)
    for btn in layout.buttons:
        active = (btn.action == "sign" and state.sign) or (btn.action == "refine" and state.refine) \
            or (btn.action == "guides" and state.guides)
        color = {"ok": OK_C, "cancel": BAD_C}.get(btn.action)
        draw_button(canvas, btn, active, color)

    for k, line in enumerate(data_lines(state, preview, polarity, img.shape, library)):
        draw_text(canvas, line, px, layout.data_y + 16 + k * 18, 0.4, FG)

    zx, zy, zw, zh = layout.zoom
    cv2.rectangle(canvas, (zx, zy), (zx + zw, zy + zh), (20, 20, 20), -1)
    if preview is None or not preview.enabled:
        draw_text(canvas, preview.message if preview else "Dibuja la ROI sobre el numero",
              px, zy + zh // 2 + 4, 0.45, DIM)
    else:
        if preview.zoom is not None and preview.zoom.size:
            z = preview.zoom
            f = min(zw / z.shape[1], zh / z.shape[0])
            zs = cv2.resize(z, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)
            zs = cv2.cvtColor(zs, cv2.COLOR_GRAY2BGR)
            canvas[zy : zy + zs.shape[0], zx : zx + zs.shape[1]] = zs
            for c in preview.cuts:
                cx = zx + int(c * zs.shape[1])
                cv2.line(canvas, (cx, zy), (cx, zy + zs.shape[0]), YELLOW, 1)
            cell_w = zs.shape[1] / max(len(preview.chars), 1)
            for i, ch in enumerate(preview.chars):
                cx = int(zx + (i + 0.5) * cell_w)
                draw_char(canvas, ch, cx - 5, layout.chars_y, 0.7, FG, True)
                if i < len(preview.scores):
                    good = preview.scores[i] >= 0.6
                    draw_text(canvas, f"{preview.scores[i]:.2f}" if preview.scores[i] < 1 else "1.0",
                          cx - 14, layout.scores_y, 0.4, score_color(good))
        if preview.value is not None:
            msg, col = (f"Lectura: {preview.value:+.3f}   conf {preview.confidence:.2f}",
                        GOOD_SCORE_C)
        else:
            msg, col = f"No se puede leer ({preview.status})", BAD_SCORE_C
        draw_text(canvas, msg, px, layout.reading_y + 10, 0.55, col, True)

    if probing:
        draw_text(canvas, "probando...", px, layout.probe_y, 0.45, YELLOW)
    elif probe is not None and probe.total:
        range_text = f"{probe.vmin:+.3f} .. {probe.vmax:+.3f}" if probe.valid else "sin valores"
        draw_text(canvas, f"{probe.valid}/{probe.total} validas   {range_text}", px, layout.probe_y, 0.45)
        extra = f"{probe.negatives} negativas" if probe.valid else f"motivo: {probe.top_reason}"
        if probe.valid and probe.valid < probe.total:
            extra += f"   descarte: {probe.top_reason}"
        draw_text(canvas, extra, px, layout.probe_y + 18, 0.4, DIM)
        draw_text(canvas, "preliminar: sin re-registro de camara", px, layout.probe_y + 36, 0.38, DIM)
    return canvas, layout


# --------------------------------------------------------------------------
# Loop de OpenCV (delgado)
# --------------------------------------------------------------------------
def run_calibration_ui(
    color: np.ndarray,
    polarity: str = "auto",
    initial: UIState | None = None,
    library: list | None = None,
    templates_cfg: TemplateConfig | None = None,
    frame_paths: list[Path] | None = None,
) -> UIResult | None:
    """Abre la ventana y devuelve el estado confirmado, o ``None`` si se cancela."""
    title = "spectro calibrate"
    scale = fit_scale(color.shape)
    iw = int(color.shape[1] * scale)
    h: dict = {"state": initial or UIState(), "drag": None, "start": None,
               "layout": layout_panel(iw, PANEL_MIN_H), "probe": None, "probing": False,
               "cursor": None}
    ih = int(color.shape[0] * scale)
    cache: dict = {"rot": None, "color": None, "gray": None, "key": None, "preview": None}

    def rotated(deg: float):
        if cache["rot"] != deg:
            c = rotate(color, deg)
            cache.update(rot=deg, color=c, gray=cv2.cvtColor(c, cv2.COLOR_BGR2GRAY))
        return cache["color"], cache["gray"]

    def on_mouse(event, mx, my, flags, _param):
        lay = h["layout"]
        # La lupa sigue al cursor mientras este sobre el fotograma.
        h["cursor"] = (mx, my) if mx < lay.x0 and my < ih else None
        if event == cv2.EVENT_LBUTTONDOWN:
            if mx < lay.x0:
                h["drag"], h["start"] = "roi", (mx, my)
            elif in_slider(lay, mx, my):
                h["drag"] = "slider"
                h["state"] = set_rotation(h["state"], slider_value(mx, lay.slider))
            else:
                action = hit_test(lay, mx, my)
                if action:
                    h["state"] = apply_action(h["state"], action)
        elif event == cv2.EVENT_MOUSEMOVE and flags & cv2.EVENT_FLAG_LBUTTON:
            if h["drag"] == "slider":
                h["state"] = set_rotation(h["state"], slider_value(mx, lay.slider))
            elif h["drag"] == "roi" and h["start"]:
                mx = min(mx, lay.x0 - 1)
                (sx, sy), (ex, ey) = h["start"], (mx, my)
                x0, y0 = to_frame_coords(min(sx, ex), min(sy, ey), scale)
                x1, y1 = to_frame_coords(max(sx, ex), max(sy, ey), scale)
                h["state"] = replace(h["state"], roi=ROI(x0, y0, x1 - x0, y1 - y0))
        elif event == cv2.EVENT_LBUTTONUP:
            h["drag"], h["start"] = None, None

    open_window(title, on_mouse)
    result = None
    try:
        while True:
            st = h["state"]
            img, gray = rotated(st.rotation)
            pol = polarity
            if pol == "auto":
                pol = "light_on_dark"
                if st.roi is not None and st.roi.is_valid():
                    crop = st.roi.crop(gray)
                    if crop.size:
                        pol = detect_polarity(crop)
            key = (st.rotation, st.roi, st.n_digits, st.decimal_after, st.sign, st.refine, pol)
            if cache["key"] != key:
                cache.update(key=key, preview=preview_reading(gray, st, pol, library, templates_cfg))
            if st.probe_requested:
                h["state"] = st = replace(st, probe_requested=False)
                cfg = build_config(gray, st, pol, templates_cfg)
                if cfg is not None and library and frame_paths:
                    frame, _ = render(img, st, scale, pol, cache["preview"], h["probe"], True, library,
                                    h["cursor"])
                    cv2.imshow(title, frame)
                    cv2.waitKey(1)
                    h["probe"] = probe_frames(frame_paths, cfg, library)
            frame, h["layout"] = render(
                img, st, scale, pol, cache["preview"], h["probe"], False, library, h["cursor"]
            )
            cv2.imshow(title, frame)
            k = cv2.waitKey(30) & 0xFF
            if k != 255:
                h["state"] = apply_key(h["state"], k)
            st = h["state"]
            if window_closed(title) or st.cancelled:
                break
            if st.done:
                roi = final_roi(gray, st, pol)
                if roi is not None:
                    result = UIResult(state=st, roi=roi)
                    break
                h["state"] = replace(st, done=False)  # sin ROI no se puede guardar
    finally:
        cv2.destroyAllWindows()
    return result
