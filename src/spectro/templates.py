"""Etapa 4: biblioteca de plantillas de digitos -> ``calib/templates/``.

Con camara fija y fuente monoespaciada, cada caracter en pantalla se ve siempre
*igual*. Muestreando fotogramas y agrupando los recortes de slot por hash
perceptual, miles de recortes colapsan en ~11 glifos unicos (0-9 y el punto).
Etiquetar eso son ~11 pulsaciones de tecla, una sola vez.

Dos modos, misma salida:

* **Interactivo** (default): muestra cada glifo unico y pide teclear el caracter.
* **No interactivo**: ``--labels 0,.,5,9,7,...`` en el orden de la hoja de
  contacto ``runs/<id>/out/glifos.png``, que este mismo comando escribe siempre.

Interfaz publica:
    build_library(args) -> int              (handler del subcomando)
    collect_glyphs(...) -> list[GlyphCluster]
    load_templates(dir) -> list[Template]
    template_path(label, n) -> Path
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .config import Config
from .extract import FRAMES_DIR, index_from_dir, load_frames_index, load_roi_sidecar
from .imaging import (
    binarize,
    contact_sheet,
    crop_for_reading,
    hamming,
    load_gray,
    normalize_glyph,
    phash,
    slot_boxes,
)

#: La biblioteca de glifos es **compartida** entre corridas: el display es el
#: mismo aunque la camara se re-monte. Vive en calib/, no en runs/<id>/.
TEMPLATES_DIR = Path("calib/templates")

#: El punto decimal no puede ir literal en un nombre de archivo.
LABEL_TO_FILE = {".": "dot", "-": "minus", " ": "blank"}
FILE_TO_LABEL = {v: k for k, v in LABEL_TO_FILE.items()}


@dataclass
class GlyphCluster:
    """Un glifo unico encontrado en el muestreo, y cuantas veces aparecio."""

    hash_: int
    glyph: np.ndarray
    count: int = 1
    ejemplos: list[str] = field(default_factory=list)
    label: str | None = None


@dataclass
class Template:
    """Una plantilla etiquetada de la biblioteca."""

    label: str
    image: np.ndarray
    path: Path


def template_path(label: str, n: int, directory: Path | str = TEMPLATES_DIR) -> Path:
    stem = LABEL_TO_FILE.get(label, label)
    return Path(directory) / f"{stem}_{n}.png"


def label_from_filename(path: Path | str) -> str:
    stem = Path(path).stem.rsplit("_", 1)[0]
    return FILE_TO_LABEL.get(stem, stem)


def collect_glyphs(
    cfg: Config,
    frames_dir: Path | str = FRAMES_DIR,
    sample: int = 200,
    verbose: bool = True,
) -> list[GlyphCluster]:
    """Recorre una muestra de fotogramas y devuelve los glifos unicos por slot."""
    frames_dir = Path(frames_dir)
    try:
        index = load_frames_index()
    except FileNotFoundError:
        index = index_from_dir(frames_dir)
    if not index:
        raise FileNotFoundError(
            f"No hay fotogramas en {frames_dir}. Corre primero: python -m spectro extract"
        )
    step = max(len(index) // max(sample, 1), 1)
    chosen = index[::step][:sample]
    frames_roi = load_roi_sidecar(frames_dir)
    if verbose:
        print(f"  muestreando {len(chosen)} de {len(index)} fotogramas (1 cada {step})")

    clusters: list[GlyphCluster] = []
    for entry in chosen:
        try:
            gray = load_gray(frames_dir / entry.archivo)
        except RuntimeError:
            continue
        roi = crop_for_reading(gray, cfg, frames_roi)
        binary = binarize(roi, cfg.digits.polarity)
        for x0, x1 in slot_boxes(roi.shape[1], cfg.digits):
            glyph = normalize_glyph(binary[:, x0:x1], cfg.templates.size)
            h = phash(glyph)
            for cluster in clusters:
                if hamming(cluster.hash_, h) <= cfg.templates.cluster_hamming:
                    cluster.count += 1
                    if len(cluster.ejemplos) < 5:
                        cluster.ejemplos.append(entry.archivo)
                    break
            else:
                clusters.append(
                    GlyphCluster(hash_=h, glyph=glyph, ejemplos=[entry.archivo])
                )
    clusters.sort(key=lambda c: -c.count)
    return clusters


def _label_interactive(clusters: list[GlyphCluster]) -> None:
    """Muestra cada glifo y pide el caracter. ``x`` descarta, ESC corta."""
    print("  Teclea el caracter de cada glifo: 0-9, punto (.), x para descartar, ESC para cortar.")
    for i, cluster in enumerate(clusters):
        big = cv2.resize(cluster.glyph, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
        cv2.imshow(f"glifo {i + 1}/{len(clusters)}  ({cluster.count} apariciones)", big)
        key = cv2.waitKey(0) & 0xFF
        cv2.destroyAllWindows()
        if key == 27:
            break
        char = chr(key)
        if char in "0123456789.-":
            cluster.label = char
        elif char != "x":
            print(f"    '{char}' no es un caracter valido; glifo descartado")


def build_library(args: argparse.Namespace) -> int:
    """Handler del subcomando ``templates``."""
    cfg = Config.load(args.config)
    print("== templates ==")
    clusters = collect_glyphs(cfg, args.frames_dir, args.sample)
    print(f"  {len(clusters)} glifos unicos")

    sheet_path = Path(args.sheet)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet = contact_sheet(
        [cv2.resize(c.glyph, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
         for c in clusters],
        [f"#{i + 1} x{c.count}" for i, c in enumerate(clusters)],
    )
    cv2.imwrite(str(sheet_path), sheet)
    print(f"  hoja de contacto de glifos: {sheet_path}")

    if args.labels is not None:
        labels = [s.strip() for s in args.labels.split(",")]
        if len(labels) != len(clusters):
            print(
                f"  --labels trae {len(labels)} etiquetas pero hay {len(clusters)} glifos.\n"
                f"  Mira {sheet_path} y pasa una etiqueta por glifo, en ese orden."
            )
            return 2
        for cluster, label in zip(clusters, labels):
            cluster.label = None if label in ("x", "") else label
    else:
        _label_interactive(clusters)

    directory = Path(args.templates_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if not args.keep:
        for old in directory.glob("*.png"):
            old.unlink()

    per_label: dict[str, int] = {}
    for cluster in clusters:
        if not cluster.label:
            continue
        n = per_label.get(cluster.label, 0)
        path = template_path(cluster.label, n, directory)
        cv2.imwrite(str(path), cluster.glyph)
        per_label[cluster.label] = n + 1

    if not per_label:
        print("  No se etiqueto ningun glifo; la biblioteca quedo vacia.")
        return 1
    resumen = ", ".join(f"{k}:{v}" for k, v in sorted(per_label.items()))
    print(f"  {sum(per_label.values())} plantillas en {directory}/  ({resumen})")
    faltan = [str(d) for d in range(10) if str(d) not in per_label]
    if faltan:
        print(
            f"  aviso: no hay plantilla para {', '.join(faltan)}. Si esos digitos aparecen\n"
            "         mas adelante en el video, sus fotogramas se descartaran por baja\n"
            "         confianza. Volve a correr templates con --sample mas alto."
        )
    return 0


def load_templates(directory: Path | str = TEMPLATES_DIR) -> list[Template]:
    """Carga la biblioteca etiquetada desde disco."""
    directory = Path(directory)
    paths = sorted(directory.glob("*.png"))
    if not paths:
        raise FileNotFoundError(
            f"No hay plantillas en {directory}. Corre primero: python -m spectro templates"
        )
    out: list[Template] = []
    for p in paths:
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        out.append(Template(label=label_from_filename(p), image=img, path=p))
    return out
