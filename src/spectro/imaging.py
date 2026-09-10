"""Primitivas de imagen compartidas por ``qc``, ``templates``, ``read`` y ``calibrate``.

Concentra en un solo lugar las operaciones que deben ser *identicas* en todas
las etapas: si la binarizacion que usa ``templates`` para construir la
biblioteca no fuera la misma que usa ``read`` para comparar, la correlacion
caeria sin motivo aparente. Por eso viven aca y no duplicadas en cada modulo.

Interfaz publica:
    load_gray(path)                  -> ndarray uint8 (H, W)
    crop_for_reading(img, cfg, ...)  -> ndarray recortado a la ROI
    binarize(gray, polarity)         -> ndarray uint8 {0,255}, tinta en blanco
    slot_boxes(roi_w, digits)        -> [(x0, x1), ...] por slot
    normalize_glyph(binary, size)    -> ndarray uint8 del tamano de plantilla
    ncc(a, b)                        -> float en [-1, 1]
    phash(binary)                    -> int (hash perceptual de 64 bits)
    hamming(a, b)                    -> int
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .config import ROI, Config, DigitsConfig


def load_gray(path: Path | str) -> np.ndarray:
    """Carga un fotograma en escala de grises. Lanza si el archivo no se puede leer."""
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"No se pudo leer la imagen: {path}")
    return img


def load_color(path: Path | str) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"No se pudo leer la imagen: {path}")
    return img


def crop_for_reading(
    image: np.ndarray,
    cfg: Config,
    frames_roi: ROI | None = None,
    offset: tuple[int, int] = (0, 0),
) -> np.ndarray:
    """Devuelve la ROI de ``image``, corrida por ``offset`` (dx, dy).

    ``frames_roi`` es la ROI que ``extract --roi-only`` ya aplico al escribir los
    fotogramas: en ese caso la imagen *es* la ROI y no hay que recortar de nuevo
    (ni se puede re-registrar: ya no queda contexto alrededor del numero).

    ``offset`` viene del re-registro de ``qc``: compensa la deriva lenta de la
    camara, de modo que la ROI siga cayendo sobre los digitos aunque el encuadre
    se haya corrido unos pixeles a lo largo del video.
    """
    if frames_roi is not None and frames_roi.is_valid():
        return image
    if not cfg.roi.is_valid():
        raise ValueError(
            "config.json no tiene una ROI valida. Corre: python -m spectro calibrate"
        )
    return shifted(cfg.roi, offset, image.shape).crop(image)


def shifted(roi: ROI, offset: tuple[int, int], shape: tuple[int, ...]) -> ROI:
    """La ROI corrida por ``offset``, recortada a los limites de la imagen."""
    dx, dy = offset
    if dx == 0 and dy == 0:
        return roi
    h, w = shape[0], shape[1]
    x = min(max(roi.x + int(dx), 0), max(w - roi.w, 0))
    y = min(max(roi.y + int(dy), 0), max(h - roi.h, 0))
    return ROI(x=x, y=y, w=roi.w, h=roi.h)


def estimate_shift(
    reference_patch: np.ndarray, frame: np.ndarray, anchor: ROI, margin: int = 40
) -> tuple[int, int, float]:
    """Busca el ancla en ``frame`` y devuelve ``(dx, dy, score)``.

    Es el re-registro: template matching del parche de referencia dentro de una
    ventana ``margin`` pixeles mas grande que el ancla. ``(dx, dy)`` es cuanto se
    corrio la escena respecto del fotograma de referencia, y ``score`` la NCC del
    mejor calce, que ya viene corregida por ese corrimiento (a diferencia de
    comparar el ancla en su posicion nominal, que confunde "se movio" con
    "se degrado").
    """
    h, w = frame.shape[:2]
    x0 = max(anchor.x - margin, 0)
    y0 = max(anchor.y - margin, 0)
    x1 = min(anchor.x + anchor.w + margin, w)
    y1 = min(anchor.y + anchor.h + margin, h)
    window = frame[y0:y1, x0:x1]
    if (
        reference_patch.size == 0
        or window.shape[0] < reference_patch.shape[0]
        or window.shape[1] < reference_patch.shape[1]
    ):
        return 0, 0, 0.0
    res = cv2.matchTemplate(
        window.astype(np.float32), reference_patch.astype(np.float32), cv2.TM_CCOEFF_NORMED
    )
    _, score, _, loc = cv2.minMaxLoc(res)
    return int(x0 + loc[0] - anchor.x), int(y0 + loc[1] - anchor.y), float(score)


def auto_anchor(gray: np.ndarray, roi: ROI, size: tuple[int, int] | None = None) -> ROI:
    """Elige automaticamente un ancla: la zona con mas estructura fuera de la ROI.

    Un ancla sirve para registrar solo si tiene bordes: una region de fondo liso
    da una NCC ruidosa y detecta movimiento donde no lo hay. Por eso se busca el
    maximo de energia de gradiente, excluyendo la vecindad del numero (que si
    cambia con la medicion).
    """
    aw, ah = size or (min(3 * roi.w, gray.shape[1]), min(2 * roi.h, gray.shape[0]))
    aw, ah = int(min(aw, gray.shape[1])), int(min(ah, gray.shape[0]))
    grad = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    energy = cv2.boxFilter(grad, -1, (aw, ah), normalize=True)

    # Anular la vecindad de la ROI: ahi la "estructura" son los digitos, que cambian.
    mask = np.ones_like(energy)
    ex0 = max(roi.x - 2 * roi.w - aw // 2, 0)
    ey0 = max(roi.y - 2 * roi.h - ah // 2, 0)
    ex1 = min(roi.x + 3 * roi.w + aw // 2, energy.shape[1])
    ey1 = min(roi.y + 3 * roi.h + ah // 2, energy.shape[0])
    mask[ey0:ey1, ex0:ex1] = 0.0
    # Y los bordes, donde el centro de la ventana no cabe entera.
    mask[: ah // 2, :] = 0.0
    mask[energy.shape[0] - ah // 2 :, :] = 0.0
    mask[:, : aw // 2] = 0.0
    mask[:, energy.shape[1] - aw // 2 :] = 0.0

    cy, cx = np.unravel_index(int(np.argmax(energy * mask)), energy.shape)
    x = int(min(max(cx - aw // 2, 0), gray.shape[1] - aw))
    y = int(min(max(cy - ah // 2, 0), gray.shape[0] - ah))
    return ROI(x=x, y=y, w=aw, h=ah)


def detect_polarity(gray_roi: np.ndarray) -> str:
    """Infiere si el display es claro sobre oscuro, o al reves.

    La tinta es siempre la clase minoritaria: se binariza con Otsu y gana la
    polaridad cuya clase ocupa menos superficie.
    """
    _, mask = cv2.threshold(gray_roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright_fraction = float(np.count_nonzero(mask)) / mask.size
    return "light_on_dark" if bright_fraction <= 0.5 else "dark_on_light"


def binarize(gray: np.ndarray, polarity: str = "light_on_dark") -> np.ndarray:
    """Binariza con Otsu dejando **la tinta en blanco (255)** sin importar la polaridad.

    Normalizar el contraste antes hace que el umbral no dependa del brillo
    absoluto del fotograma, que varia con el enfoque y la exposicion del telefono.
    """
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    flags = cv2.THRESH_BINARY + cv2.THRESH_OTSU
    if polarity == "dark_on_light":
        flags = cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    _, binary = cv2.threshold(norm, 0, 255, flags)
    return binary


def slot_boxes(roi_width: int, digits: DigitsConfig) -> list[tuple[int, int]]:
    """Limites horizontales ``(x0, x1)`` de cada slot dentro de la ROI."""
    cuts = digits.resolved_splits(roi_width)
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


def normalize_glyph(binary_slot: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Lleva el recorte de un slot al tamano canonico de plantilla.

    No se recorta al bounding box de la tinta a proposito: en una fuente
    monoespaciada la *posicion* del glifo dentro de su celda es informacion util
    (distingue el punto decimal de un digito), y ademas evita que el ruido de un
    pixel suelto desplace todo el glifo.
    """
    w, h = size
    if binary_slot.size == 0:
        return np.zeros((h, w), dtype=np.uint8)
    return cv2.resize(binary_slot, (w, h), interpolation=cv2.INTER_AREA)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Correlacion cruzada normalizada entre dos imagenes del mismo tamano."""
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    af = a.astype(np.float32) - float(a.mean())
    bf = b.astype(np.float32) - float(b.mean())
    denom = float(np.linalg.norm(af) * np.linalg.norm(bf))
    if denom < 1e-9:
        # Alguna de las dos es uniforme (slot vacio): iguales si ambas lo son.
        return 1.0 if float(np.linalg.norm(af)) < 1e-9 and float(np.linalg.norm(bf)) < 1e-9 else 0.0
    return float(np.sum(af * bf) / denom)


def phash(binary: np.ndarray, side: int = 8) -> int:
    """Hash perceptual de 64 bits: 1 por pixel de tinta en una grilla ``side``x``side``.

    Alcanza para agrupar recortes del mismo glifo, que es todo lo que necesita
    ``templates`` para reducir miles de recortes a ~11 glifos unicos.
    """
    small = cv2.resize(binary, (side, side), interpolation=cv2.INTER_AREA)
    bits = (small > 127).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    """Distancia de Hamming entre dos hashes."""
    return int(a ^ b).bit_count()


def draw_overlay(
    image: np.ndarray, roi: ROI, digits: DigitsConfig, anchor: ROI | None = None
) -> np.ndarray:
    """Dibuja ROI, cortes de slots y ancla sobre una copia en color de ``image``.

    Es la imagen que ``calibrate`` guarda para que se pueda auditar el corte sin
    volver a abrir una ventana interactiva.
    """
    canvas = image.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(canvas, (roi.x, roi.y), (roi.x + roi.w, roi.y + roi.h), (0, 255, 0), 1)
    for i, (x0, x1) in enumerate(slot_boxes(roi.w, digits)):
        color = (0, 128, 255) if i in (digits.separator_slots or []) else (0, 255, 255)
        cv2.line(canvas, (roi.x + x0, roi.y), (roi.x + x0, roi.y + roi.h), color, 1)
    cv2.line(
        canvas,
        (roi.x + roi.w, roi.y),
        (roi.x + roi.w, roi.y + roi.h),
        (0, 255, 255),
        1,
    )
    if anchor is not None and anchor.is_valid():
        cv2.rectangle(
            canvas,
            (anchor.x, anchor.y),
            (anchor.x + anchor.w, anchor.y + anchor.h),
            (255, 0, 255),
            1,
        )
    return canvas


def contact_sheet(
    tiles: list[np.ndarray], labels: list[str], cols: int = 8, tile_h: int = 96
) -> np.ndarray:
    """Mosaico etiquetado de recortes, para revisar glifos o lecturas dudosas a ojo."""
    if not tiles:
        return np.zeros((tile_h, tile_h, 3), dtype=np.uint8)
    prepared = []
    for tile in tiles:
        img = tile if tile.ndim == 3 else cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
        scale = tile_h / max(img.shape[0], 1)
        prepared.append(
            cv2.resize(img, (max(int(img.shape[1] * scale), 1), tile_h),
                       interpolation=cv2.INTER_NEAREST)
        )
    cell_w = max(t.shape[1] for t in prepared) + 8
    cell_h = tile_h + 22
    rows = (len(prepared) + cols - 1) // cols
    sheet = np.full((rows * cell_h, cols * cell_w, 3), 30, dtype=np.uint8)
    for i, tile in enumerate(prepared):
        r, c = divmod(i, cols)
        y0, x0 = r * cell_h + 20, c * cell_w + 4
        sheet[y0 : y0 + tile.shape[0], x0 : x0 + tile.shape[1]] = tile
        cv2.putText(
            sheet,
            labels[i] if i < len(labels) else "",
            (x0, r * cell_h + 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return sheet
