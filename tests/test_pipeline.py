"""Contratos entre etapas: config, indice de fotogramas, CSV de salida y cuadre.

Estos tests recorren el pipeline de qc en adelante sobre fotogramas sinteticos
escritos en disco, sin tocar ffmpeg ni el video real.
"""

import csv

import cv2
import pytest

from conftest import make_config, render_display
from spectro.config import ROI, Config
from spectro.extract import FrameRow, load_frames_index, write_frames_index
from spectro.qc import load_qc_report, run_qc
from spectro.read import run_read
from spectro.report import run_report
from spectro.library import load as load_templates, template_path


@pytest.fixture
def proyecto(tmp_path, library):
    """Un proyecto completo en disco: fotogramas, indice, plantillas y config."""
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    # Valores que cambian despacio: un salto grande seria descartado como spike,
    # que es justo lo que prueba tests/test_confidence.py.
    valores = ["0.245", "0.246", "0.248", "0.247", "0.245"]
    rows = []
    for i, texto in enumerate(valores):
        t = float(i)
        nombre = f"t_{t:011.3f}.jpg"
        cv2.imwrite(str(frames_dir / nombre), render_display(texto))
        rows.append(FrameRow(file=nombre, t_s=t, index=i + 1))
    index_path = tmp_path / "frames_index.csv"
    write_frames_index(rows, index_path)

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    for i, tpl in enumerate(library):
        cv2.imwrite(str(template_path(tpl.label, i, templates_dir)), tpl.image)

    cfg = make_config()
    cfg.qc.reference_frame = rows[0].file
    cfg_path = tmp_path / "config.json"
    cfg.save(cfg_path)
    return {
        "cfg": cfg,
        "cfg_path": cfg_path,
        "frames_dir": frames_dir,
        "index": index_path,
        "templates": templates_dir,
        "out": tmp_path / "out",
        "valores": valores,
    }


def test_config_ida_y_vuelta(tmp_path):
    cfg = make_config()
    cfg.time.offset_s = -12.5
    cfg.time.absolute_start = "2026-09-01 16:42:20"
    path = cfg.save(tmp_path / "config.json")
    recargado = Config.load(path)
    assert recargado.roi == cfg.roi
    assert recargado.digits.separator_slots == [1]
    assert recargado.time.offset_s == -12.5
    assert recargado.templates.size == cfg.templates.size


def test_config_faltante_da_mensaje_util(tmp_path):
    with pytest.raises(FileNotFoundError, match="calibrate"):
        Config.load(tmp_path / "no_existe.json")


def test_indice_de_fotogramas_ida_y_vuelta(tmp_path):
    rows = [FrameRow(file="t_0000001.000.jpg", t_s=1.0, index=1)]
    path = write_frames_index(rows, tmp_path / "idx.csv")
    assert load_frames_index(path) == rows


def test_pipeline_completo(proyecto):
    cfg = proyecto["cfg"]
    qc_path = proyecto["out"] / "qc_report.csv"
    run_qc(cfg, proyecto["frames_dir"], proyecto["index"], qc_path,
           auto_thresholds=False, verbose=False)
    readings = run_read(cfg, proyecto["frames_dir"], qc_path, proyecto["templates"],
                        proyecto["out"] / "readings.csv", verbose=False)
    assert [r.value for r in readings] == pytest.approx(
        [float(v) for v in proyecto["valores"]]
    )

    n = run_report(cfg, proyecto["out"] / "readings.csv", qc_path, proyecto["frames_dir"],
                   proyecto["out"], no_plots=True, verbose=False)
    assert n == len(proyecto["valores"])

    with (proyecto["out"] / "absorbance.csv").open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    assert [f["absorbance"] for f in filas] == proyecto["valores"]
    assert filas[1]["t_video"] == "00:00:01.000"


def test_cuadre_de_conteos(proyecto):
    """validas + descartadas debe dar exactamente los fotogramas extraidos."""
    cfg = proyecto["cfg"]
    qc_path = proyecto["out"] / "qc_report.csv"
    run_qc(cfg, proyecto["frames_dir"], proyecto["index"], qc_path,
           auto_thresholds=False, verbose=False)
    run_read(cfg, proyecto["frames_dir"], qc_path, proyecto["templates"],
             proyecto["out"] / "readings.csv", verbose=False)
    n = run_report(cfg, proyecto["out"] / "readings.csv", qc_path, proyecto["frames_dir"],
                   proyecto["out"], no_plots=True, verbose=False)
    qc_rows = load_qc_report(qc_path)
    descartadas = sum(1 for r in qc_rows if r.status != "ok")
    assert n + descartadas == len(qc_rows)


def test_offset_de_tiempo_se_aplica(proyecto):
    cfg = proyecto["cfg"]
    cfg.time.offset_s = 100.0
    qc_path = proyecto["out"] / "qc_report.csv"
    run_qc(cfg, proyecto["frames_dir"], proyecto["index"], qc_path,
           auto_thresholds=False, verbose=False)
    run_read(cfg, proyecto["frames_dir"], qc_path, proyecto["templates"],
             proyecto["out"] / "readings.csv", verbose=False)
    run_report(cfg, proyecto["out"] / "readings.csv", qc_path, proyecto["frames_dir"],
               proyecto["out"], no_plots=True, verbose=False)
    with (proyecto["out"] / "absorbance.csv").open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    assert filas[0]["t_s"] == "0.000"
    assert filas[0]["t_exp"] == "100.000"


def test_hora_absoluta_agrega_columna(proyecto):
    cfg = proyecto["cfg"]
    cfg.time.absolute_start = "2026-09-01 16:42:20"
    qc_path = proyecto["out"] / "qc_report.csv"
    run_qc(cfg, proyecto["frames_dir"], proyecto["index"], qc_path,
           auto_thresholds=False, verbose=False)
    run_read(cfg, proyecto["frames_dir"], qc_path, proyecto["templates"],
             proyecto["out"] / "readings.csv", verbose=False)
    run_report(cfg, proyecto["out"] / "readings.csv", qc_path, proyecto["frames_dir"],
               proyecto["out"], no_plots=True, verbose=False)
    with (proyecto["out"] / "absorbance.csv").open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    assert filas[0]["datetime"].startswith("2026-09-01T16:42:20")


def test_biblioteca_vacia_da_mensaje_util(tmp_path):
    with pytest.raises(FileNotFoundError, match="teach"):
        load_templates(tmp_path)


def test_roi_invalida_da_mensaje_util(library):
    from spectro.read import read_frame

    cfg = Config.default()
    cfg.roi = ROI(0, 0, 0, 0)
    with pytest.raises(ValueError, match="calibrate"):
        read_frame(render_display("0.245"), cfg, library)


def _read_con_signo(tmp_path, biblioteca):
    """``read`` con una config de 6 celdas (signo) sobre un fotograma positivo."""
    cfg = make_config(sign=True)
    frames = tmp_path / "frames"
    frames.mkdir()
    cv2.imwrite(str(frames / "t_0000001.000.jpg"), render_display("0.245"))
    write_frames_index([FrameRow("t_0000001.000.jpg", 1.0, 1)], tmp_path / "idx.csv")
    tpl = tmp_path / "templates"
    tpl.mkdir()
    for i, t in enumerate(biblioteca):
        cv2.imwrite(str(template_path(t.label, i, tpl)), t.image)
    cfg.qc.reference_frame = "t_0000001.000.jpg"
    run_qc(cfg, frames, tmp_path / "idx.csv", tmp_path / "qc.csv", auto_thresholds=False, verbose=False)
    return run_read(cfg, frames, tmp_path / "qc.csv", tpl, tmp_path / "r.csv", verbose=False)


def test_read_avisa_por_stderr_si_falta_el_menos_y_no_cambia_las_lecturas(tmp_path, library, capsys):
    """Rompe: quitar el aviso de ``read`` (``warn_missing_sign``) o hacer que cambie el resultado."""
    lecturas = _read_con_signo(tmp_path, [t for t in library if t.label != "-"])
    err = capsys.readouterr().err
    assert "plantilla '-'" in err and "teach train" in err
    assert len(lecturas) == 1


def test_read_no_avisa_si_la_biblioteca_trae_el_menos(tmp_path, library_sign, capsys):
    """Rompe: avisar siempre, aun con la plantilla '-' presente."""
    _read_con_signo(tmp_path, library_sign)
    assert "plantilla '-'" not in capsys.readouterr().err
