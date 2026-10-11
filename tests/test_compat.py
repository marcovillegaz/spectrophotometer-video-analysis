"""Compatibilidad con los nombres en espanol (Fase 3.5).

Los lectores aceptan encabezados, estados y claves viejos; los escritores emiten solo los
nuevos; los flags viejos fallan con la tabla de migracion. Los archivos viejos de estos tests
se escriben a mano (el formato de antes), nunca con los escritores actuales.

Cada test dice en su docstring que rompe. La mutacion se hizo vaciando el mapa de alias
(``compat.HEADER_ALIASES`` / ``VALUE_ALIASES`` / ``CONFIG_KEY_ALIASES`` / ``LEGACY_FLAGS``) o
parcheando el lector/escritor correspondiente; ver el informe del agente.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime

import pytest

from conftest import make_config
from spectro import compat
from spectro import teach as T
from spectro.cli import main
from spectro.config import Config
from spectro.evaluation import (
    HISTORY_FIELDS,
    TestReport,
    append_history,
    load_history,
    write_test_report,
)
from spectro.extract import FrameRow, load_frames_index, write_frames_index
from spectro.project import RunPaths
from spectro.qc import QCRow, load_qc_report, write_qc_report
from spectro.read import Reading, load_read_meta, load_readings, write_read_meta, write_readings
from spectro.report import (
    BATCH_REPORT_FIELDS,
    RunInput,
    batch_summary,
    run_report,
    write_batch_report,
)
from spectro.teach_cli import MIGRATION, legacy_error


def _escribir(path, texto):
    path.write_text(texto, encoding="utf-8", newline="")
    return path


def _encabezado(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


# ==========================================================================
# compat: las funciones puras
# ==========================================================================
def test_normalize_row_traduce_encabezados_y_estados_viejos():
    """Rompe: vaciar HEADER_ALIASES o VALUE_ALIASES."""
    fila = compat.normalize_row({"archivo": "a.jpg", "estado": "roi_fuera", "confianza": "0.9"})
    assert fila == {"file": "a.jpg", "status": "roi_outside", "confidence": "0.9"}


def test_un_alias_recortado_ya_no_se_traduce():
    """Documenta que solo quedan alias de archivos que se leen. Rompe: reponer ``resultado``/``veredicto``/``revisar``."""
    fila = {"archivo": "a.jpg", "resultado": "correcta", "veredicto": "revisar", "estado": "revisar"}
    assert compat.normalize_row(dict(fila)) == {
        "file": "a.jpg", "resultado": "correcta", "veredicto": "revisar", "status": "revisar"}
    assert compat.normalize_status("revisar") == "revisar"


def test_normalize_row_no_toca_los_nombres_nuevos_ni_inventa_columnas():
    """Rompe: traducir de mas (p. ej. quitar el ``get`` con default) o perder columnas desconocidas."""
    fila = {"file": "a.jpg", "status": "roi_outside", "extra": "x"}
    assert compat.normalize_row(dict(fila)) == fila


def test_los_valores_solo_se_traducen_en_las_columnas_de_estado():
    """Rompe: traducir valores en cualquier columna (un archivo llamado ``roi_fuera`` no es un estado)."""
    fila = compat.normalize_row({"archivo": "roi_fuera", "valor": "misma_corrida", "estado": "misma_corrida"})
    assert fila == {"file": "roi_fuera", "value": "misma_corrida", "status": "same_run"}


def test_normalize_status_deja_pasar_lo_desconocido():
    """Rompe: levantar KeyError con un estado que no esta en el mapa."""
    assert compat.normalize_status("dark") == "dark"
    assert compat.normalize_status("roi_fuera") == "roi_outside"


def test_normalize_config_traduce_acceptance_sin_mutar_la_entrada():
    """Rompe: vaciar CONFIG_KEY_ALIASES, o mutar el dict de entrada."""
    data = {"acceptance": {"min_exactitud": 0.9, "max_error": 0.1, "min_cobertura": 0.8}}
    nuevo = compat.normalize_config(data)
    assert nuevo["acceptance"] == {"min_accuracy": 0.9, "max_error": 0.1, "min_coverage": 0.8}
    assert data["acceptance"]["min_exactitud"] == 0.9


@pytest.mark.parametrize("data", [{}, {"acceptance": None}, {"acceptance": "x"}])
def test_normalize_config_sin_acceptance_valido_no_rompe(data):
    """Rompe: asumir que ``acceptance`` siempre es un dict."""
    assert compat.normalize_config(data) == data


def test_el_mapa_de_alias_no_tiene_destinos_repetidos_ni_ciclos():
    """Rompe: un alias que apunte a otro alias (la traduccion dependeria del orden)."""
    viejos = set(compat.HEADER_ALIASES)
    assert not viejos & set(compat.HEADER_ALIASES.values())
    assert not set(compat.VALUE_ALIASES) & set(compat.VALUE_ALIASES.values())
    assert len(set(compat.HEADER_ALIASES.values())) == len(compat.HEADER_ALIASES)


# ==========================================================================
# Lectores: archivos viejos siguen cargando
# ==========================================================================
def test_truth_csv_y_test_csv_viejos_cargan(tmp_path):
    """Rompe: ``load_truth`` leyendo ``r['archivo']``/``r['valor']`` directo, o sin alias."""
    viejo = _escribir(tmp_path / "truth.csv", "archivo,valor\nt_0000001.000.jpg,-0.245\nt_0000002.000.jpg,0.100\n")
    assert [(s.file, s.value) for s in T.load_truth(viejo)] == [
        ("t_0000001.000.jpg", "-0.245"), ("t_0000002.000.jpg", "0.100")]


def test_load_truth_nuevo_y_viejo_dan_lo_mismo(tmp_path):
    """Rompe: que el formato nuevo y el viejo se lean distinto."""
    viejo = _escribir(tmp_path / "v.csv", "archivo,valor\na.jpg,1.5\n")
    nuevo = _escribir(tmp_path / "n.csv", "file,value\na.jpg,1.5\n")
    assert T.load_truth(viejo) == T.load_truth(nuevo)


def test_qc_report_viejo_con_roi_fuera_carga_como_roi_outside(tmp_path):
    """Rompe: no traducir el estado ``roi_fuera`` (read lo trataria como un estado desconocido)."""
    viejo = _escribir(tmp_path / "qc_report.csv", (
        "archivo,t_s,indice,mean_luma,p05,p95,contraste,blur_var,ink_fraction,anchor_ncc,dx,dy,estado\n"
        "t_0000001.000.jpg,1.000,1,100,10,200,190,50,0.2,0.99,1,-2,ok\n"
        "t_0000002.000.jpg,2.000,2,100,10,200,190,50,0.2,0.99,0,0,roi_fuera\n"))
    filas = load_qc_report(viejo)
    assert [r.status for r in filas] == ["ok", "roi_outside"]
    assert (filas[0].file, filas[0].index, filas[0].contrast, filas[0].dx, filas[0].dy) == (
        "t_0000001.000.jpg", 1, 190.0, 1, -2)


def test_qc_report_viejo_sin_dx_dy_carga_con_cero(tmp_path):
    """Rompe: exigir ``dx``/``dy`` (los qc_report mas viejos no los tienen)."""
    viejo = _escribir(tmp_path / "qc.csv", (
        "archivo,t_s,indice,mean_luma,p05,p95,contraste,blur_var,ink_fraction,anchor_ncc,estado\n"
        "a.jpg,1.0,1,1,1,1,1,1,1,1,ok\n"))
    (fila,) = load_qc_report(viejo)
    assert (fila.dx, fila.dy, fila.status) == (0, 0, "ok")


def test_readings_viejo_carga_con_todos_sus_campos(tmp_path):
    """Rompe: cualquier encabezado viejo (``confianza``, ``caracteres``, ``estado``...) sin traducir."""
    viejo = _escribir(tmp_path / "readings.csv", (
        "archivo,t_s,indice,valor,confianza,margen,caracteres,dx,dy,estado\n"
        "a.jpg,1.000,1,-0.245,0.9100,0.2500,-0.245,1,2,ok\n"
        "b.jpg,2.000,2,,0.1000,0.0000,,0,0,roi_fuera\n"))
    ok, fuera = load_readings(viejo)
    assert (ok.value, ok.confidence, ok.margin, ok.chars, ok.dx, ok.dy, ok.status) == (
        -0.245, 0.91, 0.25, "-0.245", 1, 2, "ok")
    assert fuera.value is None and fuera.status == "roi_outside"


def test_readings_viejo_sin_margen_da_cero(tmp_path):
    """Rompe: exigir la columna ``margen`` (los readings anteriores a la Fase 1 no la traen)."""
    viejo = _escribir(tmp_path / "r.csv", (
        "archivo,t_s,indice,valor,confianza,caracteres,dx,dy,estado\n"
        "a.jpg,1.000,1,0.5,0.9000, 0.500,0,0,ok\n"))
    assert load_readings(viejo)[0].margin == 0.0


def test_frames_index_viejo_carga(tmp_path):
    """Rompe: ``load_frames_index`` leyendo ``r['archivo']`` / ``r['indice']``."""
    viejo = _escribir(tmp_path / "frames_index.csv", "archivo,t_s,indice\nt_0000001.000.jpg,1.000,1\nt_0000002.000.jpg,2.000,2\n")
    assert load_frames_index(viejo) == [
        FrameRow("t_0000001.000.jpg", 1.0, 1), FrameRow("t_0000002.000.jpg", 2.0, 2)]


def test_read_meta_viejo_con_huella_carga_como_fingerprint(tmp_path):
    """Rompe: ``normalize_keys`` en ``load_read_meta`` (``outputs_state`` marcaria todo ``stale``)."""
    viejo = _escribir(tmp_path / "read_meta.json", json.dumps(
        {"huella": "abc123def456", "fecha": "2026-01-01 10:00:00", "plantillas": 12}))
    meta = load_read_meta(viejo)
    assert meta == {"fingerprint": "abc123def456", "date": "2026-01-01 10:00:00", "templates": 12}


def test_read_meta_ilegible_o_que_no_es_un_dict_da_none(tmp_path):
    """Rompe: dejar pasar una lista JSON o una excepcion de parseo."""
    assert load_read_meta(_escribir(tmp_path / "a.json", "[1, 2]")) is None
    assert load_read_meta(_escribir(tmp_path / "b.json", "{no es json")) is None
    assert load_read_meta(tmp_path / "no_existe.json") is None


def test_config_json_viejo_con_acceptance_en_espanol_carga(tmp_path):
    """Rompe: ``Config.load`` sin ``normalize_config`` (las claves viejas se perderian o romperian)."""
    cfg = make_config()
    ruta = tmp_path / "config.json"
    cfg.save(ruta)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["acceptance"] = {"min_exactitud": 0.95, "max_error": 0.02, "min_cobertura": 0.9}
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    acc = Config.load(ruta).acceptance
    assert (acc.min_accuracy, acc.max_error, acc.min_coverage) == (0.95, 0.02, 0.9)


def test_config_json_sin_acceptance_carga_con_umbrales_sin_fijar(tmp_path):
    """Rompe: que un config anterior a ``acceptance`` falle o invente umbrales."""
    ruta = tmp_path / "config.json"
    make_config().save(ruta)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.pop("acceptance", None)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert not Config.load(ruta).acceptance.is_set()


def test_config_guardada_emite_solo_las_claves_nuevas(tmp_path):
    """Rompe: que ``save`` escriba ``min_exactitud``/``min_cobertura``."""
    ruta = tmp_path / "config.json"
    cfg = make_config()
    cfg.acceptance.min_accuracy = 0.9
    cfg.acceptance.min_coverage = 0.8
    cfg.save(ruta)
    acc = json.loads(ruta.read_text(encoding="utf-8"))["acceptance"]
    assert set(acc) == {"min_accuracy", "max_error", "min_coverage"}
    assert acc["min_accuracy"] == 0.9 and acc["min_coverage"] == 0.8


def test_config_vieja_y_guardada_de_nuevo_queda_con_claves_nuevas(tmp_path):
    """Rompe: que cargar y guardar conserve las claves viejas (migracion al guardar por su cuenta)."""
    ruta = tmp_path / "config.json"
    make_config().save(ruta)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["acceptance"] = {"min_exactitud": 0.7}
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    Config.load(ruta).save(ruta)
    acc = json.loads(ruta.read_text(encoding="utf-8"))["acceptance"]
    assert "min_exactitud" not in acc and acc["min_accuracy"] == 0.7


# ==========================================================================
# Historial: append_history reescribe el viejo con el encabezado nuevo
# ==========================================================================
HISTORIAL_VIEJO = (
    "fecha,tipo,plantillas,entrenamiento,prueba,valores_distintos,correctas,erroneas,descartadas,"
    "exactitud,error_aceptadas,cobertura\n"
    "2026-01-01 10:00:00,misma_corrida,12,30,5,4,4,0,1,1.0000,0.0000,0.8000\n"
    "2026-01-02 10:00:00,otro_video,12,30,6,5,5,1,0,0.8333,0.1667,1.0000\n"
)


def _informe():
    return TestReport(kind="other_video", n_train=30, n_templates=12)


def test_append_history_reescribe_un_historial_viejo_con_el_encabezado_nuevo(tmp_path):
    """Rompe: agregar la fila nueva sin migrar (CSV con dos encabezados distintos) o perder filas."""
    ruta = _escribir(tmp_path / "teach_history.csv", HISTORIAL_VIEJO)
    append_history(ruta, _informe(), when=datetime(2026, 2, 1, 9, 0, 0), fingerprint="ffee")
    assert _encabezado(ruta) == HISTORY_FIELDS
    filas = load_history(ruta)
    assert len(filas) == 3
    assert [f["date"] for f in filas] == ["2026-01-01 10:00:00", "2026-01-02 10:00:00", "2026-02-01 09:00:00"]
    assert [f["kind"] for f in filas[:2]] == ["same_run", "other_video"]
    assert filas[0]["accuracy"] == "1.0000" and filas[1]["accepted_error"] == "0.1667"
    assert [f["fingerprint"] for f in filas] == ["", "", "ffee"]


def test_append_history_viejo_no_deja_columnas_en_espanol(tmp_path):
    """Rompe: dejar el encabezado viejo (``exactitud``...) en el archivo."""
    ruta = _escribir(tmp_path / "h.csv", HISTORIAL_VIEJO)
    append_history(ruta, _informe())
    assert not set(_encabezado(ruta)) & set(compat.HEADER_ALIASES)


def test_append_history_es_idempotente_sobre_un_historial_ya_migrado(tmp_path):
    """Rompe: reescribir (y duplicar o perder filas) un historial que ya tiene el encabezado nuevo."""
    ruta = _escribir(tmp_path / "h.csv", HISTORIAL_VIEJO)
    append_history(ruta, _informe(), when=datetime(2026, 2, 1))
    tras_uno = ruta.read_text(encoding="utf-8")
    append_history(ruta, _informe(), when=datetime(2026, 2, 2))
    assert len(load_history(ruta)) == 4
    assert ruta.read_text(encoding="utf-8").startswith(tras_uno.rstrip("\n"))
    assert ruta.read_text(encoding="utf-8").count("date,kind") == 1


def test_append_history_en_archivo_nuevo_escribe_solo_el_encabezado_nuevo(tmp_path):
    """Rompe: que el historial nuevo nazca con el encabezado en espanol."""
    ruta = tmp_path / "h.csv"
    append_history(ruta, _informe())
    assert _encabezado(ruta) == HISTORY_FIELDS
    assert len(load_history(ruta)) == 1


def test_history_fields_son_todos_nombres_nuevos():
    """Rompe: dejar un nombre viejo en HISTORY_FIELDS."""
    assert not set(HISTORY_FIELDS) & set(compat.HEADER_ALIASES)
    assert "fingerprint" in HISTORY_FIELDS


# ==========================================================================
# absorbance.csv vs absorbancia.csv
# ==========================================================================
def test_existing_absorbance_usa_el_viejo_si_falta_el_nuevo(tmp_path):
    """Rompe: ``existing_absorbance`` apuntando siempre a ``absorbance.csv``."""
    run = RunPaths.for_run("r1", base=tmp_path).create()
    _escribir(run.legacy_absorbance, "t_s,absorbancia\n")
    assert run.existing_absorbance == run.legacy_absorbance
    assert run.is_done()


def test_existing_absorbance_prefiere_el_nuevo_si_estan_los_dos(tmp_path):
    """Rompe: preferir el viejo cuando existe el nuevo (se leeria una salida desactualizada)."""
    run = RunPaths.for_run("r1", base=tmp_path).create()
    _escribir(run.legacy_absorbance, "viejo\n")
    _escribir(run.absorbance, "nuevo\n")
    assert run.existing_absorbance == run.absorbance


def test_sin_ninguna_salida_la_corrida_no_esta_hecha_y_apunta_al_nuevo(tmp_path):
    """Rompe: que ``is_done`` sea verdadero sin entregable, o que apunte al nombre viejo."""
    run = RunPaths.for_run("r1", base=tmp_path).create()
    assert not run.is_done()
    assert run.existing_absorbance == run.absorbance
    assert run.absorbance.name == "absorbance.csv" and run.legacy_absorbance.name == "absorbancia.csv"


def test_report_nunca_borra_ni_renombra_el_absorbancia_viejo(tmp_path):
    """Rompe: que ``run_report`` borre, renombre o pise ``absorbancia.csv`` al escribir el nuevo."""
    out = tmp_path / "out"
    out.mkdir()
    viejo = _escribir(out / "absorbancia.csv", "t_s,absorbancia\n0.000,0.245\n")
    contenido = viejo.read_bytes()
    write_readings([Reading("t_0000000.000.jpg", 0.0, 1, 0.245, 0.99, "0.245")], tmp_path / "readings.csv")
    write_qc_report([QCRow("t_0000000.000.jpg", 0.0, 1)], tmp_path / "qc_report.csv")
    n = run_report(make_config(), tmp_path / "readings.csv", tmp_path / "qc_report.csv",
                   tmp_path / "frames", out, no_plots=True, verbose=False)
    assert n == 1
    assert viejo.exists() and viejo.read_bytes() == contenido
    assert (out / "absorbance.csv").exists()
    assert _encabezado(out / "absorbance.csv")[3] == "absorbance"


# ==========================================================================
# Los escritores emiten solo nombres nuevos
# ==========================================================================
def _sin_alias(encabezado):
    return not set(encabezado) & set(compat.HEADER_ALIASES)


def test_save_truth_emite_file_value(tmp_path):
    """Rompe: ``save_truth`` con ``archivo,valor``."""
    ruta = T.save_truth(tmp_path / "truth.csv", [T.Sample("a.jpg", "1.5")])
    assert _encabezado(ruta) == ["file", "value"]


def test_write_readings_emite_solo_nombres_nuevos(tmp_path):
    """Rompe: cualquier columna vieja en ``readings.csv``."""
    ruta = write_readings([Reading("a.jpg", 1.0, 1, 0.5, 0.9, "0.500", margin=0.2)], tmp_path / "r.csv")
    cab = _encabezado(ruta)
    assert _sin_alias(cab)
    assert cab == ["file", "t_s", "index", "value", "confidence", "margin", "chars", "dx", "dy", "status"]


def test_write_qc_report_emite_solo_nombres_nuevos_y_el_estado_nuevo(tmp_path):
    """Rompe: ``contraste``/``estado`` en el reporte, o el estado ``roi_fuera`` en el valor."""
    ruta = write_qc_report([QCRow("a.jpg", 1.0, 1, status="roi_outside")], tmp_path / "qc.csv")
    assert _sin_alias(_encabezado(ruta))
    assert "contrast" in _encabezado(ruta) and "status" in _encabezado(ruta)
    assert "roi_outside" in ruta.read_text(encoding="utf-8")
    assert "roi_fuera" not in ruta.read_text(encoding="utf-8")


def test_write_frames_index_emite_solo_nombres_nuevos(tmp_path):
    """Rompe: ``archivo,t_s,indice`` en ``frames_index.csv``."""
    ruta = write_frames_index([FrameRow("a.jpg", 1.0, 1)], tmp_path / "frames_index.csv")
    assert _encabezado(ruta) == ["file", "t_s", "index"]


def test_write_read_meta_emite_fingerprint_date_templates(tmp_path):
    """Rompe: ``huella``/``fecha``/``plantillas`` como claves del JSON."""
    (tmp_path / "templates").mkdir()
    ruta = write_read_meta(tmp_path / "read_meta.json", tmp_path / "templates", 0)
    assert set(json.loads(ruta.read_text(encoding="utf-8"))) == {"fingerprint", "date", "templates"}


def test_write_test_report_emite_solo_nombres_nuevos(tmp_path):
    """Rompe: ``escrito``/``leido``/``resultado`` en ``test_report.csv``."""
    ruta = write_test_report(_informe(), tmp_path / "t.csv")
    assert _encabezado(ruta) == ["file", "typed", "read_value", "status", "confidence", "result"]


def test_write_batch_report_emite_solo_nombres_nuevos(tmp_path):
    """Rompe: columnas o estados viejos en ``batch_report.csv``."""
    fila = RunInput("r", ["ok", "roi_outside"], True, None, templates=3, fingerprint="abc", outputs="up_to_date")
    ruta = write_batch_report(batch_summary([fila]), tmp_path / "b.csv")
    assert _encabezado(ruta) == BATCH_REPORT_FIELDS
    assert _sin_alias(BATCH_REPORT_FIELDS)
    texto = ruta.read_text(encoding="utf-8")
    assert "up_to_date" in texto and "al_dia" not in texto


def test_write_absorbance_csv_emite_absorbance_y_no_absorbancia(tmp_path):
    """Rompe: la columna ``absorbancia`` en la salida final."""
    from spectro.report import write_absorbance_csv

    ruta = tmp_path / "absorbance.csv"
    write_absorbance_csv([Reading("a.jpg", 0.0, 1, 0.245, 0.99, "0.245")], make_config(), ruta)
    cab = _encabezado(ruta)
    assert "absorbance" in cab and "absorbancia" not in cab and "frame" in cab


def test_un_archivo_viejo_leido_y_reescrito_sale_con_nombres_nuevos(tmp_path):
    """Rompe: que leer un ``readings.csv`` viejo y volver a escribirlo conserve el formato viejo."""
    viejo = _escribir(tmp_path / "v.csv", (
        "archivo,t_s,indice,valor,confianza,caracteres,dx,dy,estado\n"
        "a.jpg,1.000,1,0.5,0.9000, 0.500,0,0,ok\n"))
    nuevo = write_readings(load_readings(viejo), tmp_path / "n.csv")
    assert _sin_alias(_encabezado(nuevo))
    assert load_readings(nuevo)[0].value == 0.5


# ==========================================================================
# Flags viejos: rc 2 y tabla de migracion
# ==========================================================================
@pytest.fixture
def glob(tmp_path):
    return ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]


@pytest.mark.parametrize("flag", ["--min-exactitud", "--min-cobertura"])
def test_legacy_error_reconoce_los_flags_renombrados_en_cualquier_subcomando(flag):
    """Rompe: vaciar LEGACY_FLAGS o limitar la deteccion a ``teach``."""
    for argv in (["batch", "v.mov", flag, "0.9"], ["teach", "test", "eval", flag, "0.9"],
                 ["batch", f"{flag}=0.9"], ["--runs-dir", "x", "teach", "test", "eval", flag, "0.9"]):
        assert legacy_error(argv) == MIGRATION


@pytest.mark.parametrize("flag", ["--min-accuracy", "--min-coverage", "--max-error"])
def test_legacy_error_no_toca_los_flags_nuevos(flag):
    """Rompe: marcar como viejos los flags nuevos (prefijo comun con los viejos)."""
    assert legacy_error(["batch", "v.mov", flag, "0.9"]) is None
    assert legacy_error(["teach", "test", "eval", flag, "0.9"]) is None


@pytest.mark.parametrize("flag, nuevo", [("--min-exactitud", "--min-accuracy"), ("--min-cobertura", "--min-coverage")])
def test_la_tabla_de_migracion_nombra_cada_flag_renombrado(flag, nuevo):
    """Rompe: omitir un flag de la tabla de migracion."""
    assert flag in MIGRATION and nuevo in MIGRATION
    assert compat.LEGACY_FLAGS[flag] == nuevo


@pytest.mark.parametrize("flag", ["--min-exactitud", "--min-cobertura"])
def test_batch_con_flag_viejo_sale_con_2_y_muestra_la_tabla(glob, capsys, flag):
    """Rompe: dejar que argparse acepte/ignore el flag viejo, o devolver 1 en vez de 2."""
    assert main(glob + ["batch", "no_importa.mov", flag, "0.9"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and "antes" in err and "ahora" in err
    assert flag in err and compat.LEGACY_FLAGS[flag] in err


@pytest.mark.parametrize("flag", ["--min-exactitud", "--min-cobertura"])
def test_teach_test_eval_con_flag_viejo_sale_con_2(glob, capsys, flag):
    """Rompe: que ``teach test eval`` acepte el flag viejo."""
    assert main(glob + ["teach", "test", "eval", "r1", flag, "0.9"]) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_flag_viejo_con_igual_tambien_falla(glob, capsys):
    """Rompe: comparar el token entero (``--min-exactitud=0.9``) en vez de lo que va antes del ``=``."""
    assert main(glob + ["batch", "v.mov", "--min-exactitud=0.9"]) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_flag_viejo_no_toca_el_disco(glob, tmp_path):
    """Rompe: crear carpetas o corridas antes de rechazar el flag viejo."""
    main(glob + ["batch", "v.mov", "--min-exactitud", "0.9"])
    assert not (tmp_path / "runs").exists() and not (tmp_path / "calib").exists()


def test_flag_nuevo_no_dispara_el_error_de_migracion(glob, capsys):
    """Rompe: detectar mal los flags nuevos; llega al batch (que dice que no hay videos), no a la tabla."""
    main(glob + ["batch", "no_existe.mov", "--min-accuracy", "0.9"])
    captura = capsys.readouterr()
    assert "No hay videos" in captura.out
    assert "antes" not in captura.err and "ERROR" not in captura.err


# ==========================================================================
# Glosario: no quedan nombres en espanol en la interfaz publica
# ==========================================================================
GLOSARIO = {
    "archivo", "valor", "indice", "estado", "confianza", "margen", "caracteres", "contraste",
    "absorbancia", "huella", "exactitud", "cobertura", "umbral", "respaldo", "respaldar",
    "min_exactitud", "min_cobertura", "veredicto", "motivo", "corrida", "fotogramas",
}


def _nombres_de_la_interfaz():
    """(modulo, nombre) de funciones publicas, sus parametros, y campos de dataclass/atributos de clase."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src" / "spectro"
    for py in sorted(src.glob("*.py")):
        arbol = ast.parse(py.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and not nodo.name.startswith("_"):
                yield py.name, nodo.name
                a = nodo.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                    yield py.name, f"{nodo.name}({arg.arg})"
            elif isinstance(nodo, ast.ClassDef):
                yield py.name, nodo.name
                for cuerpo in nodo.body:
                    if isinstance(cuerpo, ast.AnnAssign) and isinstance(cuerpo.target, ast.Name):
                        yield py.name, f"{nodo.name}.{cuerpo.target.id}"


def test_la_interfaz_publica_no_usa_nombres_del_glosario_en_espanol():
    """Rompe: renombrar de vuelta una funcion, parametro o campo de dataclass al espanol (ast, no grep)."""
    malos = []
    for modulo, nombre in _nombres_de_la_interfaz():
        partes = nombre.replace("(", ".").replace(")", "").split(".")
        if any(p in GLOSARIO for p in partes):
            malos.append(f"{modulo}: {nombre}")
    assert not malos, "nombres en espanol en la interfaz:\n" + "\n".join(malos)


def test_el_detector_de_nombres_ve_los_campos_y_parametros_que_existen():
    """Rompe: que el recorrido ast no vea nada (el test anterior pasaria vacio)."""
    nombres = {n for _, n in _nombres_de_la_interfaz()}
    assert "Reading.confidence" in nombres and "QCRow.status" in nombres
    assert "delete(backup)" in nombres or any(n.endswith("(backup)") for n in nombres)
    assert len(nombres) > 300
