"""``python -m spectro summary``: funciones puras de ``summary.py``, los campos nuevos de
``TestReport`` (``confusion`` y ``char_total``) y el comando sobre un proyecto de juguete.

Reglas que protegen estos tests:
- el comando es de **solo lectura** sobre ``calib/``, ``teach/`` y ``test/`` (solo escribe
  ``runs/summary*``);
- la fila ``TOTAL`` mide la prueba con ``other_video`` si existe (``same_run`` es optimista) y
  suma solo las corridas que tienen ``readings.csv``;
- sin umbrales ``acceptance`` el veredicto queda vacio (no se inventa);
- los nombres de fotograma se repiten entre corridas: las pruebas juntas son ``corrida/archivo``.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from conftest import make_config, render_display
from spectro import summary as S
from spectro import teach as T
from spectro.cli import main
from spectro.config import AcceptanceConfig
from spectro.evaluation import TestReport, TestResult, evaluate_test
from spectro.qc import QCRow, write_qc_report
from spectro.read import Reading, write_readings
from spectro.report import RunInput
from spectro.teach import SampleResult, TrainResult, ValidationReport


# ==========================================================================
# Ayudas
# ==========================================================================
def informe(kind="other_video", correct=0, wrong=0, discarded=0, **kw) -> TestReport:
    """Un ``TestReport`` armado a mano (sin leer fotogramas)."""
    rep = TestReport(kind=kind, **kw)
    n = 0
    for res, cuantos in (("correct", correct), ("wrong", wrong), ("discarded", discarded)):
        for _ in range(cuantos):
            n += 1
            rep.results.append(TestResult(
                f"t_{n:07d}.000.jpg", "0.245", "0.245", "ok", 0.9, res))
    return rep


def entrada(run_id="r", statuses=None, read_value=True, test=None, outputs="up_to_date") -> RunInput:
    statuses = ["ok"] * 10 if statuses is None else statuses
    return RunInput(run_id, statuses, read_value, test, templates=12, fingerprint="abc", outputs=outputs)


def corrida(run_id="r", statuses=None, read_value=True, test=None, outputs="up_to_date",
            tiempos=None, history=None) -> S.RunEval:
    """``tiempos`` -> lecturas ``ok`` en esos segundos (vacio = sin lecturas)."""
    lecturas = [Reading(f"t_{i}.jpg", t, i, status="ok") for i, t in enumerate(tiempos or [])]
    return S.RunEval(entrada(run_id, statuses, read_value, test, outputs), history or [], lecturas)


def loo_de(resultados: list[tuple[str, bool]], confusion=None, datas=None) -> TrainResult:
    """Un ``TrainResult`` con solo lo que lee ``summarize``: el leave-one-out."""
    rep = ValidationReport(
        results=[SampleResult(f, "0.245", "0.245", 0.9, "ok", ok) for f, ok in resultados],
        confusion=Counter(confusion or {}),
    )
    return TrainResult(datas=datas or [], errors=[], loo=rep)


def resumir(evals, loo=None, acceptance=None, hole=10.0) -> S.Summary:
    return S.summarize(evals, loo, acceptance or AcceptanceConfig(), hole, "abc", 12)


def fila(summary: S.Summary, run_id: str) -> S.RunRow:
    return next(r for r in summary.rows if r.s.run_id == run_id)


# ==========================================================================
# series_gaps
# ==========================================================================
def test_series_gaps_sin_lecturas_ni_bordes_es_cero():
    assert S.series_gaps([], 10) == (0.0, 0)


def test_series_gaps_una_sola_lectura_sin_bordes_no_tiene_huecos():
    assert S.series_gaps([5.0], 10) == (0.0, 0)


def test_series_gaps_sin_lecturas_pero_con_bordes_toda_la_corrida_es_un_hueco():
    """Una corrida sin una sola lectura valida perdio todo el tiempo entre sus bordes."""
    assert S.series_gaps([], 10, start=0.0, end=100.0) == (100.0, 1)


def test_series_gaps_una_sola_lectura_con_bordes_mide_hacia_ambos_lados():
    assert S.series_gaps([30.0], 10, start=0.0, end=35.0) == (30.0, 1)


def test_series_gaps_hueco_exacto_en_el_umbral_no_cuenta():
    """Rompe: comparar con `>=` en vez de `>` (un hueco de exactamente --hole segundos no es hueco)."""
    assert S.series_gaps([0.0, 10.0], 10.0) == (10.0, 0)


def test_series_gaps_hueco_justo_arriba_del_umbral_cuenta():
    longest, n = S.series_gaps([0.0, 10.5], 10.0)
    assert longest == pytest.approx(10.5) and n == 1


def test_series_gaps_cuenta_varios_y_devuelve_el_mas_largo():
    longest, n = S.series_gaps([0, 5, 20, 24, 60], 10)
    assert (longest, n) == (36, 2)       # 5->20 (15) y 24->60 (36)


def test_series_gaps_no_depende_del_orden_de_los_tiempos():
    assert S.series_gaps([60, 0, 24, 5, 20], 10) == S.series_gaps([0, 5, 20, 24, 60], 10)


def test_series_gaps_los_bordes_cuentan_como_extremos():
    """Rompe: ignorar start/end (una serie que arranca tarde o termina antes tambien pierde datos)."""
    assert S.series_gaps([20.0, 25.0], 10, start=0.0, end=26.0) == (20.0, 1)       # solo el inicio
    assert S.series_gaps([1.0, 5.0], 10, start=0.0, end=40.0) == (35.0, 1)         # solo el final
    assert S.series_gaps([20.0, 25.0], 10) == (5.0, 0)                             # sin bordes: no hay


def test_series_gaps_borde_en_el_umbral_tampoco_es_hueco():
    assert S.series_gaps([10.0], 10.0, start=0.0) == (10.0, 0)


# ==========================================================================
# pool_tests
# ==========================================================================
def test_pool_tests_sin_pruebas_devuelve_vacio():
    assert S.pool_tests({}) == {}
    assert S.pool_tests({"a": None, "b": TestReport()}) == {}     # sin resultados: no cuenta


def test_pool_tests_prefija_el_archivo_con_la_corrida_aunque_los_nombres_se_repitan():
    """Rompe: juntar sin prefijo `corrida/archivo` (los videos repiten nombres de fotograma)."""
    a, b = informe(correct=1), informe(wrong=1)
    assert a.results[0].file == b.results[0].file
    pool = S.pool_tests({"r1": a, "r2": b})["other_video"]
    assert [r.file for r in pool.results] == ["r1/t_0000001.000.jpg", "r2/t_0000001.000.jpg"]
    assert (pool.correct, pool.wrong) == (1, 1)


def test_pool_tests_separa_por_tipo():
    pools = S.pool_tests({"r1": informe("same_run", correct=2), "r2": informe("other_video", wrong=1)})
    assert set(pools) == {"same_run", "other_video"}
    assert pools["same_run"].n == 2 and pools["other_video"].n == 1


def test_pool_tests_suma_confusiones_totales_fugas_y_entrenamiento():
    a = informe(correct=1, n_train=3, n_templates=10, missing_chars=["9"], errors=["x: mal"],
                leaks=[("f1", "f2", 1.5)])
    a.confusion.update({("6", "5"): 1})
    a.char_total.update({"6": 2, "5": 1})
    b = informe(wrong=1, n_train=4, n_templates=12, missing_chars=["8", "9"],
                kind="other_video")
    b.confusion.update({("6", "5"): 2, ("8", "9"): 1})
    b.char_total.update({"6": 1, "8": 1})
    pool = S.pool_tests({"r1": a, "r2": b})["other_video"]
    assert pool.confusion == Counter({("6", "5"): 3, ("8", "9"): 1})
    assert pool.char_total == Counter({"6": 3, "5": 1, "8": 1})
    assert pool.n_train == 7 and pool.n_templates == 12
    assert pool.missing_chars == ["8", "9"]                       # union, sin repetir, ordenada
    assert pool.errors == ["r1/x: mal"] and pool.leaks == [("r1/f1", "r1/f2", 1.5)]


def test_pool_tests_no_modifica_los_informes_de_origen():
    a = informe(correct=1)
    a.confusion.update({("6", "5"): 1})
    S.pool_tests({"r1": a, "r2": informe(correct=1)})
    assert a.results[0].file == "t_0000001.000.jpg" and a.confusion == Counter({("6", "5"): 1})


# ==========================================================================
# loo_char_totals y char_table
# ==========================================================================
def test_loo_char_totals_sin_resultado_es_vacio():
    assert S.loo_char_totals(None) == Counter()
    assert S.loo_char_totals(TrainResult(datas=[], errors=[])) == Counter()


def test_loo_char_totals_cuenta_por_caracter_y_no_cuenta_el_espacio():
    datas = [SimpleNamespace(cells=list(" 0.245")), SimpleNamespace(cells=list("-0.255"))]
    assert S.loo_char_totals(loo_de([], datas=datas)) == Counter(
        {"0": 2, ".": 2, "2": 2, "4": 1, "5": 3, "-": 1})


def test_char_table_sin_datos_es_vacia():
    assert S.char_table([], Counter(), Counter()) == []


def test_char_table_junta_prueba_y_leave_one_out_ordenada_por_caracter():
    t = TestReport()
    t.char_total.update({"6": 4, "5": 3})
    t.confusion.update({("6", "5"): 1})
    filas = S.char_table([t], Counter({"6": 10, "8": 5}), Counter({("8", "9"): 2, ("6", "5"): 1}))
    por = {c.char: c for c in filas}
    assert [c.char for c in filas] == ["5", "6", "8"]
    assert (por["6"].test_cells, por["6"].test_errors, por["6"].loo_cells, por["6"].loo_errors) == (4, 1, 10, 1)
    assert por["6"].top_confusions == "'6'->'5' x2"           # prueba + leave-one-out
    assert (por["8"].test_cells, por["8"].loo_cells, por["8"].loo_errors) == (0, 5, 2)
    assert por["8"].top_confusions == "'8'->'9' x2"
    assert por["5"].top_confusions == "" and por["5"].test_errors == 0


def test_char_table_marca_los_caracteres_que_ninguna_prueba_incluye():
    t = TestReport()
    t.char_total.update({"1": 2})
    por = {c.char: c for c in S.char_table([t], Counter({"8": 3, "1": 3}), Counter())}
    assert por["1"].in_test and not por["8"].in_test


def test_char_table_suma_varias_pruebas_y_deja_las_mas_frecuentes_primero_con_tope_de_tres():
    a, b = TestReport(), TestReport()
    a.char_total.update({"6": 5})
    b.char_total.update({"6": 5})
    a.confusion.update({("6", "5"): 1, ("6", "8"): 1})
    b.confusion.update({("6", "5"): 2, ("6", "0"): 1, ("6", "3"): 1})
    (c,) = S.char_table([a, b], Counter(), Counter())
    assert (c.test_cells, c.test_errors) == (10, 6)
    partes = c.top_confusions.split("; ")
    assert partes[0] == "'6'->'5' x3" and len(partes) == 3     # tope de tres


# ==========================================================================
# trend
# ==========================================================================
def test_trend_sin_historial_es_vacia():
    t = S.trend([], "abc")
    assert (t.evals, t.first, t.last, t.current, t.delta_pts) == (0, None, None, None, None)


def test_trend_cambio_en_puntos_entre_la_primera_y_la_ultima():
    hist = [{"accuracy": "0.5", "fingerprint": "abc"}, {"accuracy": "0.9", "fingerprint": "abc"},
            {"accuracy": "0.75", "fingerprint": "abc"}]
    t = S.trend(hist, "abc")
    assert t.evals == 3 and t.first == 0.5 and t.last == 0.75
    assert t.delta_pts == pytest.approx(25.0)


def test_trend_una_sola_evaluacion_no_cambia():
    t = S.trend([{"accuracy": "0.8", "fingerprint": "abc"}], "abc")
    assert t.evals == 1 and t.delta_pts == pytest.approx(0.0)


def test_trend_evaluacion_con_otra_biblioteca_no_es_vigente():
    """Rompe: dar por vigente una evaluacion hecha con una biblioteca distinta de la actual."""
    t = S.trend([{"accuracy": "0.8", "fingerprint": "vieja"}], "nueva")
    assert t.current is False


def test_trend_huella_igual_es_vigente():
    assert S.trend([{"accuracy": "0.8", "fingerprint": "abc"}], "abc").current is True


@pytest.mark.parametrize("hist_fp, vigente", [("", "abc"), ("abc", ""), ("", "")])
def test_trend_huella_vacia_deja_la_vigencia_desconocida(hist_fp, vigente):
    """Rompe: tratar '' == '' como coincidencia (un historial viejo sin huella no prueba nada)."""
    assert S.trend([{"accuracy": "0.8", "fingerprint": hist_fp}], vigente).current is None


def test_trend_historial_viejo_sin_columna_de_huella_carga():
    t = S.trend([{"accuracy": "0.8"}], "abc")
    assert t.evals == 1 and t.current is None


def test_trend_exactitud_ilegible_queda_en_none():
    t = S.trend([{"accuracy": ""}, {"accuracy": "0.5", "fingerprint": "abc"}], "abc")
    assert t.first is None and t.last == 0.5 and t.delta_pts is None


# ==========================================================================
# summarize
# ==========================================================================
def test_summarize_una_fila_por_corrida_y_al_final_la_fila_total():
    s = resumir([corrida("a"), corrida("b")])
    assert [r.s.run_id for r in s.rows] == ["a", "b", S.TOTAL]
    assert s.total is s.rows[-1] and [r.s.run_id for r in s.runs] == ["a", "b"]


def test_summarize_sin_corridas_deja_solo_total_sin_romper():
    s = resumir([])
    assert [r.s.run_id for r in s.rows] == [S.TOTAL] and s.pooled == {} and s.chars == []
    assert s.total.s.frames == 0


def test_summarize_sin_umbrales_el_veredicto_queda_vacio_aunque_todo_este_mal():
    """Rompe: inventar un veredicto sin umbrales fijados por el usuario."""
    malo = corrida("a", statuses=["dark"] * 10, test=informe(wrong=5), outputs="stale")
    s = resumir([malo])
    assert all(r.s.verdict == "" and r.s.detail == "" for r in s.rows)
    assert not s.acceptance.is_set()


def test_summarize_con_umbrales_da_veredicto_por_corrida_y_en_total():
    bueno = corrida("a", test=informe(correct=10))
    malo = corrida("b", statuses=["ok"] * 5 + ["dark"] * 5, test=informe(correct=10))
    s = resumir([bueno, malo], acceptance=AcceptanceConfig(min_coverage=0.8, min_accuracy=0.9))
    assert fila(s, "a").s.verdict == "accept"
    assert fila(s, "b").s.verdict == "review" and "cobertura" in fila(s, "b").s.detail
    assert s.total.s.verdict == "review"       # 15 ok de 20 = 75% < 80%


def test_summarize_total_mide_other_video_si_existe_y_no_mezcla_con_same_run():
    """Rompe: que TOTAL use same_run (optimista) o mezcle los dos tipos."""
    a = corrida("a", test=informe("same_run", correct=10))
    b = corrida("b", test=informe("other_video", correct=3, wrong=1))
    s = resumir([a, b])
    assert s.total.s.test_kind == "other_video" and s.total.s.test == 4
    assert s.total.s.accuracy == pytest.approx(0.75)
    assert set(s.pooled) == {"same_run", "other_video"}


def test_summarize_total_usa_same_run_si_no_hay_other_video():
    s = resumir([corrida("a", test=informe("same_run", correct=2)),
                 corrida("b", test=informe("same_run", correct=1, wrong=1))])
    assert s.total.s.test_kind == "same_run" and s.total.s.test == 4
    assert s.total.s.accuracy == pytest.approx(0.75)


def test_summarize_sin_ninguna_prueba_total_no_tiene_tipo_ni_exactitud():
    s = resumir([corrida("a"), corrida("b")])
    assert s.total.s.test_kind == "" and s.total.s.accuracy is None and s.total.test is None
    assert s.pooled == {}


def test_summarize_total_suma_solo_las_corridas_con_lecturas():
    """Rompe: sumar en TOTAL tambien las corridas sin readings.csv (inflaria los descartes y bajaria la cobertura)."""
    leida = corrida("a", statuses=["ok"] * 4 + ["dark"])
    sin_leer = corrida("b", statuses=["dark"] * 100, read_value=False)
    s = resumir([leida, sin_leer])
    assert fila(s, "b").s.ok is None and fila(s, "b").s.coverage is None
    assert s.total.s.frames == 5 and s.total.s.ok == 4
    assert s.total.s.coverage == pytest.approx(0.8)


def test_summarize_total_sin_ninguna_corrida_leida_no_inventa_cobertura():
    s = resumir([corrida("a", read_value=False), corrida("b", read_value=False)])
    assert s.total.s.ok is None and s.total.s.coverage is None


def test_summarize_total_toma_el_peor_estado_de_salidas():
    s = resumir([corrida("a", outputs="up_to_date"), corrida("b", outputs="stale"),
                 corrida("c", outputs="no_fingerprint")])
    assert s.total.s.outputs == "stale"
    assert resumir([corrida("a", outputs="up_to_date")]).total.s.outputs == "up_to_date"


def test_summarize_huecos_por_corrida_y_en_total():
    # r1: lecturas en 0,5,40 (hueco de 35); r2: 0,3,6 (sin huecos)
    s = resumir([corrida("r1", tiempos=[0, 5, 40]), corrida("r2", tiempos=[0, 3, 6])], hole=10)
    assert (fila(s, "r1").longest_hole_s, fila(s, "r1").holes) == (35.0, 1)
    assert (fila(s, "r2").longest_hole_s, fila(s, "r2").holes) == (3.0, 0)
    assert (s.total.longest_hole_s, s.total.holes) == (35.0, 1)


def test_summarize_los_bordes_de_la_corrida_salen_de_todas_las_lecturas_no_solo_de_las_ok():
    """El primer y ultimo fotograma leidos (aunque no sean ok) son los bordes de la serie."""
    lecturas = [Reading("a", 0.0, 0, status="low_confidence"), Reading("b", 4.0, 1, status="ok"),
                Reading("c", 30.0, 2, status="spike")]
    ev = S.RunEval(entrada("r"), [], lecturas)
    r = fila(resumir([ev], hole=10), "r")
    assert (r.longest_hole_s, r.holes) == (26.0, 1)          # 4 -> 30 (el 'spike' no es lectura valida)


def test_summarize_corrida_sin_lecturas_no_tiene_huecos_calculados():
    s = resumir([corrida("a", read_value=False)])
    assert fila(s, "a").longest_hole_s is None and fila(s, "a").holes is None
    assert s.total.longest_hole_s is None and s.total.holes is None


def test_summarize_hueco_exacto_en_el_umbral_no_se_cuenta():
    assert fila(resumir([corrida("a", tiempos=[0, 10])], hole=10), "a").holes == 0
    assert fila(resumir([corrida("a", tiempos=[0, 10.5])], hole=10), "a").holes == 1


def test_summarize_leave_one_out_por_corrida_y_total():
    loo = loo_de([("r1/a.jpg", True), ("r1/b.jpg", False), ("r2/a.jpg", True)])
    s = resumir([corrida("r1"), corrida("r2"), corrida("r3")], loo)
    assert (fila(s, "r1").loo_exact, fila(s, "r1").loo_total) == (1, 2)
    assert (fila(s, "r2").loo_exact, fila(s, "r2").loo_total) == (1, 1)
    assert fila(s, "r3").loo_total is None                      # no entreno: no hay dato
    assert (s.total.loo_exact, s.total.loo_total) == (2, 3)
    assert s.has_loo


def test_summarize_sin_leave_one_out_no_inventa_cifras():
    s = resumir([corrida("r1")])
    assert not s.has_loo and s.total.loo_total is None and fila(s, "r1").loo_total is None


def test_summarize_confusiones_del_leave_one_out_ignoran_el_espacio_esperado():
    loo = loo_de([("r1/a.jpg", False)], confusion={(" ", "1"): 4, ("6", "5"): 1})
    s = resumir([corrida("r1")], loo)
    assert s.confusion == Counter({("6", "5"): 1})


def test_summarize_junta_las_confusiones_de_la_prueba_y_del_leave_one_out():
    t = informe(wrong=1)
    t.confusion.update({("6", "5"): 2})
    t.char_total.update({"6": 3})
    loo = loo_de([("r1/a.jpg", False)], confusion={("6", "5"): 1, ("8", "9"): 1})
    s = resumir([corrida("r1", test=t)], loo)
    assert s.confusion == Counter({("6", "5"): 3, ("8", "9"): 1})
    por = {c.char: c for c in s.chars}
    assert por["6"].test_errors == 2 and por["6"].loo_errors == 1


def test_summarize_avisa_de_corridas_sin_prueba_y_sin_lectura():
    s = resumir([corrida("a", test=informe(correct=1)), corrida("b", read_value=False)])
    assert not any(n.startswith("a:") for n in s.notes)
    assert any(n.startswith("b: sin prueba") and "teach test suggest b 20" in n for n in s.notes)
    assert any(n.startswith("b: sin readings.csv") and "read --run b" in n for n in s.notes)


def test_summarize_lleva_tendencia_historial_y_confianzas():
    hist = [{"accuracy": "0.5", "fingerprint": "abc"}, {"accuracy": "1.0", "fingerprint": "abc"}]
    ev = corrida("a", tiempos=[0, 1], history=hist)
    s = resumir([ev])
    assert fila(s, "a").trend.evals == 2 and fila(s, "a").trend.current is True
    assert s.histories == {"a": hist} and len(s.confidences) == 2


# ==========================================================================
# format_summary
# ==========================================================================
def _texto(summary) -> str:
    return "\n".join(S.format_summary(summary))


def test_format_summary_tiene_las_cinco_secciones_y_es_ascii():
    """Rompe: tildes o enies en la consola de Windows."""
    t = informe(correct=3, wrong=1)
    t.char_total.update({"6": 2})
    t.confusion.update({("6", "5"): 1})
    s = resumir([corrida("a", test=t, tiempos=[0, 20],
                         history=[{"accuracy": "0.5", "fingerprint": "abc"}])],
                loo_de([("a/x.jpg", True)]))
    lineas = S.format_summary(s)
    for n in range(1, 6):
        assert any(l.startswith(f"-- {n}. ") for l in lineas)
    assert all(l.isascii() for l in lineas), [l for l in lineas if not l.isascii()]


def test_format_summary_sin_umbrales_explica_como_fijarlos():
    texto = _texto(resumir([corrida("a")]))
    assert "sin umbrales de aceptacion" in texto and "--min-accuracy" in texto
    assert " accept" not in texto and "review" not in texto      # ninguna fila lleva veredicto


def test_format_summary_con_umbrales_muestra_el_veredicto_de_cada_fila():
    texto = _texto(resumir([corrida("a", statuses=["ok", "dark"])],
                           acceptance=AcceptanceConfig(min_coverage=0.9)))
    assert "sin umbrales de aceptacion" not in texto
    assert "review (cobertura 50.0% < 90.0%)" in texto


def test_format_summary_sin_prueba_sugiere_armarla():
    texto = _texto(resumir([corrida("a")]))
    assert "ninguna corrida tiene prueba" in texto and "teach test suggest <id> 20" in texto
    assert "sin prueba ni muestras de entrenamiento" in texto


def test_format_summary_incluye_la_prueba_conjunta_y_el_aviso_de_caracteres_ausentes():
    t = informe(correct=1)
    t.char_total.update({"1": 1})
    texto = _texto(resumir([corrida("a", test=t)], loo_de([("a/x.jpg", True)],
                           datas=[SimpleNamespace(cells=list("1 8"))])))
    assert "prueba other_video (todas las corridas)" in texto
    assert "ninguna prueba incluye 8" in texto


def test_format_summary_dice_con_que_prueba_se_mide_el_total():
    texto = _texto(resumir([corrida("a", test=informe("same_run", correct=1))]))
    assert f"la fila {S.TOTAL} mide la prueba same_run" in texto


def test_format_summary_corrida_sin_historial_lo_dice_y_con_historial_da_el_cambio():
    hist = [{"accuracy": "0.5", "fingerprint": "otra"}, {"accuracy": "0.75", "fingerprint": "otra"}]
    texto = _texto(resumir([corrida("a"), corrida("b", history=hist)]))
    assert "sin historial de evaluaciones" in texto
    assert "+25.0 pts" in texto and "con otra biblioteca" in texto


def test_format_summary_sin_lecturas_muestra_guion_en_el_hueco():
    texto = _texto(resumir([corrida("a", read_value=False)]))
    linea = next(l for l in texto.splitlines() if "mas largo" in l and l.strip().startswith("a "))
    assert "-" in linea.split("mas largo")[1]


# ==========================================================================
# Escritura de CSV y HTML a partir de un Summary
# ==========================================================================
def test_write_summary_csv_tiene_las_columnas_una_fila_por_corrida_y_total(tmp_path):
    t = informe(correct=3, wrong=1)
    s = resumir([corrida("a", test=t, tiempos=[0, 30]), corrida("b", read_value=False)])
    ruta = S.write_summary_csv(s, tmp_path / "sub" / "summary.csv")
    with ruta.open(encoding="utf-8") as fh:
        lector = csv.DictReader(fh)
        assert lector.fieldnames == S.SUMMARY_FIELDS
        filas = list(lector)
    assert [f["run"] for f in filas] == ["a", "b", "TOTAL"]
    a, b = filas[0], filas[1]
    assert a["test"] == "4" and a["correct"] == "3" and a["wrong"] == "1"
    assert float(a["accuracy_lo"]) < float(a["accuracy"]) < float(a["accuracy_hi"])
    assert a["longest_hole_s"] == "30.0" and a["holes"] == "1"
    assert b["ok"] == "" and b["coverage"] == "" and b["longest_hole_s"] == "" and b["test"] == ""


def test_write_chars_csv_una_fila_por_caracter(tmp_path):
    t = TestReport()
    t.char_total.update({"6": 2})
    t.confusion.update({("6", "5"): 1})
    s = resumir([corrida("a", test=informe(correct=1))], loo_de([("a/x.jpg", True)]))
    s.chars = S.char_table([t], Counter({"6": 5}), Counter())
    ruta = S.write_chars_csv(s, tmp_path / "c.csv")
    with ruta.open(encoding="utf-8") as fh:
        lector = csv.DictReader(fh)
        assert lector.fieldnames == S.CHARS_FIELDS
        (f,) = list(lector)
    assert f == {"char": "6", "test_cells": "2", "test_errors": "1", "loo_cells": "5",
                 "loo_errors": "0", "top_confusions": "'6'->'5' x1"}


def test_write_html_con_datos_vacios_no_rompe_y_no_referencia_recursos_externos(tmp_path):
    ruta = S.write_html(resumir([]), tmp_path / "s.html")
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith("<!DOCTYPE html>") and "http" not in texto


# ==========================================================================
# to_test_report: confusion y char_total
# ==========================================================================
def _frame(carpeta: Path, t: float, texto: str | None = None, ruido: bool = False) -> str:
    nombre = f"t_{int(t):07d}.000.jpg"
    if ruido:
        img = np.random.default_rng(int(t)).integers(0, 255, (140, 320), dtype=np.uint8)
    else:
        img = render_display(texto)
    cv2.imwrite(str(carpeta / nombre), img)
    return nombre


def test_char_total_cuenta_las_celdas_esperadas_y_no_el_espacio(cfg_sign, library_sign, tmp_path):
    a = _frame(tmp_path, 0, " 1.789")        # signo en blanco: el espacio esperado no cuenta
    rep = evaluate_test([T.Sample(a, "1.789")], cfg_sign, tmp_path, None, library_sign)
    assert rep.results[0].result == "correct"
    assert rep.char_total == Counter({"1": 1, ".": 1, "7": 1, "8": 1, "9": 1})
    assert " " not in rep.char_total and rep.confusion == Counter()


def test_confusion_registra_esperado_y_leido_de_la_celda_mal_leida(cfg_sign, library_sign, tmp_path):
    """Rompe: no comparar celda a celda en to_test_report (la confusion quedaria vacia)."""
    c = _frame(tmp_path, 20, "-3.056")        # el display dice 056; se escribio 057
    rep = evaluate_test([T.Sample(c, "-3.057")], cfg_sign, tmp_path, None, library_sign)
    assert rep.results[0].result == "wrong"
    assert rep.confusion == Counter({("7", "6"): 1})
    assert rep.char_total["7"] == 1 and sum(rep.char_total.values()) == 6


def test_confusion_cuenta_las_celdas_mal_leidas_aunque_la_lectura_se_descarte(cfg_sign, library_sign, tmp_path):
    """Rompe: contar la confusion solo de las lecturas aceptadas (la descartada tambien dice en que falla)."""
    ruido = _frame(tmp_path, 30, ruido=True)
    rep = evaluate_test([T.Sample(ruido, "0.000")], cfg_sign, tmp_path, None, library_sign)
    assert rep.results[0].result == "discarded"
    assert rep.char_total == Counter({"0": 4, ".": 1})
    errores = sum(rep.confusion.values())
    assert errores >= 1
    assert all(want != got and want != " " for want, got in rep.confusion)


def test_confusion_suma_varias_muestras_y_vacio_no_cuenta_nada(cfg_sign, library_sign, tmp_path):
    muestras = [T.Sample(_frame(tmp_path, 0, "-3.056"), "-3.057"),
                T.Sample(_frame(tmp_path, 10, "-3.056"), "-3.057"),
                T.Sample(_frame(tmp_path, 20, "-3.056"), "-3.056")]
    rep = evaluate_test(muestras, cfg_sign, tmp_path, None, library_sign)
    assert rep.confusion == Counter({("7", "6"): 2})
    assert rep.char_total["6"] == 1 and rep.char_total["7"] == 2   # se cuenta lo esperado
    vacio = evaluate_test([], cfg_sign, tmp_path, None, library_sign)
    assert vacio.confusion == Counter() and vacio.char_total == Counter()


def test_los_contadores_de_dos_informes_no_se_comparten():
    a, b = TestReport(), TestReport()
    a.confusion[("1", "2")] += 1
    a.char_total["1"] += 1
    assert b.confusion == Counter() and b.char_total == Counter()


# ==========================================================================
# CLI sobre un proyecto de juguete
# ==========================================================================
TRAIN_TEXTS = ["-0.123", " 4.567", "-8.901", " 2.345", " 6.789", "-0.246", " 1.357", " 9.048"]


def _png(carpeta: Path, t: float, texto: str) -> str:
    # mismos nombres en las dos corridas: los videos repiten nombres de fotograma
    nombre = f"t_{int(t):07d}.000.jpg"
    cv2.imwrite(str(carpeta / nombre), render_display(texto))
    return nombre


def _escribir_salidas(run: Path, nombres: list[str], estados: list[str]) -> None:
    """qc_report.csv y readings.csv a mano: el resumen solo los lee."""
    write_qc_report([QCRow(n, float(i * 10), i + 1) for i, n in enumerate(nombres)],
                    run / "out" / "qc_report.csv")
    write_readings([Reading(n, float(i * 10), i + 1, value=0.1, confidence=0.9, chars=" 0.245",
                            status=e) for i, (n, e) in enumerate(zip(nombres, estados))],
                   run / "out" / "readings.csv")


@pytest.fixture
def proyecto(tmp_path):
    """r1: entrenamiento + prueba (misma corrida), readings. r2: solo prueba (otro video), sin readings.

    Las dos corridas tienen **los mismos nombres de fotograma**. Ya se entreno y se evaluo la prueba
    (para que exista ``test/teach_history.csv``).
    """
    runs, calib = tmp_path / "runs", tmp_path / "calib"
    base = ["--runs-dir", str(runs), "--calib-dir", str(calib)]
    for rid in ("r1", "r2"):
        (runs / rid / "frames").mkdir(parents=True)
        make_config(sign=True).save(runs / rid / "config.json")
    train = [(_png(runs / "r1" / "frames", i * 10, t), t.strip()) for i, t in enumerate(TRAIN_TEXTS)]
    pruebas = [" 3.456", "-7.890"]
    test1 = [(_png(runs / "r1" / "frames", 100 + i * 10, t), t.strip()) for i, t in enumerate(pruebas)]
    test2 = [(_png(runs / "r2" / "frames", 100 + i * 10, t), t.strip()) for i, t in enumerate(pruebas)]
    for args in (["samples", "add", "r1", *[f"{a}={v}" for a, v in train]],
                 ["test", "add", "r1", *[f"{a}={v}" for a, v in test1]],
                 ["test", "add", "r2", *[f"{a}={v}" for a, v in test2]],
                 ["train", "r1"], ["test", "eval", "r1"], ["test", "eval", "r2"]):
        assert main(base + ["teach", *args]) == 0, args
    nombres = [a for a, _ in train] + [a for a, _ in test1]
    _escribir_salidas(runs / "r1", nombres, ["ok"] * 8 + ["low_confidence", "spike"])
    return SimpleNamespace(base=base, runs=runs, calib=calib, tmp=tmp_path)


def _correr(p, *args) -> int:
    return main(p.base + ["summary", *args])


def _huellas(*raices: Path, excepto: tuple[str, ...] = ()) -> dict[str, str]:
    """sha256 de cada archivo bajo las raices (ruta -> hash), menos los de ``excepto``."""
    out = {}
    for raiz in raices:
        for f in sorted(raiz.rglob("*")):
            if f.is_file() and not f.name.startswith(excepto):
                out[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def _leer(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_cli_escribe_los_tres_archivos_y_el_codigo_es_cero(proyecto, capsys):
    assert _correr(proyecto) == 0
    for nombre in ("summary.csv", "summary_chars.csv", "summary.html"):
        assert (proyecto.runs / nombre).exists(), nombre
    salida = capsys.readouterr().out
    assert "== summary" in salida and "-- 5. Veredicto --" in salida and "escrito:" in salida


def test_cli_no_html_escribe_solo_los_dos_csv(proyecto):
    assert _correr(proyecto, "--no-html") == 0
    assert (proyecto.runs / "summary.csv").exists() and (proyecto.runs / "summary_chars.csv").exists()
    assert not (proyecto.runs / "summary.html").exists()


def test_cli_el_html_es_autocontenido(proyecto):
    """Rompe: cargar un recurso externo (script, hoja de estilo o imagen remota)."""
    assert _correr(proyecto) == 0
    texto = (proyecto.runs / "summary.html").read_text(encoding="utf-8")
    assert "http" not in texto
    assert "data:image/png;base64," in texto


def test_cli_summary_csv_trae_las_corridas_el_total_y_los_numeros(proyecto):
    assert _correr(proyecto) == 0
    filas = {f["run"]: f for f in _leer(proyecto.runs / "summary.csv")}
    assert list(filas) == ["r1", "r2", "TOTAL"]
    r1, r2, total = filas["r1"], filas["r2"], filas["TOTAL"]
    assert r1["frames"] == "10" and r1["ok"] == "8" and r1["low_confidence"] == "1" and r1["spike"] == "1"
    assert float(r1["coverage"]) == pytest.approx(0.8)
    assert r1["test"] == "2" and r1["test_kind"] == "same_run"
    assert r2["test"] == "2" and r2["test_kind"] == "other_video"
    assert r2["ok"] == "" and r2["coverage"] == ""          # r2 no tiene readings.csv
    assert total["test_kind"] == "other_video"               # hold-out por video si existe
    assert total["frames"] == "10"                           # solo r1 tiene lecturas
    assert total["verdict"] == "" and r1["verdict"] == ""    # sin umbrales
    assert int(r1["evals"]) == 1 and r1["eval_current"] == "yes"
    assert r1["loo_total"] == "8"


def test_cli_summary_chars_csv_lista_los_caracteres(proyecto):
    assert _correr(proyecto) == 0
    chars = {f["char"]: f for f in _leer(proyecto.runs / "summary_chars.csv")}
    assert {"0", "1", "9", "."} <= set(chars)
    assert int(chars["."]["loo_cells"]) >= 8 and int(chars["."]["test_cells"]) >= 1


def test_cli_no_modifica_calib_ni_teach_ni_test_ni_el_historial(proyecto):
    """Rompe: que summary escriba en calib/ o dentro de runs/<id>/ (teach/, test/, out/, config)."""
    historial = [proyecto.runs / r / "test" / "teach_history.csv" for r in ("r1", "r2")]
    assert all(h.exists() for h in historial)
    antes = _huellas(proyecto.calib, proyecto.runs)
    assert _correr(proyecto) == 0
    despues = _huellas(proyecto.calib, proyecto.runs, excepto=("summary",))
    assert despues == antes


def test_cli_dos_veces_es_idempotente(proyecto):
    assert _correr(proyecto) == 0
    csv1 = (proyecto.runs / "summary.csv").read_bytes()
    chars1 = (proyecto.runs / "summary_chars.csv").read_bytes()
    datos1 = _huellas(proyecto.runs, proyecto.calib, excepto=("summary",))
    assert _correr(proyecto) == 0
    assert (proyecto.runs / "summary.csv").read_bytes() == csv1
    assert (proyecto.runs / "summary_chars.csv").read_bytes() == chars1
    assert _huellas(proyecto.runs, proyecto.calib, excepto=("summary",)) == datos1


def test_cli_no_agrega_muestras_de_prueba_a_la_biblioteca(proyecto, monkeypatch):
    """La prueba nunca entra a la biblioteca: el leave-one-out de summary solo ve el entrenamiento."""
    vistos: list[str] = []
    original = T.build_pool_runs

    def espia(runs, *a, **k):
        for r in runs:
            vistos.extend(s.file for s in r.train)
        return original(runs, *a, **k)

    monkeypatch.setattr(T, "build_pool_runs", espia)
    assert _correr(proyecto) == 0
    probados = {s.file for s in T.load_truth(proyecto.runs / "r1" / "test" / "test.csv")}
    assert vistos and not (probados & set(vistos))


def test_cli_sin_biblioteca_falla_y_dice_que_correr(tmp_path, capsys):
    runs = tmp_path / "runs"
    (runs / "r1" / "frames").mkdir(parents=True)
    make_config(sign=True).save(runs / "r1" / "config.json")
    base = ["--runs-dir", str(runs), "--calib-dir", str(tmp_path / "calib")]
    assert main(base + ["summary"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and "teach train" in err
    assert not (runs / "summary.csv").exists()


def test_cli_corrida_inexistente_da_error_y_no_escribe_nada(proyecto, capsys):
    assert _correr(proyecto, "no_existe") == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and "no_existe" in err
    assert not (proyecto.runs / "summary.csv").exists()
    assert not (proyecto.runs / "summary.html").exists()


def test_cli_una_corrida_inexistente_entre_las_validas_tampoco_escribe_nada(proyecto):
    assert _correr(proyecto, "r1", "fantasma") == 1
    assert not (proyecto.runs / "summary.csv").exists()


@pytest.mark.parametrize("hole", ["0", "-5"])
def test_cli_hole_no_positivo_da_error_claro(proyecto, capsys, hole):
    assert _correr(proyecto, "--hole", hole) == 1
    assert "--hole" in capsys.readouterr().err
    assert not (proyecto.runs / "summary.csv").exists()


def test_cli_umbral_fuera_de_rango_da_error_claro(proyecto, capsys):
    assert _correr(proyecto, "--min-coverage", "95") == 1
    assert "--min-coverage" in capsys.readouterr().err


def test_cli_filtra_por_corrida(proyecto):
    assert _correr(proyecto, "r2", "--no-html") == 0
    filas = _leer(proyecto.runs / "summary.csv")
    assert [f["run"] for f in filas] == ["r2", "TOTAL"]


def test_cli_corrida_repetida_en_los_argumentos_se_cuenta_una_vez(proyecto):
    assert _correr(proyecto, "r1", "r1", "--no-html") == 0
    assert [f["run"] for f in _leer(proyecto.runs / "summary.csv")] == ["r1", "TOTAL"]


def test_cli_sin_argumentos_incluye_todas_las_corridas_dadas_de_alta(proyecto):
    (proyecto.runs / "carpeta_suelta").mkdir()          # sin config.json: no es una corrida
    assert _correr(proyecto, "--no-html") == 0
    assert [f["run"] for f in _leer(proyecto.runs / "summary.csv")] == ["r1", "r2", "TOTAL"]


def test_cli_los_umbrales_de_los_flags_dan_veredicto(proyecto, capsys):
    assert _correr(proyecto, "--min-coverage", "0.9", "--no-html") == 0
    filas = {f["run"]: f for f in _leer(proyecto.runs / "summary.csv")}
    assert filas["r1"]["verdict"] == "review" and "cobertura 80.0% < 90.0%" in filas["r1"]["detail"]
    assert filas["TOTAL"]["verdict"] == "review"
    assert "sin umbrales de aceptacion" not in capsys.readouterr().out


def test_cli_hole_cambia_el_conteo_de_huecos(proyecto):
    # r1: lecturas ok en 0..70 s cada 10 s; la baja confianza (80) y el spike (90) no son validas.
    # El ultimo fotograma (90) es el borde: el hueco final mide 20 s.
    assert _correr(proyecto, "r1", "--hole", "20", "--no-html") == 0
    f = _leer(proyecto.runs / "summary.csv")[0]
    assert (f["longest_hole_s"], f["holes"]) == ("20.0", "0")          # exactamente en el umbral
    assert _correr(proyecto, "r1", "--hole", "19.9", "--no-html") == 0
    assert _leer(proyecto.runs / "summary.csv")[0]["holes"] == "1"
    assert _correr(proyecto, "r1", "--hole", "5", "--no-html") == 0
    assert _leer(proyecto.runs / "summary.csv")[0]["holes"] == "8"      # 7 intervalos de 10 s + el final


def test_cli_un_historial_viejo_sin_columna_de_huella_carga(proyecto):
    """Compatibilidad: teach_history.csv de antes de la huella (se arma a mano en la copia temporal)."""
    h = proyecto.runs / "r1" / "test" / "teach_history.csv"
    lineas = h.read_text(encoding="utf-8").splitlines()
    cab = lineas[0].split(",")
    i = cab.index("fingerprint")
    viejo = [",".join(c for j, c in enumerate(l.split(",")) if j != i) for l in lineas]
    h.write_text("\n".join(viejo) + "\n", encoding="utf-8")
    assert _correr(proyecto, "r1", "--no-html") == 0
    fila_r1 = _leer(proyecto.runs / "summary.csv")[0]
    assert fila_r1["evals"] == "1" and fila_r1["eval_current"] == ""
