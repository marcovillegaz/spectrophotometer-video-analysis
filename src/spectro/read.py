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
    write_read_meta(path, templates_dir, n) / load_read_meta(path)   (huella de la biblioteca)
    outputs_state(readings, templates_dir) -> str   (up_to_date | stale | no_fingerprint | no_reading)

``run_read`` escribe ``read_meta.json`` junto a ``readings.csv``: ``fingerprint`` de la biblioteca,
``date`` y cantidad de ``templates``. El formato de ``readings.csv`` no cambia.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .compat import normalize_keys, read_csv_rows
from .config import Config
from .extract import FRAMES_DIR, load_roi_sidecar
from .imaging import cell_glyphs, load_frame, ncc
from .qc import QC_REPORT, load_qc_report, write_qc_report
from .library import TEMPLATES_DIR, Template, fingerprint, load, warn_missing_sign

#: Default relativo a la raiz de la corrida; ver ``extract.FRAMES_DIR``.
READINGS = Path("out/readings.csv")
READ_META = Path("out/read_meta.json")


@dataclass
class Reading:
    """El resultado de leer un fotograma."""

    file: str
    t_s: float
    index: int
    value: float | None = None
    confidence: float = 0.0
    chars: str = ""
    #: Corrimiento aplicado a la ROI, heredado de qc.
    dx: int = 0
    dy: int = 0
    status: str = "ok"
    scores: list[float] = field(default_factory=list)
    #: Minimo del margen entre la mejor etiqueta y la mejor de otra etiqueta, por celda.
    #: Junto con ``confidence`` es lo que decide si una lectura se acepta.
    margin: float = 0.0

    @property
    def is_valid(self) -> bool:
        return self.status == "ok" and self.value is not None


def assemble(digits: str, decimal_after: int, negative: bool = False) -> float:
    """Arma el numero con el punto decimal fijo: ``"0597", 1 -> 0.597``.

    ``negative`` aplica el signo; ``-0.000`` se normaliza a ``0.0``.
    """
    if not digits or not digits.isdigit():
        raise ValueError(f"Cadena de digitos invalida: {digits!r}")
    if not 0 <= decimal_after <= len(digits):
        raise ValueError(
            f"decimal_after={decimal_after} fuera de rango para {len(digits)} digitos"
        )
    integer = digits[:decimal_after] or "0"
    decimals = digits[decimal_after:]
    value = float(f"{integer}.{decimals}") if decimals else float(integer)
    return -value if negative and value != 0.0 else value


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
    reading = Reading(file="", t_s=0.0, index=0)
    separators = set(cfg.digits.separator_slots or [])
    sign_slot = cfg.digits.sign_slot
    negative = False

    chars: list[str] = []
    scores: list[float] = []
    margins: list[float] = []
    for i, cell in enumerate(cell_glyphs(gray, cfg, offset, frames_roi)):
        if i == sign_slot:
            # Se decide por tinta, no por NCC: una celda vacia con ruido no
            # correlaciona con nada y seria un falso descarte.
            if cell.is_empty(cfg.digits):
                chars.append(" ")
                scores.append(1.0)
                continue
            label, best, margin = match_slot(cell.image, library)
            scores.append(best)
            margins.append(margin)
            chars.append(label)
            if (
                label != "-"
                or best < cfg.templates.min_score
                or margin < cfg.templates.min_margin
            ):
                reading.status = "low_confidence"
            else:
                negative = True
            continue
        label, best, margin = match_slot(cell.image, library)
        scores.append(best)
        margins.append(margin)
        chars.append(label)
        if best < cfg.templates.min_score or margin < cfg.templates.min_margin:
            reading.status = "low_confidence"
        if i in separators and label != ".":
            # El separador no matcheo un punto: la ROI no esta donde deberia.
            reading.status = "low_confidence"
        if i not in separators and not label.isdigit():
            reading.status = "low_confidence"

    reading.chars = "".join(chars)
    reading.scores = scores
    reading.confidence = float(min(scores)) if scores else 0.0
    reading.margin = float(min(margins)) if margins else 1.0
    if reading.status == "ok":
        skip = separators | ({sign_slot} if sign_slot is not None else set())
        digits = "".join(c for i, c in enumerate(chars) if i not in skip)
        try:
            reading.value = assemble(digits, cfg.digits.decimal_after, negative)
        except ValueError:
            reading.status = "low_confidence"
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
        rate_prev = abs(cur.value - prev.value) / dt_prev
        rate_next = abs(cur.value - nxt.value) / dt_next
        rate_span = abs(nxt.value - prev.value) / dt_span
        if rate_prev > max_rate and rate_next > max_rate and rate_span <= max_rate:
            cur.status = "spike"
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
    library = load(templates_dir)
    qc_rows = load_qc_report(qc_path)
    frames_roi = load_roi_sidecar(frames_dir)
    labels = sorted({t.label for t in library})
    if verbose:
        print(f"== read ==\n  biblioteca: {len(library)} plantillas ({', '.join(labels)})")
    warning = warn_missing_sign(cfg, library)
    if warning:  # solo avisa: las lecturas y el codigo de salida no cambian
        print("  " + warning.replace("\n", "\n  "), file=sys.stderr)

    readings: list[Reading] = []
    for row in qc_rows:
        if not row.passed_qc:
            continue
        try:
            gray = load_frame(frames_dir / row.file, cfg)
        except RuntimeError:
            continue
        try:
            reading = read_frame(gray, cfg, library, frames_roi, row.offset)
        except ValueError:  # la ROI no cabe en el fotograma: lectura descartada
            reading = Reading(row.file, row.t_s, row.index, status="roi_outside")
        reading.file, reading.t_s, reading.index = row.file, row.t_s, row.index
        reading.dx, reading.dy = row.dx, row.dy
        readings.append(reading)

    spikes = flag_spikes(readings, cfg.read.max_rate)
    write_readings(readings, output)
    write_read_meta(Path(output).with_name(READ_META.name), templates_dir, len(library))

    status_by_file = {r.file: r.status for r in readings}
    for row in qc_rows:
        if row.file in status_by_file:
            row.status = status_by_file[row.file]
    write_qc_report(qc_rows, qc_path)

    if verbose:
        valid = sum(1 for r in readings if r.is_valid)
        low = sum(1 for r in readings if r.status == "low_confidence")
        print(f"  {valid}/{len(readings)} lecturas validas")
        if low:
            print(f"    descartadas por baja confianza: {low}")
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
            ["file", "t_s", "index", "value", "confidence", "margin", "chars", "dx", "dy",
             "status"]
        )
        for r in readings:
            writer.writerow(
                [
                    r.file,
                    f"{r.t_s:.3f}",
                    r.index,
                    "" if r.value is None else f"{r.value:.6g}",
                    f"{r.confidence:.4f}",
                    f"{r.margin:.4f}",
                    r.chars,
                    r.dx,
                    r.dy,
                    r.status,
                ]
            )
    return path


def write_read_meta(path: Path | str, templates_dir: Path | str, n_templates: int) -> Path:
    """Guarda la huella de la biblioteca con la que se leyo (junto a ``readings.csv``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "fingerprint": fingerprint(templates_dir),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "templates": n_templates,
    }
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path


def load_read_meta(path: Path | str) -> dict | None:
    """El ``read_meta.json`` de una corrida, o ``None`` si no existe o no se puede leer."""
    path = Path(path)
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return normalize_keys(meta) if isinstance(meta, dict) else None


#: Estados de las salidas de una corrida frente a la biblioteca vigente (``outputs_state``).
NO_READING, UP_TO_DATE, STALE, NO_FINGERPRINT = (
    "no_reading", "up_to_date", "stale", "no_fingerprint")


def outputs_state(
    readings: Path | str, templates_dir: Path | str, lib_fingerprint: str | None = None
) -> str:
    """Si ``readings.csv`` se produjo con la biblioteca de hoy.

    Compara la huella de ``read_meta.json`` con la de la biblioteca. Un ``readings.csv``
    anterior a la huella (sin ``read_meta.json``) se juzga por fecha: mas viejo que la
    plantilla mas nueva = ``stale``; si no, ``no_fingerprint`` (no se sabe). ``fingerprint``
    evita recalcular la de la biblioteca cuando quien llama ya la tiene.
    """
    readings = Path(readings)
    if not readings.exists():
        return NO_READING
    meta = load_read_meta(readings.with_name(READ_META.name))
    if meta is not None:
        actual = fingerprint(templates_dir) if lib_fingerprint is None else lib_fingerprint
        return UP_TO_DATE if meta.get("fingerprint") == actual else STALE
    templates = list(Path(templates_dir).glob("*.png")) if Path(templates_dir).is_dir() else []
    if any(p.stat().st_mtime > readings.stat().st_mtime for p in templates):
        return STALE
    return NO_FINGERPRINT


def load_readings(path: Path | str = READINGS) -> list[Reading]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Corre primero: python -m spectro read")
    out: list[Reading] = []
    for r in read_csv_rows(path):
        out.append(
            Reading(
                file=r["file"],
                t_s=float(r["t_s"]),
                index=int(r["index"]),
                value=float(r["value"]) if r["value"] else None,
                confidence=float(r["confidence"]),
                margin=float(r.get("margin") or 0.0),
                chars=r["chars"],
                dx=int(r.get("dx", 0) or 0),
                dy=int(r.get("dy", 0) or 0),
                status=r["status"],
            )
        )
    return out
