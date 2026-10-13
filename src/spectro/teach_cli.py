"""``teach`` por areas: un sustantivo (area) y un verbo, con el id de la corrida explicito.

``teach`` crecio como un solo comando con ~30 flags que eran "modos". Aca cada accion es un
verbo con solo los flags que le sirven, y se agrupan por lo que tocan:

    teach status                                   panorama de todo y siguiente paso
    teach lib {list,delete,relabel,clear,backups,restore}
                                                   la biblioteca GLOBAL (calib/templates), sin corrida
    teach train [RUN ...] [--exclude RUN ...]      arma la biblioteca desde las muestras
    teach check [RUN ...]                          valida (leave-one-out) sin escribirla
    teach samples {list,add,remove,suggest,label}  muestras de ENTRENAMIENTO de una corrida (truth.csv)
    teach test {list,add,remove,suggest,label,eval,history}
                                                   PRUEBAS de una corrida (test.csv): nunca entran a la biblioteca
    teach rejected {list,remove}                   fotogramas descartados al etiquetar (rejected.csv)

El id de la corrida va como argumento posicional, completo: nunca se adivina sobre que
experimento se trabaja. Los handlers no pasan por ``cli.resolve_paths`` (``needs_paths=False``):
las rutas salen de ``RunPaths`` / ``CalibPaths``, y para probar sobre una copia basta
``--calib-dir`` / ``--runs-dir``. Los modulos pesados (cv2) se importan dentro de cada handler.

Interfaz publica:
    register(sub, layout)       registra el comando ``teach`` en el parser principal
    legacy_error(argv)          mensaje de migracion si se uso la sintaxis vieja (``teach --build``...)
    MIGRATION                   la tabla "antes -> ahora"
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .compat import LEGACY_FLAGS
from .config import DEFAULT_MAX_PER_LABEL, Config
from .project import RunContext, RunPaths, list_runs, require_run

AREAS = ("status", "lib", "train", "check", "samples", "test", "rejected")
#: Flags del layout que llevan valor: se saltean al buscar el area.
_LAYOUT_WITH_VALUE = ("--run", "--runs-dir", "--calib-dir", "--config")

MIGRATION = """\
teach ya no usa flags de modo: se elige un area y un verbo, y el id de la corrida va como argumento.

  antes                                   ahora
  teach --run ID --library                teach lib list      (las muestras de una corrida: teach samples list ID)
  teach --run ID --delete 0_3 5_1         teach lib delete 0_3 5_1
  teach --run ID --build [--keep]         teach train ID [--keep]
  teach --all-runs --build                teach train
  teach --all-runs --exclude-runs ID      teach train --exclude ID
  teach --run ID --check                  teach check ID
  teach --run ID --suggest N              teach samples suggest ID N
  teach --run ID --suggest N --for test   teach test suggest ID N
  teach --run ID --queue N                teach samples label ID --queue N
  teach --run ID                          teach samples label ID      (la prueba: teach test label ID)
  teach --run ID --add A=V                teach samples add ID A=V
  teach --run ID --add-test A=V           teach test add ID A=V
  teach --run ID --eval                   teach test eval ID
  teach --eval-all                        teach test eval
  --min-exactitud / --min-cobertura       --min-accuracy / --min-coverage   (teach test eval, batch)
  (nuevo)                                 teach status | teach lib restore | teach test history ID
  (nuevo)                                 teach rejected list [ID] | teach rejected remove ID ARCHIVO...

--strategy, --seed, --gap, --keep y --max-per-label siguen existiendo, pero en el verbo al que sirven.
Areas: status, lib, train, check, samples, test, rejected. Ayuda de cada una: teach <area> --help"""


# --------------------------------------------------------------------------
# Sintaxis vieja
# --------------------------------------------------------------------------
def legacy_error(argv: list[str]) -> str | None:
    """El mensaje de migracion si se uso la sintaxis vieja: ``teach`` sin area o un flag renombrado."""
    if any(tok.split("=")[0] in LEGACY_FLAGS for tok in argv):
        return MIGRATION
    i = 0
    while i < len(argv) and argv[i].split("=")[0] in _LAYOUT_WITH_VALUE:
        i += 1 if "=" in argv[i] else 2
    if i >= len(argv) or argv[i] != "teach":
        return None
    rest = argv[i + 1:]
    j = 0
    while j < len(rest) and rest[j].split("=")[0] in _LAYOUT_WITH_VALUE:
        j += 1 if "=" in rest[j] else 2
    if j < len(rest) and (rest[j] in AREAS or rest[j] in ("-h", "--help")):
        return None
    if j < len(rest) and not rest[j].startswith("-"):
        return (f"area desconocida {rest[j]!r}. Areas: {', '.join(AREAS)}. "
                "Ayuda: python -m spectro teach --help")
    return MIGRATION


# --------------------------------------------------------------------------
# Ayudas compartidas por los handlers
# --------------------------------------------------------------------------
def _guard(args: argparse.Namespace) -> None:
    """``teach`` no usa ``--run`` ni ``--config``: el id va como argumento y cada corrida tiene su config."""
    if getattr(args, "run", None):
        raise ValueError(
            f"teach no usa --run: el id de la corrida va como argumento. "
            f"Ej: python -m spectro teach samples list {args.run}")
    if getattr(args, "config", None):
        raise ValueError("teach no usa --config: cada corrida usa runs/<id>/config.json")


def _load(args: argparse.Namespace, run_id: str) -> RunContext:
    """Config, fotogramas, offsets y muestras de una corrida que existe."""
    run = require_run(run_id, args.runs_dir, args.calib_dir)
    ctx = RunContext.load(run, args.calib_paths)
    if not ctx.has_qc:
        print(f"aviso: no existe {ctx.qc_report}; sin QC no se compensa la deriva de camara. "
              f"Corre primero: python -m spectro qc --run {run_id}")
    return ctx


def _run_ids(args: argparse.Namespace) -> list[str]:
    """Las corridas dadas de alta (con config.json), con el layout viejo ya migrado a ``teach/`` y ``test/``."""
    paths = [RunPaths.for_run(r, runs_dir=args.runs_dir, calib_dir=args.calib_dir)
             for r in list_runs(runs_dir=args.runs_dir)]
    found = [p for p in paths if p.exists()]
    for p in found:
        p.migrate_layout()
    return [p.id for p in found]


def _run_paths(args: argparse.Namespace, run_id: str) -> RunPaths:
    return RunPaths.for_run(run_id, runs_dir=args.runs_dir, calib_dir=args.calib_dir)


def library_or_empty(args: argparse.Namespace) -> list:
    """La biblioteca vigente, o ``[]`` si todavia no hay plantillas."""
    from . import library

    try:
        return library.load(args.calib_paths.templates)
    except FileNotFoundError:
        return []


def _required_chars(args: argparse.Namespace) -> set[str]:
    """Los caracteres que la geometria de las corridas (o la receta) necesita poder leer."""
    cfgs = [Config.load(_run_paths(args, r).config) for r in _run_ids(args)]
    if not cfgs:
        cfgs = [Config.load_or_default(args.calib_paths.config)]
    return set().union(*(c.digits.required_chars() for c in cfgs))


def _fmt_counts(counts: dict[str, int]) -> str:
    return "  ".join(f"{k}:{v}" for k, v in counts.items())


def _backups(args: argparse.Namespace) -> set[str]:
    from . import library

    return set(library.list_backups(args.calib_paths.templates))


def _backup_line(args: argparse.Namespace, before: set[str]) -> str:
    """Que respaldo dejo ESTA operacion (los nombres nuevos), o que no habia nada que respaldar."""
    new_backups = sorted(_backups(args) - before)
    if not new_backups:
        return "  no hubo nada que respaldar (la biblioteca estaba vacia)"
    return f"  respaldo: {new_backups[-1]}   (para deshacer: python -m spectro teach lib restore)"


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
def cmd_status(args: argparse.Namespace) -> int:
    """Panorama: biblioteca, una fila por corrida y el siguiente paso sugerido."""
    from . import library, read
    from .evaluation import load_history
    from .qc import load_qc_report
    from .rejected import load_rejected
    from .report import QC_REASONS
    from .teach import ALL_CHARS, load_truth

    _guard(args)
    calib = args.calib_paths
    tdir = calib.templates
    lib = library_or_empty(args)
    fingerprint = library.fingerprint(tdir)
    ids = _run_ids(args)
    runs = {r: _run_paths(args, r) for r in ids}
    cfgs = {r: Config.load(p.config) for r, p in runs.items()}
    train = {r: load_truth(p.truth) for r, p in runs.items()}
    test = {r: load_truth(p.test) for r, p in runs.items()}
    rejected = {r: load_rejected(p.rejected) for r, p in runs.items()}

    print("== teach status ==")
    print(f"biblioteca: {tdir}   {len(lib)} plantillas   huella {fingerprint or '-'}")
    counts = {c: sum(1 for t in lib if t.label == c) for c in ALL_CHARS}
    print("  " + _fmt_counts(counts))
    missing = sorted(_required_chars(args) - {t.label for t in lib})
    print(f"  faltan: {' '.join(repr(c) for c in missing) if missing else 'ninguno'}")
    backups = library.list_backups(tdir)
    print(f"  respaldos: {len(backups)}" + (f" (ultimo {backups[-1]})" if backups else ""))
    for r in ids:
        warning = library.warn_missing_sign(cfgs[r], lib)
        if warning:
            print("  " + warning.replace("\n", "\n  "))
            break

    print(f"\ncorridas ({len(ids)}):")
    if not ids:
        print("  (ninguna) crea una con: python -m spectro new videos/<video>.MOV")
    else:
        print(f"  {'corrida':22s} {'entren.':>7s} {'prueba':>6s} {'descart.':>8s}  {'salidas':16s} ultima evaluacion")
        for r in ids:
            hist = load_history(runs[r].history)
            last_eval_text = (f"{hist[-1]['date']}  exactitud {float(hist[-1]['accuracy']):.1%}"
                   if hist else "-")
            status = read.outputs_state(runs[r].readings, tdir, fingerprint)
            print(f"  {r:22s} {len(train[r]):7d} {len(test[r]):6d} {len(rejected[r]):8d}  {status:16s} {last_eval_text}")

        print("\ndescartes de qc por motivo (fotogramas que no se leen):")
        print(f"  {'corrida':22s} " + " ".join(f"{m[:11]:>11s}" for m in QC_REASONS))
        for r in ids:
            if not runs[r].qc_report.exists():
                print(f"  {r:22s} (sin qc_report.csv)")
                continue
            statuses = [x.status for x in load_qc_report(runs[r].qc_report)]
            print(f"  {r:22s} " + " ".join(f"{statuses.count(m):11d}" for m in QC_REASONS))

    print("\nsiguiente paso:")
    steps = _next_steps(args, lib, fingerprint, ids, runs, cfgs, train, test)
    for p in steps or ["nada pendiente"]:
        print(f"  - {p}")
    return 0


def _next_steps(args, lib, fingerprint, ids, runs, cfgs, train, test) -> list[str]:
    from . import read
    from .evaluation import load_history

    tdir = args.calib_paths.templates
    steps: list[str] = []
    with_samples = [r for r in ids if train[r]]
    mtimes = [p.stat().st_mtime for p in tdir.glob("*.png")] if tdir.is_dir() else []
    newest_mtime = max(mtimes) if mtimes else 0.0
    if not lib:
        steps.append("la biblioteca esta vacia: python -m spectro teach train" if with_samples else
                     "no hay biblioteca ni muestras: python -m spectro teach samples label <id>")
    else:
        no_sign = [r for r in ids if cfgs[r].digits.sign_slot is not None
                     and not any(s.value.startswith("-") for s in train[r])]
        if lib and not any(t.label == "-" for t in lib) and no_sign:
            steps.append("falta la plantilla '-': etiqueta valores negativos con "
                         f"python -m spectro teach samples label {no_sign[0]}")
        newer = [r for r in with_samples if runs[r].truth.stat().st_mtime > newest_mtime]
        if newer:
            steps.append("hay muestras mas nuevas que la biblioteca ("
                         + ", ".join(newer) + "): python -m spectro teach train")
    for r in ids:
        if read.outputs_state(runs[r].readings, tdir, fingerprint) == read.STALE:
            steps.append(f"las salidas de {r} son anteriores a la biblioteca: "
                         f"python -m spectro read --run {r}  y luego  report --run {r}")
    not_evaluated = []
    for r in ids:
        if not test[r]:
            continue
        hist = load_history(runs[r].history)
        if not hist:
            not_evaluated.append(r)
        elif hist[-1].get("fingerprint"):  # la huella manda; las filas viejas se juzgan por fecha
            if hist[-1]["fingerprint"] != fingerprint:
                not_evaluated.append(r)
        else:
            try:
                last_eval = datetime.strptime(hist[-1]["date"], "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                last_eval = 0.0
            if last_eval < newest_mtime:
                not_evaluated.append(r)
    for r in not_evaluated:
        steps.append(f"la prueba de {r} no se evaluo con la biblioteca vigente: "
                     f"python -m spectro teach test eval {r}")
    return steps


# --------------------------------------------------------------------------
# lib
# --------------------------------------------------------------------------
def cmd_lib_list(args: argparse.Namespace) -> int:
    from . import library
    from .teach import ALL_CHARS, build_pool_runs, gather_runs

    _guard(args)
    tdir = args.calib_paths.templates
    entries = library.list_entries(tdir)
    print(f"== biblioteca: {len(entries)} plantillas en {tdir}   huella {library.fingerprint(tdir) or '-'} ==")
    if args.usage:
        runs = gather_runs(args.runs_dir, args.calib_dir)
        _, datas, errors = build_pool_runs(runs)
        library.usage(entries, datas)
        cells = sum(len(d.glyphs) for d in datas)
        print(f"  uso medido sobre {cells} celdas de {len(datas)} muestras de {len(runs)} corridas"
              + (f" ({len(errors)} muestras no se pudieron procesar)" if errors else ""))
    for ch in ALL_CHARS:
        with_char = [e for e in entries if e.label == ch]
        if not args.usage:
            print(f"  {ch!r:5} x{len(with_char)}  {' '.join(e.path.stem for e in with_char)}")
            continue
        print(f"  {ch!r:5} x{len(with_char)}")
        for e in with_char:
            mark = "  DANINA: gana celdas de otro caracter" if e.errors else (
                "  sin uso" if e.uses == 0 else "")
            print(f"      {e.path.stem:8s} gana bien {e.uses:4d}   gana mal {e.errors:3d}{mark}")
    missing = sorted(_required_chars(args) - {e.label for e in entries})
    print(f"  faltan: {' '.join(repr(c) for c in missing) if missing else 'ninguno'}")
    return 0


def _entry_paths(args: argparse.Namespace, names: list[str]):
    from . import library

    by_name = {e.path.stem: e for e in library.list_entries(args.calib_paths.templates)}
    out = []
    for name in names:
        e = by_name.get(Path(name).stem)
        if e is None:
            raise ValueError(f"No existe la plantilla {name!r} en {args.calib_paths.templates}. "
                             "Mira los nombres con: python -m spectro teach lib list")
        out.append(e)
    return out


def cmd_lib_delete(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    entries = _entry_paths(args, args.names)
    before = _backups(args)
    library.delete([e.path for e in entries])
    print(f"{len(entries)} plantillas borradas de {args.calib_paths.templates}: "
          + " ".join(e.path.stem for e in entries))
    print(_backup_line(args, before))
    return 0


def cmd_lib_relabel(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    (e,) = _entry_paths(args, [args.name])
    before = _backups(args)
    dest = library.relabel(e.path, args.char, args.calib_paths.templates)
    print(f"{e.path.name} -> {dest.name}")
    print(_backup_line(args, before))
    return 0


def cmd_lib_clear(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    if not args.yes:
        raise ValueError("lib clear borra TODAS las plantillas de la biblioteca compartida "
                         "(se respalda antes). Confirmalo con: python -m spectro teach lib clear --yes")
    before = _backups(args)
    n = library.clear(args.calib_paths.templates)
    print(f"{n} plantillas borradas de {args.calib_paths.templates}")
    print(_backup_line(args, before))
    return 0


def cmd_lib_backups(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    tdir = args.calib_paths.templates
    names = library.list_backups(tdir)
    print(f"== respaldos de la biblioteca ({library.backups_root(tdir)}) ==")
    if not names:
        print("  (ninguno)")
    for n in names:
        n_files = len(list((library.backups_root(tdir) / n).glob("*.png")))
        print(f"  {n}   {n_files} plantillas")
    return 0


def cmd_lib_restore(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    before = set(library.list_backups(args.calib_paths.templates))
    name = library.restore_backup(args.calib_paths.templates, args.name)
    print(f"biblioteca restaurada desde el respaldo {name} "
          f"({args.calib_paths.n_templates()} plantillas)")
    new_backups = sorted(set(library.list_backups(args.calib_paths.templates)) - before)
    if new_backups:
        print(f"  el estado anterior quedo respaldado como {new_backups[-1]}")
    return 0


# --------------------------------------------------------------------------
# train / check
# --------------------------------------------------------------------------
def _train(args: argparse.Namespace, build: bool) -> int:
    from . import library
    from . import teach as T
    from .sampling import leakage

    _guard(args)
    exclude = list(args.exclude or [])
    if args.runs:
        ctxs = []
        for r in dict.fromkeys(args.runs):
            if r in exclude:
                continue
            ctx = _load(args, r)
            if not ctx.train:
                raise ValueError(f"La corrida {r} no tiene muestras de entrenamiento en {ctx.paths.truth}. "
                                 f"Etiqueta algunas con: python -m spectro teach samples label {r}")
            ctxs.append(ctx)
    else:
        ctxs = T.gather_runs(args.runs_dir, args.calib_dir, exclude)
    if not ctxs:
        raise ValueError(f"Ninguna corrida de {args.runs_dir}/ tiene muestras de entrenamiento. "
                         "Etiqueta algunas con: python -m spectro teach samples label <id>")

    tdir = args.calib_paths.templates
    before = set(library.list_backups(tdir))
    print(f"== teach {'train' if build else 'check'} ==")
    for c in ctxs:
        print(f"  {c.run_id:22s} {len(c.train):3d} muestras de entrenamiento")
    if exclude:
        print(f"  excluidas (quedan como prueba): {', '.join(exclude)}")
    res = T.train(ctxs, tdir, build=build, keep=getattr(args, "keep", False),
                  max_per_label=getattr(args, "max_per_label", DEFAULT_MAX_PER_LABEL))
    for e in res.errors:
        print(f"  muestra descartada: {e}")
    if not res.datas:
        raise ValueError("Ninguna muestra se pudo procesar.")
    print("  cobertura: " + _fmt_counts(res.coverage))
    if res.missing:
        print(f"  aviso: faltan ejemplos de {', '.join(res.missing)}; esos caracteres no se van a leer")
    if res.added is not None:
        print(f"  {sum(res.added.values())} plantillas escritas en {tdir}  "
              f"({', '.join(f'{k}:{v}' for k, v in sorted(res.added.items()))})")
        new_backups = sorted(set(library.list_backups(tdir)) - before)
        if new_backups:
            print(f"  respaldo de la biblioteca anterior: {new_backups[-1]}")
    if res.sign_warning:
        print("  " + res.sign_warning.replace("\n", "\n  "))

    print("  " + T.format_report(res.loo, "leave-one-out sobre todas las muestras")[0])
    for line in T.format_report(res.loo, "")[1:]:
        print("  " + line)
    if res.current is None:
        print("  no hay biblioteca vigente todavia")
    print(f"  {'corrida':22s} {'leave-one-out':>14s} {'biblioteca vigente':>20s}")
    for c in ctxs:
        a = T.split_by_run(res.loo, c.run_id)
        b = T.split_by_run(res.current, c.run_id) if res.current else None
        print(f"  {c.run_id:22s} {a.exact:>6d}/{a.total:<7d} "
              f"{(str(b.exact) + '/' + str(b.total)) if b else '-':>20s}")
        T.write_report(a, c.paths.teach_report)
        overlapping = leakage(c.train, c.test, args.gap)
        if overlapping:
            print(f"    aviso: {len(overlapping)} fotogramas de prueba de {c.run_id} estan a menos de "
                  f"{args.gap:g} s de uno de entrenamiento")
    print("  informes por corrida: runs/<id>/teach/teach_report.csv")
    print("  las pruebas (test.csv) no se usaron; para medirlas: python -m spectro teach test eval")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    return _train(args, build=True)


def cmd_check(args: argparse.Namespace) -> int:
    return _train(args, build=False)


# --------------------------------------------------------------------------
# samples / test: los dos conjuntos son simetricos (args.which = "train" | "test")
# --------------------------------------------------------------------------
#: Semilla de las sugerencias cuando no se pasa ``--seed`` (reproducibles por omision).
DEFAULT_SUGGEST_SEED = 0

_SET_NAME = {"train": "entrenamiento", "test": "prueba"}


def _samples(ctx: RunContext, which: str) -> list:
    return ctx.train if which == "train" else ctx.test


def _file_set(ctx: RunContext, which: str) -> Path:
    return ctx.paths.truth if which == "train" else ctx.paths.test


def cmd_set_list(args: argparse.Namespace) -> int:
    from . import teach as T
    from .extract import time_from_name

    _guard(args)
    which = args.which
    if args.run_id is None:
        print(f"== muestras de {_SET_NAME[which]} por corrida ==")
        print(f"  {'corrida':22s} {'muestras':>8s} {'valores':>8s}  caracteres sin cubrir")
        for r in _run_ids(args):
            run = _run_paths(args, r)
            cfg = Config.load(run.config)
            samples = T.load_truth(run.truth if which == "train" else run.test)
            cov = T.coverage(samples, cfg.digits)
            sin = [c for c in sorted(cfg.digits.required_chars()) if not cov.get(c)]
            print(f"  {r:22s} {len(samples):8d} {len({m.value for m in samples}):8d}  "
                  f"{' '.join(repr(c) for c in sin) if sin else 'ninguno'}")
        return 0

    ctx = _load(args, args.run_id)
    samples = sorted(_samples(ctx, which), key=lambda s: s.file)
    print(f"== {len(samples)} muestras de {_SET_NAME[which]} de {args.run_id} "
          f"({_file_set(ctx, which)}) ==")
    for s in samples:
        print(f"  {s.file}   t={time_from_name(s.file):8.2f} s   {s.value}")
    print("  cobertura: " + _fmt_counts(T.coverage(samples, ctx.cfg.digits)))
    lib = library_or_empty(args)
    if not samples:
        print("  (sin muestras)")
    elif not lib:
        print("  biblioteca vigente: no hay plantillas todavia (teach train)")
    else:
        _, datas, errors = T.build_pool(samples, ctx.cfg, ctx.frames_dir, ctx.offsets)
        rep = T.evaluate_library(datas, lib, ctx.cfg)
        print(f"  la biblioteca vigente lee bien {rep.exact}/{rep.total} de estas muestras")
        for e in errors:
            print(f"  muestra descartada: {e}")
    return 0


def cmd_set_add(args: argparse.Namespace) -> int:
    from . import teach as T
    from .rejected import rejected_files, remove_rejected, save_rejected
    from .sampling import assign

    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    train0, test0 = list(ctx.train), list(ctx.test)
    train, test = list(train0), list(test0)
    for item in args.items:
        file, sep, value = item.partition("=")
        if not sep or not value:
            raise ValueError(f"se espera ARCHIVO=VALOR, recibi {item!r}")
        if not (ctx.frames_dir / file).exists():
            raise FileNotFoundError(f"No existe el fotograma {ctx.frames_dir / file}")
        value = T.parse_value(value, ctx.cfg.digits)  # falla con el formato esperado
        already_trained = which == "test" and any(x.file == file for x in train)
        already_test = which == "train" and any(x.file == file for x in test)
        train, test = assign(train, test, T.Sample(file, value), which)
        if already_trained:
            print(f"  aviso: {file} estaba en entrenamiento y ya aporto glifos a la biblioteca; "
                  "para una prueba limpia reconstruila: python -m spectro teach train")
        if already_test:
            print(f"  aviso: {file} estaba en la prueba y paso a entrenamiento")
    if train != train0:
        T.save_truth(ctx.paths.truth, train)
    if test != test0:
        T.save_truth(ctx.paths.test, test)
    restored = {x.file for x in train + test} & rejected_files(ctx.rejected)
    if restored:
        save_rejected(ctx.paths.rejected, remove_rejected(ctx.rejected, restored)[0])
        print(f"  aviso: {', '.join(sorted(restored))} estaba descartado; lo saque de {ctx.paths.rejected}")
    print(f"{len(train)} muestras de entrenamiento en {ctx.paths.truth}; "
          f"{len(test)} de prueba en {ctx.paths.test}")
    return 0


def cmd_set_remove(args: argparse.Namespace) -> int:
    from . import teach as T

    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    samples = _samples(ctx, which)
    present_files = {s.file for s in samples}
    for a in args.files:
        if a not in present_files:
            print(f"  aviso: {a} no esta en las muestras de {_SET_NAME[which]}")
    to_remove = set(args.files) & present_files
    if not to_remove:
        raise ValueError(f"Ninguno de esos fotogramas esta en {_file_set(ctx, which)}")
    remaining = [s for s in samples if s.file not in to_remove]
    T.save_truth(_file_set(ctx, which), remaining)
    print(f"{len(to_remove)} muestras quitadas; quedan {len(remaining)} de {_SET_NAME[which]} "
          f"en {_file_set(ctx, which)}")
    return 0


def _suggest_fetch(args: argparse.Namespace, ctx: RunContext):
    """Arma el pedido de sugerencias: ``(fetch, base_exclude, base_avoid)``.

    ``fetch(exclude, avoid_times, n, round) -> (sugerencias, avisos)`` aplica la estrategia
    (``round`` suma a la semilla: cada ronda de reposicion da un lote distinto). La prueba
    siempre es al azar y lejos del entrenamiento (y el entrenamiento lejos de la prueba):
    una prueba elegida por incertidumbre subestimaria el error real. ``base_exclude`` es lo
    etiquetado en cualquiera de los dos conjuntos mas lo descartado sin muestra.
    """
    from . import read
    from . import sampling as S
    from .extract import time_from_name

    for_test = args.which == "test"
    strategy = "random" if for_test else args.strategy
    other = ctx.train if for_test else ctx.test
    base_avoid = [time_from_name(x.file) for x in other]
    base_exclude = {x.file for x in ctx.train + ctx.test} | ctx.rejected_files()
    run = ctx.paths
    reads, stale = None, False
    if strategy in ("mixed", "uncertain") and run.readings.exists():
        reads = read.load_readings(run.readings)
        stale = (S.readings_stale(run.readings, ctx.templates_dir, run.config)
                 or read.outputs_state(run.readings, ctx.templates_dir) == read.STALE)
    seed = DEFAULT_SUGGEST_SEED if args.seed is None else args.seed

    def fetch(exclude: set[str], avoid: list[float], n: int, round: int = 0):
        return S.suggest(strategy, items=ctx.items(), readings=reads, cfg=ctx.cfg,
                         exclude=exclude, n=n, seed=seed + round, gap_s=args.gap,
                         avoid_times=avoid, stale=stale)

    return fetch, base_exclude, base_avoid


def _suggestions(args: argparse.Namespace, ctx: RunContext, n: int):
    """Fotogramas a etiquetar segun la estrategia. Devuelve ``(sugerencias, avisos)``."""
    fetch, exclude, avoid = _suggest_fetch(args, ctx)
    return fetch(exclude, avoid, n, 0)


def cmd_set_suggest(args: argparse.Namespace) -> int:
    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    sug, warnings = _suggestions(args, ctx, args.n)
    used = "random" if which == "test" else args.strategy
    print(f"== teach: {len(sug)} fotogramas sugeridos para {_SET_NAME[which]} de {args.run_id} "
          f"(estrategia {used}) ==")
    for a in warnings:
        print(f"  aviso: {a}")
    for sg in sug:
        print(f"  {sg.file}   t={sg.t_s:8.2f} s   {sg.reason}")
    if ctx.rejected_files():
        print(f"  aviso: se excluyeron {len(ctx.rejected_files())} fotogramas descartados "
              f"(ver: python -m spectro teach rejected list {args.run_id})")
    area = "samples" if which == "train" else "test"
    print(f"  para cargarlos: python -m spectro teach {area} label {args.run_id} --queue {args.n}")
    return 0


def _label_queue(args: argparse.Namespace, ctx: RunContext):
    """La cola de ``label``: ``(names, reasons, refill)``.

    Sin ``--queue``, todos los fotogramas que pasaron QC menos los descartados y sin
    reposicion. Con ``--queue N``, la lista de ``suggest`` mas un ``QueueRefill`` que repone
    la cola cuando se descarta un fotograma.
    """
    from .sampling import QueueRefill

    if not args.queue:
        rejected = ctx.rejected_files()
        names = [n for n in ctx.names() if n not in rejected]
        if not names:
            if rejected:
                raise ValueError(
                    "Todos los fotogramas estan descartados. Restauralos con: python -m spectro "
                    f"teach rejected remove {args.run_id} ARCHIVO...")
            raise ValueError("No hay fotogramas. Corre primero extract y qc.")
        return names, {}, None
    fetch, exclude, avoid = _suggest_fetch(args, ctx)
    sug, warnings = fetch(exclude, avoid, args.queue, 0)
    for a in warnings:
        print(f"aviso: {a}")
    if not sug:
        raise ValueError("No hay fotogramas que sugerir (todo esta etiquetado, descartado o excluido).")
    refill = QueueRefill(fetch, max(args.queue, 5), args.gap)
    return [sg.file for sg in sug], {sg.file: sg.reason for sg in sug}, refill


def cmd_set_label(args: argparse.Namespace) -> int:
    from .teach_session import TeachParams
    from .teach_ui import run_teach_ui

    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    names, reasons, refill = _label_queue(args, ctx)
    ui_args = TeachParams.from_context(ctx, args.max_per_label, args.gap, args.seed)
    return run_teach_ui(ctx.cfg, ui_args, names, ctx.offsets, ctx.train, test=ctx.test,
                        reasons=reasons, target=which, rejected=ctx.rejected, refill=refill)


# --------------------------------------------------------------------------
# rejected
# --------------------------------------------------------------------------
def cmd_rejected_list(args: argparse.Namespace) -> int:
    from .extract import time_from_name
    from .rejected import load_rejected

    _guard(args)
    if args.run_id is None:
        print("== fotogramas descartados por corrida ==")
        print(f"  {'corrida':22s} {'descartados':>11s} {'entren.':>7s} {'prueba':>6s}")
        for r in _run_ids(args):
            rows = load_rejected(_run_paths(args, r).rejected)
            print(f"  {r:22s} {len(rows):11d} {sum(x.which == 'train' for x in rows):7d} "
                  f"{sum(x.which == 'test' for x in rows):6d}")
        return 0
    ctx = _load(args, args.run_id)
    rows = sorted(ctx.rejected, key=lambda x: x.file)
    print(f"== {len(rows)} fotogramas descartados de {args.run_id} ({ctx.paths.rejected}) ==")
    if not rows:
        print("  (ninguno)")
    else:
        print(f"  {'archivo':24s} {'t (s)':>9s}  {'set':5s} fecha")
        for x in rows:
            print(f"  {x.file:24s} {time_from_name(x.file):9.2f}  {x.which:5s} {x.date}")
    return 0


def cmd_rejected_remove(args: argparse.Namespace) -> int:
    from .rejected import remove_rejected, save_rejected

    _guard(args)
    ctx = _load(args, args.run_id)
    remaining, was = remove_rejected(ctx.rejected, args.files)
    for a in args.files:
        if a not in was:
            print(f"  aviso: {a} no esta descartado")
    if not was:
        raise ValueError(f"Ninguno de esos fotogramas esta en {ctx.paths.rejected}")
    save_rejected(ctx.paths.rejected, remaining)
    print(f"{len(was)} fotogramas restaurados; quedan {len(remaining)} descartados en {ctx.paths.rejected}")
    return 0


# --------------------------------------------------------------------------
# test eval / history
# --------------------------------------------------------------------------
def cmd_test_eval(args: argparse.Namespace) -> int:
    """Una corrida: informe detallado, ``test_report.csv`` e historial. Varias o ninguna: tabla."""
    from . import library
    from .evaluation import append_history, evaluate_test, format_test_report, write_test_report
    from .report import (
        acceptance_for, batch_summary, format_batch_table, load_run_input,
    )
    from .teach import load_truth

    _guard(args)
    calib = args.calib_paths
    lib = library.load(calib.templates)  # sin biblioteca: el error dice que correr
    fingerprint = library.fingerprint(calib.templates)
    acc = acceptance_for(calib.config, args.min_accuracy, args.max_error, args.min_coverage)

    if len(args.runs) == 1:
        ctx = _load(args, args.runs[0])
        run = ctx.paths
        if not ctx.test:
            raise ValueError(
                f"No hay muestras de prueba en {run.test}. Arma el conjunto con: python -m spectro "
                f"teach test suggest {run.id} 20, y cargalo con: teach test label {run.id}")
        rep = evaluate_test(ctx.test, ctx.cfg, ctx.frames_dir, ctx.offsets, lib, ctx.train, args.gap)
        print(f"== teach test eval {run.id} ==")
        for line in format_test_report(rep):
            print("  " + line)
        write_test_report(rep, run.test_report)
        append_history(run.history, rep, fingerprint=fingerprint)
        print(f"  informe: {run.test_report}   historial: {run.history}")
        run_input = load_run_input(run, calib, lib, with_eval=False, fingerprint=fingerprint)
        run_input.test = rep
        for line in format_batch_table(batch_summary([run_input], acc)):
            print(line)
        return 0

    ids = list(dict.fromkeys(args.runs)) or [
        r for r in _run_ids(args) if load_truth(_run_paths(args, r).test)]
    print(f"== teach test eval (biblioteca: {len(lib)} plantillas) ==")
    if not ids:
        print("  ninguna corrida tiene test.csv. Arma uno con: python -m spectro teach test suggest <id> 20")
        return 0
    entries = [load_run_input(require_run(r, args.runs_dir, args.calib_dir), calib, lib,
                               gap_s=args.gap, fingerprint=fingerprint) for r in ids]
    for line in format_batch_table(batch_summary(entries, acc)):
        print(line)
    print("  detalle de una corrida: python -m spectro teach test eval <id>")
    return 0


def cmd_test_history(args: argparse.Namespace) -> int:
    from .evaluation import load_history

    _guard(args)
    run = require_run(args.run_id, args.runs_dir, args.calib_dir)
    rows = load_history(run.history)
    print(f"== historial de evaluaciones de {run.id} ({run.history}) ==")
    if not rows:
        print(f"  (vacio) corre: python -m spectro teach test eval {run.id}")
        return 0
    print(f"  {'fecha':19s} {'tipo':14s} {'plant.':>6s} {'entren.':>7s} {'prueba':>6s} "
          f"{'correctas':>9s} {'erroneas':>8s} {'descart.':>8s} {'exact.':>7s} {'error':>6s} "
          f"{'cobert.':>8s}  cambio")
    prior = None
    for f in rows:
        ex = float(f["accuracy"])
        change = "" if prior is None else f"{100 * (ex - prior):+.1f} pt"
        print(f"  {f['date']:19s} {f['kind']:14s} {f['templates']:>6s} {f['training']:>7s} "
              f"{f['test']:>6s} {f['correct']:>9s} {f['wrong']:>8s} {f['discarded']:>8s} "
              f"{ex:7.1%} {float(f['accepted_error']):6.1%} {float(f['coverage']):8.1%}  {change}")
        prior = ex
    return 0


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def register(sub, layout: argparse.ArgumentParser) -> None:
    """Registra ``teach`` y su arbol de areas y verbos en el parser principal."""
    fmt = argparse.ArgumentDefaultsHelpFormatter

    def leaf(group, name, func, help_text, **defaults):
        p = group.add_parser(name, help=help_text, description=help_text, parents=[layout],
                             formatter_class=fmt)
        p.set_defaults(func=func, needs_paths=False, **defaults)
        return p

    def area(name, help_text, dest):
        p = sub_teach.add_parser(name, help=help_text, description=help_text, parents=[layout],
                                 formatter_class=fmt)
        return p, p.add_subparsers(dest=dest, required=True, metavar="VERBO")

    def run_arg(p, optional=False):
        p.add_argument("run_id", metavar="RUN", nargs="?" if optional else None,
                       help="Id de la corrida, completo (ej. img_8102)")

    th = sub.add_parser(
        "teach", help="Biblioteca, muestras y pruebas del lector, por areas",
        description="Entrenar el lector con valores reales y medirlo. Se elige un area y un verbo.",
        epilog=MIGRATION, parents=[layout], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub_teach = th.add_subparsers(dest="area", required=True, metavar="AREA")

    leaf(sub_teach, "status", cmd_status,
         "Panorama de la biblioteca y de cada corrida, y el siguiente paso")

    # -- lib
    _, lib = area("lib", "La biblioteca global de plantillas (calib/templates), sin corrida", "verb")
    p = leaf(lib, "list", cmd_lib_list, "Plantillas por caracter y caracteres que faltan")
    p.add_argument("--usage", action="store_true",
                   help="Medir cuantas celdas gana bien y mal cada plantilla sobre las muestras de todas las corridas")
    p = leaf(lib, "delete", cmd_lib_delete, "Borrar plantillas por nombre (se respalda antes)")
    p.add_argument("names", nargs="+", metavar="NOMBRE", help="Ej. 0_3 5_1")
    p = leaf(lib, "relabel", cmd_lib_relabel, "Cambiar la etiqueta de una plantilla (se respalda antes)")
    p.add_argument("name", metavar="NOMBRE", help="Ej. 0_3")
    p.add_argument("char", metavar="CARACTER", help="Uno de 0123456789.-")
    p = leaf(lib, "clear", cmd_lib_clear, "Vaciar la biblioteca (se respalda antes)")
    p.add_argument("--yes", action="store_true", help="Confirmar el borrado")
    leaf(lib, "backups", cmd_lib_backups, "Listar los respaldos (se conservan los ultimos 5)")
    p = leaf(lib, "restore", cmd_lib_restore,
             "Volver a un respaldo (el ultimo, o NOMBRE); respalda antes el estado actual")
    p.add_argument("name", metavar="NOMBRE", nargs="?", help="Nombre del respaldo (ver lib backups)")

    # -- train / check
    for name, func, help_text in (
        ("train", cmd_train, "Arma la biblioteca global con las muestras de entrenamiento (respalda la anterior)"),
        ("check", cmd_check, "Valida las muestras (leave-one-out) sin tocar la biblioteca"),
    ):
        p = leaf(sub_teach, name, func, help_text)
        p.add_argument("runs", nargs="*", metavar="RUN",
                       help="Corridas a usar (default: todas las que tengan truth.csv)")
        p.add_argument("--exclude", nargs="+", metavar="RUN",
                       help="Corridas que no se usan para entrenar (hold-out por video)")
        p.add_argument("--gap", type=float, default=5.0, metavar="SEGUNDOS",
                       help="Avisar si una prueba esta a menos de esto de un fotograma de entrenamiento")
        if name == "train":
            p.add_argument("--keep", action="store_true",
                           help="Sumar a las plantillas existentes (sin duplicar) en vez de reemplazarlas")
            p.add_argument("--max-per-label", type=int, default=DEFAULT_MAX_PER_LABEL,
                           help="Maximo de variantes de plantilla por caracter")

    # -- samples y test
    for name, which, help_text in (
        ("samples", "train", "Muestras de ENTRENAMIENTO de una corrida (runs/<id>/teach/truth.csv)"),
        ("test", "test", "PRUEBAS de una corrida (runs/<id>/test/test.csv): nunca entran a la biblioteca"),
    ):
        _, g = area(name, help_text, "verb")
        d = {"which": which}
        p = leaf(g, "list", cmd_set_list, "Sin corrida, una tabla de todas; con corrida, sus muestras", **d)
        run_arg(p, optional=True)
        p = leaf(g, "add", cmd_set_add,
                 "Agregar muestras; un fotograma esta en un solo conjunto (la saca del otro)", **d)
        run_arg(p)
        p.add_argument("items", nargs="+", metavar="ARCHIVO=VALOR", help="Ej. t_0001352.000.jpg=-0.018")
        p = leaf(g, "remove", cmd_set_remove, "Quitar muestras", **d)
        run_arg(p)
        p.add_argument("files", nargs="+", metavar="ARCHIVO", help="Ej. t_0001352.000.jpg")
        d2 = d if which == "train" else {**d, "strategy": "random"}
        p = leaf(g, "suggest", cmd_set_suggest,
                 "Imprimir fotogramas para etiquetar" + ("" if which == "train" else
                                                          " (siempre al azar y lejos del entrenamiento)"),
                 **d2)
        run_arg(p)
        p.add_argument("n", metavar="N", nargs="?", type=int, default=20, help="Cuantos fotogramas")
        p2 = leaf(g, "label", cmd_set_label,
                  "Abrir la ventana para etiquetar (conjunto activo: "
                  + ("Entrenam.)" if which == "train" else "Prueba)"), **d2)
        run_arg(p2)
        p2.add_argument("--queue", type=int, default=0, metavar="N",
                        help="Abrir la ventana solo con los N fotogramas sugeridos")
        p2.add_argument("--max-per-label", type=int, default=DEFAULT_MAX_PER_LABEL,
                        help="Maximo de variantes de plantilla por caracter (botones de biblioteca)")
        for q in (p, p2):
            if which == "train":
                q.add_argument("--strategy", choices=["mixed", "uncertain", "random", "uniform"],
                               default="mixed",
                               help="mixed = mitad incertidumbre, mitad azar")
            q.add_argument("--seed", type=int, default=None,
                           help="Semilla del muestreo al azar y del boton Aleatorio "
                                "(sin ella: sugerencias con semilla 0 y Aleatorio no determinista)")
            q.add_argument("--gap", type=float, default=5.0, metavar="SEGUNDOS",
                           help="Separacion minima entre fotogramas elegidos, y entre prueba y entrenamiento")
        if which == "test":
            p = leaf(g, "eval", cmd_test_eval,
                     "Evaluar con la biblioteca vigente: una corrida da el informe; varias o ninguna, una tabla")
            p.add_argument("runs", nargs="*", metavar="RUN",
                           help="Corridas (default: todas las que tengan test.csv)")
            p.add_argument("--gap", type=float, default=5.0, metavar="SEGUNDOS",
                           help="Avisar si una prueba esta a menos de esto de un fotograma de entrenamiento")
            for flag, h in (("--min-accuracy", "exactitud minima"),
                            ("--max-error", "error maximo entre las aceptadas"),
                            ("--min-coverage", "cobertura minima")):
                p.add_argument(flag, type=float, default=None,
                               help=f"Veredicto: {h} (fraccion). Sin valor, 'acceptance' de calib/config.json")
            p = leaf(g, "history", cmd_test_history, "La curva de aprendizaje: una fila por evaluacion")
            run_arg(p)

    # -- rejected
    _, g = area("rejected", "Fotogramas descartados al etiquetar (runs/<id>/teach/rejected.csv)", "verb")
    p = leaf(g, "list", cmd_rejected_list, "Sin corrida, una tabla de todas; con corrida, sus descartados")
    run_arg(p, optional=True)
    p = leaf(g, "remove", cmd_rejected_remove, "Restaurar fotogramas: vuelven a sugerirse")
    run_arg(p)
    p.add_argument("files", nargs="+", metavar="ARCHIVO", help="Ej. t_0001352.000.jpg")
