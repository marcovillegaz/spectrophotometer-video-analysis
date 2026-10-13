"""Reporte general de efectividad del lector: ``python -m spectro summary``.

Hoy saber si el lector funciona obliga a juntar a mano ``teach status``, ``teach check``,
``teach test eval`` y ``batch``. Este modulo los junta en un solo lugar y contesta cuanto
acierta en total, en que digitos se equivoca, cuanta serie se pierde y si esta mejorando.

Es **solo lectura sobre los datos**: lee fotogramas unicamente para evaluar la prueba y el
leave-one-out, y no toca ``calib/``, ``teach/`` ni ``test/``. Lo unico que escribe son
``runs/summary.csv``, ``runs/summary_chars.csv`` y ``runs/summary.html``.

Las funciones puras (``pool_tests``, ``series_gaps``, ``char_table``, ``trend``,
``summarize``, ``format_summary``) no abren archivos; ``load_all`` es el cargador delgado y
reutiliza ``report.load_run_input`` (que ya llama al evaluador unico, ``evaluation``) y
``teach.train(build=False)`` para el leave-one-out.

Interfaz publica:
    RunEval, RunRow, CharRow, TrendRow, Summary    datos
    load_all(...)            -> (list[RunEval], TrainResult | None)   cargador (lee disco)
    pool_tests(reports)      -> dict[tipo, TestReport]   junta las pruebas por tipo
    series_gaps(times, hole_s, start, end) -> (hueco mas largo en s, cuantos huecos > hole_s)
    loo_char_totals(train)   -> Counter   celdas del leave-one-out por caracter
    char_table(tests, loo_total, loo_confusion) -> list[CharRow]
    trend(history, fingerprint)             -> TrendRow
    summarize(evals, loo, acceptance, hole_s, ...) -> Summary
    format_summary(summary)                 -> list[str]
    write_summary_csv(summary, path)        -> Path
    write_chars_csv(summary, path)          -> Path
    write_html(summary, path)               -> Path
"""

from __future__ import annotations

import base64
import csv
import html
import io
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from .evaluation import TestReport, format_test_report, load_history, wilson
from .read import Reading
from .report import (
    QC_REASONS,
    RunInput,
    RunSummary,
    _pct,
    _verdict,
    batch_summary,
    format_batch_table,
)
from .teach import TrainResult, ValidationReport, split_by_run

#: Nombre de la fila de totales en ``summary.csv``.
TOTAL = "TOTAL"

#: Orden de gravedad de ``read.outputs_state`` para la fila de totales: gana el peor.
_OUTPUTS_ORDER = ("stale", "no_reading", "no_fingerprint", "up_to_date")


# --------------------------------------------------------------------------
# Datos
# --------------------------------------------------------------------------
@dataclass
class RunEval:
    """Lo que se sabe de una corrida, ya leido del disco."""

    inp: RunInput
    history: list[dict] = field(default_factory=list)
    #: Lecturas de ``readings.csv`` (vacio si la corrida no se leyo).
    readings: list[Reading] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return self.inp.run_id


@dataclass
class TrendRow:
    """Evolucion de la exactitud segun ``teach_history.csv``."""

    evals: int = 0
    first: float | None = None
    last: float | None = None
    #: La ultima evaluacion uso la biblioteca vigente; ``None`` si no se sabe.
    current: bool | None = None

    @property
    def delta_pts(self) -> float | None:
        """Cambio en puntos porcentuales entre la primera y la ultima evaluacion."""
        if self.first is None or self.last is None:
            return None
        return 100.0 * (self.last - self.first)


@dataclass
class RunRow:
    """Una fila de ``summary.csv``: el resumen de ``batch`` mas lo propio de ``summary``."""

    s: RunSummary
    test: TestReport | None = None
    longest_hole_s: float | None = None
    holes: int | None = None
    loo_exact: int | None = None
    loo_total: int | None = None
    trend: TrendRow | None = None


@dataclass
class CharRow:
    """Errores de un caracter, en la prueba y en el leave-one-out."""

    char: str
    test_cells: int = 0
    test_errors: int = 0
    loo_cells: int = 0
    loo_errors: int = 0
    #: ``"'6'->'5' x1; ..."``, las mas frecuentes (prueba y leave-one-out juntas).
    top_confusions: str = ""

    @property
    def in_test(self) -> bool:
        return self.test_cells > 0


@dataclass
class Summary:
    """Todo lo que muestran la consola, los CSV y la pagina."""

    #: Una fila por corrida y, al final, la fila ``TOTAL``.
    rows: list[RunRow]
    #: Las pruebas de todas las corridas juntas, por tipo (``same_run`` / ``other_video``).
    pooled: dict[str, TestReport]
    chars: list[CharRow]
    acceptance: object
    hole_s: float
    fingerprint: str = ""
    n_templates: int = 0
    #: Historial por corrida (para la curva de exactitud).
    histories: dict[str, list[dict]] = field(default_factory=dict)
    #: Confianza de cada lectura de todas las corridas (para el histograma).
    confidences: list[float] = field(default_factory=list)
    #: Confusiones (esperado, leido) de la prueba y el leave-one-out juntas.
    confusion: Counter = field(default_factory=Counter)
    #: Avisos de una linea (corridas sin prueba o sin lectura).
    notes: list[str] = field(default_factory=list)
    has_loo: bool = False

    @property
    def total(self) -> RunRow:
        return self.rows[-1]

    @property
    def runs(self) -> list[RunRow]:
        return self.rows[:-1]


# --------------------------------------------------------------------------
# Funciones puras
# --------------------------------------------------------------------------
def pool_tests(reports: dict[str, TestReport]) -> dict[str, TestReport]:
    """Junta las pruebas de varias corridas (``corrida -> informe``) en un informe por tipo.

    Concatena los resultados (el archivo pasa a ``corrida/archivo``: los nombres de
    fotograma se repiten entre videos) y suma fugas, errores, confusiones y totales.
    """
    out: dict[str, TestReport] = {}
    for run_id, rep in reports.items():
        if rep is None or not rep.n:
            continue
        pool = out.setdefault(rep.kind, TestReport(kind=rep.kind))
        pool.results.extend(replace(r, file=f"{run_id}/{r.file}") for r in rep.results)
        pool.leaks.extend((f"{run_id}/{a}", f"{run_id}/{b}", d) for a, b, d in rep.leaks)
        pool.errors.extend(f"{run_id}/{e}" for e in rep.errors)
        pool.missing_chars = sorted(set(pool.missing_chars) | set(rep.missing_chars))
        pool.confusion.update(rep.confusion)
        pool.char_total.update(rep.char_total)
        pool.n_train += rep.n_train
        pool.n_templates = max(pool.n_templates, rep.n_templates)
    return out


def series_gaps(
    times: list[float], hole_s: float, start: float | None = None, end: float | None = None
) -> tuple[float, int]:
    """``(hueco mas largo en s, cantidad de huecos > hole_s)`` de una serie de tiempos validos.

    Un hueco es el tiempo entre dos lecturas validas consecutivas. ``start`` y ``end`` (el
    primer y el ultimo fotograma de la corrida) cuentan como bordes: una serie que no
    arranca o termina a tiempo tambien pierde datos. Sin lecturas validas ni bordes: (0, 0).
    """
    ts = sorted(times)
    edges = ([start] if start is not None else []) + ts + ([end] if end is not None else [])
    gaps = [b - a for a, b in zip(edges, edges[1:])]
    if not gaps:
        return 0.0, 0
    return max(gaps), sum(1 for g in gaps if g > hole_s)


def loo_char_totals(res: TrainResult | None) -> Counter:
    """Celdas del leave-one-out por caracter esperado (sin el espacio)."""
    total: Counter = Counter()
    for d in (res.datas if res else []):
        total.update(c for c in d.cells if c != " ")
    return total


def _top(confusion: Counter, char: str, n: int = 3) -> str:
    items = sorted(((c, k) for k, c in confusion.items() if k[0] == char),
                   key=lambda x: (-x[0], x[1]))
    return "; ".join(f"'{k[0]}'->'{k[1]}' x{c}" for c, k in items[:n])


def char_table(
    tests: list[TestReport], loo_total: Counter, loo_confusion: Counter
) -> list[CharRow]:
    """Una fila por caracter: celdas y errores en la prueba y en el leave-one-out."""
    t_total: Counter = Counter()
    t_conf: Counter = Counter()
    for rep in tests:
        t_total.update(rep.char_total)
        t_conf.update(rep.confusion)
    both = t_conf + Counter(loo_confusion)
    rows = []
    for ch in sorted(set(t_total) | set(loo_total)):
        rows.append(CharRow(
            ch, t_total[ch], sum(c for (w, _), c in t_conf.items() if w == ch),
            loo_total[ch], sum(c for (w, _), c in loo_confusion.items() if w == ch),
            _top(both, ch),
        ))
    return rows


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def trend(history: list[dict], fingerprint: str = "") -> TrendRow:
    """Primera y ultima exactitud del historial, y si la ultima uso la biblioteca vigente."""
    if not history:
        return TrendRow()
    last_fp = history[-1].get("fingerprint") or ""
    return TrendRow(
        len(history), _float(history[0].get("accuracy")), _float(history[-1].get("accuracy")),
        (last_fp == fingerprint) if (last_fp and fingerprint) else None,
    )


def _worst_outputs(states: list[str]) -> str:
    for s in _OUTPUTS_ORDER:
        if s in states:
            return s
    return ""


def summarize(
    evals: list[RunEval],
    loo: TrainResult | None,
    acceptance,
    hole_s: float = 10.0,
    fingerprint: str = "",
    n_templates: int = 0,
) -> Summary:
    """Arma el resumen. Funcion pura: reutiliza ``report.batch_summary`` para cobertura y veredicto.

    La fila ``TOTAL`` suma las corridas **con lectura** (cobertura y descartes) y mide la
    prueba con el hold-out por video (``other_video``) si existe, porque ``same_run`` es
    optimista; si no, con ``same_run``. Sin umbrales ``acceptance`` el veredicto queda vacio.
    """
    reports = {e.run_id: e.inp.test for e in evals if e.inp.test is not None}
    pooled = pool_tests(reports)
    loo_rep: ValidationReport | None = loo.loo if loo else None
    summaries = batch_summary([e.inp for e in evals], acceptance)

    rows: list[RunRow] = []
    for e, s in zip(evals, summaries):
        row = RunRow(s, e.inp.test if (e.inp.test is not None and e.inp.test.n) else None)
        valid = [r.t_s for r in e.readings if r.status == "ok"]
        if e.readings:
            row.longest_hole_s, row.holes = series_gaps(
                valid, hole_s, min(r.t_s for r in e.readings), max(r.t_s for r in e.readings))
        if loo_rep is not None:
            sub = split_by_run(loo_rep, e.run_id)
            if sub.total:
                row.loo_exact, row.loo_total = sub.exact, sub.total
        row.trend = trend(e.history, fingerprint)
        rows.append(row)

    # fila TOTAL: cobertura sobre las corridas leidas; prueba = hold-out por video si hay
    read_evals = [e for e in evals if e.inp.read_value]
    pool_kind = "other_video" if "other_video" in pooled else next(iter(pooled), "")
    total_in = RunInput(
        TOTAL, [st for e in read_evals for st in e.inp.statuses], bool(read_evals),
        pooled.get(pool_kind), n_templates, fingerprint,
        _worst_outputs([e.inp.outputs for e in evals]),
    )
    total_row = RunRow(batch_summary([total_in], acceptance)[0], pooled.get(pool_kind))
    held = [r.longest_hole_s for r in rows if r.longest_hole_s is not None]
    if held:
        total_row.longest_hole_s = max(held)
        total_row.holes = sum(r.holes or 0 for r in rows)
    if loo_rep is not None and loo_rep.total:
        total_row.loo_exact, total_row.loo_total = loo_rep.exact, loo_rep.total
    rows.append(total_row)

    loo_conf = Counter(
        {k: v for k, v in (loo_rep.confusion if loo_rep else {}).items() if k[0] != " "})
    chars = char_table(list(pooled.values()), loo_char_totals(loo), loo_conf)
    confusion = Counter(loo_conf)
    for rep in pooled.values():
        confusion.update(rep.confusion)

    notes = []
    for e in evals:
        if e.inp.test is None or not e.inp.test.n:
            notes.append(f"{e.run_id}: sin prueba. Arma una con: "
                         f"python -m spectro teach test suggest {e.run_id} 20")
        if not e.inp.read_value:
            notes.append(f"{e.run_id}: sin readings.csv. Corre: python -m spectro read --run {e.run_id}")
    return Summary(
        rows, pooled, chars, acceptance, hole_s, fingerprint, n_templates,
        {e.run_id: e.history for e in evals},
        [r.confidence for e in evals for r in e.readings], confusion, notes,
        has_loo=loo_rep is not None,
    )


# --------------------------------------------------------------------------
# Consola
# --------------------------------------------------------------------------
def _fmt_s(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}"


def format_summary(summary: Summary) -> list[str]:
    """Las lineas que imprime ``summary`` (sin tildes: consola de Windows)."""
    L: list[str] = []
    s = summary
    L.append(f"== summary (biblioteca: {s.n_templates} plantillas, huella {s.fingerprint or '-'}) ==")

    L.append("")
    L.append("-- 1. Exactitud en la prueba --")
    if not s.pooled:
        L.append("  ninguna corrida tiene prueba. Arma una con: python -m spectro teach test suggest <id> 20")
    for kind in ("other_video", "same_run"):
        if kind in s.pooled:
            L += format_test_report(s.pooled[kind], f"prueba {kind} (todas las corridas)")

    L.append("")
    L.append("-- 2. Errores por caracter --")
    if s.chars:
        L.append(f"  {'car.':4s} {'prueba':>7s} {'err.':>5s} {'loo':>5s} {'err.':>5s}  confusiones")
        for c in s.chars:
            L.append(f"  {c.char:4s} {c.test_cells:7d} {c.test_errors:5d} {c.loo_cells:5d} "
                     f"{c.loo_errors:5d}  {c.top_confusions}".rstrip())
        absent = [c.char for c in s.chars if not c.in_test]
        if absent:
            L.append(f"  aviso: ninguna prueba incluye {', '.join(absent)}: no se sabe como los lee el lector")
    else:
        L.append("  (sin prueba ni muestras de entrenamiento)")

    L.append("")
    L.append("-- 3. Cobertura de la serie --")
    for line in format_batch_table([r.s for r in s.rows]):
        L.append(line)
    L.append(f"  huecos (> {s.hole_s:g} s entre lecturas validas):")
    for r in s.rows:
        L.append(f"    {r.s.run_id:22s} mas largo {_fmt_s(r.longest_hole_s):>8s} s   "
                 f"huecos {'-' if r.holes is None else r.holes}")
    if s.has_loo:
        L.append("  leave-one-out (entrenamiento):")
        for r in s.rows:
            if r.loo_total:
                L.append(f"    {r.s.run_id:22s} {r.loo_exact}/{r.loo_total} = "
                         f"{_pct(r.loo_exact / r.loo_total)}")

    L.append("")
    L.append("-- 4. Tendencia --")
    for r in s.runs:
        t = r.trend or TrendRow()
        if not t.evals:
            L.append(f"  {r.s.run_id:22s} sin historial de evaluaciones")
            continue
        delta = "-" if t.delta_pts is None else f"{t.delta_pts:+.1f} pts"
        cur = {True: "con la biblioteca vigente", False: "con otra biblioteca (reevalua)",
               None: "huella desconocida"}[t.current]
        L.append(f"  {r.s.run_id:22s} {t.evals} evaluaciones   primera {_pct(t.first)}  "
                 f"ultima {_pct(t.last)}  cambio {delta}   {cur}   salidas {r.s.outputs or '-'}")

    L.append("")
    L.append("-- 5. Veredicto --")
    tot = s.total.s
    if not s.acceptance.is_set():
        L.append("  sin umbrales de aceptacion: el veredicto queda vacio. Fijalos con "
                 "--min-accuracy / --max-error / --min-coverage o en la seccion 'acceptance' "
                 "de calib/config.json")
    else:
        for r in s.rows:
            L.append(f"  {r.s.run_id:22s} {r.s.verdict}" + (f" ({r.s.detail})" if r.s.detail else ""))
    if tot.test_kind:
        L.append(f"  (la fila {TOTAL} mide la prueba {tot.test_kind})")
    for n in s.notes:
        L.append(f"  aviso: {n}")
    return L


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
SUMMARY_FIELDS = [
    "run", "frames", *[f"qc_{m}" for m in QC_REASONS], "ok", "low_confidence", "spike",
    "coverage", "longest_hole_s", "holes", "test_kind", "test", "correct", "wrong", "discarded",
    "accuracy", "accuracy_lo", "accuracy_hi", "accepted_error", "loo_exact", "loo_total",
    "evals", "accuracy_first", "accuracy_last", "eval_current", "outputs", "verdict", "detail",
]

CHARS_FIELDS = ["char", "test_cells", "test_errors", "loo_cells", "loo_errors", "top_confusions"]


def _f(v, fmt: str = "{:.4f}") -> str:
    return "" if v is None else fmt.format(v)


def write_summary_csv(summary: Summary, path: Path | str) -> Path:
    """``runs/summary.csv``: una fila por corrida y una ``TOTAL``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(SUMMARY_FIELDS)
        for r in summary.rows:
            s, t, tr = r.s, r.test, r.trend or TrendRow()
            lo, hi = wilson(t.correct, t.n) if t else (None, None)
            w.writerow([
                s.run_id, s.frames, *[s.qc[m] for m in QC_REASONS],
                _f(s.ok, "{}"), _f(s.low_confidence, "{}"), _f(s.spike, "{}"), _f(s.coverage),
                _f(r.longest_hole_s, "{:.1f}"), _f(r.holes, "{}"),
                s.test_kind, s.test or "",
                _f(t.correct if t else None, "{}"), _f(t.wrong if t else None, "{}"),
                _f(t.discarded if t else None, "{}"),
                _f(s.accuracy), _f(lo), _f(hi), _f(s.accepted_error),
                _f(r.loo_exact, "{}"), _f(r.loo_total, "{}"),
                tr.evals or "", _f(tr.first), _f(tr.last),
                "" if tr.current is None else ("yes" if tr.current else "no"),
                s.outputs, s.verdict, s.detail,
            ])
    return path


def write_chars_csv(summary: Summary, path: Path | str) -> Path:
    """``runs/summary_chars.csv``: errores por caracter."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CHARS_FIELDS)
        for c in summary.chars:
            w.writerow([c.char, c.test_cells, c.test_errors, c.loo_cells, c.loo_errors,
                        c.top_confusions])
    return path


# --------------------------------------------------------------------------
# HTML (autocontenido: graficos PNG en base64, sin recursos externos)
# --------------------------------------------------------------------------
def _png_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _new_fig(w: float = 7.0, h: float = 3.6):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(w, h))
    return fig, fig.subplots()


def _chart_coverage(s: Summary) -> str | None:
    rows = [r.s for r in s.runs if r.s.ok is not None]
    if not rows:
        return None
    fig, ax = _new_fig()
    parts = [("ok", [r.ok for r in rows]), ("baja confianza", [r.low_confidence for r in rows]),
             ("spike", [r.spike for r in rows])]
    parts += [(f"QC: {m}", [r.qc[m] for r in rows]) for m in QC_REASONS
              if any(r.qc[m] for r in rows)]
    bottom = [0] * len(rows)
    for label, vals in parts:
        ax.bar([r.run_id for r in rows], vals, bottom=bottom, label=label)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_ylabel("fotogramas")
    ax.set_title("Cobertura por corrida")
    ax.legend(fontsize=7)
    return _png_b64(fig)


def _chart_confidence(s: Summary) -> str | None:
    if not s.confidences:
        return None
    fig, ax = _new_fig()
    ax.hist(s.confidences, bins=30, range=(0, 1))
    ax.set_xlabel("confianza (NCC mínima de las celdas)")
    ax.set_ylabel("lecturas")
    ax.set_title("Confianza de las lecturas")
    return _png_b64(fig)


def _chart_trend(s: Summary) -> str | None:
    series = {k: [_float(h.get("accuracy")) for h in v] for k, v in s.histories.items() if v}
    if not series:
        return None
    fig, ax = _new_fig()
    for run_id, ys in series.items():
        pts = [(i + 1, y) for i, y in enumerate(ys) if y is not None]
        if pts:
            ax.plot(*zip(*pts), marker="o", label=run_id)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("evaluación")
    ax.set_ylabel("exactitud")
    ax.set_title("Exactitud por evaluación")
    ax.legend(fontsize=7)
    return _png_b64(fig)


def _chart_confusion(s: Summary) -> str | None:
    if not s.confusion:
        return None
    wants = sorted({w for w, _ in s.confusion})
    gots = sorted({g for _, g in s.confusion})
    fig, ax = _new_fig(5.0, 4.0)
    grid = [[s.confusion.get((w, g), 0) for g in gots] for w in wants]
    im = ax.imshow(grid, cmap="Reds")
    ax.set_xticks(range(len(gots)), [g or "' '" for g in gots])
    ax.set_yticks(range(len(wants)), wants)
    ax.set_xlabel("leído")
    ax.set_ylabel("esperado")
    ax.set_title("Confusiones (prueba y leave-one-out)")
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            if v:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax)
    return _png_b64(fig)


def _table(header: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>"
                   for r in rows)
    return f"<table><tr>{th}</tr>{body}</table>"


def write_html(summary: Summary, path: Path | str) -> Path:
    """``runs/summary.html``: las tablas de la consola y cuatro graficos, en una sola pagina."""
    s = summary
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    esc = html.escape
    out: list[str] = [
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
        "<title>spectro: resumen de efectividad</title><style>"
        "body{font-family:sans-serif;max-width:60em;margin:2em auto;padding:0 1em}"
        "table{border-collapse:collapse;margin:.5em 0;font-size:.9em}"
        "td,th{border:1px solid #bbb;padding:.2em .6em;text-align:right}"
        "th{background:#eee}pre{background:#f6f6f6;padding:.6em}img{max-width:100%}"
        "</style></head><body>",
        "<h1>Resumen de efectividad del lector</h1>",
        f"<p>Biblioteca: {s.n_templates} plantillas, huella <code>{esc(s.fingerprint or '-')}</code>.</p>",
    ]

    def img(b64: str | None, alt: str) -> str:
        return (f"<img alt='{esc(alt)}' src='data:image/png;base64,{b64}'>" if b64
                else f"<p><em>{esc(alt)}: sin datos.</em></p>")

    out.append("<h2>1. Exactitud en la prueba</h2>")
    if not s.pooled:
        out.append("<p>Ninguna corrida tiene prueba. Armá una con "
                   "<code>python -m spectro teach test suggest &lt;id&gt; 20</code>.</p>")
    for kind in ("other_video", "same_run"):
        if kind in s.pooled:
            out.append("<pre>" + esc("\n".join(format_test_report(
                s.pooled[kind], f"prueba {kind} (todas las corridas)"))) + "</pre>")
    out.append(img(_chart_trend(s), "Exactitud por evaluación"))

    out.append("<h2>2. Errores por carácter</h2>")
    out.append(_table(
        ["carácter", "celdas (prueba)", "errores", "celdas (loo)", "errores", "confusiones"],
        [[c.char, str(c.test_cells), str(c.test_errors), str(c.loo_cells), str(c.loo_errors),
          c.top_confusions] for c in s.chars]))
    absent = [c.char for c in s.chars if not c.in_test]
    if absent:
        out.append(f"<p>Ninguna prueba incluye: {esc(', '.join(absent))}.</p>")
    out.append(img(_chart_confusion(s), "Mapa de confusiones"))

    out.append("<h2>3. Cobertura de la serie</h2>")
    out.append(_table(
        ["corrida", "fotogramas", "descartes QC", "ok", "baja", "spike", "cobertura",
         "hueco más largo (s)", f"huecos > {s.hole_s:g} s", "leave-one-out"],
        [[r.s.run_id, str(r.s.frames), str(r.s.discarded_qc),
          *("-" if v is None else str(v) for v in (r.s.ok, r.s.low_confidence, r.s.spike)),
          _pct(r.s.coverage), _fmt_s(r.longest_hole_s),
          "-" if r.holes is None else str(r.holes),
          f"{r.loo_exact}/{r.loo_total}" if r.loo_total else "-"] for r in s.rows]))
    out.append(img(_chart_coverage(s), "Cobertura por corrida"))
    out.append(img(_chart_confidence(s), "Histograma de confianza"))

    out.append("<h2>4. Tendencia</h2>")
    trows = []
    for r in s.runs:
        t = r.trend or TrendRow()
        trows.append([r.s.run_id, str(t.evals), _pct(t.first), _pct(t.last),
                      "-" if t.delta_pts is None else f"{t.delta_pts:+.1f}",
                      {True: "sí", False: "no", None: "?"}[t.current], r.s.outputs or "-"])
    out.append(_table(["corrida", "evaluaciones", "primera", "última", "cambio (pts)",
                       "con la biblioteca vigente", "salidas"], trows))

    out.append("<h2>5. Veredicto</h2>")
    if not s.acceptance.is_set():
        out.append("<p>Sin umbrales de aceptación el veredicto queda vacío. Fijalos con "
                   "<code>--min-accuracy</code>, <code>--max-error</code> y "
                   "<code>--min-coverage</code>, o en la sección <code>acceptance</code> "
                   "de <code>calib/config.json</code>.</p>")
    else:
        out.append(_table(["corrida", "veredicto", "detalle"],
                          [[r.s.run_id, r.s.verdict, r.s.detail] for r in s.rows]))
    if s.total.s.test_kind:
        out.append(f"<p>La fila {TOTAL} mide la prueba <code>{esc(s.total.s.test_kind)}</code>.</p>")
    if s.notes:
        out.append("<ul>" + "".join(f"<li>{esc(n)}</li>" for n in s.notes) + "</ul>")
    out.append("</body></html>")
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Cargador (lee disco; evalua la prueba y el leave-one-out)
# --------------------------------------------------------------------------
def load_all(
    run_ids: list[str],
    runs_dir: Path | str,
    calib,
    lib: list,
    fingerprint: str,
    gap_s: float = 5.0,
    calib_dir: Path | str | None = None,
) -> tuple[list[RunEval], TrainResult | None]:
    """Lee cada corrida (``load_run_input`` evalua su prueba) y hace un leave-one-out conjunto.

    ``train(build=False)`` no escribe nada. Solo cuentan para el leave-one-out las corridas
    pedidas que tienen ``truth.csv``. ``calib`` es un ``CalibPaths``; ``calib_dir`` es su carpeta.
    """
    from .project import require_run
    from .read import load_readings
    from .report import load_run_input
    from .teach import gather_runs, train

    calib_dir = calib_dir if calib_dir is not None else calib.root
    evals: list[RunEval] = []
    for rid in run_ids:
        run = require_run(rid, runs_dir, calib_dir)
        inp = load_run_input(run, calib, lib, gap_s=gap_s, fingerprint=fingerprint)
        readings = load_readings(run.readings) if run.readings.exists() else []
        evals.append(RunEval(inp, load_history(run.history), readings))
    ctxs = gather_runs(runs_dir, calib_dir, exclude=_others(runs_dir, run_ids))
    loo = train(ctxs, calib.templates, build=False) if ctxs else None
    return evals, loo


def _others(runs_dir: Path | str, run_ids: list[str]) -> list[str]:
    from .project import list_runs

    return [r for r in list_runs(runs_dir=runs_dir) if r not in run_ids]
