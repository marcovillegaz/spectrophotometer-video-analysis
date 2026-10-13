"""Evaluacion sobre el conjunto de prueba (hold-out): cuanto se puede confiar en el lector.

El conjunto de prueba (``runs/<id>/test/test.csv``) **nunca entra a la biblioteca**: son
fotogramas con valor conocido que el lector no vio al aprender. Se lee cada uno con
la biblioteca vigente y el resultado se separa en tres, porque al proyecto le importa
mas abstenerse que equivocarse:

* ``correct``    el lector acepto la lectura y coincide con el valor escrito;
* ``wrong``     el lector acepto la lectura y **no** coincide (lo grave);
* ``discarded``  el lector se abstuvo (``low_confidence``): un hueco honesto.

Se informa la tasa de error *entre las aceptadas* y la cobertura (aceptadas / total),
con intervalos de Wilson al 95 %, que no se salen de [0, 1] ni con pocas muestras.

Dos advertencias que el informe repite porque inflan la exactitud sin avisar:

* **valores distintos**: si los fotogramas de prueba comparten pocos valores, la
  prueba es mas chica de lo que parece y el intervalo (que supone independencia) es
  optimista;
* **tipo**: ``same_run`` mide ese video; ``other_video`` (la corrida no tiene
  entrenamiento propio) es el hold-out por video, la prueba mas honesta.

Interfaz publica:
    wilson(k, n, z=1.96)                       -> (lo, hi)
    evaluate(datas, library, cfg)              -> list[Lectura]   (el unico evaluador)
    to_validation(lecturas)                    -> ValidationReport
    to_test_report(lecturas, ...)              -> TestReport   (con ``confusion`` y ``char_total`` por caracter)
    evaluate_test(...)                         -> TestReport      (envoltorio)
    format_test_report(report)                 -> list[str]
    write_test_report(report, path)            -> Path
    append_history(path, report, when, fingerprint) -> Path   (columna ``fingerprint`` al final; tolera historiales viejos)
    load_history(path)                         -> list[dict]
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .compat import read_csv_rows
from .config import Config
from .read import Reading, read_frame
from .sampling import leakage
from .library import Template
from .teach import Sample, SampleData, SampleResult, ValidationReport, build_pool

#: Cabecera de ``teach_history.csv``: una fila por evaluacion.
HISTORY_FIELDS = [
    "date", "kind", "templates", "training", "test", "distinct_values",
    "correct", "wrong", "discarded", "accuracy", "accepted_error", "coverage", "fingerprint",
]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza de Wilson para una proporcion ``k/n`` (95 % por defecto)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


@dataclass
class TestResult:
    __test__ = False  # que pytest no lo tome por una clase de tests

    file: str
    typed: str
    read_value: str
    status: str
    confidence: float
    result: str  # correcta | erronea | descartada


@dataclass
class TestReport:
    __test__ = False

    results: list[TestResult] = field(default_factory=list)
    kind: str = "other_video"
    n_train: int = 0
    n_templates: int = 0
    leaks: list[tuple[str, str, float]] = field(default_factory=list)
    missing_chars: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: Celdas mal leidas: ``(esperado, leido) -> veces`` (sin contar el espacio esperado).
    confusion: Counter = field(default_factory=Counter)
    #: Celdas de la prueba por caracter esperado (sin contar el espacio).
    char_total: Counter = field(default_factory=Counter)

    def _count(self, what: str) -> int:
        return sum(1 for r in self.results if r.result == what)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return self._count("correct")

    @property
    def wrong(self) -> int:
        return self._count("wrong")

    @property
    def discarded(self) -> int:
        return self._count("discarded")

    @property
    def accepted(self) -> int:
        return self.correct + self.wrong

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def accepted_error(self) -> float:
        return self.wrong / self.accepted if self.accepted else 0.0

    @property
    def coverage(self) -> float:
        return self.accepted / self.n if self.n else 0.0

    @property
    def distinct_values(self) -> int:
        return len({r.typed for r in self.results})


@dataclass
class SampleRead:
    """Una muestra leida con una biblioteca: lo que comparten la validacion y la prueba."""

    data: SampleData
    #: ``None`` si no habia con que leer (biblioteca vacia y ``skip_empty``).
    reading: Reading | None
    #: Caracteres de la muestra que la biblioteca usada no tiene (solo leave-one-out).
    missing: list[str] = field(default_factory=list)


def evaluate(
    datas: list[SampleData],
    library: list[Template] | Callable[[SampleData], tuple[list[Template], list[str]]],
    cfg: Config,
    skip_empty: bool = False,
) -> list[SampleRead]:
    """Lee cada muestra con la biblioteca: **el unico evaluador** del proyecto.

    ``library`` es una lista (la biblioteca vigente, igual para todas) o una funcion
    ``muestra -> (plantillas, faltan)`` (leave-one-out: la biblioteca sin los glifos de
    la propia muestra). La lectura es ``read.read_frame``, la misma que usa ``read``.
    El resultado se reduce a un informe con ``to_validation`` o ``to_test_report``.
    """
    out: list[SampleRead] = []
    for d in datas:
        lib, missing = library(d) if callable(library) else (library, [])
        reading = None if (skip_empty and not lib) else read_frame(
            d.gray, d.cfg or cfg, lib, d.frames_roi, d.offset)
        out.append(SampleRead(d, reading, missing))
    return out


def to_validation(reads: list[SampleRead]) -> ValidationReport:
    """Reduce a ``ValidationReport``: coincidencia exacta con lo escrito y confusiones."""
    report = ValidationReport()
    for item in reads:
        d, r = item.data, item.reading
        if r is None:
            report.results.append(SampleResult(
                d.ident, d.sample.value, "", 0.0, "no_library", False, item.missing))
            continue
        expected = "".join(d.cells)
        ok = r.chars == expected and r.status == "ok"
        report.results.append(SampleResult(
            d.ident, d.sample.value, r.chars.strip(), r.confidence, r.status,
            ok, item.missing))
        for want, got in zip(expected, r.chars):
            if want != got:
                report.confusion[(want, got)] += 1
    return report


def to_test_report(
    reads: list[SampleRead], library: list[Template], train: list[Sample], gap_s: float,
    test: list[Sample], errors: list[str],
) -> TestReport:
    """Reduce a ``TestReport``: correcta / erronea / descartada y exactitud por caracter."""
    report = TestReport(
        kind="same_run" if train else "other_video",
        n_train=len(train),
        n_templates=len(library),
        leaks=leakage(train, test, gap_s) if train else [],
    )
    report.errors = errors
    labels = {t.label for t in library}
    absent: set[str] = set()
    for item in reads:
        d, r = item.data, item.reading
        expected = "".join(d.cells)
        accepted = r.status == "ok"
        if not accepted:
            res = "discarded"
        elif r.chars == expected:
            res = "correct"
        else:
            res = "wrong"
        report.results.append(TestResult(
            d.sample.file, d.sample.value, r.chars.strip(), r.status, r.confidence, res))
        for want, got in zip(expected, r.chars):
            if want == " ":
                continue
            report.char_total[want] += 1
            if want != got:
                report.confusion[(want, got)] += 1
            if want not in labels:
                absent.add(want)
    report.missing_chars = sorted(absent)
    return report


def evaluate_test(
    test: list[Sample],
    cfg: Config,
    frames_dir: Path | str,
    offsets: dict[str, tuple[int, int]] | None,
    library: list[Template],
    train: list[Sample] | None = None,
    gap_s: float = 5.0,
) -> TestReport:
    """Lee cada fotograma de prueba con la biblioteca vigente y clasifica el resultado."""
    train = train or []
    _, datas, errors = build_pool(test, cfg, frames_dir, offsets)
    return to_test_report(evaluate(datas, library, cfg), library, train, gap_s, test, errors)


def format_test_report(report: TestReport, title: str = "prueba") -> list[str]:
    """Las lineas que se imprimen (y se muestran en la UI) tras evaluar."""
    n = report.n
    if n == 0:
        return [f"{title}: no hay muestras de prueba"]
    kind = ("misma corrida (optimista: mide este video)" if report.kind == "same_run"
            else "otro video (hold-out por video)")
    lines = [f"{title} [{kind}]: {n} muestras, {report.distinct_values} valores distintos"]
    lo, hi = wilson(report.correct, n)
    lines.append(f"  correctas {report.correct}/{n} = {report.accuracy:.1%}  [IC95 {lo:.1%} a {hi:.1%}]")
    if report.accepted:
        elo, ehi = wilson(report.wrong, report.accepted)
        lines.append(f"  erroneas aceptadas {report.wrong}/{report.accepted} = "
                     f"{report.accepted_error:.1%}  [IC95 {elo:.1%} a {ehi:.1%}]")
    else:
        lines.append("  erroneas aceptadas: el lector no acepto ninguna lectura")
    lines.append(f"  descartadas {report.discarded}/{n}   cobertura {report.coverage:.1%}")
    if report.distinct_values < n / 2:
        lines.append(f"  aviso: solo {report.distinct_values} valores distintos en {n} fotogramas; "
                     "el intervalo supone muestras independientes y es optimista")
    if report.leaks:
        lines.append(f"  aviso: {len(report.leaks)} fotogramas de prueba estan a menos de unos segundos de "
                     "uno de entrenamiento (casi el mismo fotograma): la exactitud puede estar inflada")
    if report.missing_chars:
        lines.append(f"  aviso: la biblioteca no tiene {', '.join(report.missing_chars)}; "
                     "esos caracteres no se pueden leer")
    if report.kind == "same_run":
        lines.append("  para medir videos nuevos, reserva un video sin entrenamiento propio como prueba")
    for e in report.errors:
        lines.append(f"  muestra descartada: {e}")
    return lines


def summary_lines(report: TestReport) -> list[str]:
    """Tres lineas cortas para el panel de la UI (el detalle completo va a consola)."""
    n = report.n
    if n == 0:
        return ["prueba: no hay muestras"]
    lo, hi = wilson(report.correct, n)
    warnings = report.distinct_values < n / 2 or bool(report.leaks) or bool(report.missing_chars)
    kind = "misma corrida" if report.kind == "same_run" else "otro video"
    return [
        f"{'! ' if warnings else ''}prueba ({kind}): {n} muestras, {report.distinct_values} valores",
        f"{report.correct} correctas · {report.wrong} erroneas · {report.discarded} descartadas",
        f"exactitud {report.accuracy:.0%} [{lo:.0%}-{hi:.0%}]  error aceptadas {report.accepted_error:.1%}",
    ]


def write_test_report(report: TestReport, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "typed", "read_value", "status", "confidence", "result"])
        for r in report.results:
            w.writerow([r.file, r.typed, r.read_value, r.status, f"{r.confidence:.3f}", r.result])
    return path


def append_history(
    path: Path | str, report: TestReport, when: datetime | None = None, fingerprint: str = ""
) -> Path:
    """Agrega una fila al historial: la curva de aprendizaje por ronda.

    ``fingerprint`` es la de la biblioteca con la que se evaluo (``library.fingerprint``). Un
    historial anterior a esa columna se completa con valores vacios antes de agregar.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    if not is_new:
        old = load_history(path)
        with path.open(encoding="utf-8", newline="") as fh:
            raw_header = next(csv.reader(fh), [])
        if old and raw_header != HISTORY_FIELDS:  # historial viejo: encabezado en espanol o sin ``fingerprint``
            with path.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(HISTORY_FIELDS)
                for f in old:
                    w.writerow([f.get(k, "") for k in HISTORY_FIELDS])
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if is_new:
            w.writerow(HISTORY_FIELDS)
        w.writerow([
            (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), report.kind,
            report.n_templates, report.n_train, report.n, report.distinct_values,
            report.correct, report.wrong, report.discarded,
            f"{report.accuracy:.4f}", f"{report.accepted_error:.4f}", f"{report.coverage:.4f}",
            fingerprint,
        ])
    return path


def load_history(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return read_csv_rows(path)
