"""Etapa 3: filtro de calidad -> ``runs/<id>/out/qc_report.csv``.

Todas las metricas se calculan **sobre la ROI**, no sobre el fotograma
completo: que la mitad de la mesa este en penumbra no importa; lo unico que
decide si un fotograma es legible es como se ve el numero.

``qc_report.csv`` es el libro mayor por fotograma del pipeline: ``read`` le
actualiza la columna ``estado`` con el resultado de la lectura y ``report`` lo
usa para el cuadre de conteos (validas + descartadas = extraidas).

| metrica          | detecta                        | estado          |
|------------------|--------------------------------|-----------------|
| luminancia media | fotograma oscuro o quemado     | dark / blown    |
| varianza Laplace | desenfoque, movimiento         | blur            |
| contraste p95-p05| display apagado o velado       | low_contrast    |
| fraccion de tinta| mano delante, pantalla vacia   | occluded/blank  |
| NCC contra ancla | la camara se movio             | camera_moved    |

El ancla ademas **re-registra** la ROI: template matching del ancla contra el
fotograma de referencia da el corrimiento ``(dx, dy)`` de cada fotograma, que
``read`` usa para mover la ROI. Sin esto, una deriva de pocos pixeles a lo largo
de 20 minutos alcanza para que el recorte empiece a comerse los digitos.

Interfaz publica:
    run_qc(cfg, ...) -> list[QCRow]
    suggest_thresholds(rows, cfg) -> QCConfig
    load_qc_report(path) -> list[QCRow]
    load_offsets(path, passed_only) -> dict[str, tuple[int, int]]
    write_qc_report(rows, path) -> Path
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import cv2
import numpy as np

from .config import Config, QCConfig
from .extract import FRAMES_DIR, FRAMES_INDEX, index_from_dir, load_frames_index, load_roi_sidecar
from .imaging import estimate_shift, load_frame, read_roi

#: Default relativo a la raiz de la corrida; ver ``extract.FRAMES_DIR``.
QC_REPORT = Path("out/qc_report.csv")

#: Estados que significan "este fotograma no se puede leer".
REJECTED = {"dark", "blown", "blur", "low_contrast", "occluded", "blank", "camera_moved",
            "roi_fuera"}


@dataclass
class QCRow:
    """Una fila de ``qc_report.csv``: metricas de un fotograma y su estado."""

    archivo: str
    t_s: float
    indice: int
    mean_luma: float = 0.0
    p05: float = 0.0
    p95: float = 0.0
    contraste: float = 0.0
    blur_var: float = 0.0
    ink_fraction: float = 0.0
    anchor_ncc: float = 1.0
    #: Corrimiento respecto del fotograma de referencia, en pixeles.
    dx: int = 0
    dy: int = 0
    estado: str = "ok"

    @property
    def offset(self) -> tuple[int, int]:
        return (self.dx, self.dy)

    @property
    def passed_qc(self) -> bool:
        return self.estado not in REJECTED


def measure(
    gray_frame: np.ndarray, cfg: Config, frames_roi=None, offset: tuple[int, int] = (0, 0)
) -> dict[str, float]:
    """Calcula las metricas de calidad de un fotograma, sobre su ROI ya registrada."""
    roi, binary = read_roi(gray_frame, cfg, offset, frames_roi)
    p05, p95 = (float(v) for v in np.percentile(roi, [5, 95]))
    return {
        "mean_luma": float(roi.mean()),
        "p05": p05,
        "p95": p95,
        "contraste": p95 - p05,
        "blur_var": float(cv2.Laplacian(roi, cv2.CV_64F).var()),
        "ink_fraction": float(np.count_nonzero(binary)) / binary.size,
    }


def classify(row: QCRow, qc: QCConfig) -> str:
    """Traduce las metricas a un estado. El primer criterio que falla manda."""
    if row.mean_luma < qc.min_mean_luma:
        return "dark"
    if row.mean_luma > qc.max_mean_luma:
        return "blown"
    if row.contraste < qc.min_contrast:
        return "low_contrast"
    if row.blur_var < qc.min_blur_var:
        return "blur"
    if row.ink_fraction < qc.min_ink_fraction:
        return "blank"
    if row.ink_fraction > qc.max_ink_fraction:
        return "occluded"
    if row.anchor_ncc < qc.min_anchor_ncc:
        return "camera_moved"
    if max(abs(row.dx), abs(row.dy)) >= qc.max_shift_px:
        return "camera_moved"
    return "ok"


def _mad(values: np.ndarray) -> float:
    """Desviacion absoluta mediana: robusta a los outliers que justamente buscamos."""
    med = float(np.median(values))
    return float(np.median(np.abs(values - med)))


def suggest_thresholds(rows: list[QCRow], base: QCConfig, k: float = 6.0) -> QCConfig:
    """Sugiere umbrales desde la distribucion observada (mediana +- k*MAD).

    Se usa MAD y no desviacion estandar porque los fotogramas malos son
    justamente los outliers: con sigma, ellos mismos inflarian el umbral que
    deberia rechazarlos.
    """
    if not rows:
        return base

    def band(name: str) -> tuple[float, float, float]:
        vals = np.array([getattr(r, name) for r in rows], dtype=float)
        med, mad = float(np.median(vals)), _mad(vals)
        spread = mad if mad > 1e-9 else max(abs(med) * 0.1, 1e-6)
        return med, med - k * spread, med + k * spread

    out = QCConfig(
        anchor=base.anchor,
        min_anchor_ncc=base.min_anchor_ncc,
        reference_frame=base.reference_frame,
        max_shift_px=base.max_shift_px,
        register=base.register,
    )
    _, lo, hi = band("mean_luma")
    out.min_mean_luma = max(lo, 5.0)
    out.max_mean_luma = min(hi, 250.0)
    _, lo, _ = band("contraste")
    out.min_contrast = max(lo, 10.0)
    _, lo, _ = band("blur_var")
    out.min_blur_var = max(lo, 5.0)
    med, lo, hi = band("ink_fraction")
    out.min_ink_fraction = max(lo, 0.2 * med, 0.002)
    out.max_ink_fraction = min(max(hi, 1.8 * med), 0.9)
    return out


def run_qc(
    cfg: Config,
    frames_dir: Path | str = FRAMES_DIR,
    index_path: Path | str = FRAMES_INDEX,
    output: Path | str = QC_REPORT,
    auto_thresholds: bool = True,
    config_path: Path | str | None = None,
    verbose: bool = True,
) -> list[QCRow]:
    """Mide todos los fotogramas, fija los umbrales y escribe el reporte."""
    frames_dir = Path(frames_dir)
    try:
        index = load_frames_index(index_path)
    except FileNotFoundError:
        index = index_from_dir(frames_dir)
    if not index:
        raise FileNotFoundError(
            f"No hay fotogramas en {frames_dir}. Corre primero: python -m spectro extract"
        )
    frames_roi = load_roi_sidecar(frames_dir)
    if verbose:
        print(f"== qc ==\n  {len(index)} fotogramas desde {frames_dir}/")

    anchor = cfg.qc.anchor
    registrar = frames_roi is None and anchor.is_valid() and cfg.qc.register
    anchor_ref = _reference_patch(cfg, frames_dir, index) if registrar else None
    if verbose:
        if registrar:
            ref_name = cfg.qc.reference_frame or index[0].archivo
            print(f"  re-registro activo contra {ref_name}, ancla {anchor.as_tuple()}")
        elif frames_roi is not None:
            print("  fotogramas ya recortados (--roi-only): sin re-registro ni ancla")

    rows: list[QCRow] = []
    for entry in index:
        path = frames_dir / entry.archivo
        row = QCRow(archivo=entry.archivo, t_s=entry.t_s, indice=entry.indice)
        try:
            gray = load_frame(path, cfg)
        except RuntimeError:
            row.estado = "blank"
            rows.append(row)
            continue
        if anchor_ref is not None:
            row.dx, row.dy, row.anchor_ncc = estimate_shift(
                anchor_ref, gray, anchor, cfg.qc.max_shift_px
            )
        try:
            medidas = measure(gray, cfg, frames_roi, row.offset)
        except ValueError:  # el fotograma no puede contener la ROI: se descarta, no se aborta
            row.estado = "roi_fuera"
            rows.append(row)
            continue
        for key, value in medidas.items():
            setattr(row, key, value)
        rows.append(row)

    qc = suggest_thresholds(rows, cfg.qc) if auto_thresholds else cfg.qc
    qc.anchor, qc.min_anchor_ncc = cfg.qc.anchor, cfg.qc.min_anchor_ncc
    for row in rows:
        if row.estado != "roi_fuera":
            row.estado = classify(row, qc)

    if auto_thresholds and config_path is not None:
        cfg.qc = qc
        cfg.save(config_path)
        if verbose:
            print(f"  umbrales auto-sugeridos y guardados en {config_path}")
    if verbose:
        for name, value in asdict(qc).items():
            if name != "anchor":
                print(f"    {name:18s} {value}")

    write_qc_report(rows, output)
    if verbose:
        summary = _summary(rows)
        total_ok = summary.get("ok", 0)
        print(f"  {total_ok}/{len(rows)} fotogramas pasan QC")
        if registrar:
            print(
                f"    deriva de camara: dx {min(r.dx for r in rows)}..{max(r.dx for r in rows)} px, "
                f"dy {min(r.dy for r in rows)}..{max(r.dy for r in rows)} px (compensada)"
            )
        for state, count in sorted(summary.items(), key=lambda kv: -kv[1]):
            if state != "ok":
                print(f"    descartados por {state}: {count}")
        print(f"  reporte: {output}")
    return rows


def _reference_patch(cfg: Config, frames_dir: Path, index) -> np.ndarray | None:
    """Recorta el ancla del fotograma de referencia: el origen del registro."""
    name = cfg.qc.reference_frame or index[0].archivo
    path = frames_dir / name
    if not path.exists():
        path = frames_dir / index[0].archivo
    try:
        return cfg.qc.anchor.crop(load_frame(path, cfg))
    except RuntimeError:
        return None


def _summary(rows: list[QCRow]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.estado] = out.get(r.estado, 0) + 1
    return out


def write_qc_report(rows: list[QCRow], path: Path | str = QC_REPORT) -> Path:
    """Escribe el libro mayor por fotograma."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [f.name for f in fields(QCRow)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(names)
        for r in rows:
            writer.writerow(
                [
                    r.archivo,
                    f"{r.t_s:.3f}",
                    r.indice,
                    f"{r.mean_luma:.2f}",
                    f"{r.p05:.1f}",
                    f"{r.p95:.1f}",
                    f"{r.contraste:.2f}",
                    f"{r.blur_var:.2f}",
                    f"{r.ink_fraction:.4f}",
                    f"{r.anchor_ncc:.4f}",
                    r.dx,
                    r.dy,
                    r.estado,
                ]
            )
    return path


def load_qc_report(path: Path | str = QC_REPORT) -> list[QCRow]:
    """Lee el reporte de QC. ``read`` lo usa para saber que fotogramas procesar."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Corre primero: python -m spectro qc")
    rows: list[QCRow] = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(
                QCRow(
                    archivo=r["archivo"],
                    t_s=float(r["t_s"]),
                    indice=int(r["indice"]),
                    mean_luma=float(r["mean_luma"]),
                    p05=float(r["p05"]),
                    p95=float(r["p95"]),
                    contraste=float(r["contraste"]),
                    blur_var=float(r["blur_var"]),
                    ink_fraction=float(r["ink_fraction"]),
                    anchor_ncc=float(r["anchor_ncc"]),
                    dx=int(r.get("dx", 0) or 0),
                    dy=int(r.get("dy", 0) or 0),
                    estado=r["estado"],
                )
            )
    return rows


def load_offsets(
    path: Path | str, passed_only: bool = False
) -> dict[str, tuple[int, int]]:
    """``{archivo: (dx, dy)}`` del reporte de QC; ``{}`` si el reporte no existe.

    Es el corrimiento de camara que ``qc`` midio por fotograma: todo recorte de
    celda (``read``, ``teach``) lo aplica para caer sobre los mismos pixeles.
    ``passed_only`` deja solo los fotogramas que pasaron el filtro, en el orden
    del reporte.
    """
    path = Path(path)
    if not path.exists():
        return {}
    return {
        r.archivo: r.offset for r in load_qc_report(path) if r.passed_qc or not passed_only
    }
