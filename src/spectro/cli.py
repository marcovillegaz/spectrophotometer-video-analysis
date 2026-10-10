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
    qc          filtro de calidad -> runs/<id>/out/qc_report.csv
    read        fotogramas -> valores numericos
    report      -> absorbancia.csv, preview.png, contact_sheet.png
    run         extract -> qc -> read -> report
    batch       new -> extract -> calibrate --auto -> run, por cada video

Las rutas no se tipean: ``--run <id>`` deriva las ocho desde ``RunPaths``
(ver ``project.py``). Un flag explicito siempre le gana a lo derivado, asi que
se puede apuntar una etapa a una carpeta cualquiera sin dejar de usar ``--run``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_MAX_PER_LABEL, ROI, Config
from .project import (
    CALIB_DIR,
    RUNS_DIR,
    VIDEOS_DIR,
    CalibPaths,
    RunContext,
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
#: convierte un ``--run <id>`` en las ocho rutas del pipeline.
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
    "truth": lambda run, calib: run.truth,
    "teach_report": lambda run, calib: run.teach_report,
    "test": lambda run, calib: run.test,
    "test_report": lambda run, calib: run.test_report,
    "history": lambda run, calib: run.history,
}


def _run_missing_message(args: argparse.Namespace, faltantes: list[str]) -> str:
    """El error de ``--run`` ausente, con las corridas disponibles listadas.

    Adivinar cual es la corrida mezclaria datos de dos experimentos en silencio,
    que es la peor forma de perder datos de laboratorio: sin ruido.
    """
    corridas = list_runs(runs_dir=args.runs_dir)
    flags = ", ".join("--" + f.replace("_", "-") for f in faltantes)
    lineas = [
        f"falta --run: no se sabe sobre que corrida trabajar ({flags} sin valor).",
    ]
    if corridas:
        lineas.append(f"Corridas disponibles en {args.runs_dir}/:")
        lineas += [f"  {c}" for c in corridas]
        lineas.append(f"Ejemplo: python -m spectro {args.comando} --run {corridas[-1]}")
    else:
        lineas.append(f"No hay ninguna corrida en {args.runs_dir}/. Crea una con:")
        lineas.append("  python -m spectro new videos/<video>.MOV")
    lineas.append("Tambien podes pasar las rutas a mano: " + flags)
    return "\n".join(lineas)


def resolve_paths(args: argparse.Namespace) -> str | None:
    """Completa las rutas en ``None`` desde ``--run``. Devuelve el error, o None.

    Deja ademas ``args.run_paths`` y ``args.calib_paths`` para los handlers que
    necesitan el layout entero (``calibrate --auto``, ``doctor``).
    """
    args.calib_paths = CalibPaths.at(args.calib_dir)
    args.run_paths = (
        RunPaths.for_run(args.run, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        if getattr(args, "run", None)
        else None
    )

    # doctor, new y batch miran el layout entero, no una corrida: no exigen --run.
    if not getattr(args, "needs_paths", True):
        return None
    # teach --eval-all / --all-runs recorren todas las corridas: solo necesitan la biblioteca.
    if getattr(args, "eval_all", False) or getattr(args, "all_runs", False):
        if getattr(args, "templates_dir", None) is None:
            args.templates_dir = str(args.calib_paths.templates)
        return None

    presentes = [name for name in _DERIVED_PATHS if hasattr(args, name)]
    if args.run_paths is not None:
        for name in presentes:
            if getattr(args, name) is None:  # un flag explicito le gana a lo derivado
                setattr(args, name, str(_DERIVED_PATHS[name](args.run_paths, args.calib_paths)))

    faltantes = [name for name in presentes if getattr(args, name) is None]
    if faltantes:
        return _run_missing_message(args, faltantes)
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
        ("pandas", "pandas"),
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

    corridas = list_runs(runs_dir=args.runs_dir)
    print(f"\nCorridas ({args.runs_dir}/): {len(corridas)}")
    for run_id in corridas:
        run = RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        n_frames = len(list(run.frames.glob("t_*.jpg"))) if run.frames.is_dir() else 0
        if run.config.exists():
            cfg = Config.load(run.config)
            estado = "calibrada" if cfg.roi.is_valid() else "SIN CALIBRAR"
            video = Path(cfg.video).name or "?"
        else:
            estado, video = "sin config.json", "?"
        salida = "absorbancia.csv" if run.is_done() else "sin salida"
        print(f"  {run_id:22s} {estado:14s} {n_frames:5d} fotogramas  {salida:15s} video={video}")
    if not corridas:
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
    videos = _expand_videos(args.videos)
    if not videos:
        print("No hay videos que procesar.")
        return 2

    print(f"== batch ==\n  {len(videos)} video(s), fps={args.fps}")
    hechas: list[str] = []
    salteadas: list[tuple[str, str]] = []
    fallidas: list[tuple[str, str]] = []

    for i, video in enumerate(videos, 1):
        run_id = run_id_from_video(video, None)
        run = RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        print(f"\n--- [{i}/{len(videos)}] {video.name} -> {run_id} ---")

        if run.is_done() and args.skip_existing:
            print(f"  ya tiene {run.absorbance}; se saltea (--no-skip-existing para rehacerla)")
            salteadas.append((run_id, "ya procesada"))
            continue

        # Se re-invoca el parser en vez de armar Namespaces a mano: asi cada
        # etapa recibe exactamente los mismos defaults que en la linea de comandos.
        globales = ["--runs-dir", str(args.runs_dir), "--calib-dir", str(args.calib_dir)]
        de_la_corrida = globales + ["--run", run_id]
        etapas: list[tuple[str, list[str]]] = [
            ("new", globales + ["new", str(video), "--fps", str(args.fps), "--force"]),
            ("extract", de_la_corrida + ["extract", "--fps", str(args.fps)]),
            ("calibrate", de_la_corrida + ["calibrate", "--auto",
                                           "--search-px", str(args.search_px),
                                           "--min-score", str(args.min_score)]),
            ("qc", de_la_corrida + ["qc"]),
            ("read", de_la_corrida + ["read"]),
            ("report", de_la_corrida + ["report"]),
        ]

        permitidas = batch_stages(args.until)
        for etapa, argv in (e for e in etapas if e[0] in permitidas):
            rc = main(argv)
            if rc:
                if etapa == "calibrate":
                    print(f"  calibracion automatica sin exito: {run_id} queda pendiente")
                    salteadas.append((run_id, "pendiente de calibracion manual"))
                else:
                    fallidas.append((run_id, f"fallo en {etapa} (codigo {rc})"))
                break
        else:
            hechas.append(run_id)

    print(f"\n== resumen del lote ==")
    for run_id in hechas:
        run = RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        resumen = _run_summary(run) if args.until == "report" else f"preparada hasta {args.until}"
        print(f"  [ok]       {run_id:22s} {resumen}")
    for run_id, motivo in salteadas:
        print(f"  [salteada] {run_id:22s} {motivo}")
    for run_id, motivo in fallidas:
        print(f"  [ERROR]    {run_id:22s} {motivo}")
    pendientes = [r for r, m in salteadas if "manual" in m]
    if pendientes:
        print("\n  Pendientes de calibracion manual:")
        for run_id in pendientes:
            print(f"    python -m spectro calibrate --run {run_id}")
    return 1 if fallidas else 0


def _expand_videos(patrones: list[str]) -> list[Path]:
    """Rutas de video, expandiendo los comodines que la shell no expandio.

    PowerShell no hace globbing de los argumentos, asi que ``videos/*.MOV``
    llega literal; en bash llega ya expandido. Se soportan los dos.
    """
    vistos: dict[Path, None] = {}
    for patron in patrones:
        p = Path(patron)
        candidatos = sorted(Path(p.parent or ".").glob(p.name)) if any(
            c in patron for c in "*?["
        ) else [p]
        for c in candidatos:
            if c.is_file():
                vistos.setdefault(c, None)
            elif "*" not in patron:
                print(f"  aviso: no existe {c}, se ignora")
    return list(vistos)


def _run_summary(run: RunPaths) -> str:
    """``N validas, cobertura X%, absorbancia [min, max]`` leido de las salidas."""
    import csv

    if not run.absorbance.exists():
        return "sin salida"
    with run.absorbance.open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    if not filas:
        return "0 validas"
    valores = [float(f["absorbancia"]) for f in filas]
    total = len(filas)
    if run.qc_report.exists():
        with run.qc_report.open(encoding="utf-8") as fh:
            total = sum(1 for _ in csv.DictReader(fh)) or total
    return (f"{len(filas)} validas de {total} ({100 * len(filas) / total:.0f}%), "
            f"absorbancia [{min(valores):.3f}, {max(valores):.3f}]")


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


def _teach_context(args: argparse.Namespace) -> RunContext:
    """Config, fotogramas, offsets y muestras de la corrida, comunes a todos los modos de ``teach``."""
    ctx = RunContext.load(
        args.run_paths, args.calib_paths, config=args.config, frames_dir=args.frames_dir,
        qc_report=args.qc_report, truth=args.truth, test=args.test,
        templates_dir=args.templates_dir,
    )
    if not ctx.has_qc:
        print(f"aviso: no existe {args.qc_report}; sin QC no se compensa la deriva de camara. "
              "Corre primero: python -m spectro qc")
    return ctx


def _teach_suggestions(args, cfg, items, train, test):
    """Fotogramas a etiquetar segun ``--strategy`` y ``--for``. Devuelve ``(sugerencias, avisos)``."""
    from . import sampling as S
    from .extract import time_from_name
    from .read import load_readings

    para_prueba = args.for_set == "test"
    strategy = "random" if para_prueba else args.strategy
    avisos: list[str] = []
    if para_prueba and args.strategy not in ("mixed", "random"):
        avisos.append("la prueba siempre se elige al azar: una prueba por incertidumbre "
                      "subestimaria el error real.")
    # la prueba se aleja del entrenamiento, y el entrenamiento de la prueba: no hay fugas
    otro = test if not para_prueba else train
    avoid = [time_from_name(x.archivo) for x in otro]
    exclude = {x.archivo for x in train + test}
    readings = None
    stale = False
    if strategy in ("mixed", "uncertain") and Path(args.readings).exists():
        readings = load_readings(args.readings)
        stale = S.readings_stale(args.readings, args.templates_dir, args.config)
    sug, notas = S.suggest(
        strategy, items=items, readings=readings, cfg=cfg, exclude=exclude, n=args.suggest or args.queue,
        seed=args.seed, gap_s=args.gap, avoid_times=avoid, stale=stale,
    )
    return sug, avisos + notas


def _teach_eval_all(args: argparse.Namespace) -> int:
    """Una linea por corrida con ``test.csv``: la biblioteca es compartida, la prueba no."""
    from . import teach as T
    from .evaluation import evaluate_test, wilson
    from .library import load

    library = load(args.templates_dir)
    print(f"== teach --eval-all (biblioteca: {len(library)} plantillas) ==")
    print(f"  {'corrida':22s} {'tipo':14s} {'n':>3s} {'correctas':>10s} {'erroneas':>8s} "
          f"{'descart.':>8s}  exactitud [IC95]")
    hubo = False
    for run_id in list_runs(runs_dir=args.runs_dir):
        run = RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
        if not run.config.exists():
            continue
        ctx = RunContext.load(run, args.calib_paths)
        if not ctx.test:
            continue
        hubo = True
        rep = evaluate_test(ctx.test, ctx.cfg, ctx.frames_dir, ctx.offsets, library, ctx.train,
                            args.gap)
        lo, hi = wilson(rep.correctas, rep.n)
        print(f"  {run_id:22s} {rep.tipo:14s} {rep.n:3d} {rep.correctas:10d} {rep.erroneas:8d} "
              f"{rep.descartadas:8d}  {rep.exactitud:.1%} [{lo:.0%}-{hi:.0%}]")
    if not hubo:
        print("  ninguna corrida tiene test.csv. Arma uno con: teach --run <id> --suggest 20 --for test")
    return 0


def _teach_all_runs(args: argparse.Namespace) -> int:
    """``--build --all-runs``: una biblioteca compartida con las muestras de TODAS las corridas."""
    from . import teach as T

    if not (args.build or args.check):
        raise ValueError("--all-runs se usa con --build (arma la biblioteca) o --check (solo valida)")
    runs = T.gather_runs(args.runs_dir, args.calib_dir, args.exclude_runs or [])
    if not runs:
        raise ValueError(f"Ninguna corrida de {args.runs_dir}/ tiene muestras en truth.csv. "
                         "Etiqueta algunas con: teach --run <id>")
    print("== teach --all-runs ==")
    for run in runs:
        print(f"  {run.run_id:22s} {len(run.train):3d} muestras de entrenamiento")
    if args.exclude_runs:
        print(f"  excluidas (quedan como prueba): {', '.join(args.exclude_runs)}")
    res = T.train(runs, args.templates_dir, build=args.build, keep=args.keep,
                  max_per_label=args.max_per_label)
    for e in res.errores:
        print(f"  muestra descartada: {e}")
    if not res.datas:
        raise ValueError("Ninguna muestra se pudo procesar.")

    print("  cobertura: " + "  ".join(f"{k}:{v}" for k, v in res.coverage.items()))
    if res.faltan:
        print(f"  aviso: faltan ejemplos de {', '.join(res.faltan)}; esos caracteres no se van a leer")
    if res.nuevas is not None:
        print(f"  {sum(res.nuevas.values())} plantillas escritas en {args.templates_dir}  "
              f"({', '.join(f'{k}:{v}' for k, v in sorted(res.nuevas.items()))})")
    if res.aviso_signo:
        print("  " + res.aviso_signo.replace("\n", "\n  "))

    loo, vigente = res.loo, res.vigente
    print("  " + T.format_report(loo, "leave-one-out sobre todas las corridas")[0])
    for line in T.format_report(loo, "")[1:]:
        print("  " + line)
    if vigente is None:
        print("  no hay biblioteca vigente todavia")
    print(f"  {'corrida':22s} {'leave-one-out':>14s} {'biblioteca vigente':>20s}")
    for run in runs:
        a = T.split_by_run(loo, run.run_id)
        b = T.split_by_run(vigente, run.run_id) if vigente else None
        print(f"  {run.run_id:22s} {a.exact:>6d}/{a.total:<7d} "
              f"{(str(b.exact) + '/' + str(b.total)) if b else '-':>20s}")
        T.write_report(a, run.paths.teach_report)
    print("  informes por corrida: runs/<id>/out/teach_report.csv")
    print("  las pruebas (test.csv) no se usaron; para medirlas: teach --eval-all")
    return 0


def cmd_teach(args: argparse.Namespace) -> int:
    """Calibra el lector con valores reales y lo evalua sobre un conjunto de prueba."""
    from . import teach as T
    from .evaluation import append_history, evaluate_test, format_test_report, write_test_report
    from .library import delete, list_entries, load
    from .sampling import assign, leakage

    if args.eval_all:
        return _teach_eval_all(args)
    if args.all_runs:
        return _teach_all_runs(args)

    ctx = _teach_context(args)
    cfg, frames_dir, offsets = ctx.cfg, ctx.frames_dir, ctx.offsets
    names, items = ctx.names(), ctx.items()
    train, test = ctx.train, ctx.test
    samples = train

    if args.library or args.delete:
        entries = list_entries(args.templates_dir)
        if args.delete:
            by_name = {e.path.stem: e for e in entries}
            quitar = []
            for name in args.delete:
                e = by_name.get(Path(name).stem)
                if e is None:
                    raise ValueError(f"No existe la plantilla {name!r} en {args.templates_dir}")
                quitar.append(e.path)
            delete(quitar)
            print(f"{len(quitar)} plantillas borradas de {args.templates_dir}")
            entries = list_entries(args.templates_dir)
        print(f"== biblioteca: {len(entries)} plantillas en {args.templates_dir} ==")
        for ch in T.ALL_CHARS:
            stems = [e.path.stem for e in entries if e.label == ch]
            print(f"  {ch!r:5} x{len(stems)}  {' '.join(stems)}")
        if not (args.add or args.add_test or args.build or args.check or args.eval or args.suggest):
            return 0

    if args.suggest:
        sug, avisos = _teach_suggestions(args, cfg, items, train, test)
        destino = "prueba" if args.for_set == "test" else "entrenamiento"
        usada = "random" if args.for_set == "test" else args.strategy
        print(f"== teach: {len(sug)} fotogramas sugeridos para {destino} (estrategia {usada}) ==")
        for a in avisos:
            print(f"  aviso: {a}")
        for sg in sug:
            print(f"  {sg.archivo}   t={sg.t_s:8.2f} s   {sg.motivo}")
        return 0

    for flag, which in ((args.add, "train"), (args.add_test, "test")):
        if not flag:
            continue
        for item in flag:
            archivo, sep, valor = item.partition("=")
            if not sep or not valor:
                raise ValueError(f"se espera ARCHIVO=VALOR, recibi {item!r}")
            if not (frames_dir / archivo).exists():
                raise FileNotFoundError(f"No existe el fotograma {frames_dir / archivo}")
            valor = T.parse_value(valor, cfg.digits)  # falla con el formato esperado
            ya_entreno = which == "test" and any(x.archivo == archivo for x in train)
            ya_prueba = which == "train" and any(x.archivo == archivo for x in test)
            train, test = assign(train, test, T.Sample(archivo, valor), which)
            if ya_entreno:
                print(f"  aviso: {archivo} estaba en entrenamiento y ya aporto glifos a la biblioteca; "
                      "para una prueba limpia usa 'Reemplazar biblioteca' (teach --build)")
            if ya_prueba:
                print(f"  aviso: {archivo} estaba en la prueba y paso a entrenamiento")
        T.save_truth(args.truth, train)
        T.save_truth(args.test, test)
        print(f"{len(train)} muestras de entrenamiento en {args.truth}; "
              f"{len(test)} de prueba en {args.test}")
    samples = train

    if args.eval:
        if not test:
            raise ValueError(f"No hay muestras de prueba en {args.test}. Arma el conjunto con: "
                             "teach --suggest 20 --for test, y cargalo con --add-test")
        library = load(args.templates_dir)
        rep = evaluate_test(test, cfg, frames_dir, offsets, library, train, args.gap)
        print("== teach --eval ==")
        for line in format_test_report(rep):
            print("  " + line)
        write_test_report(rep, args.test_report)
        append_history(args.history, rep)
        print(f"  informe: {args.test_report}   historial: {args.history}")
        return 0

    if args.build or args.check:
        if not samples:
            raise ValueError(f"No hay muestras en {args.truth}. Usa teach --add o la UI.")
        ctx.train = samples
        res = T.train([ctx], args.templates_dir, build=args.build, keep=args.keep,
                      max_per_label=args.max_per_label, prefixed=False)
        for e in res.errores:
            print(f"  muestra descartada: {e}")
        if not res.datas:
            raise ValueError("Ninguna muestra se pudo procesar.")
        print("== teach ==")
        print("  cobertura: " + "  ".join(f"{k}:{v}" for k, v in res.coverage.items()))
        if res.faltan:
            print(f"  aviso: faltan ejemplos de {', '.join(res.faltan)}; esos caracteres no se van a leer")
        if res.nuevas is not None:
            print(f"  {sum(res.nuevas.values())} plantillas escritas en {args.templates_dir}  "
                  f"({', '.join(f'{k}:{v}' for k, v in sorted(res.nuevas.items()))})")
        if res.aviso_signo:
            print("  " + res.aviso_signo.replace("\n", "\n  "))
        for line in T.format_report(res.loo, "leave-one-out (sin las plantillas de la propia muestra)"):
            print("  " + line)
        T.write_report(res.loo, args.teach_report)
        if res.vigente is None:
            print("  no hay biblioteca vigente todavia")
        else:
            for line in T.format_report(res.vigente, "biblioteca vigente"):
                print("  " + line)
        solapadas = leakage(train, test, args.gap)
        if solapadas:
            print(f"  aviso: {len(solapadas)} fotogramas de prueba estan a menos de {args.gap:g} s "
                  "de uno de entrenamiento")
        print(f"  informe: {args.teach_report}")
        return 0

    if args.add or args.add_test:
        return 0

    motivos: dict[str, str] = {}
    if args.queue:
        sug, avisos = _teach_suggestions(args, cfg, items, train, test)
        for a in avisos:
            print(f"aviso: {a}")
        if not sug:
            raise ValueError("No hay fotogramas que sugerir (todo esta etiquetado o excluido).")
        names = [sg.archivo for sg in sug]
        motivos = {sg.archivo: sg.motivo for sg in sug}
    from .teach_ui import run_teach_ui

    return run_teach_ui(cfg, args, names, offsets, train, test=test, motivos=motivos,
                        target=args.for_set)


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
    padre = argparse.ArgumentParser(add_help=False)
    for flag, ayuda, _ in _FLAGS_LAYOUT:
        padre.add_argument(flag, default=argparse.SUPPRESS, help=ayuda)
    return padre


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m spectro",
        description=(
            "Extrae la serie temporal de absorbancia desde un video de la pantalla "
            "del espectrofotometro. Pipeline: extract -> qc -> read -> report."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    for flag, ayuda, defecto in _FLAGS_LAYOUT:
        p.add_argument(flag, default=defecto, help=ayuda)

    sub = p.add_subparsers(dest="comando", required=True)
    layout = _layout_parent()

    def subcomando(nombre: str, **kwargs) -> argparse.ArgumentParser:
        """Un subparser con los flags del layout ya incorporados."""
        kwargs["parents"] = [*kwargs.get("parents", []), layout]
        return sub.add_parser(nombre, **kwargs)

    # -- doctor
    d = subcomando("doctor", help="Diagnostico del entorno, la calib y las corridas")
    d.set_defaults(func=cmd_doctor, needs_paths=False)

    # -- new
    n = subcomando("new", help="Da de alta una corrida a partir de un video",
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

    e = subcomando("extract", help="Video -> fotogramas con nombre temporal",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_extract_flags(e)
    e.set_defaults(func=cmd_extract)

    # -- calibrate
    c = subcomando("calibrate", help="Define ROI, slots de digito y polaridad",
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

    # -- teach
    th = subcomando("teach", help="Calibra el lector con valores reales escritos a mano",
                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    th.add_argument("--frames-dir", default=None, help="Carpeta de fotogramas")
    th.add_argument("--qc-report", default=None, help="Reporte de QC (offsets de camara)")
    th.add_argument("--truth", default=None, help="CSV de muestras archivo,valor")
    th.add_argument("--templates-dir", default=None,
                    help="Biblioteca de plantillas (default: calib/templates, compartida)")
    th.add_argument("--teach-report", default=None, help="CSV con el informe de validacion")
    th.add_argument("--readings", default=None,
                    help="CSV de lecturas de `read` (la incertidumbre sale de ahi)")
    th.add_argument("--test", default=None, help="CSV del conjunto de prueba archivo,valor")
    th.add_argument("--test-report", default=None, help="CSV con el informe de la prueba")
    th.add_argument("--history", default=None,
                    help="CSV con una fila por evaluacion: la curva de aprendizaje")
    th.add_argument("--suggest", type=int, default=0, metavar="N",
                    help="Imprimir N fotogramas para etiquetar, segun --strategy")
    th.add_argument("--strategy", choices=["mixed", "uncertain", "random", "uniform"],
                    default="mixed",
                    help="Como elegir los fotogramas: mixed = mitad incertidumbre, mitad azar")
    th.add_argument("--for", dest="for_set", choices=["train", "test"], default="train",
                    help="Para que conjunto se sugiere; la prueba siempre es al azar")
    th.add_argument("--seed", type=int, default=0, help="Semilla del muestreo al azar")
    th.add_argument("--gap", type=float, default=5.0, metavar="SEGUNDOS",
                    help="Separacion minima entre fotogramas elegidos, y entre prueba y entrenamiento")
    th.add_argument("--queue", type=int, default=0, metavar="N",
                    help="Abrir la UI solo con los N fotogramas sugeridos")
    th.add_argument("--add-test", nargs="+", metavar="ARCHIVO=VALOR",
                    help="Agregar muestras al conjunto de prueba (nunca entran a la biblioteca)")
    th.add_argument("--eval", action="store_true",
                    help="Evaluar la biblioteca vigente sobre el conjunto de prueba")
    th.add_argument("--all-runs", action="store_true",
                    help=("Con --build o --check: usar las muestras de entrenamiento de TODAS las "
                          "corridas, cada una con su propia config, en una sola biblioteca"))
    th.add_argument("--exclude-runs", nargs="+", metavar="CORRIDA",
                    help="Con --all-runs: corridas que no se usan para entrenar (hold-out por video)")
    th.add_argument("--eval-all", action="store_true",
                    help="Evaluar la biblioteca sobre la prueba de todas las corridas que la tengan")
    th.add_argument("--add", nargs="+", metavar="ARCHIVO=VALOR",
                    help="Agregar muestras sin ventana, ej. t_0001352.000.jpg=-0.018")
    th.add_argument("--build", action="store_true",
                    help="Construir calib/templates desde las muestras y validar")
    th.add_argument("--check", action="store_true",
                    help="Solo validar (leave-one-out) y escribir el informe")
    th.add_argument("--keep", action="store_true",
                    help="Con --build, sumar a las plantillas existentes (sin duplicar) "
                         "en vez de reemplazarlas")
    th.add_argument("--library", action="store_true",
                    help="Listar las plantillas de la biblioteca por caracter")
    th.add_argument("--delete", nargs="+", metavar="NOMBRE",
                    help="Borrar plantillas por nombre, ej. 0_3 5_1")
    th.add_argument("--max-per-label", type=int, default=DEFAULT_MAX_PER_LABEL,
                    help="Maximo de variantes de plantilla por caracter")
    th.set_defaults(func=cmd_teach)

    # -- qc
    q = subcomando("qc", help="Filtro de calidad sobre la ROI",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    q.add_argument("--frames-dir", default=None, help="Carpeta de fotogramas")
    q.add_argument("--index", default=None, help="CSV de indice")
    q.add_argument("--qc-report", default=None,
                   help="CSV de salida con las metricas y el estado por fotograma")
    q.add_argument("--no-auto-thresholds", action="store_true",
                   help="Usar los umbrales de config.json sin auto-sugerirlos")
    q.set_defaults(func=cmd_qc)

    # -- read
    r = subcomando("read", help="Fotogramas -> valores numericos via NCC",
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
    rp = subcomando("report", help="Genera absorbancia.csv, preview y hoja de contacto",
                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    rp.add_argument("--readings", default=None, help="CSV de lecturas")
    rp.add_argument("--qc-report", default=None, help="Reporte de QC")
    rp.add_argument("--frames-dir", default=None, help="Carpeta de fotogramas")
    rp.add_argument("--out-dir", default=None, help="Carpeta de salidas")
    rp.add_argument("--no-plots", action="store_true",
                    help="Solo CSV, sin preview.png ni contact_sheet.png")
    rp.set_defaults(func=cmd_report)

    # -- run
    rn = subcomando("run", help="Pipeline completo: extract -> qc -> read -> report",
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
    b = subcomando("batch", help="Procesa varios videos de punta a punta",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    b.add_argument("videos", nargs="+",
                   help=f"Videos a procesar, ej. {VIDEOS_DIR}/*.MOV")
    b.add_argument("--fps", type=float, default=1.0, help="Frecuencia de muestreo en Hz")
    b.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True,
                   help="Saltear las corridas que ya tienen out/absorbancia.csv")
    b.add_argument("--until", choices=list(BATCH_STAGES[3:]), default="report",
                   help=("Cortar despues de esta etapa. 'qc' prepara el pool de fotogramas "
                         "sin leer: sirve antes de armar la biblioteca (arranque en frio)"))
    b.add_argument("--search-px", type=int, default=200,
                   help="Margen de busqueda del ancla en calibrate --auto")
    b.add_argument("--min-score", type=float, default=0.6,
                   help="NCC minima del ancla en calibrate --auto")
    b.set_defaults(func=cmd_batch, needs_paths=False)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
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
