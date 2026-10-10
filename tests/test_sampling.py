"""Muestreo: incertidumbre con persistencia, azar estratificado, arranque en frio y conjuntos."""

from __future__ import annotations

import os

import pytest

from spectro.config import Config
from spectro.extract import frame_name
from spectro.read import Reading
from spectro.sampling import (
    assign,
    is_cold_start,
    leakage,
    readings_stale,
    suggest,
    suggest_random,
    suggest_uncertain,
    suggest_uniform,
    uncertainty,
)
from spectro.teach import Sample


def mk(t: float, conf: float = 0.95, margen: float = 0.3, estado: str = "ok", chars: str = "-0.025"):
    return Reading(archivo=frame_name(t), t_s=t, indice=int(t * 4), confianza=conf, margen=margen,
                   estado=estado, caracteres=chars)


def timeline(n: int = 200, step: float = 1.0, **kw) -> list[Reading]:
    return [mk(i * step, **kw) for i in range(n)]


def items_of(readings):
    return [(r.archivo, r.t_s) for r in readings]


@pytest.fixture
def cfg():
    return Config.default()


# -- incertidumbre ----------------------------------------------------------
def test_uncertainty_relativa_a_los_umbrales(cfg):
    assert uncertainty(mk(0, conf=0.9, margen=0.3), cfg) == pytest.approx(0.5)      # (0.9-0.6)/0.6
    assert uncertainty(mk(0, conf=0.6, margen=0.3), cfg) == pytest.approx(0.0)      # en la frontera
    assert uncertainty(mk(0, conf=0.4, margen=0.3, estado="low_confidence"), cfg) < 0
    assert uncertainty(mk(0, conf=0.95, margen=0.06), cfg) == pytest.approx(0.2)    # manda el margen
    assert uncertainty(mk(0, estado="spike"), cfg) == -1.0
    assert uncertainty(mk(0, conf=0.9, margen=0.0), cfg, use_margin=False) == pytest.approx(0.5)


# -- por incertidumbre ------------------------------------------------------
def _con_bloque_y_transitoria():
    rs = timeline(200)
    for r in rs[100:111]:                       # glifo desconocido: dura segundos
        r.confianza, r.estado = 0.45, "low_confidence"
    rs[50].confianza, rs[50].estado = 0.15, "low_confidence"  # a medio redibujar: un instante
    return rs


def test_descarta_la_transitoria_aunque_sea_la_mas_incierta(cfg):
    rs = _con_bloque_y_transitoria()
    sug = suggest_uncertain(rs, cfg, set(), n=5, min_gap_s=1)
    tiempos = [s.t_s for s in sug]
    assert tiempos and all(100 <= t <= 110 for t in tiempos)
    assert 50 not in tiempos


def test_respeta_separacion_y_diversidad(cfg):
    rs = _con_bloque_y_transitoria()
    sug = suggest_uncertain(rs, cfg, set(), n=10, min_gap_s=3, per_text=2)
    ts = sorted(s.t_s for s in sug)
    assert all(b - a >= 3 for a, b in zip(ts, ts[1:]))
    assert len(sug) <= 4                      # 11 s de bloque con gap 3
    # mismo texto leido: a lo sumo per_text
    sug2 = suggest_uncertain(rs, cfg, set(), n=10, min_gap_s=0.5, per_text=2)
    assert len(sug2) == 2


def test_excluye_lo_ya_etiquetado(cfg):
    rs = _con_bloque_y_transitoria()
    todos = {r.archivo for r in rs[100:111]}
    assert suggest_uncertain(rs, cfg, todos, n=5, min_gap_s=1) == []
    uno = suggest_uncertain(rs, cfg, set(), n=1, min_gap_s=1)[0].archivo
    otro = suggest_uncertain(rs, cfg, {uno}, n=1, min_gap_s=1)[0].archivo
    assert otro != uno


def test_ignora_lecturas_que_no_pasaron_qc_y_ordena_por_incertidumbre(cfg):
    rs = _con_bloque_y_transitoria()
    rs[105].estado = "blank"                  # estado de QC: no es una lectura
    for i, r in enumerate(rs[100:111]):       # el centro del bloque es el mas incierto
        r.confianza = 0.45 - 0.02 * (5 - abs(i - 5))
    sug = suggest_uncertain(rs, cfg, set(), n=1, min_gap_s=1)
    assert sug[0].archivo != rs[105].archivo
    assert "incierta" in sug[0].motivo


def test_spike_aislado_se_sugiere_aunque_no_sea_persistente(cfg):
    rs = timeline(100)
    rs[40].estado = "spike"                   # error seguro de si mismo: lo mas informativo
    sug = suggest_uncertain(rs, cfg, set(), n=3, min_gap_s=1)
    assert [s.archivo for s in sug] == [rs[40].archivo]


def test_readings_viejos_sin_margen_siguen_sirviendo(cfg):
    rs = timeline(120, margen=0.0)
    for r in rs[60:70]:
        r.confianza, r.estado = 0.45, "low_confidence"
    sug = suggest_uncertain(rs, cfg, set(), n=3, min_gap_s=2)
    assert sug and all(60 <= s.t_s <= 69 for s in sug)


# -- al azar y uniforme -----------------------------------------------------
def test_random_reproducible_y_estratificado():
    items = [(frame_name(t), float(t)) for t in range(0, 1000, 2)]
    a = suggest_random(items, set(), 10, seed=3, min_gap_s=5)
    b = suggest_random(items, set(), 10, seed=3, min_gap_s=5)
    c = suggest_random(items, set(), 10, seed=4, min_gap_s=5)
    assert a == b and a != c
    assert len(a) == 10 and all(s.motivo == "azar" for s in a)
    bins = {min(int(s.t_s / 1000 * 10), 9) for s in a}
    assert len(bins) == 10                    # un fotograma por tramo de la corrida


def test_random_evita_el_entrenamiento_y_lo_excluido():
    items = [(frame_name(t), float(t)) for t in range(0, 200)]
    avoid = [100.0]
    sug = suggest_random(items, {frame_name(0)}, 8, seed=0, min_gap_s=10, avoid_times=avoid)
    assert all(abs(s.t_s - 100.0) >= 10 for s in sug)
    assert frame_name(0) not in {s.archivo for s in sug}
    ts = sorted(s.t_s for s in sug)
    assert all(b - a >= 10 for a, b in zip(ts, ts[1:]))


def test_random_completa_si_hay_tramos_vacios():
    items = [(frame_name(t), float(t)) for t in list(range(0, 10)) + list(range(990, 1000))]
    sug = suggest_random(items, set(), 6, seed=1, min_gap_s=2)
    assert len(sug) >= 4                      # no explota con la corrida muy desigual


def test_uniform_excluye_lo_etiquetado():
    items = [(frame_name(t), float(t)) for t in range(100)]
    sug = suggest_uniform(items, {frame_name(0)}, 5)
    assert len(sug) == 5 and frame_name(0) not in {s.archivo for s in sug}
    assert all(s.motivo == "uniforme" for s in sug)


# -- estrategia completa ----------------------------------------------------
def test_suggest_mixed_mitad_y_mitad(cfg):
    rs = _con_bloque_y_transitoria()
    for i, r in enumerate(rs[100:111]):       # textos distintos: el tope por texto no recorta
        r.caracteres = f"-0.0{i:02d}"
    sug, notas = suggest("mixed", items=items_of(rs), readings=rs, cfg=cfg, exclude=set(), n=6,
                         seed=0, gap_s=3)
    assert not notas and len(sug) == 6 and len({s.archivo for s in sug}) == 6
    motivos = {s.motivo.split()[0] for s in sug}
    assert {"incierta", "azar"} <= motivos


def test_suggest_arranque_en_frio_es_uniforme(cfg):
    rs = timeline(100, conf=0.2, margen=0.0, estado="low_confidence")
    assert is_cold_start(rs) and is_cold_start([])
    sug, notas = suggest("mixed", items=items_of(rs), readings=rs, cfg=cfg, exclude=set(), n=5)
    assert all(s.motivo == "uniforme" for s in sug) and "arranque en frio" in notas[0]
    sug, notas = suggest("uncertain", items=items_of(rs), readings=None, cfg=cfg, exclude=set(), n=5)
    assert all(s.motivo == "uniforme" for s in sug) and "readings.csv" in notas[0]


def test_suggest_con_readings_viejos_cae_a_azar(cfg):
    rs = _con_bloque_y_transitoria()
    sug, notas = suggest("mixed", items=items_of(rs), readings=rs, cfg=cfg, exclude=set(), n=5,
                         stale=True)
    assert all(s.motivo == "azar" for s in sug) and "anterior" in notas[0]


def test_suggest_estrategia_desconocida(cfg):
    with pytest.raises(ValueError):
        suggest("inventada", items=[], readings=None, cfg=cfg, exclude=set(), n=1)


def test_suggest_avisa_si_hay_pocas_inciertas(cfg):
    rs = timeline(100)
    for r in rs[10:13]:
        r.confianza, r.estado = 0.4, "low_confidence"
    sug, notas = suggest("uncertain", items=items_of(rs), readings=rs, cfg=cfg, exclude=set(),
                         n=10, gap_s=1)
    assert len(sug) < 10 and any("solo hay" in n for n in notas)


# -- lecturas viejas --------------------------------------------------------
def test_readings_stale_compara_fechas(tmp_path):
    lecturas = tmp_path / "readings.csv"
    lecturas.write_text("x", encoding="utf-8")
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "0_0.png").write_bytes(b"x")
    conf = tmp_path / "config.json"
    conf.write_text("{}", encoding="utf-8")
    base = lecturas.stat().st_mtime
    os.utime(lib / "0_0.png", (base - 100, base - 100))
    os.utime(conf, (base - 100, base - 100))
    assert not readings_stale(lecturas, lib, conf)
    os.utime(lib / "0_0.png", (base + 100, base + 100))
    assert readings_stale(lecturas, lib, conf)
    assert not readings_stale(tmp_path / "no_existe.csv", lib)


# -- entrenamiento / prueba -------------------------------------------------
def test_assign_mantiene_un_solo_conjunto():
    a, b = Sample("t_0000001.000.jpg", "0.1"), Sample("t_0000009.000.jpg", "0.2")
    train, test = assign([a], [b], b, "train")
    assert {s.archivo for s in train} == {a.archivo, b.archivo} and test == []
    train, test = assign(train, test, a, "test")
    assert [s.archivo for s in train] == [b.archivo] and [s.archivo for s in test] == [a.archivo]
    nuevo = Sample(a.archivo, "9.9")
    train, test = assign(train, test, nuevo, "test")
    assert len(test) == 1 and test[0].valor == "9.9"
    with pytest.raises(ValueError):
        assign(train, test, a, "otro")


def test_leakage_detecta_vecinos_cercanos():
    train = [Sample("t_0000010.000.jpg", "1"), Sample("t_0000100.000.jpg", "2")]
    test = [Sample("t_0000012.000.jpg", "1"), Sample("t_0000050.000.jpg", "3")]
    pares = leakage(train, test, gap_s=5)
    assert pares == [("t_0000012.000.jpg", "t_0000010.000.jpg", pytest.approx(2.0))]
    assert leakage(train, test, gap_s=1) == []


def test_el_parpadeo_del_ultimo_digito_no_es_persistente(cfg):
    # el display redibuja el ultimo digito: ok / baja alternando durante segundos
    rs = timeline(120)
    for i, r in enumerate(rs[40:60]):
        if i % 2 == 0:
            r.confianza, r.estado = 0.45, "low_confidence"
    assert suggest_uncertain(rs, cfg, set(), n=5, min_gap_s=1) == []
    # un glifo realmente desconocido duda en todos los vecinos
    for r in rs[80:95]:
        r.confianza, r.estado = 0.45, "low_confidence"
    sug = suggest_uncertain(rs, cfg, set(), n=5, min_gap_s=1)
    assert sug and all(80 <= s.t_s <= 94 for s in sug)
