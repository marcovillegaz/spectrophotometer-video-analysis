"""Calibrar el lector con valores reales: el usuario escribe lo que dice el display.

En vez de adivinar que es cada glifo en una hoja de contacto, el usuario escribe
el valor de unos cuantos fotogramas (``-0.018``). Como el formato es fijo, cada
celda del fotograma queda etiquetada sola: ``-``, ``0``, ``.``, ``0``, ``1``, ``8``.
Esos recortes forman la biblioteca de plantillas, y los mismos valores sirven de
**verdad de referencia** para medir cuanto se puede confiar en el lector.

La validacion es *leave-one-out*: cada muestra se lee con la biblioteca armada
**sin sus propios glifos**. Asi la exactitud no esta inflada por haber aprendido
justo lo que despues se pregunta.

Los valores se guardan como **texto** (``runs/<id>/truth.csv``) para conservar el
signo de ``-0.000`` y los ceros finales.

Interfaz publica:
    load_truth(path) / save_truth(path, samples)
    value_to_cells(text, digits) -> list[str]
    extract_sample(...)          -> SampleData
    build_pool(...)              -> (pool, datas)
    parse_value(text, digits)    -> str
    write_library(pool, directory, keep, max_per_label) -> dict[str, int]   (envoltorio de library.write)
    gather_runs(runs_dir, calib_dir, exclude) -> list[RunContext]
    train(runs, templates_dir, ...) -> TrainResult    (una o varias corridas)
    validate(datas, pool, cfg)   -> ValidationReport      (leave-one-out)
    evaluate_library(datas, library, cfg) -> ValidationReport
    coverage(samples, digits)    -> dict[str, int]
    suggest_frames(names, n)     -> list[str]
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .compat import read_csv_rows
from .config import DEFAULT_MAX_PER_LABEL, ROI, Config, DigitsConfig
from .extract import load_roi_sidecar
from . import library
from .imaging import cell_glyphs, load_frame
# ALL_CHARS y LibEntry se reexportan: teach_cli y teach_session las toman de aca.
from .library import ALL_CHARS, LibEntry, Template  # noqa: F401
from .project import CalibPaths, RunContext, RunPaths, list_runs

_VALUE_RE = re.compile(r"^(-)?(\d*)(?:\.(\d+))?$")


@dataclass
class Sample:
    """Un fotograma y el valor que el usuario leyo en el display."""

    file: str
    value: str


@dataclass
class Glyph:
    label: str
    image: np.ndarray
    source: str


@dataclass
class SampleData:
    """Todo lo que hace falta de una muestra: sus celdas, sus glifos y el fotograma."""

    sample: Sample
    cells: list[str]
    glyphs: list[Glyph]
    gray: np.ndarray
    offset: tuple[int, int] = (0, 0)
    #: Identificador unico de la muestra. Vale el nombre del fotograma salvo cuando se
    #: juntan varias corridas (``corrida/archivo``): los nombres se repiten entre videos.
    key: str = ""
    #: Config de la corrida de la que sale: cada video tiene su ROI, rotacion y celdas.
    cfg: Config | None = None
    #: ROI del sidecar ``.roi.json`` de la corrida (``extract --roi-only``), si hay.
    frames_roi: ROI | None = None

    @property
    def ident(self) -> str:
        return self.key or self.sample.file


@dataclass
class SampleResult:
    file: str
    typed: str
    read_value: str
    confidence: float
    status: str
    matches: bool
    missing: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    results: list[SampleResult] = field(default_factory=list)
    confusion: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def exact(self) -> int:
        return sum(1 for r in self.results if r.matches)

    @property
    def mismatches(self) -> list[SampleResult]:
        return [r for r in self.results if not r.matches]


# --------------------------------------------------------------------------
# Muestras (truth.csv)
# --------------------------------------------------------------------------
def load_truth(path: Path | str) -> list[Sample]:
    path = Path(path)
    if not path.exists():
        return []
    return [Sample(r["file"], r["value"]) for r in read_csv_rows(path) if r.get("file")]


def save_truth(path: Path | str, samples: list[Sample]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "value"])
        for s in sorted(samples, key=lambda s: s.file):
            writer.writerow([s.file, s.value])
    return path


def expected_format(digits: DigitsConfig) -> str:
    """Ejemplo legible del formato que espera la config, para los mensajes de error."""
    n = len(digits.digit_slots())
    dec = n - digits.decimal_after
    example = "0" * digits.decimal_after + ("." + "0" * dec if dec else "")
    return ("-" if digits.sign_slot is not None else "") + (example or "0")


def value_to_cells(text: str, digits: DigitsConfig) -> list[str]:
    """Una celda por slot: signo (``-`` o espacio), punto y digitos.

    Falla con el formato esperado si el texto no calza con la geometria de la
    config: es mejor rechazar un valor mal tipeado que aprender un glifo mal
    etiquetado.
    """
    text = text.strip().replace(",", ".")
    m = _VALUE_RE.match(text)
    dec = len(digits.digit_slots()) - digits.decimal_after
    if not m or not text or text in ("-", "."):
        raise ValueError(f"valor invalido {text!r}; formato esperado: {expected_format(digits)}")
    negative, ent, frac = bool(m.group(1)), m.group(2), m.group(3) or ""
    if negative and digits.sign_slot is None:
        raise ValueError(
            "este display se calibro sin celda de signo; calibra con --sign para valores negativos"
        )
    if len(ent) != digits.decimal_after or len(frac) != dec:
        raise ValueError(f"{text!r} no calza; formato esperado: {expected_format(digits)}")
    digs = iter(ent + frac)
    seps = set(digits.separator_slots or [])
    cells: list[str] = []
    for i in range(digits.n_digits):
        if i == digits.sign_slot:
            cells.append("-" if negative else " ")
        elif i in seps:
            cells.append(".")
        else:
            cells.append(next(digs))
    return cells


def parse_value(text: str, digits: DigitsConfig) -> str:
    """El valor tipeado, validado contra la geometria y normalizado (``0,245`` -> ``0.245``).

    Falla con el formato esperado (``ValueError``) si el texto no calza: es el unico
    punto por donde entra un valor escrito a mano (CLI y UI).
    """
    value_to_cells(text, digits)
    return text.strip().replace(",", ".")


def coverage(samples: list[Sample], digits: DigitsConfig) -> dict[str, int]:
    """Cuantas veces aparece cada caracter en las muestras (las invalidas no cuentan)."""
    out = {c: 0 for c in ALL_CHARS}
    for s in samples:
        try:
            for ch in value_to_cells(s.value, digits):
                if ch in out:
                    out[ch] += 1
        except ValueError:
            continue
    return out


def suggest_frames(names: list[str], n: int) -> list[str]:
    """``n`` fotogramas repartidos por la corrida: valores variados, no los mismos."""
    if not names or n <= 0:
        return []
    idx = np.linspace(0, len(names) - 1, min(n, len(names))).round().astype(int)
    return [names[i] for i in sorted(set(int(i) for i in idx))]


# --------------------------------------------------------------------------
# Extraccion de glifos y biblioteca
# --------------------------------------------------------------------------
def slot_glyphs(
    gray: np.ndarray, cfg: Config, offset: tuple[int, int] = (0, 0), frames_roi=None
) -> list[np.ndarray]:
    """El recorte normalizado de cada slot: **el mismo camino que ``read_frame``**."""
    return [c.image for c in cell_glyphs(gray, cfg, offset, frames_roi)]


def extract_sample(
    sample: Sample,
    cfg: Config,
    frames_dir: Path | str,
    offset: tuple[int, int] = (0, 0),
    frames_roi=None,
    prefix: str = "",
) -> SampleData:
    cells = value_to_cells(sample.value, cfg.digits)
    gray = load_frame(Path(frames_dir) / sample.file, cfg)
    images = slot_glyphs(gray, cfg, offset, frames_roi)
    glyphs = [
        Glyph(label=ch, image=img, source=prefix + sample.file)
        for ch, img in zip(cells, images)
        if ch != " "  # la celda de signo vacia se resuelve por tinta, no por plantilla
    ]
    return SampleData(sample, cells, glyphs, gray, offset, prefix + sample.file, cfg,
                      frames_roi)


def build_pool(
    samples: list[Sample],
    cfg: Config,
    frames_dir: Path | str,
    offsets: dict[str, tuple[int, int]] | None = None,
    prefix: str = "",
) -> tuple[list[Glyph], list[SampleData], list[str]]:
    """Extrae los glifos de todas las muestras. Devuelve ``(pool, datos, errores)``."""
    frames_roi = load_roi_sidecar(frames_dir)
    pool: list[Glyph] = []
    datas: list[SampleData] = []
    errors: list[str] = []
    for s in samples:
        try:
            d = extract_sample(s, cfg, frames_dir, (offsets or {}).get(s.file, (0, 0)),
                               frames_roi, prefix)
        except (ValueError, RuntimeError) as exc:
            errors.append(f"{s.file}: {exc}")
            continue
        datas.append(d)
        pool.extend(d.glyphs)
    return pool, datas, errors


def write_library(
    pool: list[Glyph], directory: Path | str, keep: bool = False,
    max_per_label: int = DEFAULT_MAX_PER_LABEL,
) -> dict[str, int]:
    """Escribe la biblioteca en ``directory``. Reemplaza, salvo ``keep``.

    Envoltorio de ``library.write``.
    """
    return library.write(pool, directory, "merge" if keep else "replace", max_per_label)


# --------------------------------------------------------------------------
# Varias corridas a la vez (teach train / teach check)
# --------------------------------------------------------------------------
def gather_runs(
    runs_dir: Path | str, calib_dir: Path | str, exclude: list[str] | tuple[str, ...] = ()
) -> list[RunContext]:
    """Las corridas con ``truth.csv`` no vacio, menos las de ``exclude``.

    Solo cuentan las muestras de **entrenamiento**: ``test.csv`` nunca entra a la
    biblioteca. Excluir una corrida sirve para reservarla como prueba (hold-out por
    video): su ``truth.csv`` queda sin usar.
    """
    calib = CalibPaths.at(calib_dir)
    out: list[RunContext] = []
    for run_id in list_runs(runs_dir=runs_dir):
        if run_id in exclude:
            continue
        run = RunPaths.for_run(run_id, runs_dir=runs_dir, calib_dir=calib_dir)
        if not run.config.exists():
            continue
        ctx = RunContext.load(run, calib)
        if ctx.train:
            out.append(ctx)
    return out


def build_pool_runs(
    runs: list[RunContext], prefixed: bool = True
) -> tuple[list[Glyph], list[SampleData], list[str]]:
    """Junta los glifos de todas las corridas. Cada muestra se identifica como ``corrida/archivo``.

    Cada corrida se recorta con **su** config (ROI, rotacion, celdas) y su corrimiento de
    camara; los glifos quedan normalizados al mismo tamano, asi que se pueden mezclar.
    ``prefixed=False`` deja el nombre del fotograma tal cual (el caso de una sola corrida).
    """
    pool: list[Glyph] = []
    datas: list[SampleData] = []
    errors: list[str] = []
    for run in runs:
        prefix = f"{run.run_id}/" if prefixed else ""
        p, d, e = build_pool(run.train, run.cfg, run.frames_dir, run.offsets, prefix)
        pool.extend(p)
        datas.extend(d)
        errors.extend(f"{prefix}{x}" for x in e)
    return pool, datas, errors


@dataclass
class TrainResult:
    """Lo que dejo ``train``: los glifos, la cobertura, la biblioteca escrita y las dos validaciones."""

    datas: list[SampleData]
    errors: list[str]
    #: Cuantas celdas de las muestras tiene cada caracter.
    coverage: dict[str, int] = field(default_factory=dict)
    #: Caracteres que la geometria necesita y ninguna muestra trae.
    missing: list[str] = field(default_factory=list)
    #: Plantillas escritas por caracter; ``None`` si no se pidio escribir.
    added: dict[str, int] | None = None
    loo: ValidationReport | None = None
    #: Lectura con la biblioteca vigente; ``None`` si todavia no hay biblioteca.
    current: ValidationReport | None = None
    #: Aviso de ``library.warn_missing_sign`` sobre la biblioteca vigente (``None`` si no aplica).
    sign_warning: str | None = None


def train(
    runs: list[RunContext],
    templates_dir: Path | str,
    *,
    build: bool = True,
    keep: bool = False,
    max_per_label: int = DEFAULT_MAX_PER_LABEL,
    prefixed: bool = True,
) -> TrainResult:
    """Arma (``build``) o solo valida la biblioteca con las muestras de una o varias corridas.

    Una corrida es el caso ``N = 1``. No imprime ni escribe informes: devuelve todo para
    que quien llama lo muestre. Si ninguna muestra se pudo procesar, ``datas`` queda vacio
    y no se toca la biblioteca.
    """
    pool, datas, errors = build_pool_runs(runs, prefixed)
    res = TrainResult(datas, errors)
    if not datas:
        return res
    cfg = runs[0].cfg
    res.coverage = {c: 0 for c in ALL_CHARS}
    for d in datas:
        for ch in d.cells:
            if ch in res.coverage:
                res.coverage[ch] += 1
    res.missing = [k for k, v in res.coverage.items()
                  if v == 0 and any(k in r.cfg.digits.required_chars() for r in runs)]
    if build:
        res.added = write_library(pool, templates_dir, keep, max_per_label)
    res.loo = validate(datas, pool, cfg)
    try:
        current = library.load(templates_dir)
    except FileNotFoundError:
        res.current = None
    else:
        res.current = evaluate_library(datas, current, cfg)
        res.sign_warning = next(
            (a for a in (library.warn_missing_sign(r.cfg, current) for r in runs) if a), None)
    return res


def split_by_run(report: ValidationReport, run_id: str) -> ValidationReport:
    """El pedazo de un informe conjunto que corresponde a ``run_id`` (sin el prefijo)."""
    prefix = f"{run_id}/"
    sub = ValidationReport()
    for res in report.results:
        if res.file.startswith(prefix):
            sub.results.append(SampleResult(
                res.file[len(prefix):], res.typed, res.read_value, res.confidence, res.status,
                res.matches, res.missing))
    return sub


# --------------------------------------------------------------------------
# Validacion
# --------------------------------------------------------------------------
def validate(datas: list[SampleData], pool: list[Glyph], cfg: Config) -> ValidationReport:
    """Leave-one-out: cada muestra se lee con la biblioteca sin sus propios glifos."""
    from .evaluation import evaluate, to_validation

    def library_for(d: SampleData):
        others = [g for g in pool if g.source != d.ident]
        present = {g.label for g in others}
        missing = sorted({ch for ch in d.cells if ch != " "} - present)
        return [Template(g.label, g.image, None, g.source) for g in others], missing

    return to_validation(evaluate(datas, library_for, cfg, skip_empty=True))


def evaluate_library(datas: list[SampleData], library: list[Template], cfg: Config) -> ValidationReport:
    """Que tan bien lee la biblioteca *vigente* los valores escritos (no es leave-one-out)."""
    from .evaluation import evaluate, to_validation

    return to_validation(evaluate(datas, lambda d: (library, []), cfg, skip_empty=True))


def write_report(report: ValidationReport, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "typed", "read_value", "confidence", "status", "matches", "missing"])
        for r in report.results:
            w.writerow([r.file, r.typed, r.read_value, f"{r.confidence:.3f}", r.status,
                        int(r.matches), "".join(r.missing)])
    return path


def format_report(report: ValidationReport, title: str = "validacion") -> list[str]:
    """Las lineas que se imprimen (y se muestran en la UI) tras validar."""
    lines = [f"{title}: {report.exact}/{report.total} lecturas exactas"]
    for r in report.mismatches[:10]:
        extra = f"  (sin ejemplos de {''.join(r.missing)!r} en las demas muestras)" if r.missing else ""
        lines.append(f"  {r.file}: escribiste {r.typed!r}, el lector leyo {r.read_value!r} "
                     f"[{r.status}, conf {r.confidence:.2f}]{extra}")
    if len(report.mismatches) > 10:
        lines.append(f"  ... y {len(report.mismatches) - 10} mas (ver teach_report.csv)")
    if report.confusion:
        top = ", ".join(f"{a!r}->{b!r} x{n}" for (a, b), n in report.confusion.most_common(5))
        lines.append(f"  confusiones: {top}")
    return lines
