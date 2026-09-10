"""Etapa 2: definir la ROI del numero y los slots de caracter -> ``config.json``.

El encuadre es propio de cada corrida (la camara se re-monta en cada sesion),
asi que esto se hace una vez **por corrida**. Hay tres caminos, y los tres
escriben exactamente la misma configuracion:

* **Interactivo** (default): abre un fotograma con OpenCV y se arrastra un
  rectangulo ajustado al numero (``cv2.selectROI``).
* **No interactivo**: ``--roi x,y,w,h``, util para re-calibrar desde un script,
  para los tests, o cuando no hay entorno grafico disponible.
* **Automatico**: ``--auto`` registra el fotograma de esta corrida contra
  ``calib/reference.jpg`` y corre la ROI de referencia por el desplazamiento
  medido. Es lo que hace viable el lote. Ver ``auto_calibrate``.

En los tres casos se guarda ``out/calibracion.png`` con el overlay de la ROI y
los cortes de slot dibujados, para poder auditar el corte despues.

Interfaz publica:
    calibrate(args) -> int          (handler del subcomando)
    auto_calibrate(args) -> int
    refine_roi(gray, roi) -> ROI
    pick_reference_frame(...) -> Path
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np

from .config import ROI, Config, DigitsConfig
from .imaging import (
    auto_anchor,
    binarize,
    detect_polarity,
    draw_overlay,
    load_color,
    load_gray,
    shifted,
)
from .project import CALIB_DIR, CalibPaths


def pick_reference_frame(frames_dir: Path | str, explicit: str | None = None) -> Path:
    """Elige el fotograma sobre el que calibrar: el indicado, o el del medio.

    El del medio es mejor default que el primero: al inicio del video suele
    haber manos en cuadro o la camara todavia acomodandose.
    """
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"No existe el fotograma: {p}")
        return p
    frames = sorted(Path(frames_dir).glob("t_*.jpg"))
    if not frames:
        raise FileNotFoundError(
            f"No hay fotogramas en {frames_dir}. Corre primero: python -m spectro extract"
        )
    return frames[len(frames) // 2]


def refine_roi(gray: np.ndarray, roi: ROI, polarity: str, margin: int = 2) -> ROI:
    """Ajusta la ROI al bounding box real de la tinta, con un margen chico.

    Deja el rectangulo pegado al numero aunque el arrastre a mano haya sido
    generoso, que es lo que hace que el reparto uniforme de slots caiga bien.
    """
    crop = roi.crop(gray)
    if crop.size == 0:
        return roi
    ink = binarize(crop, polarity)
    ys, xs = np.nonzero(ink)
    if xs.size == 0:
        return roi
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    x = max(roi.x + x0 - margin, 0)
    y = max(roi.y + y0 - margin, 0)
    w = min(x1 - x0 + 1 + 2 * margin, gray.shape[1] - x)
    h = min(y1 - y0 + 1 + 2 * margin, gray.shape[0] - y)
    return ROI(x=x, y=y, w=w, h=h)


def _select_roi_interactive(image: np.ndarray, title: str) -> ROI:
    print(f"  Arrastra el rectangulo sobre {title}, ENTER para confirmar, c para cancelar.")
    x, y, w, h = cv2.selectROI("spectro calibrate", image, showCrosshair=True)
    cv2.destroyAllWindows()
    return ROI(x=int(x), y=int(y), w=int(w), h=int(h))


def _ask_int(prompt: str, default: int) -> int:
    raw = input(f"  {prompt} [{default}]: ").strip()
    return int(raw) if raw else default


def _calib_paths(args: argparse.Namespace) -> CalibPaths:
    """La calib de esta invocacion. ``cli.resolve_paths`` ya la dejo resuelta."""
    resuelta = getattr(args, "calib_paths", None)
    if resuelta is not None:
        return resuelta
    return CalibPaths.at(getattr(args, "calib_dir", None) or CALIB_DIR)


def calibrate(args: argparse.Namespace) -> int:
    """Handler del subcomando ``calibrate``: despacha manual o ``--auto``."""
    if getattr(args, "auto", False):
        return auto_calibrate(args)
    return _calibrate_manual(args)


def auto_calibrate(args: argparse.Namespace) -> int:
    """Calibra por registro contra ``calib/reference.jpg``, sin intervencion.

    Reusa ``estimate_shift`` -el mismo re-registro que ``qc`` corre entre
    fotogramas de una corrida- aplicado **entre sesiones**: busca el parche del
    ancla de referencia en el fotograma de esta corrida y corre la ROI por el
    ``(dx, dy)`` que encuentra. El margen de busqueda (``--search-px``) es
    bastante mayor que los 40 px del registro intra-corrida, porque entre
    sesiones el telefono se re-monta y el encuadre salta de verdad.

    Corrige **traslacion**, no rotacion ni escala. Si el telefono quedo a otra
    distancia o inclinado, la NCC cae por debajo de ``--min-score`` y la funcion
    falla en vez de devolver una ROI mala: mezclar una ROI corrida con datos de
    laboratorio los corrompe en silencio.
    """
    calib = _calib_paths(args)
    if not calib.config.exists():
        raise FileNotFoundError(
            f"No existe {calib.config}. calibrate --auto se registra contra la "
            f"calibracion de referencia; primero calibra una corrida a mano y "
            f"promovela con: python -m spectro calibrate --run <id> --promote"
        )
    if not calib.reference.exists():
        raise FileNotFoundError(
            f"No existe {calib.reference}. Es el fotograma al que corresponden las "
            f"coordenadas de {calib.config}; sin el no hay contra que registrar."
        )

    ref_cfg = Config.load(calib.config)
    if not ref_cfg.roi.is_valid():
        raise ValueError(f"{calib.config} no tiene una ROI de referencia.")
    anchor = ref_cfg.qc.anchor
    if not anchor.is_valid():
        raise ValueError(
            f"{calib.config} no tiene un ancla de referencia, y --auto se registra "
            f"contra ella. Re-calibra la referencia dejando que se infiera el ancla."
        )

    frame_path = pick_reference_frame(args.frames_dir, args.frame)
    print(f"== calibrate --auto ==\n  fotograma de esta corrida: {frame_path}")
    print(f"  referencia: {calib.reference}")

    reference = load_gray(calib.reference)
    gray = load_gray(frame_path)
    if gray.shape != reference.shape:
        print(
            f"  ERROR: la referencia es {reference.shape[1]}x{reference.shape[0]} y este "
            f"fotograma {gray.shape[1]}x{gray.shape[0]}.\n"
            f"  El registro corrige traslacion, no escala. Calibra esta corrida a mano:\n"
            f"    python -m spectro calibrate --run {getattr(args, 'run', '<id>')}"
        )
        return 2

    dx, dy, score = auto_shift(reference, gray, anchor, margin=args.search_px)
    print(
        f"  ancla de referencia {anchor.as_tuple()} -> desplazamiento ({dx:+d}, {dy:+d}), "
        f"score {score:.3f} (minimo {args.min_score:.2f})"
    )
    if score < args.min_score:
        print(
            "  ERROR: el encuadre cambio demasiado; el ancla no se reconoce.\n"
            "  No se inventa una ROI. Calibra esta corrida a mano:\n"
            f"    python -m spectro calibrate --run {getattr(args, 'run', '<id>')}\n"
            "  (o subi --search-px si el salto fue grande pero la escena es la misma)"
        )
        return 2

    h, w = gray.shape[:2]
    roi = _shift_or_none(ref_cfg.roi, dx, dy, w, h)
    if roi is None:
        print(
            f"  ERROR: con el desplazamiento ({dx:+d}, {dy:+d}) la ROI se sale del "
            f"fotograma. El numero quedo fuera de cuadro; calibra a mano."
        )
        return 2
    nuevo_anchor = _shift_or_none(anchor, dx, dy, w, h) or anchor

    cfg = Config.load_or_default(args.config)
    cfg.roi = roi
    cfg.digits = ref_cfg.digits
    cfg.templates = ref_cfg.templates
    cfg.qc.anchor = nuevo_anchor
    cfg.qc.min_anchor_ncc = ref_cfg.qc.min_anchor_ncc
    cfg.qc.max_shift_px = ref_cfg.qc.max_shift_px
    cfg.qc.register = ref_cfg.qc.register
    # La ROI quedo expresada en coordenadas de *este* fotograma: es el origen
    # contra el que qc registra los demas de la corrida.
    cfg.qc.reference_frame = frame_path.name
    cfg.save(args.config)
    print(f"  ROI {roi.as_tuple()}, ancla {nuevo_anchor.as_tuple()}")
    print(f"  guardado en {args.config}")

    _write_overlay(args, load_color(frame_path), roi, cfg.digits, nuevo_anchor)
    if getattr(args, "promote", False):
        _promote(calib, cfg, frame_path)
    return 0


def auto_shift(
    reference: np.ndarray, frame: np.ndarray, anchor: ROI, margin: int
) -> tuple[int, int, float]:
    """``(dx, dy, score)`` del fotograma respecto de la referencia de ``calib/``."""
    from .imaging import estimate_shift

    return estimate_shift(anchor.crop(reference), frame, anchor, margin=margin)


def _shift_or_none(roi: ROI, dx: int, dy: int, w: int, h: int) -> ROI | None:
    """La ROI corrida, o ``None`` si el corrimiento la saca del fotograma.

    ``imaging.shifted`` recorta a los limites para que el pipeline no explote a
    mitad de camino; aca eso no sirve: una ROI recortada es una ROI mal puesta, y
    preferimos fallar.
    """
    x, y = roi.x + dx, roi.y + dy
    if x < 0 or y < 0 or x + roi.w > w or y + roi.h > h:
        return None
    return shifted(roi, (dx, dy), (h, w))


def _write_overlay(
    args: argparse.Namespace, color: np.ndarray, roi: ROI, digits: DigitsConfig, anchor: ROI
) -> Path:
    preview = Path(args.preview)
    preview.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(preview), draw_overlay(color, roi, digits, anchor))
    print(f"  overlay de verificacion: {preview}")
    return preview


def _promote(calib: CalibPaths, cfg: Config, frame_path: Path) -> None:
    """Sube la calibracion de esta corrida a ``calib/`` como nueva referencia."""
    from .project import calib_recipe

    calib.root.mkdir(parents=True, exist_ok=True)
    calib_recipe(cfg).save(calib.config)
    shutil.copyfile(frame_path, calib.reference)
    print(
        f"  --promote: {calib.config} y {calib.reference} actualizados "
        f"desde {frame_path.name}"
    )


def _calibrate_manual(args: argparse.Namespace) -> int:
    """Camino interactivo / ``--roi``: fija la ROI sobre un fotograma concreto."""
    frame_path = pick_reference_frame(args.frames_dir, args.frame)
    print(f"== calibrate ==\n  fotograma de referencia: {frame_path}")
    color = load_color(frame_path)
    gray = load_gray(frame_path)

    cfg = Config.load_or_default(args.config)
    interactive = args.roi is None

    # -- ROI del numero
    if interactive:
        roi = _select_roi_interactive(color, "el numero de absorbancia (ajustado)")
        if not roi.is_valid():
            print("  Seleccion vacia; no se cambio nada.")
            return 2
    else:
        roi = args.roi

    # -- polaridad
    polarity = args.polarity
    if polarity == "auto":
        polarity = detect_polarity(roi.crop(gray))
        print(f"  polaridad detectada: {polarity}")

    if not getattr(args, "no_refine", False):
        roi = refine_roi(gray, roi, polarity)
        print(f"  ROI ajustada a la tinta: {roi.as_tuple()}")
    else:
        print(f"  ROI tal cual (--no-refine): {roi.as_tuple()}")

    # -- slots
    digits = DigitsConfig(polarity=polarity)
    if args.n_digits is not None:
        digits.n_digits = args.n_digits
    elif interactive:
        print("  Contando celdas de caracter: en 0.597 el punto ocupa una celda -> 5")
        digits.n_digits = _ask_int("Cantidad de celdas (digitos + punto)", 5)
    if args.decimal_after is not None:
        digits.decimal_after = args.decimal_after
    elif interactive:
        digits.decimal_after = _ask_int("Digitos antes del punto decimal", 1)

    if args.splits:
        cuts = [int(v) for v in args.splits.split(",")]
        if len(cuts) != digits.n_digits + 1:
            print(f"  --splits debe traer {digits.n_digits + 1} valores")
            return 2
        digits.splits = cuts
    else:
        digits.splits = []

    seps = _infer_separator_slots(gray, roi, digits)
    if args.separators is not None:
        seps = [int(v) for v in args.separators.split(",") if v.strip() != ""]
    digits.separator_slots = seps
    print(
        f"  {digits.n_digits} slots, separador(es) en {digits.separator_slots or 'ninguno'}, "
        f"punto decimal despues de {digits.decimal_after} digito(s)"
    )

    # -- ancla estatica para detectar movimiento de camara
    anchor = args.anchor
    if anchor is None:
        anchor = auto_anchor(gray, roi)
        print(f"  ancla automatica (maxima estructura fuera de la ROI): {anchor.as_tuple()}")

    cfg.roi = roi
    cfg.digits = digits
    cfg.qc.anchor = anchor
    # La ROI se definio sobre este fotograma: es el origen de coordenadas contra
    # el que qc registra todos los demas.
    cfg.qc.reference_frame = frame_path.name
    if not cfg.video and getattr(args, "video", None):
        cfg.video = args.video
    cfg.save(args.config)
    print(f"  guardado en {args.config}")

    _write_overlay(args, color, roi, digits, anchor)
    if getattr(args, "promote", False):
        _promote(_calib_paths(args), cfg, frame_path)
    return 0


def _infer_separator_slots(gray: np.ndarray, roi: ROI, digits: DigitsConfig) -> list[int]:
    """Adivina que slot es el punto decimal: el de menos tinta, y muy por debajo.

    El punto es, por lejos, el glifo con menos pixeles encendidos de la linea.
    Si ningun slot se destaca, no se marca ninguno.
    """
    from .imaging import slot_boxes

    crop = binarize(roi.crop(gray), digits.polarity)
    boxes = slot_boxes(roi.w, digits)
    ink = [float(np.count_nonzero(crop[:, x0:x1])) / max((x1 - x0) * crop.shape[0], 1)
           for x0, x1 in boxes]
    if not ink:
        return []
    lo = min(ink)
    median = float(np.median(ink))
    if lo < 0.35 * median:
        return [int(np.argmin(ink))]
    return []
