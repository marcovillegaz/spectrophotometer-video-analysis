"""UI de ``teach``: escribir el valor real de unos fotogramas para calibrar el lector.

Dos modos, que se alternan con ``Gestionar biblioteca`` / ``Volver a muestras``:

* **muestras**: a la izquierda, la ROI del fotograma ampliada con los cortes de slot y,
  debajo de cada celda, el caracter que le corresponde segun el valor tipeado y lo que
  lee hoy el lector. A la derecha, el panel: navegacion, teclado numerico de botones,
  cobertura de caracteres y los botones ``Agregar a biblioteca`` (suma sin duplicar),
  ``Reemplazar biblioteca`` (pide confirmacion) y ``Validar``.
* **biblioteca**: una grilla con las plantillas de ``calib/templates``. Se elige una
  y se puede borrar, borrar todas las de un caracter, cambiarle la etiqueta o deshacer
  el ultimo borrado. Cada plantilla muestra cuantas celdas de las muestras gana bien y
  cuantas gana mal, para decidir cuales sobran.

El estado, las acciones y el layout son puros y se testean sin ventana.

Interfaz publica:
    TeachState, apply_action(state, action, n_names, n_lib) -> TeachState
    layout_teach(...) -> TLayout          tile_rect(i) -> (x, y, w, h)
    add_to_set(train, test, archivo, text, digits, which) -> (train, test, mensaje)
    remove_sample(samples, archivo) -> samples
    render_teach(view) -> (canvas, TLayout)
    run_teach_ui(cfg, args, names, offsets, samples) -> int
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

from . import teach as T
from .calib_ui import BAD_C, BG, BTN_ON, DIM, FG, OK_C, YELLOW, Button, _button, _text, hit_test
from .config import ROI, Config, DigitsConfig
from .extract import load_roi_sidecar, time_from_name
from .imaging import load_frame, read_roi, shifted, slot_boxes
from .read import Reading, read_frame

PANEL_W = 360
VIEW_W = 760
HEIGHT = 800
CROP_BOX = (10, 10, VIEW_W - 20, 240)
THUMB_BOX = (10, 350, VIEW_W - 20, 440)
MARGIN_PX = 14
GREEN = (0, 255, 0)
ORANGE = (0, 128, 255)

# grilla de la biblioteca
COLS, ROWS = 9, 6
PER_PAGE = COLS * ROWS
TILE_W, TILE_H, TILE_GAP = 80, 122, 2

#: Acciones destructivas: el primer clic arma la confirmacion y el segundo ejecuta.
CONFIRM_ACTIONS = ("replace", "del_one", "del_label")


def tile_rect(i: int) -> tuple[int, int, int, int]:
    """Rectangulo de la miniatura ``i`` de la pagina (coordenadas del canvas)."""
    col, row = i % COLS, i // COLS
    return 10 + col * (TILE_W + TILE_GAP), 10 + row * (TILE_H + 6), TILE_W, TILE_H


# --------------------------------------------------------------------------
# Estado y acciones (puros)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TeachState:
    index: int = 0
    text: str = ""
    color: bool = False
    done: bool = False
    #: Pedido para el loop (build/validate/borrar/...): lo que toca archivos.
    request: str = ""
    message: str = ""
    mode: str = "muestras"      # "muestras" | "biblioteca"
    sel: int = 0                # plantilla elegida (indice global en la biblioteca)
    page: int = 0
    confirm: str = ""           # accion destructiva esperando el segundo clic
    target: str = "train"       # conjunto al que va "Agregar muestra": train | test


def go_to(state: TeachState, samples: list[T.Sample], names: list[str], index: int) -> TeachState:
    """Cambia de fotograma y precarga el valor si ya tiene muestra."""
    index = max(0, min(index, len(names) - 1)) if names else 0
    existing = next((s.valor for s in samples if names and s.archivo == names[index]), "")
    return replace(state, index=index, text=existing, message="")


def apply_action(state: TeachState, action: str, n_names: int, n_lib: int = 0) -> TeachState:
    """Reducer de las acciones que solo tocan el estado. Las que tocan archivos dejan un ``request``."""
    # Cualquier accion distinta de la destructiva pendiente cancela la confirmacion.
    if action not in CONFIRM_ACTIONS and state.confirm:
        state = replace(state, confirm="")
    if action in CONFIRM_ACTIONS:
        if action != "replace" and not n_lib:
            return state
        if state.confirm == action:
            return replace(state, confirm="", request=action)
        return replace(state, confirm=action, message="")

    if action.startswith("key:"):
        ch = action[4:]
        if len(state.text) < 12 and ch in "0123456789.-":
            return replace(state, text=state.text + ch, message="")
        return state
    if action == "back":
        return replace(state, text=state.text[:-1], message="")
    if action == "clear":
        return replace(state, text="", message="")
    nav = {"prev": -1, "next": 1, "jump-10": -10, "jump+10": 10}
    if action in nav and n_names:
        return replace(state, index=max(0, min(state.index + nav[action], n_names - 1)), message="")
    if action == "color":
        return replace(state, color=not state.color)
    if action in ("validate", "add_lib", "undo", "eval"):
        return replace(state, request=action)
    if action == "target":
        return replace(state, target="test" if state.target == "train" else "train", message="")
    if action == "save":
        return replace(state, done=True)
    # -- modo biblioteca
    if action == "lib":
        return replace(state, mode="biblioteca", sel=0, page=0, request="refresh_lib", message="")
    if action == "samples":
        return replace(state, mode="muestras", message="")
    if action in ("page+", "page-"):
        last = max((n_lib - 1) // PER_PAGE, 0)
        page = min(state.page + 1, last) if action == "page+" else max(state.page - 1, 0)
        return replace(state, page=page)
    if action.startswith("tile:"):
        idx = state.page * PER_PAGE + int(action[5:])
        return replace(state, sel=idx) if idx < n_lib else state
    if action.startswith("relabel:") and n_lib:
        return replace(state, request=action)
    return state


def remove_sample(samples: list[T.Sample], archivo: str) -> list[T.Sample]:
    return [s for s in samples if s.archivo != archivo]


def add_to_set(
    train: list[T.Sample], test: list[T.Sample], archivo: str, text: str, digits: DigitsConfig,
    which: str,
) -> tuple[list[T.Sample], list[T.Sample], str]:
    """Agrega la muestra a ``which`` (``train`` o ``test``) sin que quede en los dos conjuntos.

    Si el valor no calza con la config no cambia nada. Mover una muestra de
    entrenamiento a prueba avisa que ya aporto glifos a la biblioteca.
    """
    from .sampling import assign

    try:
        valor = T.parse_value(text, digits)
    except ValueError as exc:
        return train, test, str(exc)
    estaba_en_train = any(s.archivo == archivo for s in train)
    train, test = assign(train, test, T.Sample(archivo, valor), which)
    if which == "test" and estaba_en_train:
        return train, test, "agregada a prueba (ya habia aportado glifos: reemplaza la biblioteca)"
    return train, test, "muestra agregada" if which == "train" else "muestra de prueba agregada"


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TLayout:
    x0: int
    height: int
    buttons: list[Button]
    field: tuple[int, int, int, int]
    chips_y: int
    result_y: int
    titles: dict[str, int] = field(default_factory=dict)


def layout_teach(
    x0: int = VIEW_W,
    height: int = HEIGHT,
    mode: str = "muestras",
    n_tiles: int = 0,
    sel_label: str = "",
    confirm: str = "",
    lib_size: int = 0,
    target: str = "train",
) -> TLayout:
    px, inner = x0 + 10, PANEL_W - 20
    half = (inner - 6) // 2
    b: list[Button] = []

    if mode == "biblioteca":
        for i in range(min(n_tiles, PER_PAGE)):
            b.append(Button(f"tile:{i}", *tile_rect(i), ""))
        b.append(Button("del_one", px, 214, inner, 32,
                        "Confirmar: borrar seleccionada" if confirm == "del_one"
                        else "Borrar seleccionada"))
        b.append(Button("del_label", px, 252, inner, 32,
                        f"Confirmar: borrar todas las de '{sel_label}'" if confirm == "del_label"
                        else f"Borrar todas las de '{sel_label}'"))
        b.append(Button("undo", px, 290, inner, 32, "Deshacer ultimo borrado"))
        b.append(Button("page-", px, 328, half, 30, "Pag <"))
        b.append(Button("page+", px + half + 6, 328, half, 30, "Pag >"))
        w6 = (inner - 5 * 6) // 6
        for i, ch in enumerate(T.ALL_CHARS):
            r, c = divmod(i, 6)
            b.append(Button(f"relabel:{ch}", px + c * (w6 + 6), 436 + r * 40, w6, 34, ch))
        b.append(Button("samples", px, height - 46, inner, 34, "Volver a muestras"))
        return TLayout(
            x0=x0, height=height, buttons=b, field=(px, 0, 0, 0), chips_y=66, result_y=536,
            titles={"BIBLIOTECA": 12, "SELECCIONADA": 118, "CAMBIAR ETIQUETA": 384},
        )

    q = (inner - 3 * 6) // 4
    for i, (act, lab) in enumerate((("jump-10", "<<10"), ("prev", "<"), ("next", ">"),
                                    ("jump+10", "10>>"))):
        b.append(Button(act, px + i * (q + 6), 78, q, 28, lab))
    b.append(Button("random", px, 112, half, 28, "Aleatorio"))
    b.append(Button("color", px + half + 6, 112, half, 28, "Color / binario"))
    # teclado numerico
    keys = [["7", "8", "9", "back"], ["4", "5", "6", "."], ["1", "2", "3", "-"]]
    for r, row in enumerate(keys):
        for c, k in enumerate(row):
            act = "back" if k == "back" else f"key:{k}"
            b.append(Button(act, px + c * (q + 6), 244 + r * 38, q, 32, "<-" if k == "back" else k))
    b.append(Button("key:0", px, 244 + 3 * 38, 2 * q + 6, 32, "0"))
    b.append(Button("clear", px + 2 * (q + 6), 244 + 3 * 38, 2 * q + 6, 32, "Borrar todo"))
    b.append(Button("add", px, 410, 2 * q + 6 + q + 6, 32, "Agregar muestra"))
    b.append(Button("remove", px + 3 * (q + 6), 410, q, 32, "Quitar"))
    b.append(Button("add_lib", px, 572, half, 32, "Agregar a biblioteca"))
    b.append(Button("replace", px + half + 6, 572, half, 32,
                    f"Confirmar: reemplaza {lib_size}" if confirm == "replace"
                    else "Reemplazar biblioteca"))
    b.append(Button("validate", px, 610, half, 32, "Validar"))
    b.append(Button("lib", px + half + 6, 610, half, 32, "Gestionar biblioteca"))
    b.append(Button("target", px, 648, half, 30,
                    "Conjunto: " + ("Prueba" if target == "test" else "Entrenam.")))
    b.append(Button("eval", px + half + 6, 648, half, 30, "Evaluar prueba"))
    b.append(Button("save", px, height - 46, inner, 34, "Guardar y salir"))
    return TLayout(
        x0=x0, height=height, buttons=b, field=(px, 190, inner, 34), chips_y=502, result_y=684,
        titles={"FOTOGRAMA": 12, "VALOR": 156, "MUESTRAS": 456},
    )


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------
@dataclass
class TeachView:
    state: TeachState
    cfg: Config
    names: list[str]
    gray: np.ndarray | None
    color: np.ndarray | None
    offset: tuple[int, int]
    samples: list[T.Sample]
    reading: Reading | None = None
    library_size: int = 0
    result_lines: list[str] = field(default_factory=list)
    entries: list[T.LibEntry] = field(default_factory=list)
    can_undo: bool = False
    test: list[T.Sample] = field(default_factory=list)
    motivos: dict[str, str] = field(default_factory=dict)
    #: ROI que ``extract --roi-only`` ya aplico a los fotogramas (``None`` si son completos).
    frames_roi: ROI | None = None


def _fit(img: np.ndarray, box: tuple[int, int, int, int], max_zoom: float = 12.0):
    bx, by, bw, bh = box
    f = min(bw / img.shape[1], bh / img.shape[0], max_zoom)
    out = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)
    return out, f, bx + (bw - out.shape[1]) // 2, by


def _chips(canvas, x: int, y: int, inner: int, counts: dict[str, int], cfg: Config) -> None:
    """Un cuadrito por caracter: verde con 2+ ejemplos, naranja con 1, rojo si falta."""
    cw = inner // len(T.ALL_CHARS)
    for i, ch in enumerate(T.ALL_CHARS):
        n = counts.get(ch, 0)
        needed = ch in cfg.digits.required_chars()
        color = (60, 60, 60) if not needed else (OK_C if n >= 2 else ((0, 140, 255) if n == 1 else BAD_C))
        cx = x + i * cw
        cv2.rectangle(canvas, (cx, y), (cx + cw - 3, y + 38), color, -1)
        _text(canvas, ch, cx + 6, y + 17, 0.5, (255, 255, 255), True)
        _text(canvas, str(n), cx + 6, y + 33, 0.38, (255, 255, 255))


def render_teach(view: TeachView) -> tuple[np.ndarray, TLayout]:
    if view.state.mode == "biblioteca":
        return _render_library(view)
    st, cfg = view.state, view.cfg
    lay = layout_teach(confirm=st.confirm, lib_size=view.library_size, target=st.target)
    canvas = np.full((HEIGHT, VIEW_W + PANEL_W, 3), BG, dtype=np.uint8)
    name = view.names[st.index] if view.names else ""

    # -- ROI ampliada con los cortes de slot
    cells, err = None, ""
    if st.text:
        try:
            cells = T.value_to_cells(st.text, cfg.digits)
        except ValueError as exc:
            err = str(exc)
    roi_bin, crop_err = None, ""
    if view.gray is not None and cfg.roi.is_valid():
        try:
            # El mismo camino que la lectura: respeta --roi-only y el corrimiento de qc.
            roi_bin = read_roi(view.gray, cfg, view.offset, view.frames_roi)[1]
        except ValueError as exc:
            crop_err = str(exc)
    if crop_err:
        _text(canvas, crop_err[:90], 20, 60, 0.45, BAD_C)
    elif view.gray is not None and cfg.roi.is_valid():
        if view.frames_roi is not None and view.frames_roi.is_valid():
            # El fotograma ya es la ROI: no hay contexto alrededor ni corrimiento.
            roi = ROI(x=0, y=0, w=view.gray.shape[1], h=view.gray.shape[0])
        else:
            roi = shifted(cfg.roi, view.offset, view.gray.shape)
        x0, y0 = max(roi.x - MARGIN_PX, 0), max(roi.y - MARGIN_PX, 0)
        x1 = min(roi.x + roi.w + MARGIN_PX, view.gray.shape[1])
        y1 = min(roi.y + roi.h + MARGIN_PX, view.gray.shape[0])
        if st.color and view.color is not None:
            crop = view.color[y0:y1, x0:x1]
        else:
            crop = cv2.cvtColor(view.gray[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
            crop[roi.y - y0 : roi.y - y0 + roi.h, roi.x - x0 : roi.x - x0 + roi.w] = \
                cv2.cvtColor(roi_bin, cv2.COLOR_GRAY2BGR)
        zoomed, f, ox, oy = _fit(crop, CROP_BOX)
        canvas[oy : oy + zoomed.shape[0], ox : ox + zoomed.shape[1]] = zoomed
        rx, ry = ox + int((roi.x - x0) * f), oy + int((roi.y - y0) * f)
        rw, rh = int(roi.w * f), int(roi.h * f)
        cv2.rectangle(canvas, (rx, ry), (rx + rw, ry + rh), YELLOW, 2)
        digits = cfg.digits
        boxes = slot_boxes(roi.w, digits)
        base = oy + zoomed.shape[0] + 26
        for i, (a, c) in enumerate(boxes):
            col = GREEN if i == digits.sign_slot else (ORANGE if i in (digits.separator_slots or []) else YELLOW)
            cv2.line(canvas, (rx + int(a * f), ry), (rx + int(a * f), ry + rh), col, 1)
            cx = rx + int((a + c) / 2 * f)
            if cells is not None and i < len(cells):
                _text(canvas, cells[i] if cells[i] != " " else "_", cx - 8, base, 0.9, FG, True)
            if view.reading is not None and i < len(view.reading.caracteres):
                ch = view.reading.caracteres[i]
                sc = view.reading.scores[i] if i < len(view.reading.scores) else 0.0
                good = sc >= cfg.templates.min_score
                _text(canvas, ch if ch != " " else "_", cx - 6, base + 30, 0.6,
                      (80, 220, 80) if good else (80, 80, 240))
                _text(canvas, f"{sc:.2f}", cx - 14, base + 48, 0.38, DIM)
        _text(canvas, "escrito", 12, base, 0.45, DIM)
        _text(canvas, "lector", 12, base + 30, 0.45, DIM)
        _text(canvas, "score", 12, base + 48, 0.38, DIM)
        # miniatura del fotograma entero con la ROI
        full = view.color if view.color is not None else cv2.cvtColor(view.gray, cv2.COLOR_GRAY2BGR)
        thumb, tf, tx, ty = _fit(full, THUMB_BOX, 1.0)
        canvas[ty : ty + thumb.shape[0], tx : tx + thumb.shape[1]] = thumb
        cv2.rectangle(canvas, (tx + int(roi.x * tf) - 3, ty + int(roi.y * tf) - 3),
                      (tx + int((roi.x + roi.w) * tf) + 3, ty + int((roi.y + roi.h) * tf) + 3),
                      YELLOW, 2)
    else:
        _text(canvas, "Sin ROI: calibra primero con calibrate", 20, 60, 0.6, BAD_C)

    # -- panel
    px = lay.x0 + 10
    inner = PANEL_W - 20
    for title, ty in lay.titles.items():
        _text(canvas, title, px, ty + 14, 0.5, YELLOW, True)
        cv2.line(canvas, (px, ty + 20), (px + inner, ty + 20), (90, 90, 90), 1)
    en_train = any(s.archivo == name for s in view.samples)
    en_test = any(s.archivo == name for s in view.test)
    has = en_train or en_test
    estado = "CON muestra (entrenamiento)" if en_train else (
        "CON muestra (prueba)" if en_test else "sin muestra")
    _text(canvas, name, px, 52, 0.46, FG)
    motivo = view.motivos.get(name, "")
    if motivo:
        _text(canvas, motivo[:24], px + 190, 52, 0.38, YELLOW)
    t_s = time_from_name(name) if name else 0.0
    _text(canvas, f"{st.index + 1}/{len(view.names)}   t={t_s:.2f} s   {estado}",
          px, 70, 0.4, OK_C if has else DIM)
    fx, fy, fw, fh = lay.field
    cv2.rectangle(canvas, (fx, fy), (fx + fw, fy + fh), (20, 20, 20), -1)
    cv2.rectangle(canvas, (fx, fy), (fx + fw, fy + fh), BTN_ON if st.text else (110, 110, 110), 1)
    _text(canvas, st.text + "|", fx + 8, fy + 25, 0.8, FG, True)
    ok = cells is not None
    hint = f"formato: {T.expected_format(cfg.digits)}"
    _text(canvas, err if err else hint, px, 240, 0.4, BAD_C if err else DIM)
    for b in lay.buttons:
        active = b.action == "color" and st.color
        col = {"save": OK_C, "add_lib": OK_C, "validate": (150, 90, 40),
               "lib": (150, 90, 40), "replace": (0, 110, 220), "eval": (150, 90, 40),
               "target": (0, 150, 200) if st.target == "test" else None}.get(b.action)
        if b.action == "replace" and st.confirm == "replace":
            col = BAD_C
        if b.action == "add" and ok:
            col = OK_C
        _button(canvas, b, active, col)

    # -- muestras y cobertura
    cov = T.coverage(view.samples, cfg.digits)
    _text(canvas, f"{len(view.samples)} entrenamiento · {len(view.test)} prueba · "
          f"biblioteca {view.library_size}", px, 494, 0.42, FG)
    _chips(canvas, px, lay.chips_y, inner, cov, cfg)
    _text(canvas, "verde: 2+ ejemplos   naranja: 1   rojo: faltan", px, 552, 0.36, DIM)

    y = lay.result_y + 14
    for line in (view.result_lines or [])[:3]:
        _text(canvas, line[:58], px, y, 0.38, FG if "exactas" not in line else YELLOW)
        y += 17
    if st.message:
        _text(canvas, st.message[:56], px, lay.height - 58, 0.42, YELLOW)
    return canvas, lay


def _render_library(view: TeachView) -> tuple[np.ndarray, TLayout]:
    st, cfg = view.state, view.cfg
    entries = view.entries
    page_entries = entries[st.page * PER_PAGE : (st.page + 1) * PER_PAGE]
    sel = entries[st.sel] if 0 <= st.sel < len(entries) else None
    lay = layout_teach(
        mode="biblioteca", n_tiles=len(page_entries), sel_label=sel.label if sel else "",
        confirm=st.confirm,
    )
    canvas = np.full((HEIGHT, VIEW_W + PANEL_W, 3), BG, dtype=np.uint8)

    # -- grilla de miniaturas
    for i, e in enumerate(page_entries):
        x, y, w, h = tile_rect(i)
        selected = st.page * PER_PAGE + i == st.sel
        unused = e.uses == 0 and e.errors == 0
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (46, 46, 46) if unused else (62, 62, 62), -1)
        border = YELLOW if selected else (BAD_C if e.errors else (80, 80, 80))
        cv2.rectangle(canvas, (x, y), (x + w, y + h), border, 2 if selected or e.errors else 1)
        glyph = cv2.resize(e.image, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        glyph = cv2.cvtColor(glyph, cv2.COLOR_GRAY2BGR)
        if unused:
            glyph = (glyph * 0.45).astype(np.uint8)
        gx = x + (w - glyph.shape[1]) // 2
        canvas[y + 22 : y + 22 + glyph.shape[0], gx : gx + glyph.shape[1]] = glyph
        _text(canvas, f"{e.label}_{e.n}", x + 6, y + 15, 0.42, YELLOW if selected else FG)
        txt = f"{e.uses} usos" + (f" {e.errors} mal" if e.errors else "")
        _text(canvas, txt, x + 4, y + h - 6, 0.34, BAD_C if e.errors else DIM)
    if not entries:
        _text(canvas, "La biblioteca esta vacia. Volve a muestras y pulsa Agregar a biblioteca.",
              20, 60, 0.55, BAD_C)

    # -- panel
    px = lay.x0 + 10
    inner = PANEL_W - 20
    for title, ty in lay.titles.items():
        _text(canvas, title, px, ty + 14, 0.5, YELLOW, True)
        cv2.line(canvas, (px, ty + 20), (px + inner, ty + 20), (90, 90, 90), 1)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.label] = counts.get(e.label, 0) + 1
    _text(canvas, f"{len(entries)} plantillas en total", px, 52, 0.45, FG)
    _chips(canvas, px, lay.chips_y, inner, counts, cfg)
    if sel is not None:
        _text(canvas, f"{sel.path.name}    caracter '{sel.label}'", px, 154, 0.5, FG, True)
        _text(canvas, f"gana bien {sel.uses} celdas de las muestras", px, 176, 0.42, FG)
        if sel.errors:
            _text(canvas, f"gana MAL {sel.errors} celdas: confunde con otro caracter", px, 194, 0.4, BAD_C)
        elif sel.uses == 0:
            _text(canvas, "no aporta a las muestras actuales", px, 194, 0.4, DIM)
    last = max((len(entries) - 1) // PER_PAGE, 0)
    _text(canvas, f"pagina {st.page + 1} de {last + 1}", px + 110, 372, 0.4, DIM)
    _text(canvas, "Cambia el caracter de la plantilla elegida:", px, 428, 0.4, DIM)
    for b in lay.buttons:
        if b.action.startswith("tile:"):
            continue
        col = {"del_one": BAD_C if st.confirm == "del_one" else (60, 60, 150),
               "del_label": BAD_C if st.confirm == "del_label" else (60, 60, 150),
               "samples": OK_C}.get(b.action)
        if b.action == "undo" and not view.can_undo:
            col = (55, 55, 55)
        _button(canvas, b, False, col)
    y = lay.result_y + 14
    for line in (view.result_lines or [])[:6]:
        _text(canvas, line[:58], px, y, 0.38, FG if "exactas" not in line else YELLOW)
        y += 17
    if st.message:
        _text(canvas, st.message[:56], px, lay.height - 58, 0.42, YELLOW)
    return canvas, lay


# --------------------------------------------------------------------------
# Loop de OpenCV (delgado)
# --------------------------------------------------------------------------
KEY_ENTER, KEY_ESC, KEY_BACKSPACE = 13, 27, 8
KEY_LEFT, KEY_RIGHT = 2424832, 2555904


def run_teach_ui(
    cfg: Config,
    args,
    names: list[str],
    offsets: dict,
    samples: list[T.Sample],
    test: list[T.Sample] | None = None,
    motivos: dict[str, str] | None = None,
    target: str = "train",
) -> int:
    """Abre la ventana de ``teach``. Entrenamiento y prueba se guardan en cada cambio.

    ``names`` es la cola de fotogramas (todos los que pasaron QC, o los N sugeridos con
    ``--queue``); ``motivos`` dice por que se sugirio cada uno.
    """
    from . import library as biblioteca

    if not names:
        print("ERROR: no hay fotogramas. Corre primero extract y qc.")
        return 1
    if not cfg.roi.is_valid():
        print("ERROR: la corrida no tiene ROI. Corre primero: python -m spectro calibrate")
        return 1
    frames_dir = Path(args.frames_dir)
    frames_roi = load_roi_sidecar(frames_dir)

    def library():
        try:
            return biblioteca.load(args.templates_dir)
        except FileNotFoundError:
            return []

    h = {"samples": list(samples), "test": list(test or []), "lib": library(), "result": [],
         "frame": None, "layout": layout_teach(), "entries": [], "trash": []}
    motivos = motivos or {}
    h["state"] = go_to(TeachState(index=len(names) // 2, target=target),
                       h["samples"] + h["test"], names, len(names) // 2)

    def frame_for(index: int):
        if h["frame"] is None or h["frame"][0] != index:
            path = frames_dir / names[index]
            gray = load_frame(path, cfg)
            color = load_frame(path, cfg, color=True)
            off = offsets.get(names[index], (0, 0))
            reading = read_frame(gray, cfg, h["lib"], frames_roi, off) if h["lib"] else None
            h["frame"] = (index, gray, color, off, reading)
        return h["frame"]

    def persist():
        T.save_truth(args.truth, h["samples"])
        if h["test"] or Path(args.test).exists():
            T.save_truth(args.test, h["test"])

    def refresh_library() -> list[str]:
        """Recarga la biblioteca y mide su efecto sobre las muestras (usos, errores, exactitud)."""
        h["lib"], h["frame"] = library(), None
        h["entries"] = biblioteca.list_entries(args.templates_dir)
        lines: list[str] = []
        pool, datas, _ = T.build_pool(h["samples"], cfg, frames_dir, offsets)
        biblioteca.usage(h["entries"], datas)
        if datas and h["lib"]:
            vig = T.evaluate_library(datas, h["lib"], cfg)
            lines = T.format_report(vig, "biblioteca vigente")[:3]
        return lines

    def run_request(kind: str):
        pool, datas, errores = T.build_pool(h["samples"], cfg, frames_dir, offsets)
        lines = [f"muestra descartada: {e}" for e in errores]
        if not datas:
            h["result"] = lines + ["No hay muestras validas."]
            return
        if kind == "add_lib":
            res = biblioteca.add(pool, args.templates_dir, args.max_per_label)
            lines.append(f"+{sum(res.new.values())} plantillas nuevas, {res.skipped} ya estaban")
        elif kind == "replace":
            nuevas = biblioteca.write(pool, args.templates_dir, "replace", args.max_per_label)
            lines.append(f"biblioteca reemplazada: {sum(nuevas.values())} plantillas")
            h["trash"] = []
        loo = T.validate(datas, pool, cfg)
        T.write_report(loo, args.teach_report)
        h["result"] = lines + T.format_report(loo, "leave-one-out")[:3]
        if kind != "validate":
            h["result"] += refresh_library()[:1]

    def run_eval() -> None:
        from .evaluation import append_history, evaluate_test, summary_lines, write_test_report

        if not h["test"]:
            h["result"] = ["No hay muestras de prueba.", "Pone 'Conjunto: Prueba' y agrega algunas."]
            return
        lib = library()
        if not lib:
            h["result"] = ["No hay biblioteca vigente: agrega muestras a la biblioteca primero."]
            return
        rep = evaluate_test(h["test"], cfg, frames_dir, offsets, lib, h["samples"], args.gap)
        write_test_report(rep, args.test_report)
        append_history(args.history, rep)
        h["result"] = summary_lines(rep)

    def library_request(kind: str, st: TeachState) -> TeachState:
        entries = h["entries"]
        sel = entries[st.sel] if 0 <= st.sel < len(entries) else None
        msg = ""
        dest = None
        if kind == "refresh_lib":
            h["result"] = refresh_library()
        elif kind == "del_one" and sel:
            h["trash"].append(biblioteca.delete([sel.path]))
            msg = f"borrada {sel.path.name}"
        elif kind == "del_label" and sel:
            paths = [e.path for e in entries if e.label == sel.label]
            h["trash"].append(biblioteca.delete(paths))
            msg = f"borradas {len(paths)} plantillas de '{sel.label}'"
        elif kind == "undo":
            if h["trash"]:
                n = biblioteca.restore(h["trash"].pop())
                msg = f"restauradas {n} plantillas"
            else:
                msg = "nada que deshacer"
        elif kind.startswith("relabel:") and sel:
            try:
                dest = biblioteca.relabel(sel.path, kind[8:], args.templates_dir)
                msg = f"{sel.path.name} -> {dest.name}"
            except ValueError as exc:
                msg = str(exc)
        if kind != "refresh_lib":
            h["result"] = refresh_library()
            st = replace(st, sel=_reselect(st, dest))
        return replace(st, message=msg, page=min(st.page, max((len(h["entries"]) - 1) // PER_PAGE, 0)))

    def _reselect(st, dest) -> int:
        """Despues de un cambio, deja elegida una plantilla razonable."""
        entries = h["entries"]
        if not entries:
            return 0
        if dest is not None:
            for i, e in enumerate(entries):
                if e.path == dest:
                    return i
        return min(st.sel, len(entries) - 1)

    def on_mouse(event, mx, my, flags, _param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        action = hit_test(h["layout"], mx, my)
        if action:
            do(action)

    def do(action: str):
        st = h["state"]
        name = names[st.index]
        n_lib = len(h["entries"])
        if st.mode == "muestras" and action == "random":
            h["state"] = go_to(st, h["samples"] + h["test"], names, random.randrange(len(names)))
        elif st.mode == "muestras" and action in ("prev", "next", "jump-10", "jump+10"):
            h["state"] = go_to(st, h["samples"] + h["test"], names,
                               apply_action(st, action, len(names)).index)
        elif st.mode == "muestras" and action == "add":
            h["samples"], h["test"], msg = add_to_set(
                h["samples"], h["test"], name, st.text, cfg.digits, st.target)
            h["state"] = replace(st, message=msg)
            persist()
            if msg.startswith(("muestra", "agregada")):
                h["state"] = go_to(h["state"], h["samples"] + h["test"], names, st.index + 1)
                h["state"] = replace(h["state"], message=msg)
        elif st.mode == "muestras" and action == "remove":
            h["samples"] = remove_sample(h["samples"], name)
            h["test"] = remove_sample(h["test"], name)
            h["state"] = replace(st, text="", message="muestra quitada")
            persist()
        else:
            h["state"] = apply_action(st, action, len(names), n_lib)

    title = "spectro teach"
    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, on_mouse)

    def draw(st: TeachState):
        _, gray, color, off, reading = frame_for(st.index)
        view = TeachView(st, cfg, names, gray, color, off, h["samples"], reading,
                         len(h["lib"]), h["result"], h["entries"], bool(h["trash"]),
                         h["test"], motivos, frames_roi)
        canvas, h["layout"] = render_teach(view)
        cv2.imshow(title, canvas)

    try:
        while True:
            st = h["state"]
            if st.request:
                kind = st.request
                h["state"] = st = replace(st, request="", message="trabajando...")
                if kind == "eval":
                    draw(st)
                    cv2.waitKey(1)
                    run_eval()
                    h["state"] = st = replace(st, message="")
                elif kind in ("validate", "add_lib", "replace"):
                    draw(st)
                    cv2.waitKey(1)
                    run_request(kind)
                    h["state"] = st = replace(st, message="")
                else:
                    h["state"] = st = library_request(kind, replace(st, message=""))
            draw(st)
            k = cv2.waitKeyEx(30)
            if k != -1:
                kk = k & 0xFF
                lib_mode = h["state"].mode == "biblioteca"
                if k == KEY_LEFT:
                    do("page-" if lib_mode else "prev")
                elif k == KEY_RIGHT:
                    do("page+" if lib_mode else "next")
                elif kk == KEY_ESC:
                    if lib_mode:
                        do("samples")
                    else:
                        break
                elif not lib_mode:
                    if kk == KEY_ENTER:
                        do("add")
                    elif kk == KEY_BACKSPACE:
                        do("back")
                    elif 0 < kk < 128 and chr(kk) in "0123456789.-":
                        do(f"key:{chr(kk)}")
            if h["state"].done or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()
        persist()
    print(f"{len(h['samples'])} muestras de entrenamiento en {args.truth}; "
          f"{len(h['test'])} de prueba en {args.test}")
    return 0
