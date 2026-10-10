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
"""

from __future__ import annotations

import csv
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
    # Tantos decimales como dígitos haya despues del punto en el display: el CSV
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
