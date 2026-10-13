"""UI de ``teach``: escribir el valor real de unos fotogramas para calibrar el lector.

Dos modos, que se alternan con ``Gestionar biblioteca`` / ``Volver a muestras``:

* **muestras**: a la izquierda, la ROI del fotograma ampliada con los cortes de slot y,
  debajo de cada celda, el caracter que le corresponde segun el valor tipeado y lo que
  lee hoy el lector. A la derecha, el panel: navegacion, valor por teclado fisico,
  cobertura de caracteres y los botones ``Agregar a biblioteca`` (suma sin duplicar),
  ``Reemplazar biblioteca`` (pide confirmacion) y ``Validar``. ``Descartar`` saca el
  fotograma de la cola (borra su muestra, lo registra y, con ``--queue``, lo repone) y
  ``Deshacer descarte`` lo devuelve.
* **biblioteca**: una grilla con las plantillas de ``calib/templates``. Se elige una
  y se puede borrar, borrar todas las de un caracter, cambiarle la etiqueta o deshacer
  el ultimo borrado. Cada plantilla muestra cuantas celdas de las muestras gana bien y
  cuantas gana mal, para decidir cuales sobran.

El estado, las acciones, los efectos (``TeachSession``) y el layout son puros y se
testean sin ventana: el estado, el reducer y la sesion viven en ``teach_session``;
este modulo solo dibuja y lee eventos.

Interfaz publica:
    layout_teach(...) -> TLayout          tile_rect(i) -> (x, y, w, h)
    render_teach(view) -> (canvas, TLayout)
    TeachView(..., n_rejected, can_undo_discard)
    run_teach_ui(cfg, params: TeachParams, names, offsets, samples, test, reasons, target, rejected, refill) -> int
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import teach as T
from .config import ROI, Config
from .extract import time_from_name
from .imaging import read_roi, shifted, slot_boxes
from .read import Reading
from .ui_common import (
    BAD_C,
    BG,
    BTN_ON,
    DIM,
    FG,
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
from .teach_session import (
    COLS,
    PER_PAGE,
    TeachParams,
    TeachSession,
    TeachState,
    labeled_in_queue,
)

VIEW_W = 760
HEIGHT = 800
CROP_BOX = (10, 10, VIEW_W - 20, 240)
THUMB_BOX = (10, 350, VIEW_W - 20, 440)
MARGIN_PX = 14

# grilla de la biblioteca (COLS, ROWS y PER_PAGE viven en teach_session)
TILE_W, TILE_H, TILE_GAP = 80, 122, 2


def tile_rect(i: int) -> tuple[int, int, int, int]:
    """Rectangulo de la miniatura ``i`` de la pagina (coordenadas del canvas)."""
    col, row = i % COLS, i // COLS
    return 10 + col * (TILE_W + TILE_GAP), 10 + row * (TILE_H + 6), TILE_W, TILE_H


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TLayout(BaseLayout):
    field: tuple[int, int, int, int]
    chips_y: int
    result_y: int


def layout_teach(
    x0: int = VIEW_W,
    height: int = HEIGHT,
    mode: str = "samples",
    n_tiles: int = 0,
    sel_label: str = "",
    confirm: str = "",
    lib_size: int = 0,
    target: str = "train",
) -> TLayout:
    px, inner = panel_geometry(x0)
    half = (inner - 6) // 2
    b: list[Button] = []

    if mode == "library":
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
    b.append(Button("clear", px, 248, half, 32, "Borrar todo"))
    b.append(Button("undo_discard", px + half + 6, 248, half, 32, "Deshacer descarte"))
    b.append(Button("add", px, 290, 2 * q + 6, 32, "Agregar muestra"))
    b.append(Button("discard", px + 2 * (q + 6), 290, 2 * q + 6, 32, "Descartar"))
    b.append(Button("add_lib", px, 452, half, 32, "Agregar a biblioteca"))
    b.append(Button("replace", px + half + 6, 452, half, 32,
                    f"Confirmar: reemplaza {lib_size}" if confirm == "replace"
                    else "Reemplazar biblioteca"))
    b.append(Button("validate", px, 490, half, 32, "Validar"))
    b.append(Button("lib", px + half + 6, 490, half, 32, "Gestionar biblioteca"))
    b.append(Button("target", px, 528, half, 30,
                    "Conjunto: " + ("Prueba" if target == "test" else "Entrenam.")))
    b.append(Button("eval", px + half + 6, 528, half, 30, "Evaluar prueba"))
    b.append(Button("save", px, height - 46, inner, 34, "Guardar y salir"))
    return TLayout(
        x0=x0, height=height, buttons=b, field=(px, 190, inner, 34), chips_y=382, result_y=564,
        titles={"FOTOGRAMA": 12, "VALOR": 156, "MUESTRAS": 336},
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
    reasons: dict[str, str] = field(default_factory=dict)
    #: ROI que ``extract --roi-only`` ya aplico a los fotogramas (``None`` si son completos).
    frames_roi: ROI | None = None
    #: Fotogramas en ``rejected.csv`` de la corrida.
    n_rejected: int = 0
    #: Hay un descarte para deshacer (enciende ``Deshacer descarte``).
    can_undo_discard: bool = False


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
        draw_text(canvas, ch, cx + 6, y + 17, 0.5, (255, 255, 255), True)
        draw_text(canvas, str(n), cx + 6, y + 33, 0.38, (255, 255, 255))


def render_teach(view: TeachView) -> tuple[np.ndarray, TLayout]:
    if view.state.mode == "library":
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
        draw_text(canvas, crop_err[:90], 20, 60, 0.45, BAD_C)
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
            col = slot_color(i, digits, with_separators=True)
            cv2.line(canvas, (rx + int(a * f), ry), (rx + int(a * f), ry + rh), col, 1)
            cx = rx + int((a + c) / 2 * f)
            if cells is not None and i < len(cells):
                draw_char(canvas, cells[i], cx - 8, base, 0.9, FG, True)
            if view.reading is not None and i < len(view.reading.chars):
                ch = view.reading.chars[i]
                sc = view.reading.scores[i] if i < len(view.reading.scores) else 0.0
                good = sc >= cfg.templates.min_score
                draw_char(canvas, ch, cx - 6, base + 30, 0.6, score_color(good))
                draw_text(canvas, f"{sc:.2f}", cx - 14, base + 48, 0.38, DIM)
        draw_text(canvas, "escrito", 12, base, 0.45, DIM)
        draw_text(canvas, "lector", 12, base + 30, 0.45, DIM)
        draw_text(canvas, "score", 12, base + 48, 0.38, DIM)
        # miniatura del fotograma entero con la ROI
        full = view.color if view.color is not None else cv2.cvtColor(view.gray, cv2.COLOR_GRAY2BGR)
        thumb, tf, tx, ty = _fit(full, THUMB_BOX, 1.0)
        canvas[ty : ty + thumb.shape[0], tx : tx + thumb.shape[1]] = thumb
        cv2.rectangle(canvas, (tx + int(roi.x * tf) - 3, ty + int(roi.y * tf) - 3),
                      (tx + int((roi.x + roi.w) * tf) + 3, ty + int((roi.y + roi.h) * tf) + 3),
                      YELLOW, 2)
    elif not view.names:
        draw_text(canvas, "Cola vacia: Deshacer descarte o Guardar y salir", 20, 60, 0.6, BAD_C)
    else:
        draw_text(canvas, "Sin ROI: calibra primero con calibrate", 20, 60, 0.6, BAD_C)

    # -- panel
    px, inner = panel_geometry(lay.x0)
    draw_titles(canvas, lay)
    in_train = any(s.file == name for s in view.samples)
    in_test = any(s.file == name for s in view.test)
    has = in_train or in_test
    status = "CON muestra (entrenamiento)" if in_train else (
        "CON muestra (prueba)" if in_test else "sin muestra")
    draw_text(canvas, name, px, 52, 0.46, FG)
    reason = view.reasons.get(name, "")
    if reason:
        draw_text(canvas, reason[:24], px + 190, 52, 0.38, YELLOW)
    t_s = time_from_name(name) if name else 0.0
    n_con = labeled_in_queue(view.names, view.samples, view.test)
    draw_text(canvas, f"{st.index + 1 if view.names else 0}/{len(view.names)} en cola · {n_con} con muestra"
          f"   t={t_s:.2f} s", px, 32, 0.4, FG)
    draw_text(canvas, status, px, 70, 0.4, OK_C if has else DIM)
    if view.n_rejected:
        draw_text(canvas, f"{view.n_rejected} descartados", px + 200, 70, 0.4, DIM)
    fx, fy, fw, fh = lay.field
    cv2.rectangle(canvas, (fx, fy), (fx + fw, fy + fh), (20, 20, 20), -1)
    cv2.rectangle(canvas, (fx, fy), (fx + fw, fy + fh), BTN_ON if st.text else (110, 110, 110), 1)
    draw_text(canvas, st.text + "|", fx + 8, fy + 25, 0.8, FG, True)
    ok = cells is not None
    hint = f"formato: {T.expected_format(cfg.digits)}"
    draw_text(canvas, err if err else hint, px, 240, 0.4, BAD_C if err else DIM)
    for b in lay.buttons:
        active = b.action == "color" and st.color
        col = {"save": OK_C, "add_lib": OK_C, "validate": (150, 90, 40),
               "lib": (150, 90, 40), "replace": (0, 110, 220), "eval": (150, 90, 40),
               "target": (0, 150, 200) if st.target == "test" else None}.get(b.action)
        if b.action == "replace" and st.confirm == "replace":
            col = BAD_C
        if b.action == "add" and ok:
            col = OK_C
        if b.action == "discard":
            col = (60, 60, 150)
        if b.action == "undo_discard" and not view.can_undo_discard:
            col = (55, 55, 55)
        draw_button(canvas, b, active, col)

    # -- muestras y cobertura
    cov = T.coverage(view.samples, cfg.digits)
    draw_text(canvas, f"{len(view.samples)} entrenamiento · {len(view.test)} prueba · "
          f"biblioteca {view.library_size}", px, lay.chips_y - 8, 0.42, FG)
    _chips(canvas, px, lay.chips_y, inner, cov, cfg)
    draw_text(canvas, "verde: 2+ ejemplos   naranja: 1   rojo: faltan", px, lay.chips_y + 50, 0.36, DIM)

    y = lay.result_y + 14
    for line in (view.result_lines or [])[:3]:
        draw_text(canvas, line[:58], px, y, 0.38, FG if "exactas" not in line else YELLOW)
        y += 17
    if st.message:
        draw_text(canvas, st.message[:56], px, lay.height - 58, 0.42, YELLOW)
    return canvas, lay


def _render_library(view: TeachView) -> tuple[np.ndarray, TLayout]:
    st, cfg = view.state, view.cfg
    entries = view.entries
    page_entries = entries[st.page * PER_PAGE : (st.page + 1) * PER_PAGE]
    sel = entries[st.sel] if 0 <= st.sel < len(entries) else None
    lay = layout_teach(
        mode="library", n_tiles=len(page_entries), sel_label=sel.label if sel else "",
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
        draw_text(canvas, f"{e.label}_{e.n}", x + 6, y + 15, 0.42, YELLOW if selected else FG)
        txt = f"{e.uses} usos" + (f" {e.errors} mal" if e.errors else "")
        draw_text(canvas, txt, x + 4, y + h - 6, 0.34, BAD_C if e.errors else DIM)
    if not entries:
        draw_text(canvas, "La biblioteca esta vacia. Volve a muestras y pulsa Agregar a biblioteca.",
              20, 60, 0.55, BAD_C)

    # -- panel
    px, inner = panel_geometry(lay.x0)
    draw_titles(canvas, lay)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.label] = counts.get(e.label, 0) + 1
    draw_text(canvas, f"{len(entries)} plantillas en total", px, 52, 0.45, FG)
    _chips(canvas, px, lay.chips_y, inner, counts, cfg)
    if sel is not None:
        draw_text(canvas, f"{sel.path.name}    caracter '{sel.label}'", px, 154, 0.5, FG, True)
        draw_text(canvas, f"gana bien {sel.uses} celdas de las muestras", px, 176, 0.42, FG)
        if sel.errors:
            draw_text(canvas, f"gana MAL {sel.errors} celdas: confunde con otro caracter", px, 194, 0.4, BAD_C)
        elif sel.uses == 0:
            draw_text(canvas, "no aporta a las muestras actuales", px, 194, 0.4, DIM)
    last = max((len(entries) - 1) // PER_PAGE, 0)
    draw_text(canvas, f"pagina {st.page + 1} de {last + 1}", px + 110, 372, 0.4, DIM)
    draw_text(canvas, "Cambia el caracter de la plantilla elegida:", px, 428, 0.4, DIM)
    for b in lay.buttons:
        if b.action.startswith("tile:"):
            continue
        col = {"del_one": BAD_C if st.confirm == "del_one" else (60, 60, 150),
               "del_label": BAD_C if st.confirm == "del_label" else (60, 60, 150),
               "samples": OK_C}.get(b.action)
        if b.action == "undo" and not view.can_undo:
            col = (55, 55, 55)
        draw_button(canvas, b, False, col)
    y = lay.result_y + 14
    for line in (view.result_lines or [])[:6]:
        draw_text(canvas, line[:58], px, y, 0.38, FG if "exactas" not in line else YELLOW)
        y += 17
    if st.message:
        draw_text(canvas, st.message[:56], px, lay.height - 58, 0.42, YELLOW)
    return canvas, lay


# --------------------------------------------------------------------------
# Loop de OpenCV (delgado)
# --------------------------------------------------------------------------
def _preconditions(cfg: Config, names: list[str]) -> bool:
    """Imprime el error y devuelve ``False`` si la ventana no puede abrirse."""
    if not names:
        print("ERROR: no hay fotogramas. Corre primero extract y qc.")
    elif not cfg.roi.is_valid():
        print("ERROR: la corrida no tiene ROI. Corre primero: python -m spectro calibrate")
    return bool(names) and cfg.roi.is_valid()


def _view(s: TeachSession) -> TeachView:
    gray, color, off, reading = s.frame(s.state.index)
    return TeachView(s.state, s.cfg, s.names, gray, color, off, s.samples, reading,
                     len(s.library), s.result, s.entries, bool(s.trash), s.test, s.reasons,
                     s.frames_roi, len(s.rejected), s.can_undo_discard)


def run_teach_ui(
    cfg: Config,
    params: TeachParams,
    names: list[str],
    offsets: dict,
    samples: list[T.Sample],
    test: list[T.Sample] | None = None,
    reasons: dict[str, str] | None = None,
    target: str = "train",
    rejected: list | None = None,
    refill=None,
) -> int:
    """Abre la ventana de ``teach``. Entrenamiento, prueba y descartados se guardan en cada cambio.

    ``names`` es la cola de fotogramas (los que pasaron QC y no se descartaron, o los N
    sugeridos con ``--queue``); ``reasons`` dice por que se sugirio cada uno. ``rejected``
    son los descartados de la corrida y ``refill`` (``sampling.QueueRefill``) repone la
    cola al descartar. Todo lo que decide vive en ``TeachSession``: aca solo se leen
    eventos y se dibuja.
    """
    if not _preconditions(cfg, names):
        return 1
    s = TeachSession(cfg, params, names, offsets, samples, test, reasons, target, rejected, refill)
    title, lay = "spectro teach", [layout_teach()]

    def on_mouse(event, mx, my, flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and (action := hit_test(lay[0], mx, my)):
            s.act(action)

    def draw() -> None:
        canvas, lay[0] = render_teach(_view(s))
        cv2.imshow(title, canvas)

    open_window(title, on_mouse)
    try:
        while True:
            kind = s.begin_request()
            if s.is_slow(kind):
                draw()
                cv2.waitKey(1)
            if kind:
                s.run_request(kind)
            draw()
            if (k := cv2.waitKeyEx(30)) != -1:
                s.on_key(k)
            if s.state.done or window_closed(title):
                break
    finally:
        cv2.destroyAllWindows()
        s.persist()
    print(f"{len(s.samples)} muestras de entrenamiento en {params.truth}; "
          f"{len(s.test)} de prueba en {params.test}")
    if params.rejected:
        print(f"{len(s.rejected)} fotogramas descartados en {params.rejected}   "
              "(para restaurar: python -m spectro teach rejected remove)")
    if s.backup_path is not None:
        print(f"respaldo de la biblioteca previa a la sesion (tomado antes del primer cambio): "
              f"{s.backup_path.name}   (para deshacer: python -m spectro teach lib restore)")
    return 0
