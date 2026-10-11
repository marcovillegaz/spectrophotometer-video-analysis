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

El id de la corrida va como argumento posicional, completo: nunca se adivina sobre que
experimento se trabaja. Los handlers no pasan por ``cli.resolve_paths`` (``needs_paths=False``):
las rutas salen de ``RunPaths`` / ``CalibPaths``, y para probar sobre una copia basta
``--calib-dir`` / ``--runs-dir``. Los modulos pesados (cv2) se importan dentro de cada handler.

Interfaz publica:
    register(sub, layout)       registra el comando ``teach`` en el parser principal
    legacy_error(argv)          mensaje de migracion si se uso la sintaxis vieja (``teach --build``...)
    MIGRACION                   la tabla "antes -> ahora"
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_MAX_PER_LABEL, Config
from .project import RunContext, RunPaths, list_runs, require_run

AREAS = ("status", "lib", "train", "check", "samples", "test")
#: Flags del layout que llevan valor: se saltean al buscar el area.
_LAYOUT_CON_VALOR = ("--run", "--runs-dir", "--calib-dir", "--config")

MIGRACION = """\
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
  (nuevo)                                 teach status | teach lib restore | teach test history ID

--strategy, --seed, --gap, --keep y --max-per-label siguen existiendo, pero en el verbo al que sirven.
Areas: status, lib, train, check, samples, test. Ayuda de cada una: teach <area> --help"""


# --------------------------------------------------------------------------
# Sintaxis vieja
# --------------------------------------------------------------------------
def legacy_error(argv: list[str]) -> str | None:
    """El mensaje de migracion si ``teach`` se uso sin area (la sintaxis de flags de modo)."""
    i = 0
    while i < len(argv) and argv[i].split("=")[0] in _LAYOUT_CON_VALOR:
        i += 1 if "=" in argv[i] else 2
    if i >= len(argv) or argv[i] != "teach":
        return None
    resto = argv[i + 1:]
    j = 0
    while j < len(resto) and resto[j].split("=")[0] in _LAYOUT_CON_VALOR:
        j += 1 if "=" in resto[j] else 2
    if j < len(resto) and (resto[j] in AREAS or resto[j] in ("-h", "--help")):
        return None
    if j < len(resto) and not resto[j].startswith("-"):
        return (f"area desconocida {resto[j]!r}. Areas: {', '.join(AREAS)}. "
                "Ayuda: python -m spectro teach --help")
    return MIGRACION


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
    """Las corridas dadas de alta (con config.json)."""
    return [r for r in list_runs(runs_dir=args.runs_dir)
            if RunPaths.for_run(r, runs_dir=args.runs_dir, calib_dir=args.calib_dir).exists()]


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


def _respaldos(args: argparse.Namespace) -> set[str]:
    from . import library

    return set(library.list_backups(args.calib_paths.templates))


def _linea_respaldo(args: argparse.Namespace, antes: set[str]) -> str:
    """Que respaldo dejo ESTA operacion (los nombres nuevos), o que no habia nada que respaldar."""
    nuevos = sorted(_respaldos(args) - antes)
    if not nuevos:
        return "  no hubo nada que respaldar (la biblioteca estaba vacia)"
    return f"  respaldo: {nuevos[-1]}   (para deshacer: python -m spectro teach lib restore)"


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
def cmd_status(args: argparse.Namespace) -> int:
    """Panorama: biblioteca, una fila por corrida y el siguiente paso sugerido."""
    from . import library, read
    from .evaluation import load_history
    from .qc import load_qc_report
    from .report import QC_REASONS
    from .teach import ALL_CHARS, load_truth

    _guard(args)
    calib = args.calib_paths
    tdir = calib.templates
    lib = library_or_empty(args)
    huella = library.fingerprint(tdir)
    ids = _run_ids(args)
    runs = {r: _run_paths(args, r) for r in ids}
    cfgs = {r: Config.load(p.config) for r, p in runs.items()}
    train = {r: load_truth(p.truth) for r, p in runs.items()}
    test = {r: load_truth(p.test) for r, p in runs.items()}

    print("== teach status ==")
    print(f"biblioteca: {tdir}   {len(lib)} plantillas   huella {huella or '-'}")
    cuenta = {c: sum(1 for t in lib if t.label == c) for c in ALL_CHARS}
    print("  " + _fmt_counts(cuenta))
    faltan = sorted(_required_chars(args) - {t.label for t in lib})
    print(f"  faltan: {' '.join(repr(c) for c in faltan) if faltan else 'ninguno'}")
    respaldos = library.list_backups(tdir)
    print(f"  respaldos: {len(respaldos)}" + (f" (ultimo {respaldos[-1]})" if respaldos else ""))
    for r in ids:
        aviso = library.warn_missing_sign(cfgs[r], lib)
        if aviso:
            print("  " + aviso.replace("\n", "\n  "))
            break

    print(f"\ncorridas ({len(ids)}):")
    if not ids:
        print("  (ninguna) crea una con: python -m spectro new videos/<video>.MOV")
    else:
        print(f"  {'corrida':22s} {'entren.':>7s} {'prueba':>6s}  {'salidas':16s} ultima evaluacion")
        for r in ids:
            hist = load_history(runs[r].history)
            ult = (f"{hist[-1]['fecha']}  exactitud {float(hist[-1]['exactitud']):.1%}"
                   if hist else "-")
            estado = read.outputs_state(runs[r].readings, tdir, huella)
            print(f"  {r:22s} {len(train[r]):7d} {len(test[r]):6d}  {estado:16s} {ult}")

        print("\ndescartes de qc por motivo (fotogramas que no se leen):")
        print(f"  {'corrida':22s} " + " ".join(f"{m[:9]:>9s}" for m in QC_REASONS))
        for r in ids:
            if not runs[r].qc_report.exists():
                print(f"  {r:22s} (sin qc_report.csv)")
                continue
            estados = [x.estado for x in load_qc_report(runs[r].qc_report)]
            print(f"  {r:22s} " + " ".join(f"{estados.count(m):9d}" for m in QC_REASONS))

    print("\nsiguiente paso:")
    pasos = _siguientes_pasos(args, lib, huella, ids, runs, cfgs, train, test)
    for p in pasos or ["nada pendiente"]:
        print(f"  - {p}")
    return 0


def _siguientes_pasos(args, lib, huella, ids, runs, cfgs, train, test) -> list[str]:
    from . import read
    from .evaluation import load_history

    tdir = args.calib_paths.templates
    pasos: list[str] = []
    con_muestras = [r for r in ids if train[r]]
    mtimes = [p.stat().st_mtime for p in tdir.glob("*.png")] if tdir.is_dir() else []
    nueva = max(mtimes) if mtimes else 0.0
    if not lib:
        pasos.append("la biblioteca esta vacia: python -m spectro teach train" if con_muestras else
                     "no hay biblioteca ni muestras: python -m spectro teach samples label <id>")
    else:
        sin_signo = [r for r in ids if cfgs[r].digits.sign_slot is not None
                     and not any(s.valor.startswith("-") for s in train[r])]
        if lib and not any(t.label == "-" for t in lib) and sin_signo:
            pasos.append("falta la plantilla '-': etiqueta valores negativos con "
                         f"python -m spectro teach samples label {sin_signo[0]}")
        mas_nuevas = [r for r in con_muestras if runs[r].truth.stat().st_mtime > nueva]
        if mas_nuevas:
            pasos.append("hay muestras mas nuevas que la biblioteca ("
                         + ", ".join(mas_nuevas) + "): python -m spectro teach train")
    for r in ids:
        if read.outputs_state(runs[r].readings, tdir, huella) == read.DESACTUALIZADAS:
            pasos.append(f"las salidas de {r} son anteriores a la biblioteca: "
                         f"python -m spectro read --run {r}  y luego  report --run {r}")
    sin_evaluar = []
    for r in ids:
        if not test[r]:
            continue
        hist = load_history(runs[r].history)
        if not hist:
            sin_evaluar.append(r)
        elif hist[-1].get("huella"):  # la huella manda; las filas viejas se juzgan por fecha
            if hist[-1]["huella"] != huella:
                sin_evaluar.append(r)
        else:
            try:
                ultima = datetime.strptime(hist[-1]["fecha"], "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                ultima = 0.0
            if ultima < nueva:
                sin_evaluar.append(r)
    for r in sin_evaluar:
        pasos.append(f"la prueba de {r} no se evaluo con la biblioteca vigente: "
                     f"python -m spectro teach test eval {r}")
    return pasos


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
        _, datas, errores = build_pool_runs(runs)
        library.usage(entries, datas)
        celdas = sum(len(d.glyphs) for d in datas)
        print(f"  uso medido sobre {celdas} celdas de {len(datas)} muestras de {len(runs)} corridas"
              + (f" ({len(errores)} muestras no se pudieron procesar)" if errores else ""))
    for ch in ALL_CHARS:
        de_ch = [e for e in entries if e.label == ch]
        if not args.usage:
            print(f"  {ch!r:5} x{len(de_ch)}  {' '.join(e.path.stem for e in de_ch)}")
            continue
        print(f"  {ch!r:5} x{len(de_ch)}")
        for e in de_ch:
            marca = "  DANINA: gana celdas de otro caracter" if e.errors else (
                "  sin uso" if e.uses == 0 else "")
            print(f"      {e.path.stem:8s} gana bien {e.uses:4d}   gana mal {e.errors:3d}{marca}")
    faltan = sorted(_required_chars(args) - {e.label for e in entries})
    print(f"  faltan: {' '.join(repr(c) for c in faltan) if faltan else 'ninguno'}")
    return 0


def _entry_paths(args: argparse.Namespace, nombres: list[str]):
    from . import library

    by_name = {e.path.stem: e for e in library.list_entries(args.calib_paths.templates)}
    out = []
    for nombre in nombres:
        e = by_name.get(Path(nombre).stem)
        if e is None:
            raise ValueError(f"No existe la plantilla {nombre!r} en {args.calib_paths.templates}. "
                             "Mira los nombres con: python -m spectro teach lib list")
        out.append(e)
    return out


def cmd_lib_delete(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    entradas = _entry_paths(args, args.nombres)
    antes = _respaldos(args)
    library.delete([e.path for e in entradas])
    print(f"{len(entradas)} plantillas borradas de {args.calib_paths.templates}: "
          + " ".join(e.path.stem for e in entradas))
    print(_linea_respaldo(args, antes))
    return 0


def cmd_lib_relabel(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    (e,) = _entry_paths(args, [args.nombre])
    antes = _respaldos(args)
    dest = library.relabel(e.path, args.caracter, args.calib_paths.templates)
    print(f"{e.path.name} -> {dest.name}")
    print(_linea_respaldo(args, antes))
    return 0


def cmd_lib_clear(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    if not args.yes:
        raise ValueError("lib clear borra TODAS las plantillas de la biblioteca compartida "
                         "(se respalda antes). Confirmalo con: python -m spectro teach lib clear --yes")
    antes = _respaldos(args)
    n = library.clear(args.calib_paths.templates)
    print(f"{n} plantillas borradas de {args.calib_paths.templates}")
    print(_linea_respaldo(args, antes))
    return 0


def cmd_lib_backups(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    tdir = args.calib_paths.templates
    nombres = library.list_backups(tdir)
    print(f"== respaldos de la biblioteca ({library.backups_root(tdir)}) ==")
    if not nombres:
        print("  (ninguno)")
    for n in nombres:
        cant = len(list((library.backups_root(tdir) / n).glob("*.png")))
        print(f"  {n}   {cant} plantillas")
    return 0


def cmd_lib_restore(args: argparse.Namespace) -> int:
    from . import library

    _guard(args)
    antes = set(library.list_backups(args.calib_paths.templates))
    nombre = library.restore_backup(args.calib_paths.templates, args.nombre)
    print(f"biblioteca restaurada desde el respaldo {nombre} "
          f"({args.calib_paths.n_templates()} plantillas)")
    nuevos = sorted(set(library.list_backups(args.calib_paths.templates)) - antes)
    if nuevos:
        print(f"  el estado anterior quedo respaldado como {nuevos[-1]}")
    return 0


# --------------------------------------------------------------------------
# train / check
# --------------------------------------------------------------------------
def _train(args: argparse.Namespace, build: bool) -> int:
    from . import library
    from . import teach as T
    from .sampling import leakage

    _guard(args)
    excluir = list(args.exclude or [])
    if args.runs:
        ctxs = []
        for r in dict.fromkeys(args.runs):
            if r in excluir:
                continue
            ctx = _load(args, r)
            if not ctx.train:
                raise ValueError(f"La corrida {r} no tiene muestras de entrenamiento en {ctx.paths.truth}. "
                                 f"Etiqueta algunas con: python -m spectro teach samples label {r}")
            ctxs.append(ctx)
    else:
        ctxs = T.gather_runs(args.runs_dir, args.calib_dir, excluir)
    if not ctxs:
        raise ValueError(f"Ninguna corrida de {args.runs_dir}/ tiene muestras de entrenamiento. "
                         "Etiqueta algunas con: python -m spectro teach samples label <id>")

    tdir = args.calib_paths.templates
    antes = set(library.list_backups(tdir))
    print(f"== teach {'train' if build else 'check'} ==")
    for c in ctxs:
        print(f"  {c.run_id:22s} {len(c.train):3d} muestras de entrenamiento")
    if excluir:
        print(f"  excluidas (quedan como prueba): {', '.join(excluir)}")
    res = T.train(ctxs, tdir, build=build, keep=getattr(args, "keep", False),
                  max_per_label=getattr(args, "max_per_label", DEFAULT_MAX_PER_LABEL))
    for e in res.errores:
        print(f"  muestra descartada: {e}")
    if not res.datas:
        raise ValueError("Ninguna muestra se pudo procesar.")
    print("  cobertura: " + _fmt_counts(res.coverage))
    if res.faltan:
        print(f"  aviso: faltan ejemplos de {', '.join(res.faltan)}; esos caracteres no se van a leer")
    if res.nuevas is not None:
        print(f"  {sum(res.nuevas.values())} plantillas escritas en {tdir}  "
              f"({', '.join(f'{k}:{v}' for k, v in sorted(res.nuevas.items()))})")
        nuevos = sorted(set(library.list_backups(tdir)) - antes)
        if nuevos:
            print(f"  respaldo de la biblioteca anterior: {nuevos[-1]}")
    if res.aviso_signo:
        print("  " + res.aviso_signo.replace("\n", "\n  "))

    print("  " + T.format_report(res.loo, "leave-one-out sobre todas las muestras")[0])
    for line in T.format_report(res.loo, "")[1:]:
        print("  " + line)
    if res.vigente is None:
        print("  no hay biblioteca vigente todavia")
    print(f"  {'corrida':22s} {'leave-one-out':>14s} {'biblioteca vigente':>20s}")
    for c in ctxs:
        a = T.split_by_run(res.loo, c.run_id)
        b = T.split_by_run(res.vigente, c.run_id) if res.vigente else None
        print(f"  {c.run_id:22s} {a.exact:>6d}/{a.total:<7d} "
              f"{(str(b.exact) + '/' + str(b.total)) if b else '-':>20s}")
        T.write_report(a, c.paths.teach_report)
        solapadas = leakage(c.train, c.test, args.gap)
        if solapadas:
            print(f"    aviso: {len(solapadas)} fotogramas de prueba de {c.run_id} estan a menos de "
                  f"{args.gap:g} s de uno de entrenamiento")
    print("  informes por corrida: runs/<id>/out/teach_report.csv")
    print("  las pruebas (test.csv) no se usaron; para medirlas: python -m spectro teach test eval")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    return _train(args, build=True)


def cmd_check(args: argparse.Namespace) -> int:
    return _train(args, build=False)


# --------------------------------------------------------------------------
# samples / test: los dos conjuntos son simetricos (args.which = "train" | "test")
# --------------------------------------------------------------------------
_NOMBRE_SET = {"train": "entrenamiento", "test": "prueba"}


def _muestras(ctx: RunContext, which: str) -> list:
    return ctx.train if which == "train" else ctx.test


def _archivo_set(ctx: RunContext, which: str) -> Path:
    return ctx.paths.truth if which == "train" else ctx.paths.test


def cmd_set_list(args: argparse.Namespace) -> int:
    from . import teach as T
    from .extract import time_from_name

    _guard(args)
    which = args.which
    if args.run_id is None:
        print(f"== muestras de {_NOMBRE_SET[which]} por corrida ==")
        print(f"  {'corrida':22s} {'muestras':>8s} {'valores':>8s}  caracteres sin cubrir")
        for r in _run_ids(args):
            run = _run_paths(args, r)
            cfg = Config.load(run.config)
            muestras = T.load_truth(run.truth if which == "train" else run.test)
            cov = T.coverage(muestras, cfg.digits)
            sin = [c for c in sorted(cfg.digits.required_chars()) if not cov.get(c)]
            print(f"  {r:22s} {len(muestras):8d} {len({m.valor for m in muestras}):8d}  "
                  f"{' '.join(repr(c) for c in sin) if sin else 'ninguno'}")
        return 0

    ctx = _load(args, args.run_id)
    muestras = sorted(_muestras(ctx, which), key=lambda s: s.archivo)
    print(f"== {len(muestras)} muestras de {_NOMBRE_SET[which]} de {args.run_id} "
          f"({_archivo_set(ctx, which)}) ==")
    for s in muestras:
        print(f"  {s.archivo}   t={time_from_name(s.archivo):8.2f} s   {s.valor}")
    print("  cobertura: " + _fmt_counts(T.coverage(muestras, ctx.cfg.digits)))
    lib = library_or_empty(args)
    if not muestras:
        print("  (sin muestras)")
    elif not lib:
        print("  biblioteca vigente: no hay plantillas todavia (teach train)")
    else:
        _, datas, errores = T.build_pool(muestras, ctx.cfg, ctx.frames_dir, ctx.offsets)
        rep = T.evaluate_library(datas, lib, ctx.cfg)
        print(f"  la biblioteca vigente lee bien {rep.exact}/{rep.total} de estas muestras")
        for e in errores:
            print(f"  muestra descartada: {e}")
    return 0


def cmd_set_add(args: argparse.Namespace) -> int:
    from . import teach as T
    from .sampling import assign

    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    train0, test0 = list(ctx.train), list(ctx.test)
    train, test = list(train0), list(test0)
    for item in args.items:
        archivo, sep, valor = item.partition("=")
        if not sep or not valor:
            raise ValueError(f"se espera ARCHIVO=VALOR, recibi {item!r}")
        if not (ctx.frames_dir / archivo).exists():
            raise FileNotFoundError(f"No existe el fotograma {ctx.frames_dir / archivo}")
        valor = T.parse_value(valor, ctx.cfg.digits)  # falla con el formato esperado
        ya_entreno = which == "test" and any(x.archivo == archivo for x in train)
        ya_prueba = which == "train" and any(x.archivo == archivo for x in test)
        train, test = assign(train, test, T.Sample(archivo, valor), which)
        if ya_entreno:
            print(f"  aviso: {archivo} estaba en entrenamiento y ya aporto glifos a la biblioteca; "
                  "para una prueba limpia reconstruila: python -m spectro teach train")
        if ya_prueba:
            print(f"  aviso: {archivo} estaba en la prueba y paso a entrenamiento")
    if train != train0:
        T.save_truth(ctx.paths.truth, train)
    if test != test0:
        T.save_truth(ctx.paths.test, test)
    print(f"{len(train)} muestras de entrenamiento en {ctx.paths.truth}; "
          f"{len(test)} de prueba en {ctx.paths.test}")
    return 0


def cmd_set_remove(args: argparse.Namespace) -> int:
    from . import teach as T

    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    muestras = _muestras(ctx, which)
    estan = {s.archivo for s in muestras}
    for a in args.archivos:
        if a not in estan:
            print(f"  aviso: {a} no esta en las muestras de {_NOMBRE_SET[which]}")
    quitar = set(args.archivos) & estan
    if not quitar:
        raise ValueError(f"Ninguno de esos fotogramas esta en {_archivo_set(ctx, which)}")
    quedan = [s for s in muestras if s.archivo not in quitar]
    T.save_truth(_archivo_set(ctx, which), quedan)
    print(f"{len(quitar)} muestras quitadas; quedan {len(quedan)} de {_NOMBRE_SET[which]} "
          f"en {_archivo_set(ctx, which)}")
    return 0


def _suggestions(args: argparse.Namespace, ctx: RunContext, n: int):
    """Fotogramas a etiquetar segun la estrategia. Devuelve ``(sugerencias, avisos)``.

    La prueba siempre es al azar y lejos del entrenamiento (y el entrenamiento lejos de la
    prueba): una prueba elegida por incertidumbre subestimaria el error real.
    """
    from . import read
    from . import sampling as S
    from .extract import time_from_name

    para_prueba = args.which == "test"
    strategy = "random" if para_prueba else args.strategy
    otro = ctx.train if para_prueba else ctx.test
    avoid = [time_from_name(x.archivo) for x in otro]
    exclude = {x.archivo for x in ctx.train + ctx.test}
    run = ctx.paths
    lecturas, stale = None, False
    if strategy in ("mixed", "uncertain") and run.readings.exists():
        lecturas = read.load_readings(run.readings)
        stale = (S.readings_stale(run.readings, ctx.templates_dir, run.config)
                 or read.outputs_state(run.readings, ctx.templates_dir) == read.DESACTUALIZADAS)
    return S.suggest(strategy, items=ctx.items(), readings=lecturas, cfg=ctx.cfg,
                     exclude=exclude, n=n, seed=args.seed, gap_s=args.gap,
                     avoid_times=avoid, stale=stale)


def cmd_set_suggest(args: argparse.Namespace) -> int:
    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    sug, avisos = _suggestions(args, ctx, args.n)
    usada = "random" if which == "test" else args.strategy
    print(f"== teach: {len(sug)} fotogramas sugeridos para {_NOMBRE_SET[which]} de {args.run_id} "
          f"(estrategia {usada}) ==")
    for a in avisos:
        print(f"  aviso: {a}")
    for sg in sug:
        print(f"  {sg.archivo}   t={sg.t_s:8.2f} s   {sg.motivo}")
    area = "samples" if which == "train" else "test"
    print(f"  para cargarlos: python -m spectro teach {area} label {args.run_id} --queue {args.n}")
    return 0


def cmd_set_label(args: argparse.Namespace) -> int:
    from .teach_ui import run_teach_ui

    _guard(args)
    which = args.which
    ctx = _load(args, args.run_id)
    names, motivos = ctx.names(), {}
    if args.queue:
        sug, avisos = _suggestions(args, ctx, args.queue)
        for a in avisos:
            print(f"aviso: {a}")
        if not sug:
            raise ValueError("No hay fotogramas que sugerir (todo esta etiquetado o excluido).")
        names = [sg.archivo for sg in sug]
        motivos = {sg.archivo: sg.motivo for sg in sug}
    run = ctx.paths
    ui_args = argparse.Namespace(
        frames_dir=str(ctx.frames_dir), templates_dir=str(ctx.templates_dir),
        max_per_label=args.max_per_label, gap=args.gap, truth=str(run.truth), test=str(run.test),
        teach_report=str(run.teach_report), test_report=str(run.test_report),
        history=str(run.history),
    )
    return run_teach_ui(ctx.cfg, ui_args, names, ctx.offsets, ctx.train, test=ctx.test,
                        motivos=motivos, target=which)


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
    huella = library.fingerprint(calib.templates)
    acc = acceptance_for(calib.config, args.min_exactitud, args.max_error, args.min_cobertura)

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
        append_history(run.history, rep, huella=huella)
        print(f"  informe: {run.test_report}   historial: {run.history}")
        entrada = load_run_input(run, calib, lib, evaluar=False, huella=huella)
        entrada.prueba = rep
        for line in format_batch_table(batch_summary([entrada], acc)):
            print(line)
        return 0

    ids = list(dict.fromkeys(args.runs)) or [
        r for r in _run_ids(args) if load_truth(_run_paths(args, r).test)]
    print(f"== teach test eval (biblioteca: {len(lib)} plantillas) ==")
    if not ids:
        print("  ninguna corrida tiene test.csv. Arma uno con: python -m spectro teach test suggest <id> 20")
        return 0
    entradas = [load_run_input(require_run(r, args.runs_dir, args.calib_dir), calib, lib,
                               gap_s=args.gap, huella=huella) for r in ids]
    for line in format_batch_table(batch_summary(entradas, acc)):
        print(line)
    print("  detalle de una corrida: python -m spectro teach test eval <id>")
    return 0


def cmd_test_history(args: argparse.Namespace) -> int:
    from .evaluation import load_history

    _guard(args)
    run = require_run(args.run_id, args.runs_dir, args.calib_dir)
    filas = load_history(run.history)
    print(f"== historial de evaluaciones de {run.id} ({run.history}) ==")
    if not filas:
        print(f"  (vacio) corre: python -m spectro teach test eval {run.id}")
        return 0
    print(f"  {'fecha':19s} {'tipo':14s} {'plant.':>6s} {'entren.':>7s} {'prueba':>6s} "
          f"{'correctas':>9s} {'erroneas':>8s} {'descart.':>8s} {'exact.':>7s} {'error':>6s} "
          f"{'cobert.':>8s}  cambio")
    previa = None
    for f in filas:
        ex = float(f["exactitud"])
        cambio = "" if previa is None else f"{100 * (ex - previa):+.1f} pt"
        print(f"  {f['fecha']:19s} {f['tipo']:14s} {f['plantillas']:>6s} {f['entrenamiento']:>7s} "
              f"{f['prueba']:>6s} {f['correctas']:>9s} {f['erroneas']:>8s} {f['descartadas']:>8s} "
              f"{ex:7.1%} {float(f['error_aceptadas']):6.1%} {float(f['cobertura']):8.1%}  {cambio}")
        previa = ex
    return 0


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def register(sub, layout: argparse.ArgumentParser) -> None:
    """Registra ``teach`` y su arbol de areas y verbos en el parser principal."""
    fmt = argparse.ArgumentDefaultsHelpFormatter

    def hoja(grupo, nombre, func, ayuda, **defaults):
        p = grupo.add_parser(nombre, help=ayuda, description=ayuda, parents=[layout],
                             formatter_class=fmt)
        p.set_defaults(func=func, needs_paths=False, **defaults)
        return p

    def area(nombre, ayuda, dest):
        p = sub_teach.add_parser(nombre, help=ayuda, description=ayuda, parents=[layout],
                                 formatter_class=fmt)
        return p, p.add_subparsers(dest=dest, required=True, metavar="VERBO")

    def run_arg(p, opcional=False):
        p.add_argument("run_id", metavar="RUN", nargs="?" if opcional else None,
                       help="Id de la corrida, completo (ej. img_8102)")

    th = sub.add_parser(
        "teach", help="Biblioteca, muestras y pruebas del lector, por areas",
        description="Entrenar el lector con valores reales y medirlo. Se elige un area y un verbo.",
        epilog=MIGRACION, parents=[layout], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub_teach = th.add_subparsers(dest="area", required=True, metavar="AREA")

    hoja(sub_teach, "status", cmd_status,
         "Panorama de la biblioteca y de cada corrida, y el siguiente paso")

    # -- lib
    _, lib = area("lib", "La biblioteca global de plantillas (calib/templates), sin corrida", "verbo")
    p = hoja(lib, "list", cmd_lib_list, "Plantillas por caracter y caracteres que faltan")
    p.add_argument("--usage", action="store_true",
                   help="Medir cuantas celdas gana bien y mal cada plantilla sobre las muestras de todas las corridas")
    p = hoja(lib, "delete", cmd_lib_delete, "Borrar plantillas por nombre (se respalda antes)")
    p.add_argument("nombres", nargs="+", metavar="NOMBRE", help="Ej. 0_3 5_1")
    p = hoja(lib, "relabel", cmd_lib_relabel, "Cambiar la etiqueta de una plantilla (se respalda antes)")
    p.add_argument("nombre", metavar="NOMBRE", help="Ej. 0_3")
    p.add_argument("caracter", metavar="CARACTER", help="Uno de 0123456789.-")
    p = hoja(lib, "clear", cmd_lib_clear, "Vaciar la biblioteca (se respalda antes)")
    p.add_argument("--yes", action="store_true", help="Confirmar el borrado")
    hoja(lib, "backups", cmd_lib_backups, "Listar los respaldos (se conservan los ultimos 5)")
    p = hoja(lib, "restore", cmd_lib_restore,
             "Volver a un respaldo (el ultimo, o NOMBRE); respalda antes el estado actual")
    p.add_argument("nombre", metavar="NOMBRE", nargs="?", help="Nombre del respaldo (ver lib backups)")

    # -- train / check
    for nombre, func, ayuda in (
        ("train", cmd_train, "Arma la biblioteca global con las muestras de entrenamiento (respalda la anterior)"),
        ("check", cmd_check, "Valida las muestras (leave-one-out) sin tocar la biblioteca"),
    ):
        p = hoja(sub_teach, nombre, func, ayuda)
        p.add_argument("runs", nargs="*", metavar="RUN",
                       help="Corridas a usar (default: todas las que tengan truth.csv)")
        p.add_argument("--exclude", nargs="+", metavar="RUN",
                       help="Corridas que no se usan para entrenar (hold-out por video)")
        p.add_argument("--gap", type=float, default=5.0, metavar="SEGUNDOS",
                       help="Avisar si una prueba esta a menos de esto de un fotograma de entrenamiento")
        if nombre == "train":
            p.add_argument("--keep", action="store_true",
                           help="Sumar a las plantillas existentes (sin duplicar) en vez de reemplazarlas")
            p.add_argument("--max-per-label", type=int, default=DEFAULT_MAX_PER_LABEL,
                           help="Maximo de variantes de plantilla por caracter")

    # -- samples y test
    for nombre, which, ayuda in (
        ("samples", "train", "Muestras de ENTRENAMIENTO de una corrida (runs/<id>/truth.csv)"),
        ("test", "test", "PRUEBAS de una corrida (runs/<id>/test.csv): nunca entran a la biblioteca"),
    ):
        _, g = area(nombre, ayuda, "verbo")
        d = {"which": which}
        p = hoja(g, "list", cmd_set_list, "Sin corrida, una tabla de todas; con corrida, sus muestras", **d)
        run_arg(p, opcional=True)
        p = hoja(g, "add", cmd_set_add,
                 "Agregar muestras; un fotograma esta en un solo conjunto (la saca del otro)", **d)
        run_arg(p)
        p.add_argument("items", nargs="+", metavar="ARCHIVO=VALOR", help="Ej. t_0001352.000.jpg=-0.018")
        p = hoja(g, "remove", cmd_set_remove, "Quitar muestras", **d)
        run_arg(p)
        p.add_argument("archivos", nargs="+", metavar="ARCHIVO", help="Ej. t_0001352.000.jpg")
        d2 = d if which == "train" else {**d, "strategy": "random"}
        p = hoja(g, "suggest", cmd_set_suggest,
                 "Imprimir fotogramas para etiquetar" + ("" if which == "train" else
                                                          " (siempre al azar y lejos del entrenamiento)"),
                 **d2)
        run_arg(p)
        p.add_argument("n", metavar="N", nargs="?", type=int, default=20, help="Cuantos fotogramas")
        p2 = hoja(g, "label", cmd_set_label,
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
            q.add_argument("--seed", type=int, default=0, help="Semilla del muestreo al azar")
            q.add_argument("--gap", type=float, default=5.0, metavar="SEGUNDOS",
                           help="Separacion minima entre fotogramas elegidos, y entre prueba y entrenamiento")
        if which == "test":
            p = hoja(g, "eval", cmd_test_eval,
                     "Evaluar con la biblioteca vigente: una corrida da el informe; varias o ninguna, una tabla")
            p.add_argument("runs", nargs="*", metavar="RUN",
                           help="Corridas (default: todas las que tengan test.csv)")
            p.add_argument("--gap", type=float, default=5.0, metavar="SEGUNDOS",
                           help="Avisar si una prueba esta a menos de esto de un fotograma de entrenamiento")
            for flag, h in (("--min-exactitud", "exactitud minima"),
                            ("--max-error", "error maximo entre las aceptadas"),
                            ("--min-cobertura", "cobertura minima")):
                p.add_argument(flag, type=float, default=None,
                               help=f"Veredicto: {h} (fraccion). Sin valor, 'acceptance' de calib/config.json")
            p = hoja(g, "history", cmd_test_history, "La curva de aprendizaje: una fila por evaluacion")
            run_arg(p)
