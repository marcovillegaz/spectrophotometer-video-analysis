"""Etapa 6: salidas -> ``absorbancia.csv``, ``preview.png``, ``contact_sheet.png``.

``absorbancia.csv`` lleva **solo las filas validas**: las descartadas no se
interpolan ni se rellenan con ceros, quedan documentadas en ``qc_report.csv``.
Un hueco en la serie es informacion honesta; un valor inventado, no.

Columnas de ``absorbancia.csv``:

| columna      | contenido                                                     |
|--------------|---------------------------------------------------------------|
| t_s          | segundos desde el inicio del video                            |
| t_video      | hh:mm:ss.mmm, para volver al fotograma exacto                 |
| t_exp        | t_s + time.offset_s -> alinea con el log manual del laboratorio|
| absorbancia  | el valor leido                                                |
| confianza    | NCC minima entre los slots (0-1)                              |
| frame        | nombre del archivo, para trazabilidad                         |
| hora         | ISO de reloj, solo si time.absolute_start esta definido       |

Interfaz publica:
    run_report(cfg, ...) -> int         (cantidad de filas validas)
    batch_summary(runs, acceptance)     -> list[RunSummary]   (pura; una fila por corrida)
    load_run_input(run, calib, library) -> RunInput           (lee del disco lo que batch_summary necesita)
    resolve_acceptance(base, ...)       -> AcceptanceConfig   (calib/config.json con los flags encima)
    acceptance_for(calib_config, ...)   -> AcceptanceConfig   (lo mismo, leyendo el config de la calib)
    format_batch_table(rows) / write_batch_report(rows, path)

``batch_report.csv`` (una fila por corrida): fotogramas, descartes de qc por motivo
(``qc_<motivo>``, incluido ``qc_roi_fuera``), ``ok`` / ``low_confidence`` / ``spike``,
cobertura (ok / fotogramas), prueba (tipo, n, exactitud, error entre aceptadas),
plantillas, huella de la biblioteca, estado de las salidas y veredicto. El veredicto
(``acepta`` / ``revisar``) solo existe si hay umbrales (``acceptance`` o flags).
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
    decimales = max(len(cfg.digits.digit_slots()) - cfg.digits.decimal_after, 0)
    header = ["t_s", "t_video", "t_exp", "absorbancia", "confianza", "frame"]
    if start:
        header.append("hora")
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
                f"{r.valor:.{decimales}f}",
                f"{r.confianza:.4f}",
                r.archivo,
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
    ys = [r.valor for r in valid]
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
    peores = sorted((r for r in readings if r.valor is not None), key=lambda r: r.confianza)[:n]
    tiles, labels = [], []
    for r in peores:
        frame = frames_dir / r.archivo
        if not frame.exists():
            continue
        crop = crop_for_reading(load_frame(frame, cfg, color=True), cfg, frames_roi, (r.dx, r.dy))
        tiles.append(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
        labels.append(f"{r.valor:.3f} c={r.confianza:.2f} {r.estado}")
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
              "roi_fuera")

BATCH_REPORT_FIELDS = [
    "corrida", "fotogramas", *[f"qc_{m}" for m in QC_REASONS], "ok", "low_confidence", "spike",
    "cobertura", "tipo_prueba", "prueba", "exactitud", "error_aceptadas", "plantillas", "huella",
    "salidas", "veredicto", "detalle",
]


@dataclass
class RunInput:
    """Lo que ``batch_summary`` necesita de una corrida, ya leido del disco."""

    run_id: str
    #: ``estado`` de cada fotograma extraido, de ``qc_report.csv`` (con el resultado de ``read``).
    estados: list[str]
    #: Hay ``readings.csv``: si no, ``ok`` / ``low_confidence`` no significan nada todavia.
    leido: bool = True
    #: Evaluacion de ``test.csv`` con la biblioteca vigente, o ``None`` si no hay prueba.
    prueba: object | None = None
    plantillas: int = 0
    huella: str = ""
    #: ``read.outputs_state``: ``al_dia`` | ``desactualizadas`` | ``sin_huella`` | ``sin_lectura``.
    salidas: str = ""


@dataclass
class RunSummary:
    run_id: str
    fotogramas: int
    #: Fotogramas descartados antes de leer, por motivo (todos los de ``QC_REASONS``).
    qc: dict[str, int]
    ok: int | None
    low_confidence: int | None
    spike: int | None
    cobertura: float | None
    tipo_prueba: str = ""
    prueba: int = 0
    exactitud: float | None = None
    error_aceptadas: float | None = None
    plantillas: int = 0
    huella: str = ""
    salidas: str = ""
    #: ``acepta`` / ``revisar``; vacio si no hay umbrales.
    veredicto: str = ""
    detalle: str = ""

    @property
    def descartados_qc(self) -> int:
        return sum(self.qc.values())


def resolve_acceptance(base, min_exactitud=None, max_error=None, min_cobertura=None):
    """Los umbrales de ``calib/config.json`` (``base``) con los flags encima: el flag gana."""
    from .config import AcceptanceConfig

    for nombre, v in (("--min-exactitud", min_exactitud), ("--max-error", max_error),
                      ("--min-cobertura", min_cobertura)):
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError(f"{nombre} es una fraccion entre 0 y 1 (ej. 0.95), no {v}")
    return AcceptanceConfig(
        min_exactitud=min_exactitud if min_exactitud is not None else base.min_exactitud,
        max_error=max_error if max_error is not None else base.max_error,
        min_cobertura=min_cobertura if min_cobertura is not None else base.min_cobertura,
    )


def acceptance_for(calib_config, min_exactitud=None, max_error=None, min_cobertura=None):
    """Umbrales de ``calib/config.json`` (si existe) con los flags encima; valida los flags."""
    from .config import Config

    return resolve_acceptance(Config.load_or_default(calib_config).acceptance,
                              min_exactitud, max_error, min_cobertura)


def _veredicto(s: RunSummary, acc) -> tuple[str, str]:
    """``(veredicto, detalle)``. Sin umbrales fijados no hay veredicto: no se inventan."""
    if not acc.is_set():
        return "", ""
    razones: list[str] = []
    sin_prueba = False
    if acc.min_exactitud is not None:
        if s.exactitud is None:
            sin_prueba = True
        elif s.exactitud < acc.min_exactitud:
            razones.append(f"exactitud {s.exactitud:.1%} < {acc.min_exactitud:.1%}")
    if acc.max_error is not None:
        if s.error_aceptadas is None and s.prueba:
            razones.append("la prueba no tiene lecturas aceptadas: no se puede medir el error")
        elif s.error_aceptadas is None:
            sin_prueba = True
        elif s.error_aceptadas > acc.max_error:
            razones.append(f"error {s.error_aceptadas:.1%} > {acc.max_error:.1%}")
    if sin_prueba:
        razones.append("sin prueba que lo verifique")
    if acc.min_cobertura is not None:
        if s.cobertura is None:
            razones.append("sin lectura")
        elif s.cobertura < acc.min_cobertura:
            razones.append(f"cobertura {s.cobertura:.1%} < {acc.min_cobertura:.1%}")
    if s.salidas == "desactualizadas":
        razones.append("salidas anteriores a la biblioteca")
    elif s.salidas == "sin_lectura":
        razones.append("la corrida no tiene readings.csv")
    elif s.salidas == "sin_huella":
        razones.append("salidas sin huella (read_meta.json): no se sabe con que biblioteca se leyeron")
    return ("revisar" if razones else "acepta"), "; ".join(razones)


def batch_summary(runs: list[RunInput], acceptance=None) -> list[RunSummary]:
    """Una fila por corrida: descartes por motivo, lecturas, cobertura, prueba y veredicto.

    Funcion pura (no toca disco ni relee nada). ``acceptance`` es un
    ``config.AcceptanceConfig``; sin umbrales el veredicto queda vacio.
    """
    from .config import AcceptanceConfig

    acc = acceptance or AcceptanceConfig()
    out: list[RunSummary] = []
    for r in runs:
        total = len(r.estados)
        qc = {m: sum(1 for e in r.estados if e == m) for m in QC_REASONS}
        if r.leido:
            ok, low, spike = (sum(1 for e in r.estados if e == k)
                              for k in ("ok", "low_confidence", "spike"))
            cobertura = ok / total if total else 0.0
        else:
            ok = low = spike = cobertura = None
        s = RunSummary(r.run_id, total, qc, ok, low, spike, cobertura,
                       plantillas=r.plantillas, huella=r.huella, salidas=r.salidas)
        if r.prueba is not None and r.prueba.n:
            s.tipo_prueba, s.prueba = r.prueba.tipo, r.prueba.n
            s.exactitud = r.prueba.exactitud
            s.error_aceptadas = r.prueba.error_aceptadas if r.prueba.aceptadas else None
        s.veredicto, s.detalle = _veredicto(s, acc)
        out.append(s)
    return out


def load_run_input(
    run, calib, library: list, evaluar: bool = True, gap_s: float = 5.0, huella: str | None = None
) -> RunInput:
    """Arma el ``RunInput`` de una corrida desde sus archivos (sin releer los fotogramas).

    ``library`` es la biblioteca ya cargada (vacia si no hay); con ``evaluar`` mide
    ``test.csv`` con ella, que es la unica parte que abre fotogramas. ``huella`` es la de
    la biblioteca si quien llama ya la calculo. El resultado de la lectura sale de
    ``readings.csv``, no de la columna ``estado`` de ``qc_report.csv``: si se re-corrio
    ``qc`` sin ``read``, esa columna no dice nada de la lectura.
    """
    from .evaluation import evaluate_test
    from .library import fingerprint
    from .project import RunContext
    from .read import outputs_state

    huella = fingerprint(calib.templates) if huella is None else huella

    from .read import load_readings

    estado_lectura = ({r.archivo: r.estado for r in load_readings(run.readings)}
                      if run.readings.exists() else {})
    estados = []
    for r in (load_qc_report(run.qc_report) if run.qc_report.exists() else []):
        # un descarte de qc se cuenta tal cual; el resto, por lo que dijo ``read``
        estados.append(r.estado if r.estado in QC_REASONS
                       else estado_lectura.get(r.archivo, "sin_leer"))
    prueba = None
    if evaluar and library:
        ctx = RunContext.load(run, calib)
        if ctx.test:
            prueba = evaluate_test(ctx.test, ctx.cfg, ctx.frames_dir, ctx.offsets, library,
                                   ctx.train, gap_s)
    return RunInput(run.id, estados, run.readings.exists(), prueba, len(library),
                    huella, outputs_state(run.readings, calib.templates, huella))


def _pct(v: float | None, dec: int = 1) -> str:
    return "-" if v is None else f"{100 * v:.{dec}f}%"


def format_batch_table(rows: list[RunSummary]) -> list[str]:
    """La tabla que imprimen ``batch`` y ``teach test eval`` (el detalle por motivo va al CSV)."""
    cab = (f"  {'corrida':22s} {'fotog.':>6s} {'desc.qc':>7s} {'roi_fuera':>9s} {'ok':>6s} "
           f"{'baja':>5s} {'spike':>5s} {'cobert.':>8s} {'prueba':>10s} {'exact.':>7s} "
           f"{'error':>6s} {'plant.':>6s} {'huella':>12s} {'salidas':>15s}  veredicto")
    lines = [cab]
    n = lambda v: "-" if v is None else str(v)  # noqa: E731
    for s in rows:
        prueba = f"{s.prueba} {s.tipo_prueba.replace('misma_corrida', 'misma').replace('otro_video', 'otro')}" if s.prueba else "-"
        ver = s.veredicto + (f" ({s.detalle})" if s.detalle else "")
        lines.append(
            f"  {s.run_id:22s} {s.fotogramas:6d} {s.descartados_qc:7d} {s.qc['roi_fuera']:9d} "
            f"{n(s.ok):>6s} {n(s.low_confidence):>5s} {n(s.spike):>5s} {_pct(s.cobertura):>8s} "
            f"{prueba:>10s} {_pct(s.exactitud):>7s} {_pct(s.error_aceptadas):>6s} "
            f"{s.plantillas:6d} {s.huella or '-':>12s} {s.salidas or '-':>15s}  {ver}".rstrip())
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
                s.run_id, s.fotogramas, *[s.qc[m] for m in QC_REASONS],
                f(s.ok, "{}"), f(s.low_confidence, "{}"), f(s.spike, "{}"), f(s.cobertura),
                s.tipo_prueba, s.prueba or "", f(s.exactitud), f(s.error_aceptadas),
                s.plantillas, s.huella, s.salidas, s.veredicto, s.detalle,
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
    csv_path = out_dir / "absorbancia.csv"
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
    descartados = sum(1 for r in qc_rows if r.estado != "ok")
    if verbose:
        estados: dict[str, int] = {}
        for r in qc_rows:
            estados[r.estado] = estados.get(r.estado, 0) + 1
        print(f"\n  cuadre: {n} validas + {descartados} descartadas = {len(qc_rows)} extraidas", end="")
        print("  [ok]" if n + descartados == len(qc_rows) else "  [NO CUADRA]")
        for estado, count in sorted(estados.items(), key=lambda kv: -kv[1]):
            print(f"    {estado:16s} {count}")
        valid = [r for r in readings if r.is_valid]
        if valid:
            vals = [r.valor for r in valid]
            print(
                f"  absorbancia: min {min(vals):.3f}  max {max(vals):.3f}  "
                f"confianza minima {min(r.confianza for r in valid):.3f}"
            )
    return n
