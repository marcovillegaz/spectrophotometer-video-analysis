"""Cambios del code review de la Fase 2: huella en el historial, restore como cambio,
mensaje sin respaldo, qc re-corrido sin read y validacion temprana de umbrales de ``batch``.
"""

from __future__ import annotations

import csv
import os
import time

import pytest

from conftest import render_display
from spectro import library as L
from spectro import teach as T
from spectro.cli import main
from spectro.evaluation import HISTORY_FIELDS, append_history, evaluate_test, load_history
from spectro.project import CalibPaths, RunPaths
from spectro.qc import QCRow, write_qc_report
from spectro.read import DESACTUALIZADAS, Reading, outputs_state, write_readings
from spectro.report import batch_summary, load_run_input

# fixtures y ayudas de los otros archivos de CLI
from test_batch_report import lote  # noqa: F401
from test_teach_cli import entrenar, p, teach  # noqa: F401


# ==========================================================================
# evaluation.append_history: columna huella
# ==========================================================================
def _reporte(cfg_sign, library_sign, tmp_path):
    import cv2

    cv2.imwrite(str(tmp_path / "t_0000000.000.jpg"), render_display("-0.245"))
    return evaluate_test([T.Sample("t_0000000.000.jpg", "-0.245")], cfg_sign, tmp_path, None, library_sign)


def test_append_history_guarda_la_huella(cfg_sign, library_sign, tmp_path):
    rep = _reporte(cfg_sign, library_sign, tmp_path)
    hist = tmp_path / "h.csv"
    append_history(hist, rep, huella="abc123def456")
    append_history(hist, rep)
    assert [f["huella"] for f in load_history(hist)] == ["abc123def456", ""]


def test_append_history_migra_un_historial_viejo_sin_perder_filas(cfg_sign, library_sign, tmp_path):
    """Rompe: agregar una fila de 13 columnas a un archivo de 12 (CSV torcido) o perder las filas viejas."""
    rep = _reporte(cfg_sign, library_sign, tmp_path)
    viejas = [c for c in HISTORY_FIELDS if c != "huella"]
    fila = ["2026-01-01 10:00:00", "otro_video", "12", "0", "5", "5", "4", "1", "0", "0.8000",
            "0.2000", "1.0000"]
    hist = tmp_path / "viejo.csv"
    hist.write_text(",".join(viejas) + "\n" + ",".join(fila) + "\n" + ",".join(fila) + "\n", encoding="utf-8")
    append_history(hist, rep, huella="h1")
    filas = load_history(hist)
    assert len(filas) == 3 and list(filas[0]) == HISTORY_FIELDS
    assert [f["huella"] for f in filas] == ["", "", "h1"]
    assert filas[0]["exactitud"] == "0.8000" and filas[1]["fecha"] == "2026-01-01 10:00:00"
    with hist.open(encoding="utf-8") as fh:
        assert {len(r) for r in csv.reader(fh)} == {len(HISTORY_FIELDS)}


def test_append_history_en_un_archivo_nuevo_escribe_la_cabecera_con_huella(cfg_sign, library_sign, tmp_path):
    rep = _reporte(cfg_sign, library_sign, tmp_path)
    hist = tmp_path / "n.csv"
    append_history(hist, rep, huella="x")
    append_history(hist, rep, huella="y")
    assert hist.read_text(encoding="utf-8").splitlines()[0].split(",") == HISTORY_FIELDS
    assert [f["huella"] for f in load_history(hist)] == ["x", "y"]


# ==========================================================================
# la huella en el historial y teach status
# ==========================================================================
def _ultima_fila(p):
    return load_history(p["run"] / "out" / "teach_history.csv")[-1]


def _fechar_biblioteca(p, delta):
    t = time.time() + delta
    for f in p["lib"].glob("*.png"):
        os.utime(f, (t, t))


def test_test_eval_guarda_la_huella_de_la_biblioteca_en_el_historial(p):
    """Rompe: que eval no pase la huella a append_history (la columna quedaria vacia)."""
    entrenar(p)
    teach(p, "test", "eval", "r1")
    assert _ultima_fila(p)["huella"] == L.fingerprint(p["lib"]) != ""


def test_status_juzga_la_evaluacion_por_la_huella_no_por_la_fecha(p, capsys):
    """Rompe: volver a comparar fechas (tocar las plantillas sin cambiarlas no invalida la evaluacion)."""
    entrenar(p)
    teach(p, "test", "eval", "r1")
    _fechar_biblioteca(p, +3600)               # por fecha parecerian nuevas
    capsys.readouterr()
    assert teach(p, "status") == 0
    assert "no se evaluo con la biblioteca vigente" not in capsys.readouterr().out


def test_status_pide_evaluar_si_cambia_la_biblioteca_tras_la_evaluacion(p, capsys):
    entrenar(p)
    teach(p, "test", "eval", "r1")
    teach(p, "lib", "delete", "0_0")
    _fechar_biblioteca(p, -7200)               # y por fecha parecerian viejas: manda la huella
    capsys.readouterr()
    assert teach(p, "status") == 0
    assert "la prueba de r1 no se evaluo con la biblioteca vigente" in capsys.readouterr().out


def test_status_con_un_historial_viejo_sin_huella_se_juzga_por_fecha(p, capsys):
    entrenar(p)
    _fechar_biblioteca(p, -7200)
    hist = p["run"] / "out" / "teach_history.csv"
    hist.parent.mkdir(parents=True, exist_ok=True)
    viejas = [c for c in HISTORY_FIELDS if c != "huella"]
    fila = [time.strftime("%Y-%m-%d %H:%M:%S"), "misma_corrida", "12", "8", "2", "2", "2", "0", "0",
            "1.0000", "0.0000", "1.0000"]
    hist.write_text(",".join(viejas) + "\n" + ",".join(fila) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert teach(p, "status") == 0
    assert "no se evaluo" not in capsys.readouterr().out         # evaluada despues de la biblioteca
    _fechar_biblioteca(p, +7200)                                  # ahora la biblioteca es mas nueva
    assert teach(p, "status") == 0
    assert "no se evaluo con la biblioteca vigente" in capsys.readouterr().out


# ==========================================================================
# lib restore cuenta como cambio; mensajes sin respaldo
# ==========================================================================
def test_lib_restore_deja_las_plantillas_con_fecha_nueva(p):
    """Rompe: restaurar con copy2 (conserva la fecha vieja y las salidas viejas parecerian al dia por fecha)."""
    entrenar(p)
    _fechar_biblioteca(p, -3600)
    teach(p, "lib", "delete", "0_0")                        # el respaldo conserva fechas viejas (copy2)
    out = p["run"] / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "readings.csv").write_text("archivo\n", encoding="utf-8")
    t = time.time() - 600
    os.utime(out / "readings.csv", (t, t))                  # lectura de hace 10 min, sin read_meta
    assert teach(p, "lib", "restore") == 0
    restauradas = [f.stat().st_mtime for f in p["lib"].glob("*.png")]
    assert restauradas and min(restauradas) > time.time() - 120
    assert outputs_state(out / "readings.csv", p["lib"]) == DESACTUALIZADAS


@pytest.mark.parametrize("verbo", [["lib", "delete", "0_0"], ["lib", "relabel", "0_0", "5"]])
def test_delete_y_relabel_sin_respaldo_nuevo_lo_dicen(p, capsys, monkeypatch, verbo):
    """No se muestra un respaldo viejo como si fuera de esta operacion."""
    entrenar(p)
    teach(p, "lib", "delete", "1_0")                        # deja un respaldo previo
    previo = L.list_backups(p["lib"])
    monkeypatch.setattr(L, "backup", lambda *a, **k: None)
    capsys.readouterr()
    assert teach(p, *verbo) == 0
    salida = capsys.readouterr().out
    assert "no hubo nada que respaldar" in salida and previo[-1] not in salida


def test_lib_clear_sobre_una_biblioteca_vacia_dice_que_no_habia_nada_que_respaldar(p, capsys):
    assert teach(p, "lib", "clear", "--yes") == 0
    assert "no hubo nada que respaldar" in capsys.readouterr().out


def test_delete_con_respaldo_nombra_el_respaldo_de_esta_operacion(p, capsys):
    entrenar(p)
    teach(p, "lib", "delete", "1_0")
    capsys.readouterr()
    teach(p, "lib", "delete", "2_0")
    salida = capsys.readouterr().out
    assert L.list_backups(p["lib"])[-1] in salida and "no hubo nada" not in salida


# ==========================================================================
# load_run_input: qc re-corrido sin read
# ==========================================================================
def test_qc_re_corrido_sin_read_no_infla_las_lecturas_ok(tmp_path):
    """Rompe: contar `ok` desde la columna estado de qc_report.csv (si se re-corrio qc, no dice nada de read)."""
    run = RunPaths.for_run("x", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    estados = ["ok", "ok", "ok", "ok", "dark"]
    write_qc_report([QCRow(f"t_{i}.jpg", float(i), i + 1, estado=e) for i, e in enumerate(estados)],
                    run.qc_report)
    write_readings([Reading("t_0.jpg", 0.0, 1, 0.1, 0.9, "0.100"),
                    Reading("t_1.jpg", 1.0, 2, estado="low_confidence")], run.readings)
    entrada = load_run_input(run, CalibPaths.at(tmp_path / "calib"), [], evaluar=False)
    assert entrada.estados == ["ok", "low_confidence", "sin_leer", "sin_leer", "dark"]
    (fila,) = batch_summary([entrada])
    assert (fila.ok, fila.low_confidence, fila.qc["dark"]) == (1, 1, 1)
    assert fila.cobertura == pytest.approx(1 / 5)


def test_los_descartes_de_qc_se_cuentan_aunque_no_haya_lectura(tmp_path):
    run = RunPaths.for_run("x", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    write_qc_report([QCRow("a.jpg", 0.0, 1, estado="roi_fuera"), QCRow("b.jpg", 1.0, 2, estado="blur")],
                    run.qc_report)
    write_readings([], run.readings)
    (fila,) = batch_summary([load_run_input(run, CalibPaths.at(tmp_path / "calib"), [], evaluar=False)])
    assert (fila.qc["roi_fuera"], fila.qc["blur"], fila.ok) == (1, 1, 0)


# ==========================================================================
# batch: umbrales validados antes de procesar
# ==========================================================================
@pytest.mark.parametrize("flag", ["--min-exactitud", "--max-error", "--min-cobertura"])
def test_batch_valida_los_umbrales_antes_de_tocar_ningun_video(lote, monkeypatch, capsys, flag):  # noqa: F811
    """Rompe: validar al final (un flag mal tipeado costaria todo el lote)."""
    llamadas = []
    monkeypatch.setattr("spectro.extract.extract_frames", lambda *a, **k: llamadas.append(a))
    assert main(lote["glob"] + ["batch", lote["video"], flag, "95"]) == 1
    captura = capsys.readouterr()
    assert flag in captura.err and llamadas == []
    assert not lote["runs"].exists() and "== batch ==" not in captura.out


def test_batch_con_umbral_malo_y_sin_videos_falla_por_el_umbral(lote, capsys):  # noqa: F811
    assert main(lote["glob"] + ["batch", "nada*.mov", "--min-cobertura", "2"]) == 1
    assert "--min-cobertura" in capsys.readouterr().err


def test_batch_con_umbrales_validos_y_sin_videos_sigue_devolviendo_2(lote):  # noqa: F811
    assert main(lote["glob"] + ["batch", "nada*.mov", "--min-cobertura", "0.5"]) == 2
