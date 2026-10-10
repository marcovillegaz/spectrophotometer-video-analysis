"""Que fotogramas conviene etiquetar: muestreo uniforme, al azar o por incertidumbre.

Etiquetar cuesta tiempo humano, asi que importa *cuales* fotogramas se eligen:

* ``uniform``: reparte parejo por la corrida. Es la ronda 0 (arranque en frio),
  cuando el lector todavia no sabe nada y su incertidumbre no significa nada.
* ``random``: azar **estratificado por tiempo** (un fotograma por tramo). Es lo que se
  usa para el conjunto de prueba: una prueba elegida por incertidumbre subestimaria
  el error real, porque solo tendria casos dificiles.
* ``uncertain``: los fotogramas donde el lector duda (aprendizaje activo), con dos
  salvaguardas: *persistencia temporal* (el digito a medio redibujar dura un instante
  y sus vecinos leen bien; un glifo que la biblioteca no conoce dura segundos y todos
  sus vecinos dudan) y *diversidad* (separacion en el tiempo y tope por texto leido).
* ``mixed`` (default): mitad ``uncertain``, mitad ``random``, para no sesgar.

Interfaz publica:
    uncertainty(reading, cfg)                       -> float   (menor = mas incierta)
    suggest_uncertain(...) / suggest_random(...) / suggest_uniform(...)
    suggest(strategy, ...)                          -> (list[Suggestion], list[str])
    assign(train, test, sample, which)              -> (train, test)
    leakage(train, test, gap_s)                     -> list[(prueba, entrenamiento, dt)]
    readings_stale(readings_path, *dependencias)    -> bool
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .extract import time_from_name
from .read import Reading
from .teach import Sample, suggest_frames

STRATEGIES = ("mixed", "uncertain", "random", "uniform")
#: Una lectura con ``u`` por debajo de esto cuenta como "dudosa" para la persistencia.
UNCERTAIN_U = 0.25
#: Fraccion de vecinos (en +-window_s) que tienen que dudar para que un fotograma sea
#: "persistente". El ultimo digito parpadea ok/baja durante segundos cada vez que el
#: valor cambia (en img_8102 ~60 % de los vecinos dudan), asi que 50 % no separa ese
#: parpadeo de un glifo realmente desconocido, que hace dudar a casi todos los vecinos.
MIN_PERSIST = 0.8
#: Menos de esta fraccion de lecturas ``ok`` entre las que pasaron QC = arranque en frio.
COLD_START_OK_FRACTION = 0.10


@dataclass(frozen=True)
class Suggestion:
    archivo: str
    motivo: str
    t_s: float = 0.0


# --------------------------------------------------------------------------
# Incertidumbre
# --------------------------------------------------------------------------
def uncertainty(r: Reading, cfg: Config, use_margin: bool = True) -> float:
    """Distancia a la frontera de aceptacion, relativa a los umbrales de ``cfg.templates``.

    ``u < 0``: lectura descartada. ``u`` cerca de 0: al borde de la aceptacion.
    Un ``spike`` (salto aislado que paso el umbral de confianza) es un posible error
    *seguro de si mismo*: se lo trata como el mas incierto, porque etiquetarlo es lo
    mas informativo que hay.
    """
    if r.estado == "spike":
        return -1.0
    t = cfg.templates
    u = (r.confianza - t.min_score) / t.min_score
    if use_margin:
        u = min(u, (r.margen - t.min_margin) / t.min_margin)
    return u


def _is_uncertain(r: Reading, u: float) -> bool:
    return r.estado in ("low_confidence", "spike") or u < UNCERTAIN_U


def _far_enough(t: float, taken: list[float], gap_s: float) -> bool:
    return all(abs(t - x) >= gap_s for x in taken)


def suggest_uncertain(
    readings: list[Reading],
    cfg: Config,
    exclude: set[str],
    n: int,
    min_gap_s: float = 5.0,
    per_text: int = 2,
    window_s: float = 1.5,
    min_persist: float = MIN_PERSIST,
) -> list[Suggestion]:
    """Los ``n`` fotogramas mas inciertos, persistentes y diversos."""
    rs = sorted(
        (r for r in readings if r.estado in ("ok", "low_confidence", "spike")),
        key=lambda r: r.t_s,
    )
    if not rs or n <= 0:
        return []
    use_margin = any(r.margen > 0 for r in rs)  # un readings.csv viejo no trae margen
    us = [uncertainty(r, cfg, use_margin) for r in rs]
    flag = [_is_uncertain(r, u) for r, u in zip(rs, us)]
    ts = [r.t_s for r in rs]

    candidates: list[tuple[float, int]] = []
    lo = hi = 0
    for i, r in enumerate(rs):
        if r.archivo in exclude:
            continue
        while ts[lo] < r.t_s - window_s:
            lo += 1
        while hi < len(rs) and ts[hi] <= r.t_s + window_s:
            hi += 1
        vecinos = [j for j in range(lo, hi) if j != i]
        persistente = r.estado == "spike" or (
            bool(vecinos) and sum(flag[j] for j in vecinos) / len(vecinos) >= min_persist
        )
        if flag[i] and persistente:
            candidates.append((us[i], i))
    candidates.sort()

    out: list[Suggestion] = []
    taken: list[float] = []
    textos: dict[str, int] = {}
    for u, i in candidates:
        r = rs[i]
        if not _far_enough(r.t_s, taken, min_gap_s) or textos.get(r.caracteres, 0) >= per_text:
            continue
        out.append(Suggestion(r.archivo, f"incierta u={u:+.2f} ({r.caracteres.strip() or '?'})", r.t_s))
        taken.append(r.t_s)
        textos[r.caracteres] = textos.get(r.caracteres, 0) + 1
        if len(out) >= n:
            break
    return out


# --------------------------------------------------------------------------
# Azar y uniforme
# --------------------------------------------------------------------------
def suggest_random(
    items: list[tuple[str, float]],
    exclude: set[str],
    n: int,
    seed: int = 0,
    min_gap_s: float = 5.0,
    avoid_times: list[float] | None = None,
) -> list[Suggestion]:
    """Azar estratificado por tiempo: la corrida se parte en ``n`` tramos y se toma uno por tramo.

    Reproducible con ``seed``. Descarta los fotogramas a menos de ``min_gap_s`` de
    ``avoid_times`` (las muestras de entrenamiento, para que la prueba no tenga fugas).
    """
    avoid = sorted(avoid_times or [])

    def ok(t: float) -> bool:
        if not avoid:
            return True
        k = bisect_left(avoid, t)
        near = [avoid[j] for j in (k - 1, k) if 0 <= j < len(avoid)]
        return all(abs(t - a) >= min_gap_s for a in near)

    pool = sorted(((a, t) for a, t in items if a not in exclude and ok(t)), key=lambda x: x[1])
    if not pool or n <= 0:
        return []
    rng = random.Random(seed)
    t0, t1 = pool[0][1], pool[-1][1]
    span = max(t1 - t0, 1e-9)
    bins: list[list[tuple[str, float]]] = [[] for _ in range(n)]
    for a, t in pool:
        bins[min(int((t - t0) / span * n), n - 1)].append((a, t))
    chosen: list[tuple[str, float]] = []
    for b in bins:
        if b:
            cand = b[rng.randrange(len(b))]
            if _far_enough(cand[1], [t for _, t in chosen], min_gap_s):
                chosen.append(cand)
    if len(chosen) < n:  # tramos vacios o muy juntos: completar al azar respetando la separacion
        resto = [x for x in pool if x not in chosen]
        rng.shuffle(resto)
        for cand in resto:
            if len(chosen) >= n:
                break
            if _far_enough(cand[1], [t for _, t in chosen], min_gap_s):
                chosen.append(cand)
    return [Suggestion(a, "azar", t) for a, t in sorted(chosen, key=lambda x: x[1])]


def suggest_uniform(items: list[tuple[str, float]], exclude: set[str], n: int) -> list[Suggestion]:
    """Reparto parejo por la corrida (``teach.suggest_frames``), sin lo ya etiquetado."""
    por_nombre = dict(items)
    names = [a for a, _ in sorted(items, key=lambda x: x[1]) if a not in exclude]
    return [Suggestion(a, "uniforme", por_nombre[a]) for a in suggest_frames(names, n)]


# --------------------------------------------------------------------------
# Estrategia completa, con arranque en frio y lecturas viejas
# --------------------------------------------------------------------------
def readings_stale(readings_path: Path | str, *dependencies: Path | str) -> bool:
    """``readings.csv`` es anterior a la biblioteca o a la config: sus confianzas ya no valen."""
    rp = Path(readings_path)
    if not rp.exists():
        return False
    base = rp.stat().st_mtime
    for dep in dependencies:
        d = Path(dep)
        files = list(d.glob("*.png")) if d.is_dir() else [d] if d.exists() else []
        if any(f.stat().st_mtime > base for f in files):
            return True
    return False


def is_cold_start(readings: list[Reading]) -> bool:
    if not readings:
        return True
    ok = sum(1 for r in readings if r.estado == "ok")
    return ok / len(readings) < COLD_START_OK_FRACTION


def suggest(
    strategy: str,
    *,
    items: list[tuple[str, float]],
    readings: list[Reading] | None,
    cfg: Config,
    exclude: set[str],
    n: int,
    seed: int = 0,
    gap_s: float = 5.0,
    avoid_times: list[float] | None = None,
    stale: bool = False,
) -> tuple[list[Suggestion], list[str]]:
    """Devuelve ``(sugerencias, avisos)``. Cae a una estrategia segura cuando hace falta."""
    if strategy not in STRATEGIES:
        raise ValueError(f"estrategia {strategy!r} desconocida; usa una de {', '.join(STRATEGIES)}")
    notes: list[str] = []
    if strategy == "uniform":
        return suggest_uniform(items, exclude, n), notes
    if strategy == "random":
        return suggest_random(items, exclude, n, seed, gap_s, avoid_times), notes

    # uncertain / mixed necesitan lecturas validas y al dia
    if not readings:
        notes.append("no hay readings.csv: ronda uniforme (arranque en frio). Corre `read` despues de armar la biblioteca.")
        return suggest_uniform(items, exclude, n), notes
    if stale:
        notes.append("readings.csv es anterior a la biblioteca o a la config: sus confianzas ya no valen. "
                     "Muestreo al azar; corre `read` y repeti.")
        return suggest_random(items, exclude, n, seed, gap_s, avoid_times), notes
    if is_cold_start(readings):
        notes.append("arranque en frio: menos del 10% de las lecturas son validas, asi que la "
                     "incertidumbre no informa. Ronda uniforme.")
        return suggest_uniform(items, exclude, n), notes

    n_u = n if strategy == "uncertain" else math.ceil(n / 2)
    inciertas = suggest_uncertain(readings, cfg, exclude, n_u, gap_s)
    if len(inciertas) < n_u:
        notes.append(f"solo hay {len(inciertas)} fotogramas inciertos y persistentes (pedidos {n_u}).")
    if strategy == "uncertain":
        return inciertas, notes
    tomadas = {s.archivo for s in inciertas}
    azar = suggest_random(
        items, exclude | tomadas, n - len(inciertas), seed, gap_s,
        (avoid_times or []) + [s.t_s for s in inciertas],
    )
    return sorted(inciertas + azar, key=lambda s: s.t_s), notes


# --------------------------------------------------------------------------
# Entrenamiento / prueba
# --------------------------------------------------------------------------
def assign(
    train: list[Sample], test: list[Sample], sample: Sample, which: str
) -> tuple[list[Sample], list[Sample]]:
    """Pone la muestra en ``which`` (``train`` o ``test``) y la saca del otro conjunto."""
    if which not in ("train", "test"):
        raise ValueError("which debe ser 'train' o 'test'")
    train = [s for s in train if s.archivo != sample.archivo]
    test = [s for s in test if s.archivo != sample.archivo]
    (train if which == "train" else test).append(sample)
    return train, test


def leakage(
    train: list[Sample], test: list[Sample], gap_s: float = 5.0
) -> list[tuple[str, str, float]]:
    """Pares (prueba, entrenamiento) a menos de ``gap_s`` segundos: casi el mismo fotograma."""
    out = []
    tr = [(s.archivo, time_from_name(s.archivo)) for s in train]
    for s in test:
        t = time_from_name(s.archivo)
        for a, ta in tr:
            if abs(t - ta) < gap_s:
                out.append((s.archivo, a, abs(t - ta)))
    return sorted(out)
