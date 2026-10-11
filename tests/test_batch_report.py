"""Reporte de ``batch``: ``batch_summary``, el veredicto, ``resolve_acceptance`` y ``batch_report.csv``.

El veredicto (``acepta`` / ``revisar``) solo existe si el usuario fijo umbrales: el codigo
no inventa defaults. Sin dato (sin prueba, sin lectura) la corrida va a ``revisar``,
nunca a ``acepta``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from conftest import make_config, render_display
from spectro import teach as T
from spectro.cli import main
from spectro.config import AcceptanceConfig, Config
from spectro.extract import FrameRow, write_frames_index
from spectro.library import template_path
from spectro.project import calib_recipe, seed_run_config
from spectro.report import (
    BATCH_REPORT_FIELDS,
    QC_REASONS,
    RunInput,
    batch_summary,
    format_batch_table,
    resolve_acceptance,
    write_batch_report,
)


def prueba(n=10, exactitud=1.0, error=0.0, aceptadas=10, tipo="otro_video"):
    """Un duplo de ``TestReport``: lo unico que lee ``batch_summary``."""
    return SimpleNamespace(n=n, exactitud=exactitud, error_aceptadas=error, aceptadas=aceptadas, tipo=tipo)


def entrada(run_id="r", estados=None, leido=True, test=None, salidas="al_dia"):
    estados = ["ok"] * 10 if estados is None else estados
    return RunInput(run_id, estados, leido, test, plantillas=12, huella="abc123def456", salidas=salidas)


def una(e, **umbrales):
    (fila,) = batch_summary([e], AcceptanceConfig(**umbrales))
    return fila


# ==========================================================================
# AcceptanceConfig y resolve_acceptance
# ==========================================================================
def test_acceptance_sin_valores_no_esta_fijado():
    """Rompe: que AcceptanceConfig traiga defaults inventados (el plan prohibe inventar umbrales)."""
    a = AcceptanceConfig()
    assert (a.min_exactitud, a.max_error, a.min_cobertura) == (None, None, None)
    assert not a.is_set()
    assert not Config.default().acceptance.is_set()
    assert AcceptanceConfig(min_cobertura=0.0).is_set()      # cero es un umbral valido, no "vacio"


def test_el_flag_le_gana_a_calib_config():
    base = AcceptanceConfig(min_exactitud=0.9, max_error=0.05)
    acc = resolve_acceptance(base, min_exactitud=0.99)
    assert (acc.min_exactitud, acc.max_error, acc.min_cobertura) == (0.99, 0.05, None)


def test_sin_flags_quedan_los_umbrales_de_la_config_y_no_se_muta_la_base():
    base = AcceptanceConfig(min_cobertura=0.8)
    acc = resolve_acceptance(base)
    assert acc == base and acc is not base
    resolve_acceptance(base, min_cobertura=0.1)
    assert base.min_cobertura == 0.8


def test_un_flag_en_cero_gana_sobre_la_config():
    """Rompe: `if flag:` en vez de `if flag is not None:` (0.0 se tomaria como 'no dado')."""
    acc = resolve_acceptance(AcceptanceConfig(min_exactitud=0.9), min_exactitud=0.0)
    assert acc.min_exactitud == 0.0


@pytest.mark.parametrize("flag", ["min_exactitud", "max_error", "min_cobertura"])
@pytest.mark.parametrize("valor", [-0.01, 1.01, 95.0])
def test_umbrales_fuera_de_0_a_1_se_rechazan_con_el_nombre_del_flag(flag, valor):
    with pytest.raises(ValueError, match="fraccion"):
        resolve_acceptance(AcceptanceConfig(), **{flag: valor})


@pytest.mark.parametrize("valor", [0.0, 1.0])
def test_los_bordes_0_y_1_son_validos(valor):
    acc = resolve_acceptance(AcceptanceConfig(), min_exactitud=valor, max_error=valor, min_cobertura=valor)
    assert acc.min_exactitud == acc.max_error == acc.min_cobertura == valor


def test_acceptance_viaja_por_config_json(tmp_path):
    cfg = make_config()
    cfg.acceptance = AcceptanceConfig(min_exactitud=0.95, max_error=0.02)
    cfg.save(tmp_path / "c.json")
    otra = Config.load(tmp_path / "c.json")
    assert (otra.acceptance.min_exactitud, otra.acceptance.max_error, otra.acceptance.min_cobertura) == (
        0.95, 0.02, None)


def test_un_config_viejo_sin_acceptance_carga_sin_umbrales(tmp_path):
    """Compatibilidad: los config.json que ya existen no tienen la seccion."""
    import json

    d = make_config().to_dict()
    del d["acceptance"]
    (tmp_path / "viejo.json").write_text(json.dumps(d), encoding="utf-8")
    assert not Config.load(tmp_path / "viejo.json").acceptance.is_set()


# ==========================================================================
# batch_summary: conteos
# ==========================================================================
def test_cuenta_los_descartes_por_motivo_incluido_roi_fuera():
    """Rompe: dejar roi_fuera fuera de QC_REASONS (se perderia en silencio del reporte)."""
    assert "roi_fuera" in QC_REASONS
    estados = ["ok"] * 5 + ["dark", "dark", "blur", "roi_fuera", "roi_fuera", "roi_fuera", "low_confidence", "spike"]
    fila = una(entrada(estados=estados))
    assert fila.fotogramas == len(estados)
    assert fila.qc["dark"] == 2 and fila.qc["blur"] == 1 and fila.qc["roi_fuera"] == 3
    assert fila.descartados_qc == 6
    assert (fila.ok, fila.low_confidence, fila.spike) == (5, 1, 1)
    assert fila.cobertura == pytest.approx(5 / len(estados))


def test_todos_los_motivos_de_qc_aparecen_aunque_valgan_cero():
    fila = una(entrada(estados=["ok"]))
    assert set(fila.qc) == set(QC_REASONS) and fila.descartados_qc == 0


def test_corrida_sin_fotogramas_leida_tiene_cobertura_cero_sin_dividir_por_cero():
    fila = una(entrada(estados=[]))
    assert fila.fotogramas == 0 and fila.ok == 0 and fila.cobertura == 0.0


def test_corrida_sin_lectura_no_inventa_ceros():
    """Rompe: contar `ok = 0` y `cobertura = 0%` cuando todavia no hay readings.csv (no es lo mismo que mala)."""
    fila = una(entrada(estados=["dark", "ok"], leido=False))
    assert fila.ok is None and fila.low_confidence is None and fila.spike is None
    assert fila.cobertura is None
    assert fila.qc["dark"] == 1        # los descartes de qc si se conocen


def test_una_fila_por_corrida_en_el_orden_dado():
    filas = batch_summary([entrada("b"), entrada("a"), entrada("c")])
    assert [f.run_id for f in filas] == ["b", "a", "c"]
    assert batch_summary([]) == []


def test_la_prueba_se_resume_con_su_tipo_y_su_error():
    fila = una(entrada(test=prueba(n=20, exactitud=0.9, error=0.05, aceptadas=18, tipo="misma_corrida")))
    assert (fila.prueba, fila.tipo_prueba, fila.exactitud, fila.error_aceptadas) == (
        20, "misma_corrida", 0.9, 0.05)


def test_prueba_vacia_o_ausente_deja_los_campos_en_blanco():
    for t in (None, prueba(n=0)):
        fila = una(entrada(test=t))
        assert fila.prueba == 0 and fila.exactitud is None and fila.error_aceptadas is None
        assert fila.tipo_prueba == ""


def test_prueba_con_todo_descartado_no_tiene_error_entre_aceptadas():
    fila = una(entrada(test=prueba(n=5, exactitud=0.0, error=0.0, aceptadas=0)))
    assert fila.exactitud == 0.0 and fila.error_aceptadas is None


def test_el_resumen_lleva_plantillas_huella_y_estado_de_salidas():
    fila = una(entrada(salidas="desactualizadas"))
    assert (fila.plantillas, fila.huella, fila.salidas) == (12, "abc123def456", "desactualizadas")


# ==========================================================================
# batch_summary: veredicto
# ==========================================================================
def test_sin_umbrales_el_veredicto_queda_vacio_aunque_todo_este_mal():
    """Rompe: inventar un veredicto sin criterio fijado por el usuario."""
    malo = entrada(estados=["dark"] * 10, test=prueba(exactitud=0.1, error=0.9), salidas="desactualizadas")
    for acc in (None, AcceptanceConfig()):
        (fila,) = batch_summary([malo], acc)
        assert fila.veredicto == "" and fila.detalle == ""


def test_acepta_cuando_cumple_todos_los_umbrales():
    fila = una(entrada(test=prueba(exactitud=0.97, error=0.01)),
               min_exactitud=0.95, max_error=0.02, min_cobertura=0.9)
    assert fila.veredicto == "acepta" and fila.detalle == ""


def test_los_valores_justo_en_el_umbral_se_aceptan():
    """Rompe: comparar con < / > estrictos (un 95.0% con umbral 95% tiene que pasar)."""
    fila = una(entrada(estados=["ok"] * 9 + ["dark"], test=prueba(exactitud=0.95, error=0.02)),
               min_exactitud=0.95, max_error=0.02, min_cobertura=0.9)
    assert fila.veredicto == "acepta"


def test_exactitud_baja_manda_a_revisar_y_lo_explica():
    fila = una(entrada(test=prueba(exactitud=0.8, error=0.0)), min_exactitud=0.95)
    assert fila.veredicto == "revisar" and "exactitud 80.0% < 95.0%" in fila.detalle


def test_error_alto_manda_a_revisar_y_lo_explica():
    fila = una(entrada(test=prueba(exactitud=0.99, error=0.1)), max_error=0.02)
    assert fila.veredicto == "revisar" and "error 10.0% > 2.0%" in fila.detalle


def test_cobertura_baja_manda_a_revisar_y_lo_explica():
    fila = una(entrada(estados=["ok"] * 7 + ["dark"] * 3), min_cobertura=0.9)
    assert fila.veredicto == "revisar" and "cobertura 70.0% < 90.0%" in fila.detalle


def test_varias_razones_se_acumulan_en_el_detalle():
    fila = una(entrada(estados=["ok", "dark"], test=prueba(exactitud=0.5, error=0.5)),
               min_exactitud=0.9, max_error=0.1, min_cobertura=0.9)
    assert fila.detalle.count(";") == 2


@pytest.mark.parametrize("umbral", [{"min_exactitud": 0.9}, {"max_error": 0.05}])
def test_umbral_de_prueba_sin_prueba_manda_a_revisar(umbral):
    """Rompe: aceptar una corrida porque no hay nada que la contradiga (descartar antes que adivinar)."""
    fila = una(entrada(test=None), **umbral)
    assert fila.veredicto == "revisar" and "sin prueba que lo verifique" in fila.detalle


def test_con_solo_umbral_de_cobertura_la_falta_de_prueba_no_importa():
    fila = una(entrada(test=None), min_cobertura=0.5)
    assert fila.veredicto == "acepta"


def test_umbral_de_cobertura_sin_lectura_manda_a_revisar():
    fila = una(entrada(leido=False), min_cobertura=0.5)
    assert fila.veredicto == "revisar" and "sin lectura" in fila.detalle


def test_salidas_desactualizadas_van_a_revisar_aunque_cumplan_los_umbrales():
    """Rompe: ignorar que las lecturas son de una biblioteca anterior."""
    fila = una(entrada(salidas="desactualizadas"), min_cobertura=0.5)
    assert fila.veredicto == "revisar" and "anteriores a la biblioteca" in fila.detalle


@pytest.mark.parametrize("salidas", ["al_dia", ""])
def test_las_salidas_al_dia_no_bloquean_el_veredicto(salidas):
    assert una(entrada(salidas=salidas), min_cobertura=0.5).veredicto == "acepta"


@pytest.mark.parametrize("salidas, texto", [
    ("sin_huella", "sin huella"),
    ("sin_lectura", "no tiene readings.csv"),
])
def test_salidas_sin_huella_o_sin_lectura_van_a_revisar(salidas, texto):
    """Rompe: aceptar lecturas de las que no se sabe con que biblioteca salieron (o que no existen)."""
    fila = una(entrada(salidas=salidas), min_cobertura=0.5)
    assert fila.veredicto == "revisar" and texto in fila.detalle


def test_sin_umbrales_los_estados_de_salidas_no_inventan_veredicto():
    for salidas in ("sin_huella", "sin_lectura", "desactualizadas"):
        assert una(entrada(salidas=salidas)).veredicto == ""


def test_prueba_con_todo_descartado_y_umbral_de_error_manda_a_revisar():
    fila = una(entrada(test=prueba(n=5, exactitud=0.0, aceptadas=0)), max_error=0.05)
    assert fila.veredicto == "revisar"


# ==========================================================================
# tabla y CSV
# ==========================================================================
def test_la_tabla_tiene_cabecera_una_fila_por_corrida_y_columna_roi_fuera():
    filas = batch_summary([entrada("a", estados=["ok", "roi_fuera"]), entrada("b", leido=False)])
    lineas = format_batch_table(filas)
    assert len(lineas) == 3
    assert "roi_fuera" in lineas[0] and "veredicto" in lineas[0]
    fila_a = lineas[1].split()
    assert fila_a[0] == "a" and fila_a[1:4] == ["2", "1", "1"]       # fotogramas, descartes qc, roi_fuera
    assert "-" in lineas[2].split()                                   # sin lectura: guiones, no ceros


def test_la_tabla_muestra_el_veredicto_y_su_detalle():
    filas = batch_summary([entrada("a", estados=["ok", "dark"])], AcceptanceConfig(min_cobertura=0.9))
    assert "revisar (cobertura 50.0% < 90.0%)" in format_batch_table(filas)[1]


def test_batch_report_csv_tiene_las_columnas_documentadas(tmp_path):
    assert BATCH_REPORT_FIELDS[0] == "corrida" and "qc_roi_fuera" in BATCH_REPORT_FIELDS
    assert BATCH_REPORT_FIELDS[-2:] == ["veredicto", "detalle"]
    ruta = write_batch_report(batch_summary([entrada("a", estados=["ok", "roi_fuera", "dark"],
                                                     test=prueba(n=4, exactitud=0.75, error=0.0, aceptadas=3))]),
                              tmp_path / "sub" / "batch_report.csv")
    with ruta.open(encoding="utf-8") as fh:
        lector = csv.DictReader(fh)
        assert lector.fieldnames == BATCH_REPORT_FIELDS
        (fila,) = list(lector)
    assert fila["corrida"] == "a" and fila["fotogramas"] == "3"
    assert fila["qc_roi_fuera"] == "1" and fila["qc_dark"] == "1" and fila["qc_blur"] == "0"
    assert fila["ok"] == "1" and float(fila["cobertura"]) == pytest.approx(1 / 3, abs=1e-4)
    assert fila["prueba"] == "4" and float(fila["exactitud"]) == 0.75
    assert fila["plantillas"] == "12" and fila["huella"] == "abc123def456"


def test_batch_report_csv_deja_en_blanco_lo_que_no_se_conoce(tmp_path):
    ruta = write_batch_report(batch_summary([entrada("a", leido=False)]), tmp_path / "b.csv")
    with ruta.open(encoding="utf-8") as fh:
        (fila,) = list(csv.DictReader(fh))
    for campo in ("ok", "low_confidence", "spike", "cobertura", "prueba", "exactitud",
                  "error_aceptadas", "tipo_prueba", "veredicto"):
        assert fila[campo] == "", campo


def test_batch_report_csv_sin_corridas_es_solo_la_cabecera(tmp_path):
    ruta = write_batch_report([], tmp_path / "b.csv")
    assert ruta.read_text(encoding="utf-8").strip().split(",") == BATCH_REPORT_FIELDS


# ==========================================================================
# batch por CLI: la tabla, runs/batch_report.csv y los umbrales
# ==========================================================================
VALORES = ["0.245", "0.246", "0.248", "0.247", "0.245"]


@pytest.fixture
def lote(tmp_path, library, monkeypatch):
    """calib/ con receta, referencia y plantillas; un video vacio y un extract sintetico.

    El ultimo fotograma sale oscuro (qc lo descarta): cobertura 4/5 = 80%.
    """
    calib = tmp_path / "calib"
    (calib / "templates").mkdir(parents=True)
    make_config().save(calib / "config.json")
    cv2.imwrite(str(calib / "reference.jpg"), render_display("0.245"))
    for i, tpl in enumerate(library):
        cv2.imwrite(str(template_path(tpl.label, i, calib / "templates")), tpl.image)
    video = tmp_path / "videos" / "demo.mov"
    video.parent.mkdir()
    video.write_bytes(b"")

    def extract_falso(video, fps, output, index_path=None, **kw):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        rows = []
        for i, v in enumerate(VALORES):
            nombre = f"t_{float(i):011.3f}.jpg"
            cv2.imwrite(str(output / nombre), render_display(v, brightness=200 if i < 4 else 0))
            rows.append(FrameRow(archivo=nombre, t_s=float(i), indice=i + 1))
        if index_path is not None:
            write_frames_index(rows, index_path)
        return rows

    monkeypatch.setattr("spectro.extract.extract_frames", extract_falso)
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(calib)]
    return {"glob": glob, "video": str(video), "runs": tmp_path / "runs", "calib": calib}


def _reporte(lote):
    with (lote["runs"] / "batch_report.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_batch_cuenta_el_fotograma_descartado_y_deja_el_veredicto_vacio_sin_umbrales(lote, capsys):
    assert main(lote["glob"] + ["batch", lote["video"]]) == 0
    salida = capsys.readouterr().out
    (fila,) = _reporte(lote)
    assert fila["fotogramas"] == "5" and fila["ok"] == "4"
    assert int(fila["qc_dark"]) + int(fila["qc_blank"]) + int(fila["qc_low_contrast"]) == 1
    assert float(fila["cobertura"]) == pytest.approx(0.8)
    assert fila["veredicto"] == "" and "sin umbrales de aceptacion" in salida


def test_batch_aplica_los_flags_de_umbral(lote):
    assert main(lote["glob"] + ["batch", lote["video"], "--min-cobertura", "0.9"]) == 0
    (fila,) = _reporte(lote)
    assert fila["veredicto"] == "revisar" and "cobertura 80.0% < 90.0%" in fila["detalle"]


def test_batch_lee_los_umbrales_de_calib_config(lote):
    cfg = Config.load(lote["calib"] / "config.json")
    cfg.acceptance = AcceptanceConfig(min_cobertura=0.9)
    cfg.save(lote["calib"] / "config.json")
    assert main(lote["glob"] + ["batch", lote["video"]]) == 0
    assert _reporte(lote)[0]["veredicto"] == "revisar"


def test_batch_el_flag_le_gana_a_calib_config(lote):
    cfg = Config.load(lote["calib"] / "config.json")
    cfg.acceptance = AcceptanceConfig(min_cobertura=0.9)
    cfg.save(lote["calib"] / "config.json")
    assert main(lote["glob"] + ["batch", lote["video"], "--min-cobertura", "0.5"]) == 0
    assert _reporte(lote)[0]["veredicto"] == "acepta"


def test_batch_con_umbral_fuera_de_rango_da_error_claro(lote, capsys):
    assert main(lote["glob"] + ["batch", lote["video"], "--min-cobertura", "95"]) == 1
    assert "--min-cobertura" in capsys.readouterr().err


def test_batch_sin_prueba_con_umbral_de_exactitud_manda_a_revisar(lote):
    """La corrida no tiene test.csv: no hay nada que verifique la exactitud."""
    assert main(lote["glob"] + ["batch", lote["video"], "--min-exactitud", "0.9"]) == 0
    (fila,) = _reporte(lote)
    assert fila["veredicto"] == "revisar" and "sin prueba" in fila["detalle"] and fila["prueba"] == ""


def test_batch_mide_la_prueba_de_la_corrida_si_existe(lote, capsys):
    """Con test.csv, la fila lleva exactitud y el veredicto la usa. Se arma la corrida y se agrega la prueba."""
    assert main(lote["glob"] + ["batch", lote["video"]]) == 0
    T.save_truth(lote["runs"] / "demo" / "test.csv",
                 [T.Sample("t_0000000.000.jpg", "0.245"), T.Sample("t_0000001.000.jpg", "0.246")])
    capsys.readouterr()
    assert main(lote["glob"] + ["batch", lote["video"], "--min-exactitud", "0.9"]) == 0
    (fila,) = _reporte(lote)
    assert fila["prueba"] == "2" and float(fila["exactitud"]) == 1.0
    assert fila["tipo_prueba"] == "otro_video" and fila["veredicto"] == "acepta"


def test_batch_vuelve_a_correr_y_la_corrida_ya_hecha_sigue_en_el_reporte(lote, capsys):
    main(lote["glob"] + ["batch", lote["video"]])
    capsys.readouterr()
    assert main(lote["glob"] + ["batch", lote["video"]]) == 0
    assert "ya procesada" in capsys.readouterr().out
    assert [f["corrida"] for f in _reporte(lote)] == ["demo"]


def test_batch_until_read_no_escribe_el_reporte(lote):
    assert main(lote["glob"] + ["batch", lote["video"], "--until", "read"]) == 0
    assert not (lote["runs"] / "batch_report.csv").exists()


def test_batch_marca_las_salidas_desactualizadas_si_la_biblioteca_cambia(lote, capsys):
    """Despues del lote se agrega una plantilla: la tabla de un batch posterior lo ve como 'desactualizadas'."""
    from spectro.read import outputs_state

    main(lote["glob"] + ["batch", lote["video"]])
    tpl = lote["calib"] / "templates"
    run = lote["runs"] / "demo"
    assert outputs_state(run / "out" / "readings.csv", tpl) == "al_dia"
    cv2.imwrite(str(tpl / "9_5.png"), cv2.imread(str(next(tpl.glob("0_*.png"))), cv2.IMREAD_GRAYSCALE) // 2)
    capsys.readouterr()
    assert main(lote["glob"] + ["batch", lote["video"], "--min-cobertura", "0.5"]) == 0   # se saltea
    (fila,) = _reporte(lote)
    assert fila["salidas"] == "desactualizadas" and fila["veredicto"] == "revisar"


# ==========================================================================
# calibrate --promote conserva el criterio de aceptacion; las corridas no lo heredan
# ==========================================================================
def _promover(tmp_path, cfg_inicial):
    calib = tmp_path / "calib"
    calib.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(calib / "reference.jpg"), render_display("0.245"))
    if cfg_inicial is not None:
        cfg_inicial.save(calib / "config.json")
    run = tmp_path / "runs" / "r1"
    (run / "frames").mkdir(parents=True)
    cv2.imwrite(str(run / "frames" / "t_0000000.000.jpg"), render_display("0.245"))
    make_config().save(run / "config.json")
    # la corrida arranca sin ROI: calibrate --auto la engancha contra la referencia
    sin_roi = seed_run_config(calib_recipe(make_config()), "v.mov", 4.0)
    sin_roi.save(run / "config.json")
    globales = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(calib)]
    rc = main(globales + ["--run", "r1", "calibrate", "--auto", "--promote"])
    return rc, Config.load(calib / "config.json"), run


def test_promote_conserva_los_umbrales_de_aceptacion(tmp_path):
    """Rompe: que _promote pise calib/config.json con una receta sin la seccion 'acceptance'."""
    previa = calib_recipe(make_config())
    previa.acceptance = AcceptanceConfig(min_exactitud=0.95, max_error=0.02, min_cobertura=0.8)
    rc, receta, _ = _promover(tmp_path, previa)
    assert rc == 0
    assert (receta.acceptance.min_exactitud, receta.acceptance.max_error,
            receta.acceptance.min_cobertura) == (0.95, 0.02, 0.8)


def test_promote_sin_receta_previa_la_crea_sin_umbrales(tmp_path):
    """La primera calibracion manual (--auto exige receta): _promote la crea sin inventar umbrales."""
    from spectro.calibrate import _promote
    from spectro.project import CalibPaths

    calib = CalibPaths.at(tmp_path / "calib")
    frame = tmp_path / "f.jpg"
    cv2.imwrite(str(frame), render_display("0.245"))
    _promote(calib, make_config(), frame)
    assert calib.config.exists() and calib.reference.exists()
    assert not Config.load(calib.config).acceptance.is_set()


def test_promote_sin_umbrales_previos_no_los_inventa(tmp_path):
    rc, receta, _ = _promover(tmp_path, calib_recipe(make_config()))
    assert rc == 0 and not receta.acceptance.is_set()


def test_la_corrida_nueva_no_hereda_los_umbrales_de_la_calib():
    """Rompe: seed_run_config copiando 'acceptance' a runs/<id>/config.json (es criterio de la calib)."""
    receta = calib_recipe(make_config())
    receta.acceptance = AcceptanceConfig(min_exactitud=0.9)
    cfg = seed_run_config(receta, "v.mov", 4.0)
    assert not cfg.acceptance.is_set()
    assert receta.acceptance.min_exactitud == 0.9          # y la receta no se muta
