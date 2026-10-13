"""Interfaz de linea de comandos: ``python -m spectro <comando>``.

Un subcomando por etapa del pipeline, mas ``run`` que los encadena, ``batch``
que procesa varios videos y ``doctor`` que diagnostica el entorno. Cada handler
importa su modulo de forma perezosa, para que ``doctor`` siga funcionando aunque
falte alguna dependencia.

Comandos:
    doctor      diagnostico del entorno (Python, paquetes, ffmpeg, corridas)
    new         da de alta una corrida a partir de un video
    extract     video -> runs/<id>/frames/
    calibrate   define ROI, slots y polaridad -> runs/<id>/config.json
    teach       biblioteca, muestras y pruebas, por areas (ver teach_cli.py)
    qc         filtro de calidad -> runs/<id>/out/qc_report.csv
    read        fotogramas -> valores numericos
    report      -> absorbance.csv, preview.png, contact_sheet.png
    run         extract -> qc -> read -> report
    batch       new -> extract -> calibrate --auto -> run, por cada video, y runs/batch_report.csv
    summary     efectividad del lector en un solo lugar: runs/summary.csv, summary_chars.csv y summary.html

Las rutas no se tipean: ``--run <id>`` deriva las nueve desde ``RunPaths``
(ver ``project.py``). Un flag explicito siempre le gana a lo derivado, asi que
se puede apuntar una etapa a una carpeta cualquiera sin dejar de usar ``--run``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import teach_cli
from .config import ROI, Config
from .project import (
    CALIB_DIR,
    RUNS_DIR,
    VIDEOS_DIR,
    CalibPaths,
    RunPaths,
    list_runs,
    run_id_from_video,
    seed_run_config,
)


def _parse_roi(text: str) -> ROI:
    """``"x,y,w,h"`` -> ROI. Usado por los flags no interactivos."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("La ROI se escribe como x,y,w,h")
    try:
        x, y, w, h = (int(round(float(p))) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"ROI invalida: {text}") from exc
    return ROI(x=x, y=y, w=w, h=h)


# --------------------------------------------------------------------------
# Resolucion de rutas: --run deriva, un flag explicito gana
# --------------------------------------------------------------------------
#: Cada flag de ruta y de donde sale cuando viene en ``None``. Es la tabla que
#: convierte un ``--run <id>`` en las nueve rutas del pipeline.
_DERIVED_PATHS = {
    "config": lambda run, calib: run.config,
    "output": lambda run, calib: run.frames,
    "frames_dir": lambda run, calib: run.frames,
    "index": lambda run, calib: run.index,
    "out_dir": lambda run, calib: run.out,
    "qc_report": lambda run, calib: run.qc_report,
    "readings": lambda run, calib: run.readings,
    "templates_dir": lambda run, calib: calib.templates,
    "preview": lambda run, calib: run.preview,
}


def _run_missing_message(args: argparse.Namespace, missing: list[str]) -> str:
    """El error de ``--run`` ausente, con las corridas disponibles listadas.

    Adivinar cual es la corrida mezclaria datos de dos experimentos en silencio,
    que es la peor forma de perder datos de laboratorio: sin ruido.
    """
    runs = list_runs(runs_dir=args.runs_dir)
    flags = ", ".join("--" + f.replace("_", "-") for f in missing)
    lines = [
        f"falta --run: no se sabe sobre que corrida trabajar ({flags} sin valor).",
    ]
    if runs:
        lines.append(f"Corridas disponibles en {args.runs_dir}/:")
        lines += [f"  {c}" for c in runs]
        lines.append(f"Ejemplo: python -m spectro {args.command} --run {runs[-1]}")
    else:
        lines.append(f"No hay ninguna corrida en {args.runs_dir}/. Crea una con:")
        lines.append("  python -m spectro new videos/<video>.MOV")
    lines.append("Tambien podes pasar las rutas a mano: " + flags)
    return "\n".join(lines)


def resolve_paths(args: argparse.Namespace) -> str | None:
    """Completa las rutas en ``None`` desde ``--run``. Devuelve el error, o None.

    Deja ademas ``args.calib_paths`` para los handlers que necesitan el layout de
    ``calib/`` (``calibrate --auto``, ``doctor``).
    """
    args.calib_paths = CalibPaths.at(args.calib_dir)
    run_paths = (
        RunPaths.for_run(args.run, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        if getattr(args, "run", None)
        else None
    )

    # doctor, new y batch miran el layout entero, no una corrida: no exigen --run.
    if not getattr(args, "needs_paths", True):
        return None
    present = [name for name in _DERIVED_PATHS if hasattr(args, name)]
    if run_paths is not None:
        for name in present:
            if getattr(args, name) is None:  # un flag explicito le gana a lo derivado
                setattr(args, name, str(_DERIVED_PATHS[name](run_paths, args.calib_paths)))

    missing = [name for name in present if getattr(args, name) is None]
    if missing:
        return _run_missing_message(args, missing)
    return None


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    """Reporta el estado del entorno; primera linea de troubleshooting."""
    import platform

    print("== spectro doctor ==")
    print(f"Python      : {platform.python_version()}  ({sys.executable})")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    print(f"venv activo : {'si' if in_venv else 'NO (se recomienda .venv)'}")

    print("\nPaquetes:")
    ok = True
    for mod, label in (
        ("numpy", "numpy"),
        ("cv2", "opencv-python"),
        ("matplotlib", "matplotlib"),
        ("imageio_ffmpeg", "imageio-ffmpeg"),
    ):
        try:
            m = __import__(mod)
            print(f"  [ok]     {label:16s} {getattr(m, '__version__', '?')}")
        except ImportError:
            ok = False
            print(f"  [FALTA]  {label:16s} -> pip install -r requirements.txt")

    print("\nffmpeg:")
    try:
        from .extract import has_hwaccel, resolve_ffmpeg

        tools = resolve_ffmpeg()
        print(f"  origen    : {tools.source}")
        print(f"  ffmpeg    : {tools.ffmpeg}")
        print(f"  version   : {tools.version or '?'}")
        print(f"  ffprobe   : {tools.ffprobe or 'NO DISPONIBLE'}")
        if tools.source != "system":
            print(
                "  aviso     : se esta usando el respaldo del venv. Sin ffprobe los\n"
                "              metadatos se leen del stderr de ffmpeg. Para el binario\n"
                "              del sistema: winget install Gyan.FFmpeg y reabrir la terminal."
            )
        accels = has_hwaccel(tools)
        print(f"  hwaccel   : {', '.join(accels) if accels else 'ninguno'}")
    except Exception as exc:  # pragma: no cover
        ok = False
        print(f"  [ERROR] {exc}")

    calib = args.calib_paths
    print(f"\nCalib compartida ({calib.root}/):")
    if calib.config.exists():
        cfg = Config.load(calib.config)
        print(f"  config.json     : ROI={cfg.roi.as_tuple()} "
              f"n_digits={cfg.digits.n_digits} decimal_after={cfg.digits.decimal_after} "
              f"ancla={cfg.qc.anchor.as_tuple()}")
    else:
        print("  config.json     : no existe "
              "(calibra una corrida y corre: calibrate --run <id> --promote)")
    print(f"  reference.jpg   : {'si' if calib.reference.exists() else 'NO (calibrate --auto no puede registrar)'}")
    print(f"  templates/      : {calib.n_templates()} plantillas")

    runs = list_runs(runs_dir=args.runs_dir)
    print(f"\nCorridas ({args.runs_dir}/): {len(runs)}")
    for run_id in runs:
        run = RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        n_frames = len(list(run.frames.glob("t_*.jpg"))) if run.frames.is_dir() else 0
        if run.config.exists():
            cfg = Config.load(run.config)
            status = "calibrada" if cfg.roi.is_valid() else "SIN CALIBRAR"
            video = Path(cfg.video).name or "?"
        else:
            status, video = "sin config.json", "?"
        output_label = run.existing_absorbance.name if run.is_done() else "sin salida"
        print(f"  {run_id:22s} {status:14s} {n_frames:5d} fotogramas  {output_label:15s} video={video}")
    if not runs:
        print("  (ninguna) crea una con: python -m spectro new videos/<video>.MOV")

    print("\nEstado:", "listo" if ok else "faltan dependencias")
    return 0 if ok else 1


def cmd_new(args: argparse.Namespace) -> int:
    """Da de alta una corrida: crea ``runs/<id>/`` y siembra su ``config.json``.

    No toca el video ni lo copia: la corrida lo referencia por ruta.
    """
    video = Path(args.video)
    if not video.exists():
        print(f"No existe el video: {video}")
        return 2
    run_id = run_id_from_video(video, args.name)
    run = RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
    calib = args.calib_paths

    print(f"== new ==\n  video : {video}\n  id    : {run_id}")
    if run.config.exists() and not args.force:
        print(f"  la corrida ya existe: {run.config} (usa --force para re-sembrarla)")
        return 0

    if calib.config.exists():
        base = Config.load(calib.config)
        print(f"  receta: {calib.config}")
    else:
        base = Config.default()
        print(f"  receta: {calib.config} no existe todavia; se siembra con los defaults")
    cfg = seed_run_config(base, video, args.fps)
    run.create()
    cfg.save(run.config)
    print(f"  creada {run.root}/  (config, frames/, out/)")
    print(f"  fps   : {args.fps}")
    print("  siguiente paso:")
    print(f"    python -m spectro extract --run {run_id}")
    print(f"    python -m spectro calibrate --run {run_id} --auto   (o sin --auto para hacerlo a mano)")
    return 0


#: Etapas de ``batch`` en orden. ``--until`` corta despues de la indicada.
BATCH_STAGES = ("new", "extract", "calibrate", "qc", "read", "report")


def batch_stages(until: str = "report") -> list[str]:
    """Las etapas que ``batch`` corre: de ``new`` hasta ``until`` inclusive."""
    if until not in BATCH_STAGES[3:]:
        raise ValueError(f"--until debe ser uno de {', '.join(BATCH_STAGES[3:])}")
    return list(BATCH_STAGES[: BATCH_STAGES.index(until) + 1])


def cmd_batch(args: argparse.Namespace) -> int:
    """Por cada video: new -> extract -> calibrate --auto -> qc -> read -> report.

    Una corrida que no engancha la calibracion automatica **no se procesa a
    medias**: se saltea y se informa al final, para calibrarla a mano.
    """
    from .report import acceptance_for

    # los umbrales se validan antes de procesar nada: un flag mal tipeado no debe costar horas
    acc = acceptance_for(args.calib_paths.config, args.min_accuracy, args.max_error,
                         args.min_coverage)
    videos = _expand_videos(args.videos)
    if not videos:
        print("No hay videos que procesar.")
        return 2

    print(f"== batch ==\n  {len(videos)} video(s), fps={args.fps}")
    done: list[str] = []
    skipped_runs: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []

    for i, video in enumerate(videos, 1):
        run_id = run_id_from_video(video, None)
        run = RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        print(f"\n--- [{i}/{len(videos)}] {video.name} -> {run_id} ---")

        if run.is_done() and args.skip_existing:
            print(f"  ya tiene {run.absorbance}; se saltea (--no-skip-existing para rehacerla)")
            skipped_runs.append((run_id, "ya procesada"))
            continue

        # Se re-invoca el parser en vez de armar Namespaces a mano: asi cada
        # etapa recibe exactamente los mismos defaults que en la linea de comandos.
        global_args = ["--runs-dir", str(args.runs_dir), "--calib-dir", str(args.calib_dir)]
        run_args = global_args + ["--run", run_id]
        stages: list[tuple[str, list[str]]] = [
            ("new", global_args + ["new", str(video), "--fps", str(args.fps), "--force"]),
            ("extract", run_args + ["extract", "--fps", str(args.fps)]),
            ("calibrate", run_args + ["calibrate", "--auto",
                                           "--search-px", str(args.search_px),
                                           "--min-score", str(args.min_score)]),
            ("qc", run_args + ["qc"]),
            ("read", run_args + ["read"]),
            ("report", run_args + ["report"]),
        ]

        allowed = batch_stages(args.until)
        for stage, argv in (e for e in stages if e[0] in allowed):
            rc = main(argv)
            if rc:
                if stage == "calibrate":
                    print(f"  calibracion automatica sin exito: {run_id} queda pendiente")
                    skipped_runs.append((run_id, "pendiente de calibracion manual"))
                else:
                    failed.append((run_id, f"fallo en {stage} (codigo {rc})"))
                break
        else:
            done.append(run_id)

    print(f"\n== resumen del lote ==")
    for run_id in done:
        print(f"  [ok]       {run_id:22s} " + ("procesada" if args.until == "report"
                                                else f"preparada hasta {args.until}"))
    for run_id, reason in skipped_runs:
        print(f"  [salteada] {run_id:22s} {reason}")
    for run_id, reason in failed:
        print(f"  [ERROR]    {run_id:22s} {reason}")
    pending = [r for r, m in skipped_runs if "manual" in m]
    if pending:
        print("\n  Pendientes de calibracion manual:")
        for run_id in pending:
            print(f"    python -m spectro calibrate --run {run_id}")
    if args.until == "report":
        _batch_report(args, done + [r for r, m in skipped_runs if m == "ya procesada"], acc)
    return 1 if failed else 0


def _batch_report(args: argparse.Namespace, run_ids: list[str], acc) -> None:
    """Imprime y escribe ``runs/batch_report.csv``: una fila por corrida procesada (o ya hecha)."""
    from .library import fingerprint
    from .report import batch_summary, format_batch_table, load_run_input, write_batch_report

    if not run_ids:
        return
    calib = args.calib_paths
    lib, lib_fp = teach_cli.library_or_empty(args), fingerprint(calib.templates)
    entries = [
        load_run_input(RunPaths.for_run(r, runs_dir=args.runs_dir, calib_dir=args.calib_dir),
                       calib, lib, fingerprint=lib_fp)
        for r in sorted(run_ids)
    ]
    rows = batch_summary(entries, acc)
    dest = write_batch_report(rows, Path(args.runs_dir) / "batch_report.csv")
    print("\n== reporte del lote ==")
    for line in format_batch_table(rows):
        print(line)
    if not acc.is_set():
        print("  sin umbrales de aceptacion: el veredicto queda vacio. Fijalos con "
              "--min-accuracy / --max-error / --min-coverage o en la seccion 'acceptance' "
              "de calib/config.json")
    print(f"  reporte: {dest}")


def cmd_summary(args: argparse.Namespace) -> int:
    """Reporte general de efectividad (solo lectura sobre los datos). Ver ``summary.py``."""
    from . import library
    from .report import acceptance_for
    from .summary import (
        format_summary, load_all, summarize, write_chars_csv, write_html, write_summary_csv,
    )

    calib = args.calib_paths
    lib = library.load(calib.templates)  # sin biblioteca: el error dice que correr
    fingerprint = library.fingerprint(calib.templates)
    acc = acceptance_for(calib.config, args.min_accuracy, args.max_error, args.min_coverage)
    if args.hole <= 0:
        raise ValueError("--hole es un tiempo en segundos mayor que 0")
    ids = list(dict.fromkeys(args.runs)) or teach_cli._run_ids(args)
    if not ids:
        raise ValueError(f"No hay corridas en {args.runs_dir}/. Crea una con: python -m spectro new videos/<video>.MOV")
    evals, loo = load_all(ids, args.runs_dir, calib, lib, fingerprint, args.gap, args.calib_dir)
    summary = summarize(evals, loo, acc, args.hole, fingerprint, len(lib))
    for line in format_summary(summary):
        print(line)
    runs_dir = Path(args.runs_dir)
    written = [write_summary_csv(summary, runs_dir / "summary.csv"),
               write_chars_csv(summary, runs_dir / "summary_chars.csv")]
    if not args.no_html:
        written.append(write_html(summary, runs_dir / "summary.html"))
    print("\n  escrito: " +", ".join(str(w) for w in written))
    return 0


def _expand_videos(patterns: list[str]) -> list[Path]:
    """Rutas de video, expandiendo los comodines que la shell no expandio.

    PowerShell no hace globbing de los argumentos, asi que ``videos/*.MOV``
    llega literal; en bash llega ya expandido. Se soportan los dos.
    """
    seen: dict[Path, None] = {}
    for pattern in patterns:
        p = Path(pattern)
        candidates = sorted(Path(p.parent or ".").glob(p.name)) if any(
            c in pattern for c in "*?["
        ) else [p]
        for c in candidates:
            if c.is_file():
                seen.setdefault(c, None)
            elif "*" not in pattern:
                print(f"  aviso: no existe {c}, se ignora")
    return list(seen)


def cmd_extract(args: argparse.Namespace) -> int:
    from .extract import extract_frames

    cfg = Config.load_or_default(args.config)
    roi = None
    if args.roi_only:
        if cfg.rotation_deg:
            print("--roi-only no es compatible con rotation_deg: ffmpeg recorta el "
                  "fotograma sin rotar. Extrae los fotogramas completos.")
            return 2
        if not cfg.roi.is_valid():
            print("--roi-only requiere una ROI calibrada. Corre: python -m spectro calibrate")
            return 2
        roi = cfg.roi
    video = args.video or cfg.video
    if not video:
        print("Falta --video (y config.json no tiene uno guardado).")
        return 2
    # El fps es de la corrida: lo fija `new` y queda en su config. Un --fps
    # explicito lo pisa, igual que cualquier otro flag frente a lo derivado.
    fps = args.fps if args.fps is not None else (cfg.fps or 1.0)

    print("== extract ==")
    rows = extract_frames(
        video=video,
        fps=fps,
        output=args.output,
        start=args.start,
        duration=args.duration,
        scale=args.scale,
        jpeg_quality=args.jpeg_quality,
        roi=roi,
        index_path=args.index if args.index else None,
        clean=not args.no_clean,
    )
    if args.save_config:
        cfg.video, cfg.fps = str(video), fps
        cfg.save(args.config)
        print(f"  video y fps guardados en {args.config}")
    return 0 if rows else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    from .calibrate import calibrate

    return calibrate(args)


def cmd_qc(args: argparse.Namespace) -> int:
    from .qc import run_qc

    cfg = Config.load(args.config)
    report = run_qc(
        cfg,
        frames_dir=args.frames_dir,
        index_path=args.index,
        output=args.qc_report,
        auto_thresholds=not args.no_auto_thresholds,
        config_path=args.config,
    )
    return 0 if report else 1


def cmd_read(args: argparse.Namespace) -> int:
    from .read import run_read

    cfg = Config.load(args.config)
    readings = run_read(
        cfg,
        frames_dir=args.frames_dir,
        qc_path=args.qc_report,
        templates_dir=args.templates_dir,
        output=args.readings,
    )
    return 0 if readings else 1


def cmd_report(args: argparse.Namespace) -> int:
    from .report import run_report

    cfg = Config.load(args.config)
    n = run_report(
        cfg,
        readings_path=args.readings,
        qc_path=args.qc_report,
        frames_dir=args.frames_dir,
        out_dir=args.out_dir,
        no_plots=args.no_plots,
    )
    return 0 if n else 1


def cmd_run(args: argparse.Namespace) -> int:
    """Pipeline completo: extract -> qc -> read -> report."""
    Config.load(args.config)  # falla temprano si el proyecto no esta calibrado
    if not args.skip_extract:
        rc = cmd_extract(args)
        if rc:
            return rc
    for step in (cmd_qc, cmd_read, cmd_report):
        rc = step(args)
        if rc:
            return rc
    return 0


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
#: Los flags del layout. Se agregan dos veces: en el parser principal (con sus
#: defaults) y en cada subcomando (con ``SUPPRESS``, para que solo escriban en el
#: namespace si se los tipeo de verdad). Asi ``--run`` funciona en los dos lados
#: -- ``spectro --run X qc`` y ``spectro qc --run X`` -- que es la unica forma de
#: que la posicion del flag no sea una trampa. Si aparece en ambos, gana el del
#: subcomando, que es el que esta mas cerca de lo que se esta corriendo.
_FLAGS_LAYOUT = (
    ("--run", "Id de la corrida: deriva config, frames, indice y salidas de runs/<id>/", None),
    ("--runs-dir", "Carpeta que contiene las corridas", str(RUNS_DIR)),
    ("--calib-dir",
     "Carpeta de la calibracion compartida (config, reference.jpg, templates)",
     str(CALIB_DIR)),
    ("--config", "Config de la corrida (default: runs/<run>/config.json)", None),
)


def _layout_parent() -> argparse.ArgumentParser:
    """Parser padre con los flags del layout, sin defaults propios."""
    parent_parser = argparse.ArgumentParser(add_help=False)
    for flag, help_text, _ in _FLAGS_LAYOUT:
        parent_parser.add_argument(flag, default=argparse.SUPPRESS, help=help_text)
    return parent_parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m spectro",
        description=(
            "Extrae la serie temporal de absorbancia desde un video de la pantalla "
            "del espectrofotometro. Pipeline: extract -> qc -> read -> report."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    for flag, help_text, default_value in _FLAGS_LAYOUT:
        p.add_argument(flag, default=default_value, help=help_text)

    sub = p.add_subparsers(dest="command", required=True)
    layout = _layout_parent()

    def subcommand(name: str, **kwargs) -> argparse.ArgumentParser:
        """Un subparser con los flags del layout ya incorporados."""
        kwargs["parents"] = [*kwargs.get("parents", []), layout]
        return sub.add_parser(name, **kwargs)

    # -- doctor
    d = subcommand("doctor", help="Diagnostico del entorno, la calib y las corridas")
    d.set_defaults(func=cmd_doctor, needs_paths=False)

    # -- new
    n = subcommand("new", help="Da de alta una corrida a partir de un video",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    n.add_argument("video", help="Ruta del video (.MOV/.mp4)")
    n.add_argument("--name", default=None,
                   help="Id de la corrida (default: derivado del nombre del video)")
    n.add_argument("--fps", type=float, default=1.0,
                   help="Frecuencia de muestreo en Hz para esta corrida")
    n.add_argument("--force", action="store_true",
                   help="Re-sembrar el config.json aunque la corrida ya exista")
    n.set_defaults(func=cmd_new, needs_paths=False)

    # -- extract
    def add_extract_flags(sp):
        sp.add_argument("--video", help="Ruta del video de entrada (.MOV/.mp4)")
        sp.add_argument("--fps", type=float, default=None,
                        help="Frecuencia de muestreo en Hz (default: la de la corrida)")
        sp.add_argument("--output", default=None,
                        help="Carpeta destino de los fotogramas (default: runs/<run>/frames)")
        sp.add_argument("--index", default=None,
                        help="CSV de indice a escribir (default: runs/<run>/frames_index.csv)")
        sp.add_argument("--start", type=float, default=0.0,
                        help="Segundo del video donde empezar")
        sp.add_argument("--duration", type=float, default=None,
                        help="Duracion en segundos a extraer (util para pruebas)")
        sp.add_argument("--scale", type=float, default=None,
                        help="Factor de escala de la imagen, ej. 0.5")
        sp.add_argument("--jpeg-quality", type=int, default=2,
                        help="Calidad JPEG de ffmpeg (2 = mejor, 31 = peor)")
        sp.add_argument("--roi-only", action="store_true",
                        help="Guardar solo el recorte de la ROI (requiere calibrar)")
        sp.add_argument("--no-clean", action="store_true",
                        help="No borrar los fotogramas previos de la carpeta destino")
        sp.add_argument("--save-config", action="store_true",
                        help="Guardar video y fps en config.json")

    e = subcommand("extract", help="Video -> fotogramas con nombre temporal",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_extract_flags(e)
    e.set_defaults(func=cmd_extract)

    # -- calibrate
    c = subcommand("calibrate", help="Define ROI, slots de digito y polaridad",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    c.add_argument("--frame", default=None,
                   help="Fotograma a usar (default: el del medio de la carpeta de fotogramas)")
    c.add_argument("--frames-dir", default=None,
                   help="Carpeta de fotogramas de donde tomar la muestra")
    c.add_argument("--roi", type=_parse_roi, default=None,
                   help="ROI x,y,w,h en modo no interactivo (salta la UI)")
    c.add_argument("--anchor", type=_parse_roi, default=None,
                   help="Ancla estatica x,y,w,h para detectar movimiento de camara")
    c.add_argument("--n-digits", type=int, default=None, help="Cantidad de digitos")
    c.add_argument("--decimal-after", type=int, default=None,
                   help="Digitos antes del punto decimal (0.245 -> 1)")
    c.add_argument("--splits", default=None,
                   help="Cortes de slots relativos a la ROI, ej. 0,26,52,78,104,130")
    c.add_argument("--no-refine", action="store_true",
                   help="No ajustar la ROI al bounding box de la tinta (usarla tal cual)")
    c.add_argument("--separators", default=None,
                   help=("Indices de slot que son separadores (el punto decimal), "
                         "ej. 1. Vacio para ninguno. Si se omite, se infiere"))
    c.add_argument("--sign", action="store_true",
                   help="El display muestra signo: una celda fija a la izquierda, "
                        "vacia cuando el valor es positivo (n-digits la incluye)")
    c.add_argument("--rotate", type=float, default=None, metavar="DEG",
                   help="Rotar los fotogramas DEG grados (antihorario) para dejar el "
                        "numero horizontal")
    c.add_argument("--polarity", choices=["auto", "light_on_dark", "dark_on_light"],
                   default="auto", help="Polaridad del display")
    c.add_argument("--preview", default=None,
                   help="PNG con el overlay de ROI y slots, para revisar el corte")
    c.add_argument("--auto", action="store_true",
                   help=("Calibrar por registro contra calib/reference.jpg: corre la ROI "
                         "de referencia por el desplazamiento medido. Corrige traslacion, "
                         "no rotacion ni escala"))
    c.add_argument("--search-px", type=int, default=200,
                   help=("Margen de busqueda del ancla en --auto. Entre sesiones la camara "
                         "se re-monta, asi que es mucho mayor que el registro intra-corrida"))
    c.add_argument("--min-score", type=float, default=0.6,
                   help="NCC minima del ancla en --auto; por debajo se pide calibrar a mano")
    c.add_argument("--promote", action="store_true",
                   help=("Copiar la ROI, el ancla y el fotograma de esta corrida a calib/ "
                         "como nueva referencia compartida"))
    c.set_defaults(func=cmd_calibrate)

    # -- teach (areas y verbos: ver teach_cli.py)
    teach_cli.register(sub, layout)

    # -- qc
    q = subcommand("qc", help="Filtro de calidad sobre la ROI",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    q.add_argument("--frames-dir", default=None, help="Carpeta de fotogramas")
    q.add_argument("--index", default=None, help="CSV de indice")
    q.add_argument("--qc-report", default=None,
                   help="CSV de salida con las metricas y el estado por fotograma")
    q.add_argument("--no-auto-thresholds", action="store_true",
                   help="Usar los umbrales de config.json sin auto-sugerirlos")
    q.set_defaults(func=cmd_qc)

    # -- read
    r = subcommand("read", help="Fotogramas -> valores numericos via NCC",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    r.add_argument("--frames-dir", default=None, help="Carpeta de fotogramas")
    r.add_argument("--qc-report", default=None,
                   help="Reporte de QC (se actualiza con el estado de lectura)")
    r.add_argument("--templates-dir", default=None,
                   help="Biblioteca de plantillas (default: calib/templates, compartida)")
    r.add_argument("--readings", default=None,
                   help="CSV crudo de lecturas, incluidas las descartadas")
    r.set_defaults(func=cmd_read)

    # -- report
    rp = subcommand("report", help="Genera absorbance.csv, preview y hoja de contacto",
                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    rp.add_argument("--readings", default=None, help="CSV de lecturas")
    rp.add_argument("--qc-report", default=None, help="Reporte de QC")
    rp.add_argument("--frames-dir", default=None, help="Carpeta de fotogramas")
    rp.add_argument("--out-dir", default=None, help="Carpeta de salidas")
    rp.add_argument("--no-plots", action="store_true",
                    help="Solo CSV, sin preview.png ni contact_sheet.png")
    rp.set_defaults(func=cmd_report)

    # -- run
    rn = subcommand("run", help="Pipeline completo: extract -> qc -> read -> report",
                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_extract_flags(rn)
    rn.add_argument("--skip-extract", action="store_true",
                    help="Reusar los fotogramas ya extraidos")
    rn.add_argument("--frames-dir", default=None, help="Carpeta de fotogramas")
    rn.add_argument("--qc-report", default=None, help="Reporte de QC")
    rn.add_argument("--templates-dir", default=None, help="Plantillas compartidas")
    rn.add_argument("--readings", default=None, help="CSV de lecturas")
    rn.add_argument("--out-dir", default=None, help="Carpeta de salidas")
    rn.add_argument("--no-auto-thresholds", action="store_true",
                    help="Usar los umbrales de config.json tal cual")
    rn.add_argument("--no-plots", action="store_true", help="Solo CSV, sin graficos")
    rn.set_defaults(func=cmd_run)

    # -- batch
    b = subcommand("batch", help="Procesa varios videos de punta a punta",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    b.add_argument("videos", nargs="+",
                   help=f"Videos a procesar, ej. {VIDEOS_DIR}/*.MOV")
    b.add_argument("--fps", type=float, default=1.0, help="Frecuencia de muestreo en Hz")
    b.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True,
                   help="Saltear las corridas que ya tienen out/absorbance.csv")
    b.add_argument("--until", choices=list(BATCH_STAGES[3:]), default="report",
                   help=("Cortar despues de esta etapa. 'qc' prepara el pool de fotogramas "
                         "sin leer: sirve antes de armar la biblioteca (arranque en frio)"))
    b.add_argument("--search-px", type=int, default=200,
                   help="Margen de busqueda del ancla en calibrate --auto")
    b.add_argument("--min-score", type=float, default=0.6,
                   help="NCC minima del ancla en calibrate --auto")
    for flag, help_text in (
        ("--min-accuracy", "Veredicto: exactitud minima sobre test.csv (fraccion, ej. 0.95)"),
        ("--max-error", "Veredicto: error maximo entre las lecturas aceptadas de test.csv (fraccion)"),
        ("--min-coverage", "Veredicto: cobertura minima, ok / fotogramas extraidos (fraccion)"),
    ):
        b.add_argument(flag, type=float, default=None,
                       help=f"{help_text}. Sin valor se usa 'acceptance' de calib/config.json; "
                            "sin umbrales el veredicto queda vacio")
    b.set_defaults(func=cmd_batch, needs_paths=False)

    # -- summary
    sm = subcommand("summary", help="Reporte general de efectividad del lector (solo lectura)",
                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sm.add_argument("runs", nargs="*", metavar="RUN",
                    help="Corridas a incluir (default: todas las dadas de alta)")
    sm.add_argument("--gap", type=float, default=5.0,
                    help="Segundos entre un fotograma de prueba y uno de entrenamiento para avisar de fuga")
    sm.add_argument("--hole", type=float, default=10.0,
                    help="Un hueco es una pausa de mas de estos segundos entre lecturas validas")
    for flag, help_text in (
        ("--min-accuracy", "Veredicto: exactitud minima sobre la prueba (fraccion, ej. 0.95)"),
        ("--max-error", "Veredicto: error maximo entre las lecturas aceptadas de la prueba (fraccion)"),
        ("--min-coverage", "Veredicto: cobertura minima, ok / fotogramas extraidos (fraccion)"),
    ):
        sm.add_argument(flag, type=float, default=None,
                        help=f"{help_text}. Sin valor se usa 'acceptance' de calib/config.json; "
                             "sin umbrales el veredicto queda vacio")
    sm.add_argument("--no-html", action="store_true", help="No generar runs/summary.html")
    sm.set_defaults(func=cmd_summary, needs_paths=False)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    legacy = teach_cli.legacy_error(sys.argv[1:] if argv is None else argv)
    if legacy:
        print(f"ERROR: {legacy}", file=sys.stderr)
        return 2
    args = parser.parse_args(argv)
    try:
        error = resolve_paths(args)
        if error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return args.func(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
