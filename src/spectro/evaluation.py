"""Evaluacion sobre el conjunto de prueba (hold-out): cuanto se puede confiar en el lector.

El conjunto de prueba (``runs/<id>/test.csv``) **nunca entra a la biblioteca**: son
fotogramas con valor conocido que el lector no vio al aprender. Se lee cada uno con
la biblioteca vigente y el resultado se separa en tres, porque al proyecto le importa
mas abstenerse que equivocarse:

* ``correcta``    el lector acepto la lectura y coincide con el valor escrito;
* ``erronea``     el lector acepto la lectura y **no** coincide (lo grave);
* ``descartada``  el lector se abstuvo (``low_confidence``): un hueco honesto.

Se informa la tasa de error *entre las aceptadas* y la cobertura (aceptadas / total),
con intervalos de Wilson al 95 %, que no se salen de [0, 1] ni con pocas muestras.

Dos advertencias que el informe repite porque inflan la exactitud sin avisar:

* **valores distintos**: si los fotogramas de prueba comparten pocos valores, la
  prueba es mas chica de lo que parece y el intervalo (que supone independencia) es
  optimista;
* **tipo**: ``misma_corrida`` mide ese video; ``otro_video`` (la corrida no tiene
  entrenamiento propio) es el hold-out por video, la prueba mas honesta.

Interfaz publica:
    wilson(k, n, z=1.96)                       -> (lo, hi)
    evaluate(datas, library, cfg)              -> list[Lectura]   (el unico evaluador)
    to_validation(lecturas)                    -> ValidationReport
    to_test_report(lecturas, ...)              -> TestReport
    evaluate_test(...)                         -> TestReport      (envoltorio)
    format_test_report(report)                 -> list[str]
    write_test_report(report, path)            -> Path
    append_history(path, report, ...)          -> Path
    load_history(path)                         -> list[dict]
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config
from .read import Reading, read_frame
from .sampling import leakage
from .library import Template
from .teach import Sample, SampleData, SampleResult, ValidationReport, build_pool

#: Cabecera de ``teach_history.csv``: una fila por evaluacion.
HISTORY_FIELDS = [
    "fecha", "tipo", "plantillas", "entrenamiento", "prueba", "valores_distintos",
    "correctas", "erroneas", "descartadas", "exactitud", "error_aceptadas", "cobertura",
]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza de Wilson para una proporcion ``k/n`` (95 % por defecto)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    mitad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - mitad), min(1.0, centro + mitad)


@dataclass
class TestResult:
    __test__ = False  # que pytest no lo tome por una clase de tests

    archivo: str
    escrito: str
    leido: str
    estado: str
    confianza: float
    resultado: str  # correcta | erronea | descartada


@dataclass
class TestReport:
    __test__ = False

    results: list[TestResult] = field(default_factory=list)
    tipo: str = "otro_video"
    n_train: int = 0
    n_templates: int = 0
    leaks: list[tuple[str, str, float]] = field(default_factory=list)
    missing_chars: list[str] = field(default_factory=list)
    char_accuracy: dict[str, tuple[int, int]] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)

    def _count(self, what: str) -> int:
        return sum(1 for r in self.results if r.resultado == what)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def correctas(self) -> int:
        return self._count("correcta")

    @property
    def erroneas(self) -> int:
        return self._count("erronea")

    @property
    def descartadas(self) -> int:
        return self._count("descartada")

    @property
    def aceptadas(self) -> int:
        return self.correctas + self.erroneas

    @property
    def exactitud(self) -> float:
        return self.correctas / self.n if self.n else 0.0

    @property
    def error_aceptadas(self) -> float:
        return self.erroneas / self.aceptadas if self.aceptadas else 0.0

    @property
    def cobertura(self) -> float:
        return self.aceptadas / self.n if self.n else 0.0

    @property
    def valores_distintos(self) -> int:
        return len({r.escrito for r in self.results})


@dataclass
class Lectura:
    """Una muestra leida con una biblioteca: lo que comparten la validacion y la prueba."""

    data: SampleData
    #: ``None`` si no habia con que leer (biblioteca vacia y ``skip_empty``).
    reading: Reading | None
    #: Caracteres de la muestra que la biblioteca usada no tiene (solo leave-one-out).
    faltan: list[str] = field(default_factory=list)


def evaluate(
    datas: list[SampleData],
    library: list[Template] | Callable[[SampleData], tuple[list[Template], list[str]]],
    cfg: Config,
    skip_empty: bool = False,
) -> list[Lectura]:
    """Lee cada muestra con la biblioteca: **el unico evaluador** del proyecto.

    ``library`` es una lista (la biblioteca vigente, igual para todas) o una funcion
    ``muestra -> (plantillas, faltan)`` (leave-one-out: la biblioteca sin los glifos de
    la propia muestra). La lectura es ``read.read_frame``, la misma que usa ``read``.
    El resultado se reduce a un informe con ``to_validation`` o ``to_test_report``.
    """
    out: list[Lectura] = []
    for d in datas:
        lib, faltan = library(d) if callable(library) else (library, [])
        reading = None if (skip_empty and not lib) else read_frame(
            d.gray, d.cfg or cfg, lib, d.frames_roi, d.offset)
        out.append(Lectura(d, reading, faltan))
    return out


def to_validation(lecturas: list[Lectura]) -> ValidationReport:
    """Reduce a ``ValidationReport``: coincidencia exacta con lo escrito y confusiones."""
    report = ValidationReport()
    for item in lecturas:
        d, r = item.data, item.reading
        if r is None:
            report.results.append(SampleResult(
                d.ident, d.sample.valor, "", 0.0, "sin_biblioteca", False, item.faltan))
            continue
        expected = "".join(d.cells)
        ok = r.caracteres == expected and r.estado == "ok"
        report.results.append(SampleResult(
            d.ident, d.sample.valor, r.caracteres.strip(), r.confianza, r.estado,
            ok, item.faltan))
        for want, got in zip(expected, r.caracteres):
            if want != got:
                report.confusion[(want, got)] += 1
    return report


def to_test_report(
    lecturas: list[Lectura], library: list[Template], train: list[Sample], gap_s: float,
    test: list[Sample], errores: list[str],
) -> TestReport:
    """Reduce a ``TestReport``: correcta / erronea / descartada y exactitud por caracter."""
    report = TestReport(
        tipo="misma_corrida" if train else "otro_video",
        n_train=len(train),
        n_templates=len(library),
        leaks=leakage(train, test, gap_s) if train else [],
    )
    report.errores = errores
    labels = {t.label for t in library}
    absent: set[str] = set()
    per_char: dict[str, list[int]] = {}
    for item in lecturas:
        d, r = item.data, item.reading
        expected = "".join(d.cells)
        accepted = r.estado == "ok"
        if not accepted:
            res = "descartada"
        elif r.caracteres == expected:
            res = "correcta"
        else:
            res = "erronea"
        report.results.append(TestResult(
            d.sample.archivo, d.sample.valor, r.caracteres.strip(), r.estado, r.confianza, res))
        for want, got in zip(expected, r.caracteres):
            if want == " ":
                continue
            c = per_char.setdefault(want, [0, 0])
            c[1] += 1
            c[0] += want == got
            if want not in labels:
                absent.add(want)
    report.char_accuracy = {k: (v[0], v[1]) for k, v in sorted(per_char.items())}
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
    _, datas, errores = build_pool(test, cfg, frames_dir, offsets)
    return to_test_report(evaluate(datas, library, cfg), library, train, gap_s, test, errores)


def format_test_report(report: TestReport, title: str = "prueba") -> list[str]:
    """Las lineas que se imprimen (y se muestran en la UI) tras evaluar."""
    n = report.n
    if n == 0:
        return [f"{title}: no hay muestras de prueba"]
    tipo = ("misma corrida (optimista: mide este video)" if report.tipo == "misma_corrida"
            else "otro video (hold-out por video)")
    lines = [f"{title} [{tipo}]: {n} muestras, {report.valores_distintos} valores distintos"]
    lo, hi = wilson(report.correctas, n)
    lines.append(f"  correctas {report.correctas}/{n} = {report.exactitud:.1%}  [IC95 {lo:.1%} a {hi:.1%}]")
    if report.aceptadas:
        elo, ehi = wilson(report.erroneas, report.aceptadas)
        lines.append(f"  erroneas aceptadas {report.erroneas}/{report.aceptadas} = "
                     f"{report.error_aceptadas:.1%}  [IC95 {elo:.1%} a {ehi:.1%}]")
    else:
        lines.append("  erroneas aceptadas: el lector no acepto ninguna lectura")
    lines.append(f"  descartadas {report.descartadas}/{n}   cobertura {report.cobertura:.1%}")
    if report.valores_distintos < n / 2:
        lines.append(f"  aviso: solo {report.valores_distintos} valores distintos en {n} fotogramas; "
                     "el intervalo supone muestras independientes y es optimista")
    if report.leaks:
        lines.append(f"  aviso: {len(report.leaks)} fotogramas de prueba estan a menos de unos segundos de "
                     "uno de entrenamiento (casi el mismo fotograma): la exactitud puede estar inflada")
    if report.missing_chars:
        lines.append(f"  aviso: la biblioteca no tiene {', '.join(report.missing_chars)}; "
                     "esos caracteres no se pueden leer")
    if report.tipo == "misma_corrida":
        lines.append("  para medir videos nuevos, reserva un video sin entrenamiento propio como prueba")
    for e in report.errores:
        lines.append(f"  muestra descartada: {e}")
    return lines


def summary_lines(report: TestReport) -> list[str]:
    """Tres lineas cortas para el panel de la UI (el detalle completo va a consola)."""
    n = report.n
    if n == 0:
        return ["prueba: no hay muestras"]
    lo, hi = wilson(report.correctas, n)
    avisos = report.valores_distintos < n / 2 or bool(report.leaks) or bool(report.missing_chars)
    tipo = "misma corrida" if report.tipo == "misma_corrida" else "otro video"
    return [
        f"{'! ' if avisos else ''}prueba ({tipo}): {n} muestras, {report.valores_distintos} valores",
        f"{report.correctas} correctas · {report.erroneas} erroneas · {report.descartadas} descartadas",
        f"exactitud {report.exactitud:.0%} [{lo:.0%}-{hi:.0%}]  error aceptadas {report.error_aceptadas:.1%}",
    ]


def write_test_report(report: TestReport, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["archivo", "escrito", "leido", "estado", "confianza", "resultado"])
        for r in report.results:
            w.writerow([r.archivo, r.escrito, r.leido, r.estado, f"{r.confianza:.3f}", r.resultado])
    return path


def append_history(path: Path | str, report: TestReport, when: datetime | None = None) -> Path:
    """Agrega una fila al historial: la curva de aprendizaje por ronda."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if nuevo:
            w.writerow(HISTORY_FIELDS)
        w.writerow([
            (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), report.tipo,
            report.n_templates, report.n_train, report.n, report.valores_distintos,
            report.correctas, report.erroneas, report.descartadas,
            f"{report.exactitud:.4f}", f"{report.error_aceptadas:.4f}", f"{report.cobertura:.4f}",
        ])
    return path


def load_history(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))
