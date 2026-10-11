"""Etapa 6: salidas -> ``absorbance.csv``, ``preview.png``, ``contact_sheet.png``.

``absorbance.csv`` lleva **solo las filas validas**: las descartadas no se
interpolan ni se rellenan con ceros, quedan documentadas en ``qc_report.csv``.
Un hueco en la serie es informacion honesta; un valor inventado, no.

Columnas de ``absorbance.csv``:

| columna      | contenido                                                     |
|--------------|---------------------------------------------------------------|
| t_s          | segundos desde el inicio del video                            |
| t_video      | hh:mm:ss.mmm, para volver al fotograma exacto                 |
| t_exp        | t_s + time.offset_s -> alinea con el log manual del laboratorio|
| absorbance   | el valor leido                                                |
| confidence   | NCC minima entre los slots (0-1)                              |
| frame        | nombre del archivo, para trazabilidad                         |
| datetime     | ISO de reloj, solo si time.absolute_start esta definido       |

Interfaz publica:
    run_report(cfg, ...) -> int         (cantidad de filas validas)
    batch_summary(runs, acceptance)     -> list[RunSummary]   (pura; una fila por corrida)
    load_run_input(run, calib, library) -> RunInput           (lee del disco lo que batch_summary necesita)
    resolve_acceptance(base, ...)       -> AcceptanceConfig   (calib/config.json con los flags encima)
    acceptance_for(calib_config, ...)   -> AcceptanceConfig   (lo mismo, leyendo el config de la calib)
    format_batch_table(rows) / write_batch_report(rows, path)

``batch_report.csv`` (una fila por corrida): fotogramas, descartes de qc por motivo
(``qc_<reason>``, incluido ``qc_roi_outside``), ``ok`` / ``low_confidence`` / ``spike``,
cobertura (ok / fotogramas), prueba (tipo, n, exactitud, error entre aceptadas),
plantillas, huella de la biblioteca, estado de las salidas y veredicto. El veredicto
(``accept`` / ``review``) solo existe si hay umbrales (``acceptance`` o flags).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from .config import Config
from .extract import FRAMES_DIR, format_hhmmss, load_roi_sidecar
from .imaging import contact_sheet, crop_for_reading, load_frame
from .qc import QC_REPORT, load_qc_report
from .read import READINGS, load_readings

#: Default relativo a la raiz de la corrida; ver ``extract.FRAMES_DIR``.
OUT_DIR = Path("out")
#: Cantidad de recortes de menor confianza que van a la hoja de contacto.
N_CONTACT_SHEET = 40


def _parse_absolute_start(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"time.absolute_start no se pudo interpretar: {value!r}. "
        "Formato esperado: 2026-09-01 16:42:20"
    )


def write_absorbance_csv(
    readings, cfg: Config, path: Path | str
) -> int:
    """Escribe el CSV final con las filas validas. Devuelve cuantas escribio."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = _parse_absolute_start(cfg.time.absolute_start)
    # Tantos decimales como digitos haya despues del punto en el display: el CSV
    # sale con la misma precision que el instrumento, y 0 se escribe "0.000".
    decimals = max(len(cfg.digits.digit_slots()) - cfg.digits.decimal_after, 0)
    header = ["t_s", "t_video", "t_exp", "absorbance", "confidence", "frame"]
    if start:
        header.append("datetime")
    n = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for r in readings:
            if not r.is_valid:
                continue
            row = [
                f"{r.t_s:.3f}",
                format_hhmmss(r.t_s),
                f"{r.t_s + cfg.time.offset_s:.3f}",
                f"{r.value:.{decimals}f}",
                f"{r.confidence:.4f}",
                r.file,
            ]
            if start:
                row.append((start + timedelta(seconds=r.t_s)).isoformat(timespec="milliseconds"))
            writer.writerow(row)
            n += 1
    return n


def plot_preview(readings, cfg: Config, path: Path | str) -> Path | None:
    """Grafico absorbancia vs tiempo, para revisar la curva de un vistazo."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid = [r for r in readings if r.is_valid]
    if not valid:
        return None
    xs = [r.t_s + cfg.time.offset_s for r in valid]
    ys = [r.value for r in valid]
    fig, ax = plt.subplots(figsize=(11, 4.5), dpi=130)
    ax.plot(xs, ys, lw=1.0, color="#1f4e79")
    ax.scatter(xs, ys, s=3, color="#1f4e79", alpha=0.5)
    if min(ys) < 0:
        ax.axhline(0.0, color="#888888", lw=0.8, ls="--")
    ax.set_xlabel("t_exp [s]")
    ax.set_ylabel("Absorbancia [Abs]")
    ax.set_title(f"Absorbancia vs tiempo  ({len(valid)} puntos validos)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def build_contact_sheet(
    readings, cfg: Config, frames_dir: Path | str, path: Path | str, n: int = N_CONTACT_SHEET
) -> Path | None:
    """Mosaico con los recortes de menor confianza, para auditarlos a ojo."""
    frames_dir = Path(frames_dir)
    frames_roi = load_roi_sidecar(frames_dir)
    worst = sorted((r for r in readings if r.value is not None), key=lambda r: r.confidence)[:n]
    tiles, labels = [], []
    for r in worst:
        frame = frames_dir / r.file
        if not frame.exists():
            continue
        crop = crop_for_reading(load_frame(frame, cfg, color=True), cfg, frames_roi, (r.dx, r.dy))
        tiles.append(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
        labels.append(f"{r.value:.3f} c={r.confidence:.2f} {r.status}")
    if not tiles:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), contact_sheet(tiles, labels, cols=8, tile_h=110))
    return path


# --------------------------------------------------------------------------
# Resumen por corrida (batch y teach test eval)
# --------------------------------------------------------------------------
#: Motivos por los que qc/read descartan un fotograma antes de leerlo, en el orden del reporte.
QC_REASONS = ("dark", "blown", "blur", "low_contrast", "occluded", "blank", "camera_moved",
              "roi_outside")

BATCH_REPORT_FIELDS = [
    "run", "frames", *[f"qc_{m}" for m in QC_REASONS], "ok", "low_confidence", "spike",
    "coverage", "test_kind", "test", "accuracy", "accepted_error", "templates", "fingerprint",
    "outputs", "verdict", "detail",
]


@dataclass
class RunInput:
    """Lo que ``batch_summary`` necesita de una corrida, ya leido del disco."""

    run_id: str
    #: ``status`` de cada fotograma extraido, de ``qc_report.csv`` (con el resultado de ``read``).
    statuses: list[str]
    #: Hay ``readings.csv``: si no, ``ok`` / ``low_confidence`` no significan nada todavia.
    read_value: bool = True
    #: Evaluacion de ``test.csv`` con la biblioteca vigente, o ``None`` si no hay prueba.
    test: object | None = None
    templates: int = 0
    fingerprint: str = ""
    #: ``read.outputs_state``: ``up_to_date`` | ``stale`` | ``no_fingerprint`` | ``no_reading``.
    outputs: str = ""


@dataclass
class RunSummary:
    run_id: str
    frames: int
    #: Fotogramas descartados antes de leer, por motivo (todos los de ``QC_REASONS``).
    qc: dict[str, int]
    ok: int | None
    low_confidence: int | None
    spike: int | None
    coverage: float | None
    test_kind: str = ""
    test: int = 0
    accuracy: float | None = None
    accepted_error: float | None = None
    templates: int = 0
    fingerprint: str = ""
    outputs: str = ""
    #: ``accept`` / ``review``; vacio si no hay umbrales.
    verdict: str = ""
    detail: str = ""

    @property
    def discarded_qc(self) -> int:
        return sum(self.qc.values())


def resolve_acceptance(base, min_accuracy=None, max_error=None, min_coverage=None):
    """Los umbrales de ``calib/config.json`` (``base``) con los flags encima: el flag gana."""
    from .config import AcceptanceConfig

    for name, v in (("--min-accuracy", min_accuracy), ("--max-error", max_error),
                      ("--min-coverage", min_coverage)):
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError(f"{name} es una fraccion entre 0 y 1 (ej. 0.95), no {v}")
    return AcceptanceConfig(
        min_accuracy=min_accuracy if min_accuracy is not None else base.min_accuracy,
        max_error=max_error if max_error is not None else base.max_error,
        min_coverage=min_coverage if min_coverage is not None else base.min_coverage,
    )


def acceptance_for(calib_config, min_accuracy=None, max_error=None, min_coverage=None):
    """Umbrales de ``calib/config.json`` (si existe) con los flags encima; valida los flags."""
    from .config import Config

    return resolve_acceptance(Config.load_or_default(calib_config).acceptance,
                              min_accuracy, max_error, min_coverage)


def _verdict(s: RunSummary, acc) -> tuple[str, str]:
    """``(veredicto, detalle)``. Sin umbrales fijados no hay veredicto: no se inventan."""
    if not acc.is_set():
        return "", ""
    reasons: list[str] = []
    no_test = False
    if acc.min_accuracy is not None:
        if s.accuracy is None:
            no_test = True
        elif s.accuracy < acc.min_accuracy:
            reasons.append(f"exactitud {s.accuracy:.1%} < {acc.min_accuracy:.1%}")
    if acc.max_error is not None:
        if s.accepted_error is None and s.test:
            reasons.append("la prueba no tiene lecturas aceptadas: no se puede medir el error")
        elif s.accepted_error is None:
            no_test = True
        elif s.accepted_error > acc.max_error:
            reasons.append(f"error {s.accepted_error:.1%} > {acc.max_error:.1%}")
    if no_test:
        reasons.append("sin prueba que lo verifique")
    if acc.min_coverage is not None:
        if s.coverage is None:
            reasons.append("sin lectura")
        elif s.coverage < acc.min_coverage:
            reasons.append(f"cobertura {s.coverage:.1%} < {acc.min_coverage:.1%}")
    if s.outputs == "stale":
        reasons.append("salidas anteriores a la biblioteca")
    elif s.outputs == "no_reading":
        reasons.append("la corrida no tiene readings.csv")
    elif s.outputs == "no_fingerprint":
        reasons.append("salidas sin huella (read_meta.json): no se sabe con que biblioteca se leyeron")
    return ("review" if reasons else "accept"), "; ".join(reasons)


def batch_summary(runs: list[RunInput], acceptance=None) -> list[RunSummary]:
    """Una fila por corrida: descartes por motivo, lecturas, cobertura, prueba y veredicto.

    Funcion pura (no toca disco ni relee nada). ``acceptance`` es un
    ``config.AcceptanceConfig``; sin umbrales el veredicto queda vacio.
    """
    from .config import AcceptanceConfig

    acc = acceptance or AcceptanceConfig()
    out: list[RunSummary] = []
    for r in runs:
        total = len(r.statuses)
        qc = {m: sum(1 for e in r.statuses if e == m) for m in QC_REASONS}
        if r.read_value:
            ok, low, spike = (sum(1 for e in r.statuses if e == k)
                              for k in ("ok", "low_confidence", "spike"))
            coverage = ok / total if total else 0.0
        else:
            ok = low = spike = coverage = None
        s = RunSummary(r.run_id, total, qc, ok, low, spike, coverage,
                       templates=r.templates, fingerprint=r.fingerprint, outputs=r.outputs)
        if r.test is not None and r.test.n:
            s.test_kind, s.test = r.test.kind, r.test.n
            s.accuracy = r.test.accuracy
            s.accepted_error = r.test.accepted_error if r.test.accepted else None
        s.verdict, s.detail = _verdict(s, acc)
        out.append(s)
    return out


def load_run_input(
    run, calib, library: list, with_eval: bool = True, gap_s: float = 5.0, fingerprint: str | None = None
) -> RunInput:
    """Arma el ``RunInput`` de una corrida desde sus archivos (sin releer los fotogramas).

    ``library`` es la biblioteca ya cargada (vacia si no hay); con ``evaluar`` mide
    ``test.csv`` con ella, que es la unica parte que abre fotogramas. ``fingerprint`` es la de
    la biblioteca si quien llama ya la calculo. El resultado de la lectura sale de
    ``readings.csv``, no de la columna ``status`` de ``qc_report.csv``: si se re-corrio
    ``qc`` sin ``read``, esa columna no dice nada de la lectura.
    """
    from .evaluation import evaluate_test
    from .library import fingerprint as library_fingerprint
    from .project import RunContext
    from .read import outputs_state

    fingerprint = library_fingerprint(calib.templates) if fingerprint is None else fingerprint

    from .read import load_readings

    read_status = ({r.file: r.status for r in load_readings(run.readings)}
                      if run.readings.exists() else {})
    statuses = []
    for r in (load_qc_report(run.qc_report) if run.qc_report.exists() else []):
        # un descarte de qc se cuenta tal cual; el resto, por lo que dijo ``read``
        statuses.append(r.status if r.status in QC_REASONS
                       else read_status.get(r.file, "not_read"))
    test = None
    if with_eval and library:
        ctx = RunContext.load(run, calib)
        if ctx.test:
            test = evaluate_test(ctx.test, ctx.cfg, ctx.frames_dir, ctx.offsets, library,
                                   ctx.train, gap_s)
    return RunInput(run.id, statuses, run.readings.exists(), test, len(library),
                    fingerprint, outputs_state(run.readings, calib.templates, fingerprint))


def _pct(v: float | None, dec: int = 1) -> str:
    return "-" if v is None else f"{100 * v:.{dec}f}%"


def format_batch_table(rows: list[RunSummary]) -> list[str]:
    """La tabla que imprimen ``batch`` y ``teach test eval`` (el detalle por motivo va al CSV)."""
    header = (f"  {'corrida':22s} {'fotog.':>6s} {'desc.qc':>7s} {'roi_outside':>11s} {'ok':>6s} "
           f"{'baja':>5s} {'spike':>5s} {'cobert.':>8s} {'prueba':>10s} {'exact.':>7s} "
           f"{'error':>6s} {'plant.':>6s} {'huella':>12s} {'salidas':>15s}  veredicto")
    lines = [header]
    n = lambda v: "-" if v is None else str(v)  # noqa: E731
    for s in rows:
        test = f"{s.test} {s.test_kind.replace('same_run', 'misma').replace('other_video', 'otro')}" if s.test else "-"
        verdict_text = s.verdict + (f" ({s.detail})" if s.detail else "")
        lines.append(
            f"  {s.run_id:22s} {s.frames:6d} {s.discarded_qc:7d} {s.qc['roi_outside']:11d} "
            f"{n(s.ok):>6s} {n(s.low_confidence):>5s} {n(s.spike):>5s} {_pct(s.coverage):>8s} "
            f"{test:>10s} {_pct(s.accuracy):>7s} {_pct(s.accepted_error):>6s} "
            f"{s.templates:6d} {s.fingerprint or '-':>12s} {s.outputs or '-':>15s}  {verdict_text}".rstrip())
    return lines


def write_batch_report(rows: list[RunSummary], path: Path | str) -> Path:
    """``runs/batch_report.csv``: una fila por corrida, con el detalle por motivo de qc."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def f(v, fmt="{:.4f}"):
        return "" if v is None else fmt.format(v)

    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(BATCH_REPORT_FIELDS)
        for s in rows:
            w.writerow([
                s.run_id, s.frames, *[s.qc[m] for m in QC_REASONS],
                f(s.ok, "{}"), f(s.low_confidence, "{}"), f(s.spike, "{}"), f(s.coverage),
                s.test_kind, s.test or "", f(s.accuracy), f(s.accepted_error),
                s.templates, s.fingerprint, s.outputs, s.verdict, s.detail,
            ])
    return path


def run_report(
    cfg: Config,
    readings_path: Path | str = READINGS,
    qc_path: Path | str = QC_REPORT,
    frames_dir: Path | str = FRAMES_DIR,
    out_dir: Path | str = OUT_DIR,
    no_plots: bool = False,
    verbose: bool = True,
) -> int:
    """Genera el CSV final, el grafico y la hoja de contacto. Devuelve filas validas."""
    out_dir = Path(out_dir)
    readings = load_readings(readings_path)
    csv_path = out_dir / "absorbance.csv"
    n = write_absorbance_csv(readings, cfg, csv_path)
    if verbose:
        print(f"== report ==\n  {n} filas validas -> {csv_path}")

    if not no_plots:
        preview = plot_preview(readings, cfg, out_dir / "preview.png")
        if preview and verbose:
            print(f"  grafico: {preview}")
        sheet = build_contact_sheet(readings, cfg, frames_dir, out_dir / "contact_sheet.png")
        if sheet and verbose:
            print(f"  hoja de contacto (menor confianza): {sheet}")

    # -- cuadre de conteos: que no se pierda ningun fotograma en silencio
    qc_rows = load_qc_report(qc_path)
    discarded = sum(1 for r in qc_rows if r.status != "ok")
    if verbose:
        statuses: dict[str, int] = {}
        for r in qc_rows:
            statuses[r.status] = statuses.get(r.status, 0) + 1
        print(f"\n  cuadre: {n} validas + {discarded} descartadas = {len(qc_rows)} extraidas", end="")
        print("  [ok]" if n + discarded == len(qc_rows) else "  [NO CUADRA]")
        for status, count in sorted(statuses.items(), key=lambda kv: -kv[1]):
            print(f"    {status:16s} {count}")
        valid = [r for r in readings if r.is_valid]
        if valid:
            vals = [r.value for r in valid]
            print(
                f"  absorbancia: min {min(vals):.3f}  max {max(vals):.3f}  "
                f"confianza minima {min(r.confidence for r in valid):.3f}"
            )
    return n
