"""Etapa 5: fotograma -> numero, por correlacion cruzada normalizada (NCC).

Para cada fotograma que paso QC: se recorta la ROI, se binariza, se parte en
slots y cada slot se compara contra toda la biblioteca de plantillas. Gana el
caracter con mayor NCC, y solo si le saca margen suficiente al segundo mejor
*de otra etiqueta*; si no, la lectura entera se descarta en vez de inventar un
digito.

El valor se arma con el punto decimal **fijo** de ``config.json``, no con el
punto leido: el punto es el glifo mas chico y el mas facil de confundir, asi
que se lo usa solo como control de alineacion (si el slot separador no matchea
un punto, la ROI se corrio y la lectura se descarta).

Estados que puede agregar esta etapa al libro mayor de QC:
    low_confidence  algun slot no llego al umbral de score o de margen
    spike           salto aislado contra los vecinos: firma de un digito mal leido

Interfaz publica:
    run_read(cfg, ...) -> list[Reading]
    read_frame(gray, cfg, library, frames_roi) -> Reading
    assemble(digits, decimal_after) -> float
    load_readings(path) -> list[Reading]
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import Config
from .extract import FRAMES_DIR, load_roi_sidecar
from .imaging import binarize, crop_for_reading, load_gray, ncc, normalize_glyph, slot_boxes
from .qc import QC_REPORT, load_qc_report, write_qc_report
from .templates import TEMPLATES_DIR, Template, load_templates

#: Default relativo a la raiz de la corrida; ver ``extract.FRAMES_DIR``.
READINGS = Path("out/readings.csv")


@dataclass
class Reading:
    """El resultado de leer un fotograma."""

    archivo: str
    t_s: float
    indice: int
    valor: float | None = None
    confianza: float = 0.0
    caracteres: str = ""
    #: Corrimiento aplicado a la ROI, heredado de qc.
    dx: int = 0
    dy: int = 0
    estado: str = "ok"
    scores: list[float] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.estado == "ok" and self.valor is not None


def assemble(digits: str, decimal_after: int) -> float:
    """Arma el numero con el punto decimal fijo: ``"0597", 1 -> 0.597``."""
    if not digits or not digits.isdigit():
        raise ValueError(f"Cadena de digitos invalida: {digits!r}")
    if not 0 <= decimal_after <= len(digits):
        raise ValueError(
            f"decimal_after={decimal_after} fuera de rango para {len(digits)} digitos"
        )
    entero = digits[:decimal_after] or "0"
    decimales = digits[decimal_after:]
    return float(f"{entero}.{decimales}") if decimales else float(entero)


def match_slot(glyph: np.ndarray, library: list[Template]) -> tuple[str, float, float]:
    """Devuelve ``(etiqueta, mejor_score, margen)`` del slot contra la biblioteca.

    El margen se mide contra la mejor plantilla de una etiqueta **distinta**:
    tener dos plantillas del mismo digito no debe penalizar la confianza.
    """
    best_by_label: dict[str, float] = {}
    for tpl in library:
        score = ncc(glyph, tpl.image)
        if score > best_by_label.get(tpl.label, -2.0):
            best_by_label[tpl.label] = score
    ranked = sorted(best_by_label.items(), key=lambda kv: -kv[1])
    label, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    return label, best, best - second


def read_frame(
    gray: np.ndarray,
    cfg: Config,
    library: list[Template],
    frames_roi=None,
    offset: tuple[int, int] = (0, 0),
) -> Reading:
    """Lee un fotograma ya cargado. Sin efectos secundarios: util en los tests.

    ``offset`` es el corrimiento que midio ``qc`` para este fotograma: la ROI se
    mueve con la escena en vez de quedarse clavada en coordenadas absolutas.
    """
    reading = Reading(archivo="", t_s=0.0, indice=0)
    roi = crop_for_reading(gray, cfg, frames_roi, offset)
    binary = binarize(roi, cfg.digits.polarity)
    separators = set(cfg.digits.separator_slots or [])

    chars: list[str] = []
    scores: list[float] = []
    for i, (x0, x1) in enumerate(slot_boxes(roi.shape[1], cfg.digits)):
        glyph = normalize_glyph(binary[:, x0:x1], cfg.templates.size)
        label, best, margin = match_slot(glyph, library)
        scores.append(best)
        chars.append(label)
        if best < cfg.templates.min_score or margin < cfg.templates.min_margin:
            reading.estado = "low_confidence"
        if i in separators and label != ".":
            # El separador no matcheo un punto: la ROI no esta donde deberia.
            reading.estado = "low_confidence"
        if i not in separators and not label.isdigit():
            reading.estado = "low_confidence"

    reading.caracteres = "".join(chars)
    reading.scores = scores
    reading.confianza = float(min(scores)) if scores else 0.0
    if reading.estado == "ok":
        digits = "".join(c for i, c in enumerate(chars) if i not in separators)
        try:
            reading.valor = assemble(digits, cfg.digits.decimal_after)
        except ValueError:
            reading.estado = "low_confidence"
    return reading


def flag_spikes(readings: list[Reading], max_rate: float) -> int:
    """Marca como ``spike`` los saltos aislados contra ambos vecinos.

    Solo se marca si el punto se despega de los dos vecinos *y* los vecinos son
    coherentes entre si: una transicion real y rapida del experimento no se
    descarta, un digito mal leido si.
    """
    valid = [r for r in readings if r.is_valid]
    flagged = 0
    for prev, cur, nxt in zip(valid, valid[1:], valid[2:]):
        dt_prev = cur.t_s - prev.t_s
        dt_next = nxt.t_s - cur.t_s
        dt_span = nxt.t_s - prev.t_s
        if min(dt_prev, dt_next, dt_span) <= 0:
            continue
        rate_prev = abs(cur.valor - prev.valor) / dt_prev
        rate_next = abs(cur.valor - nxt.valor) / dt_next
        rate_span = abs(nxt.valor - prev.valor) / dt_span
        if rate_prev > max_rate and rate_next > max_rate and rate_span <= max_rate:
            cur.estado = "spike"
            flagged += 1
    return flagged


def run_read(
    cfg: Config,
    frames_dir: Path | str = FRAMES_DIR,
    qc_path: Path | str = QC_REPORT,
    templates_dir: Path | str = TEMPLATES_DIR,
    output: Path | str = READINGS,
    verbose: bool = True,
) -> list[Reading]:
    """Lee todos los fotogramas que pasaron QC y actualiza el libro mayor."""
    frames_dir = Path(frames_dir)
    library = load_templates(templates_dir)
    qc_rows = load_qc_report(qc_path)
    frames_roi = load_roi_sidecar(frames_dir)
    etiquetas = sorted({t.label for t in library})
    if verbose:
        print(f"== read ==\n  biblioteca: {len(library)} plantillas ({', '.join(etiquetas)})")

    readings: list[Reading] = []
    for row in qc_rows:
        if not row.passed_qc:
            continue
        try:
            gray = load_gray(frames_dir / row.archivo)
        except RuntimeError:
            continue
        reading = read_frame(gray, cfg, library, frames_roi, row.offset)
        reading.archivo, reading.t_s, reading.indice = row.archivo, row.t_s, row.indice
        reading.dx, reading.dy = row.dx, row.dy
        readings.append(reading)

    spikes = flag_spikes(readings, cfg.read.max_rate)
    write_readings(readings, output)

    estado_por_archivo = {r.archivo: r.estado for r in readings}
    for row in qc_rows:
        if row.archivo in estado_por_archivo:
            row.estado = estado_por_archivo[row.archivo]
    write_qc_report(qc_rows, qc_path)

    if verbose:
        validas = sum(1 for r in readings if r.is_valid)
        baja = sum(1 for r in readings if r.estado == "low_confidence")
        print(f"  {validas}/{len(readings)} lecturas validas")
        if baja:
            print(f"    descartadas por baja confianza: {baja}")
        if spikes:
            print(f"    descartadas por spike (|dAbs|/dt > {cfg.read.max_rate}): {spikes}")
        print(f"  lecturas crudas: {output}")
        print(f"  estado actualizado en {qc_path}")
    return readings


def write_readings(readings: list[Reading], path: Path | str = READINGS) -> Path:
    """Escribe todas las lecturas, incluidas las descartadas, para poder auditarlas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["archivo", "t_s", "indice", "valor", "confianza", "caracteres", "dx", "dy", "estado"]
        )
        for r in readings:
            writer.writerow(
                [
                    r.archivo,
                    f"{r.t_s:.3f}",
                    r.indice,
                    "" if r.valor is None else f"{r.valor:.6g}",
                    f"{r.confianza:.4f}",
                    r.caracteres,
                    r.dx,
                    r.dy,
                    r.estado,
                ]
            )
    return path


def load_readings(path: Path | str = READINGS) -> list[Reading]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Corre primero: python -m spectro read")
    out: list[Reading] = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append(
                Reading(
                    archivo=r["archivo"],
                    t_s=float(r["t_s"]),
                    indice=int(r["indice"]),
                    valor=float(r["valor"]) if r["valor"] else None,
                    confianza=float(r["confianza"]),
                    caracteres=r["caracteres"],
                    dx=int(r.get("dx", 0) or 0),
                    dy=int(r.get("dy", 0) or 0),
                    estado=r["estado"],
                )
            )
    return out
