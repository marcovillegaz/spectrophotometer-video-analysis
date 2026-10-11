"""Prueba (hold-out): Wilson, correcta / erronea / descartada, tipo, historial y flujo por CLI."""

from __future__ import annotations

import csv

import cv2
import numpy as np
import pytest

from conftest import make_config, render_display
from spectro import teach as T
from spectro.cli import BATCH_STAGES, batch_stages, build_parser, main
from spectro.evaluation import (
    HISTORY_FIELDS,
    append_history,
    evaluate_test,
    format_test_report,
    load_history,
    summary_lines,
    wilson,
    write_test_report,
)
from spectro.read import Reading, load_readings, read_frame, write_readings

TRAIN_TEXTS = ["-0.123", " 4.567", "-8.901", " 2.345", " 6.789", "-0.246", " 1.357", " 9.048"]


def frame(tmp_path, t: float, text: str | None = None, noise: bool = False) -> str:
    name = f"t_{int(t):07d}.000.jpg"
    if noise:
        img = np.random.default_rng(int(t)).integers(0, 255, (140, 320), dtype=np.uint8)
    else:
        img = render_display(text)
    cv2.imwrite(str(tmp_path / name), img)
    return name


# -- Wilson ---------------------------------------------------------------
def test_wilson_valores_conocidos():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-3) and hi == 1.0
    lo, hi = wilson(50, 100)
    assert (lo, hi) == (pytest.approx(0.4038, abs=1e-3), pytest.approx(0.5962, abs=1e-3))
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)


# -- evaluate_test --------------------------------------------------------
def test_clasifica_correcta_erronea_y_descartada(cfg_sign, library_sign, tmp_path):
    a = frame(tmp_path, 0, "-0.245")
    b = frame(tmp_path, 10, " 1.789")
    c = frame(tmp_path, 20, "-3.056")
    d = frame(tmp_path, 30, noise=True)
    test = [T.Sample(a, "-0.245"), T.Sample(b, "1.789"), T.Sample(c, "-3.057"),  # c: el display dice 056
            T.Sample(d, "0.000")]
    rep = evaluate_test(test, cfg_sign, tmp_path, None, library_sign)
    por = {r.file: r.result for r in rep.results}
    assert por[a] == por[b] == "correct"
    assert por[c] == "wrong"
    assert por[d] == "discarded"
    assert (rep.correct, rep.wrong, rep.discarded) == (2, 1, 1)
    assert rep.accepted == 3 and rep.accepted_error == pytest.approx(1 / 3)
    assert rep.coverage == pytest.approx(0.75) and rep.accuracy == pytest.approx(0.5)
    assert rep.kind == "other_video" and rep.distinct_values == 4


def test_tipo_y_fugas(cfg_sign, library_sign, tmp_path):
    n_test = frame(tmp_path, 12, "-0.245")
    n_train = frame(tmp_path, 10, " 1.789")
    lejos = frame(tmp_path, 200, "-3.056")
    test = [T.Sample(n_test, "-0.245")]
    sin = evaluate_test(test, cfg_sign, tmp_path, None, library_sign, train=[])
    assert sin.kind == "other_video" and sin.leaks == []
    con = evaluate_test(test, cfg_sign, tmp_path, None, library_sign,
                        train=[T.Sample(n_train, "1.789"), T.Sample(lejos, "-3.056")], gap_s=5)
    assert con.kind == "same_run" and len(con.leaks) == 1 and con.n_train == 2
    texto = "\n".join(format_test_report(con))
    assert "optimista" in texto and "casi el mismo fotograma" in texto


def test_avisa_valores_repetidos_y_caracteres_ausentes(cfg_sign, library_sign, tmp_path):
    muestras = [T.Sample(frame(tmp_path, i * 10, "-0.245"), "-0.245") for i in range(4)]
    rep = evaluate_test(muestras, cfg_sign, tmp_path, None, [t for t in library_sign if t.label != "7"])
    assert rep.distinct_values == 1
    texto = "\n".join(format_test_report(rep))
    assert "1 valores distintos" in texto and "optimista" in texto
    ausente = evaluate_test([T.Sample(frame(tmp_path, 99, " 1.789"), "1.789")], cfg_sign, tmp_path,
                            None, [t for t in library_sign if t.label != "7"])
    assert ausente.missing_chars == ["7"]


def test_exactitud_por_caracter_y_resumen(cfg_sign, library_sign, tmp_path):
    test = [T.Sample(frame(tmp_path, 0, "-0.245"), "-0.245"),
            T.Sample(frame(tmp_path, 10, "-0.245"), "-0.246")]
    rep = evaluate_test(test, cfg_sign, tmp_path, None, library_sign)
    lineas = summary_lines(rep)
    assert len(lineas) == 3 and not lineas[0].startswith("!") and "1 correctas" in lineas[1]
    repetidas = evaluate_test([T.Sample(frame(tmp_path, 20 + i * 10, "-0.245"), "-0.245") for i in range(4)],
                              cfg_sign, tmp_path, None, library_sign)
    assert summary_lines(repetidas)[0].startswith("!")   # 1 valor distinto en 4 fotogramas
    assert summary_lines(evaluate_test([], cfg_sign, tmp_path, None, library_sign)) == [
        "prueba: no hay muestras"]
    assert format_test_report(evaluate_test([], cfg_sign, tmp_path, None, library_sign))[0].endswith(
        "no hay muestras de prueba")


def test_muestras_con_formato_invalido_se_reportan(cfg_sign, library_sign, tmp_path):
    rep = evaluate_test([T.Sample(frame(tmp_path, 0, "-0.245"), "12.5")], cfg_sign, tmp_path, None,
                        library_sign)
    assert rep.n == 0 and len(rep.errors) == 1


def test_informe_csv_e_historial(cfg_sign, library_sign, tmp_path):
    test = [T.Sample(frame(tmp_path, 0, "-0.245"), "-0.245")]
    rep = evaluate_test(test, cfg_sign, tmp_path, None, library_sign)
    out = write_test_report(rep, tmp_path / "out" / "test_report.csv")
    assert "correct" in out.read_text(encoding="utf-8")
    hist = tmp_path / "out" / "teach_history.csv"
    append_history(hist, rep)
    append_history(hist, rep)
    filas = load_history(hist)
    assert len(filas) == 2 and list(filas[0]) == HISTORY_FIELDS
    assert filas[0]["kind"] == "other_video" and float(filas[0]["accuracy"]) == 1.0
    assert load_history(tmp_path / "no_existe.csv") == []


# -- margen en readings.csv ------------------------------------------------
def test_read_frame_calcula_el_margen(cfg_sign, library_sign):
    r = read_frame(render_display("-0.245"), cfg_sign, library_sign)
    assert r.status == "ok" and r.margin >= cfg_sign.templates.min_margin


def test_margen_se_guarda_y_un_csv_viejo_carga(tmp_path):
    p = tmp_path / "readings.csv"
    write_readings([Reading("t_0000001.000.jpg", 1.0, 1, 0.5, 0.9, "-0.500", margin=0.1234)], p)
    assert load_readings(p)[0].margin == pytest.approx(0.1234)
    viejo = tmp_path / "viejo.csv"
    viejo.write_text("archivo,t_s,indice,valor,confianza,caracteres,dx,dy,estado\n"
                     "t_0000001.000.jpg,1.000,1,0.5,0.9000, 0.500,0,0,ok\n", encoding="utf-8")
    assert load_readings(viejo)[0].margin == 0.0


# -- batch --until ---------------------------------------------------------
def test_batch_stages():
    assert batch_stages("report") == list(BATCH_STAGES)
    assert batch_stages("qc") == ["new", "extract", "calibrate", "qc"]
    assert batch_stages("read")[-1] == "read"
    with pytest.raises(ValueError):
        batch_stages("extract")


def test_parser_acepta_until_y_los_flags_de_teach():
    p = build_parser()
    assert p.parse_args(["batch", "a.mov", "--until", "qc"]).until == "qc"
    assert p.parse_args(["batch", "a.mov"]).until == "report"
    a = p.parse_args(["teach", "samples", "suggest", "x", "5", "--strategy", "random",
                      "--seed", "2", "--gap", "7"])
    assert (a.run_id, a.n, a.which, a.strategy, a.seed, a.gap) == ("x", 5, "train", "random", 2, 7.0)
    t = p.parse_args(["teach", "test", "suggest", "x", "5"])
    assert (t.which, t.strategy) == ("test", "random")          # la prueba es siempre al azar
    assert p.parse_args(["teach", "test", "eval"]).runs == []


# -- flujo completo por CLI (proyecto de juguete en tmp_path) ----------------
@pytest.fixture
def proyecto(tmp_path):
    runs, calib = tmp_path / "runs", tmp_path / "calib"
    run = runs / "r1"
    (run / "frames").mkdir(parents=True)
    make_config(sign=True).save(run / "config.json")
    train = [(frame(run / "frames", i * 10, t), t.strip()) for i, t in enumerate(TRAIN_TEXTS)]
    test = [(frame(run / "frames", 100 + i * 10, t), t.strip()) for i, t in enumerate((" 3.456", "-7.890"))]
    base = ["--runs-dir", str(runs), "--calib-dir", str(calib)]
    return {"base": base, "run": run, "calib": calib, "train": train, "test": test, "tmp": tmp_path}


def cli(p, *args):
    return main(p["base"] + ["teach", *args])


def test_flujo_completo_la_prueba_nunca_entra_a_la_biblioteca(proyecto, monkeypatch, capsys):
    """Rompe: que train arme la biblioteca con muestras de test.csv (p. ej. si juntara truth + test)."""
    p = proyecto
    assert cli(p, "samples", "add", "r1", *[f"{a}={v}" for a, v in p["train"]]) == 0
    assert cli(p, "test", "add", "r1", *[f"{a}={v}" for a, v in p["test"]]) == 0
    assert (p["run"] / "test.csv").exists()

    vistos: list[list[str]] = []
    original = T.build_pool

    def espia(samples, *a, **k):
        vistos.append([s.file for s in samples])
        return original(samples, *a, **k)

    monkeypatch.setattr(T, "build_pool", espia)
    assert cli(p, "train", "r1") == 0
    probados = {a for a, _ in p["test"]}
    assert vistos and not (probados & {x for lote in vistos for x in lote})  # nunca llega a la biblioteca
    monkeypatch.undo()

    capsys.readouterr()
    assert cli(p, "test", "eval", "r1") == 0
    salida = capsys.readouterr().out
    assert "teach test eval r1" in salida and "correct" in salida and "misma corrida" in salida
    assert cli(p, "test", "eval", "r1") == 0
    filas = load_history(p["run"] / "out" / "teach_history.csv")
    assert len(filas) == 2 and filas[0]["kind"] == "same_run" and filas[0]["test"] == "2"
    with (p["run"] / "out" / "test_report.csv").open(encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 2


def test_mover_de_entrenamiento_a_prueba_avisa_y_deja_un_solo_conjunto(proyecto, capsys):
    p = proyecto
    a, v = p["train"][0]
    cli(p, "samples", "add", "r1", f"{a}={v}")
    capsys.readouterr()
    cli(p, "test", "add", "r1", f"{a}={v}")
    assert "ya aporto glifos" in capsys.readouterr().out
    assert T.load_truth(p["run"] / "truth.csv") == []
    assert [s.file for s in T.load_truth(p["run"] / "test.csv")] == [a]


def test_suggest_para_prueba_es_al_azar_y_lejos_del_entrenamiento(proyecto, capsys):
    p = proyecto
    cli(p, "samples", "add", "r1", *[f"{a}={v}" for a, v in p["train"]])
    capsys.readouterr()
    assert cli(p, "test", "suggest", "r1", "3", "--gap", "5") == 0
    salida = capsys.readouterr().out
    nombres = [x.split()[0] for x in salida.splitlines() if x.strip().startswith("t_")]
    entrenados = {a for a, _ in p["train"]}
    assert nombres and not set(nombres) & entrenados
    assert "random" in salida and "incierta" not in salida


def test_suggest_sin_readings_avisa_arranque_en_frio(proyecto, capsys):
    p = proyecto
    assert cli(p, "samples", "suggest", "r1", "3", "--strategy", "mixed") == 0
    salida = capsys.readouterr().out
    assert "uniform" in salida and "arranque en frio" in salida


def test_eval_sin_prueba_o_sin_biblioteca_falla_con_mensaje(proyecto, capsys):
    p = proyecto
    assert cli(p, "test", "eval", "r1") == 1             # sin biblioteca: el error dice que correr
    assert "templates" in capsys.readouterr().err
    cli(p, "samples", "add", "r1", *[f"{a}={v}" for a, v in p["train"]])
    assert cli(p, "train", "r1") == 0
    assert cli(p, "test", "eval", "r1") == 1             # hay biblioteca pero no hay prueba
    assert "No hay muestras de prueba" in capsys.readouterr().err


def test_eval_sin_corrida_recorre_las_corridas_con_prueba(proyecto, capsys):
    p = proyecto
    cli(p, "samples", "add", "r1", *[f"{a}={v}" for a, v in p["train"]])
    cli(p, "test", "add", "r1", *[f"{a}={v}" for a, v in p["test"]])
    cli(p, "train", "r1")
    capsys.readouterr()
    assert cli(p, "test", "eval") == 0
    salida = capsys.readouterr().out
    assert "teach test eval (biblioteca:" in salida
    linea = next(x for x in salida.splitlines() if x.strip().startswith("r1"))
    assert "misma" in linea
