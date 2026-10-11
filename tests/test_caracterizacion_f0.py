"""Caracterizacion (fase 0 del plan v5): fija el comportamiento ACTUAL antes de refactorizar.

Estos tests no dicen que el comportamiento sea el ideal sino cual es hoy: si fallan tras
tocar ``cli.py``, ``teach.py``, ``library.py``, ``evaluation.py`` o ``read.py`` hay una
regresion (o un cambio deliberado que hay que documentar y re-fijar aca).

Grupos:
  1. ``teach`` por CLI: check, train, --keep, test eval (una corrida y tabla), errores.
  2. ``batch --until read`` con un extract falso (sin ffmpeg), batch_report.csv y el resumen por corrida.
  3. ``--roi-only``: fotograma recortado + sidecar == fotograma completo.
  4. ``sign_slot``: tinta sin plantilla '-' => low_confidence; con '-' => negativo.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from conftest import ROI_X, make_config, render_display
from spectro import teach as T
from spectro.cli import main
from spectro.evaluation import HISTORY_FIELDS, load_history
from spectro.extract import FrameRow, load_roi_sidecar, write_frames_index
from spectro.imaging import binarize, crop_for_reading, normalize_glyph, slot_boxes
from spectro.project import CalibPaths, RunPaths
from spectro.qc import QCRow, run_qc, write_qc_report
from spectro.read import Reading, read_frame, run_read, write_readings
from spectro.report import batch_summary, load_run_input
from spectro.library import fingerprint, load as load_templates, template_path

TRAIN_TEXTS = ["-0.123", " 4.567", "-8.901", " 2.345", " 6.789", "-0.246", " 1.357", " 9.048"]
TEST_TEXTS = [" 3.456", "-7.890"]


def _nombre(t: int) -> str:
    return f"t_{t:07d}.000.jpg"


def _contar(csv_path) -> int:
    with csv_path.open(encoding="utf-8") as fh:
        return len(list(csv.DictReader(fh)))


# ==========================================================================
# 1. teach por CLI
# ==========================================================================
@pytest.fixture
def proyecto(tmp_path):
    run = tmp_path / "runs" / "r1"
    (run / "frames").mkdir(parents=True)
    make_config(sign=True).save(run / "config.json")
    train, test = [], []
    for i, t in enumerate(TRAIN_TEXTS):
        cv2.imwrite(str(run / "frames" / _nombre(i * 10)), render_display(t))
        train.append(T.Sample(_nombre(i * 10), t.strip()))
    for i, t in enumerate(TEST_TEXTS):
        cv2.imwrite(str(run / "frames" / _nombre(100 + i * 10)), render_display(t))
        test.append(T.Sample(_nombre(100 + i * 10), t.strip()))
    T.save_truth(run / "truth.csv", train)
    T.save_truth(run / "test.csv", test)
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    return {"glob": glob, "run": run, "lib": tmp_path / "calib" / "templates", "tmp": tmp_path}


def teach(p, *args):
    """``teach <area> <verbo> ...``: el id de la corrida va como argumento, no como --run."""
    return main(p["glob"] + ["teach", *args])


def test_check_valida_y_escribe_solo_el_informe_sin_tocar_la_biblioteca(proyecto, capsys):
    """Rompe: que check escriba plantillas, o que deje de escribir teach_report.csv."""
    p = proyecto
    assert teach(p, "check", "r1") == 0
    salida = capsys.readouterr().out
    assert "8/8 lecturas exactas" in salida
    assert "no hay biblioteca vigente todavia" in salida
    assert "0:4  1:3  2:3  3:3  4:4  5:3  6:3  7:3  8:3  9:3" in salida
    assert not p["lib"].exists() or not list(p["lib"].glob("*.png"))
    assert _contar(p["run"] / "out" / "teach_report.csv") == 8


def test_train_escribe_una_plantilla_por_caracter_y_el_informe(proyecto, capsys):
    """Rompe: la deduplicacion/seleccion de plantillas, el conteo o los nombres de archivo."""
    p = proyecto
    assert teach(p, "train", "r1") == 0
    salida = capsys.readouterr().out
    assert "12 plantillas escritas" in salida
    assert "8/8 lecturas exactas" in salida
    nombres = sorted(f.name for f in p["lib"].glob("*.png"))
    esperados = sorted([f"{c}_0.png" for c in "0123456789"] + ["dot_0.png", "minus_0.png"])
    assert nombres == esperados
    assert _contar(p["run"] / "out" / "teach_report.csv") == 8
    # lo que se escribe se puede volver a cargar y tiene las etiquetas esperadas
    assert {t.label for t in load_templates(p["lib"])} == set("0123456789.-")


def test_train_con_keep_no_duplica_plantillas(proyecto, capsys):
    """Rompe: que --keep agregue copias de glifos casi identicos a los ya guardados."""
    p = proyecto
    teach(p, "train", "r1")
    antes = sorted(f.name for f in p["lib"].glob("*.png"))
    capsys.readouterr()
    assert teach(p, "train", "r1", "--keep") == 0
    assert "0 plantillas escritas" in capsys.readouterr().out
    assert sorted(f.name for f in p["lib"].glob("*.png")) == antes


def test_train_sin_keep_reemplaza_la_biblioteca(proyecto):
    """Rompe: que el modo por defecto conserve plantillas viejas (no seria 'reemplazar')."""
    p = proyecto
    p["lib"].mkdir(parents=True)
    huerfana = p["lib"] / "9_7.png"
    cv2.imwrite(str(huerfana), np.zeros((20, 12), np.uint8))
    assert teach(p, "train", "r1") == 0
    assert not huerfana.exists()


def test_test_eval_escribe_informe_e_historial_con_cifras_clave(proyecto, capsys):
    """Rompe: columnas de teach_history.csv, tipo de prueba, exactitud o cobertura."""
    p = proyecto
    teach(p, "train", "r1")
    capsys.readouterr()
    assert teach(p, "test", "eval", "r1") == 0
    salida = capsys.readouterr().out
    assert "teach test eval r1" in salida and "misma corrida" in salida
    assert "2 muestras, 2 valores distintos" in salida
    assert "correctas 2/2 = 100.0%" in salida and "cobertura 100.0%" in salida
    out = p["run"] / "out"
    assert _contar(out / "test_report.csv") == 2
    filas = load_history(out / "teach_history.csv")
    assert len(filas) == 1 and list(filas[0]) == HISTORY_FIELDS
    assert filas[0]["kind"] == "same_run" and filas[0]["test"] == "2"
    assert float(filas[0]["accuracy"]) == 1.0
    teach(p, "test", "eval", "r1")
    assert len(load_history(out / "teach_history.csv")) == 2          # el historial acumula


def test_test_eval_no_modifica_la_biblioteca(proyecto):
    """Rompe: que test eval escriba o borre plantillas."""
    p = proyecto
    teach(p, "train", "r1")
    antes = {f.name: f.read_bytes() for f in p["lib"].glob("*.png")}
    teach(p, "test", "eval", "r1")
    assert {f.name: f.read_bytes() for f in p["lib"].glob("*.png")} == antes


def test_test_eval_sin_corrida_da_una_fila_por_corrida_con_prueba(proyecto, capsys):
    """Rompe: el formato de la tabla (corrida, prueba, exactitud) o el recorrido de corridas."""
    p = proyecto
    teach(p, "train", "r1")
    capsys.readouterr()
    assert teach(p, "test", "eval") == 0
    salida = capsys.readouterr().out
    assert "teach test eval (biblioteca: 12 plantillas)" in salida
    linea = next(x for x in salida.splitlines() if x.strip().startswith("r1"))
    assert "2 misma" in linea and "100.0%" in linea


def test_test_eval_sin_ninguna_prueba_avisa_y_sale_con_0(proyecto, capsys):
    p = proyecto
    teach(p, "train", "r1")
    (p["run"] / "test.csv").unlink()
    capsys.readouterr()
    assert teach(p, "test", "eval") == 0
    assert "ninguna corrida tiene test.csv" in capsys.readouterr().out


def test_train_sin_corridas_junta_las_muestras_y_escribe_un_informe_por_corrida(proyecto, capsys):
    """Rompe: la union de muestras de varias corridas, el conteo o los informes por corrida."""
    p = proyecto
    r2 = p["tmp"] / "runs" / "r2"
    (r2 / "frames").mkdir(parents=True)
    make_config(sign=False).save(r2 / "config.json")
    muestras = []
    for i, t in enumerate(["0.333", "4.567", "8.901", "2.045", "6.789"]):
        cv2.imwrite(str(r2 / "frames" / _nombre(i * 10)), render_display(t))   # mismos nombres que r1
        muestras.append(T.Sample(_nombre(i * 10), t))
    T.save_truth(r2 / "truth.csv", muestras)
    assert teach(p, "train") == 0
    salida = capsys.readouterr().out
    assert "== teach train ==" in salida
    assert "8 muestras de entrenamiento" in salida and "5 muestras de entrenamiento" in salida
    assert "13/13 lecturas exactas" in salida
    assert (p["lib"] / "minus_0.png").exists() and (p["lib"] / "dot_0.png").exists()
    assert _contar(p["run"] / "out" / "teach_report.csv") == 8
    assert _contar(r2 / "out" / "teach_report.csv") == 5


@pytest.mark.parametrize(
    "args, fragmento",
    [
        (["samples", "add", "r1", "sin_igual"], "ARCHIVO=VALOR"),
        (["samples", "add", "r1", "t_9999999.000.jpg=0.123"], "No existe el fotograma"),
        (["samples", "list", "no_existe"], "No existe la corrida"),
    ],
)
def test_errores_de_teach_dan_codigo_1_y_mensaje(proyecto, capsys, args, fragmento):
    assert teach(proyecto, *args) == 1
    assert fragmento in capsys.readouterr().err


def test_train_sin_muestras_da_error_claro_y_no_escribe_nada(proyecto, capsys):
    p = proyecto
    (p["run"] / "truth.csv").unlink()
    (p["run"] / "test.csv").unlink()
    assert teach(p, "train", "r1") == 1
    assert "no tiene muestras de entrenamiento" in capsys.readouterr().err
    assert teach(p, "train") == 1                                         # sin id: ninguna corrida sirve
    assert "tiene muestras de entrenamiento" in capsys.readouterr().err
    assert not p["lib"].exists() or not list(p["lib"].glob("*.png"))      # nada a medias


def test_test_eval_sin_prueba_da_error_claro(proyecto, capsys):
    p = proyecto
    assert teach(p, "train", "r1") == 0
    (p["run"] / "test.csv").unlink()
    capsys.readouterr()
    assert teach(p, "test", "eval", "r1") == 1
    assert "No hay muestras de prueba" in capsys.readouterr().err
    assert not (p["run"] / "out" / "teach_history.csv").exists()          # nada a medias


def test_test_eval_sin_biblioteca_da_error_claro(proyecto, capsys):
    assert teach(proyecto, "test", "eval", "r1") == 1
    assert "templates" in capsys.readouterr().err
    assert not (proyecto["run"] / "out" / "teach_history.csv").exists()   # nada a medias


# ==========================================================================
# 2. batch --until read (extract falso: no hay ffmpeg ni video real)
# ==========================================================================
VALORES_BATCH = ["0.245", "0.246", "0.248", "0.247", "0.245"]


@pytest.fixture
def lote(tmp_path, library, monkeypatch):
    """calib/ con receta, referencia y plantillas; un 'video' vacio; extract sintetico."""
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
        for i, v in enumerate(VALORES_BATCH):
            nombre = f"t_{float(i):011.3f}.jpg"
            cv2.imwrite(str(output / nombre), render_display(v))
            rows.append(FrameRow(file=nombre, t_s=float(i), index=i + 1))
        if index_path is not None:
            write_frames_index(rows, index_path)
        return rows

    monkeypatch.setattr("spectro.extract.extract_frames", extract_falso)
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(calib)]
    return {"glob": glob, "video": video, "runs": tmp_path / "runs", "calib": calib}


def test_batch_until_read_deja_lecturas_y_no_hace_el_informe(lote, capsys):
    """Rompe: el orden/corte de etapas de batch, o los archivos que deja cada etapa."""
    assert main(lote["glob"] + ["batch", str(lote["video"]), "--until", "read"]) == 0
    salida = capsys.readouterr().out
    assert "[ok]" in salida and "preparada hasta read" in salida
    run = lote["runs"] / "demo"
    assert (run / "config.json").exists() and (run / "frames_index.csv").exists()
    assert _contar(run / "out" / "qc_report.csv") == 5
    with (run / "out" / "readings.csv").open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    assert [float(f["value"]) for f in filas] == pytest.approx([float(v) for v in VALORES_BATCH])
    assert not (run / "out" / "absorbance.csv").exists()


def test_batch_completo_imprime_la_tabla_y_escribe_batch_report(lote, library, capsys):
    """Rompe: la tabla del lote, runs/batch_report.csv o que no llegue a report."""
    assert main(lote["glob"] + ["batch", str(lote["video"])]) == 0
    salida = capsys.readouterr().out
    assert "== reporte del lote ==" in salida
    linea = next(x for x in salida.splitlines() if x.strip().startswith("demo"))
    assert "100.0%" in linea and "up_to_date" in linea
    assert "sin umbrales de aceptacion" in salida            # el codigo no inventa umbrales
    absorbancia = lote["runs"] / "demo" / "out" / "absorbance.csv"
    with absorbancia.open(encoding="utf-8") as fh:
        valores = [float(f["absorbance"]) for f in csv.DictReader(fh)]
    assert valores == pytest.approx([float(v) for v in VALORES_BATCH])
    with (lote["runs"] / "batch_report.csv").open(encoding="utf-8") as fh:
        (fila,) = list(csv.DictReader(fh))
    assert (fila["run"], fila["frames"], fila["ok"]) == ("demo", "5", "5")
    assert float(fila["coverage"]) == 1.0 and fila["verdict"] == ""
    assert fila["outputs"] == "up_to_date" and fila["fingerprint"] == fingerprint(lote["calib"] / "templates")
    assert int(fila["templates"]) == len(library)


def test_batch_saltea_la_corrida_ya_hecha(lote, capsys):
    main(lote["glob"] + ["batch", str(lote["video"])])
    capsys.readouterr()
    assert main(lote["glob"] + ["batch", str(lote["video"])]) == 0
    salida = capsys.readouterr().out
    assert "[salteada]" in salida and "ya procesada" in salida


def test_batch_sin_videos_devuelve_2(lote, capsys):
    assert main(lote["glob"] + ["batch", str(lote["video"].parent / "nada*.mov")]) == 2
    assert "No hay videos que procesar" in capsys.readouterr().out


def test_batch_until_invalido_lo_rechaza_el_parser_con_codigo_2(lote, capsys):
    with pytest.raises(SystemExit) as exc:
        main(lote["glob"] + ["batch", str(lote["video"]), "--until", "extract"])
    assert exc.value.code == 2
    assert "--until" in capsys.readouterr().err


def test_resumen_de_una_corrida_sin_qc_ni_lectura(tmp_path):
    """Rompe: que una corrida sin salidas cuente 0 ok / 0% de cobertura en vez de 'sin dato'."""
    run = RunPaths.for_run("x", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    entrada = load_run_input(run, CalibPaths.at(tmp_path / "calib"), [], with_eval=False)
    assert entrada.statuses == [] and not entrada.read_value and entrada.outputs == "no_reading"
    (fila,) = batch_summary([entrada])
    assert fila.frames == 0 and fila.ok is None and fila.coverage is None


def test_resumen_de_una_corrida_con_descartes_y_lecturas(tmp_path):
    """Rompe: el conteo de ok / descartes por motivo o la cobertura (ok / fotogramas extraidos)."""
    run = RunPaths.for_run("x", runs_dir=tmp_path / "runs", calib_dir=tmp_path / "calib")
    estados = ["ok", "ok", "ok", "dark"]
    write_qc_report([QCRow(f"t_{i}.jpg", float(i), i + 1, status=e) for i, e in enumerate(estados)],
                    run.qc_report)
    write_readings([Reading(f"t_{i}.jpg", float(i), i + 1, 0.1, 0.9, "0.100") for i in range(3)],
                   run.readings)
    entrada = load_run_input(run, CalibPaths.at(tmp_path / "calib"), [], with_eval=False)
    assert entrada.statuses == estados and entrada.read_value
    (fila,) = batch_summary([entrada])
    assert (fila.frames, fila.ok, fila.qc["dark"], fila.discarded_qc) == (4, 3, 1, 1)
    assert fila.coverage == pytest.approx(0.75)


# ==========================================================================
# 3. --roi-only: recorte + sidecar == fotograma completo
# ==========================================================================
@pytest.mark.parametrize("texto", ["0.245", "1.789", "3.056"])
def test_read_frame_con_recorte_y_sidecar_da_lo_mismo_que_el_completo(cfg, library, texto):
    """Rompe: que crop_for_reading recorte de nuevo un fotograma ya recortado."""
    completo = render_display(texto)
    a = read_frame(completo, cfg, library)
    b = read_frame(cfg.roi.crop(completo), cfg, library, frames_roi=cfg.roi)
    assert a.status == "ok" and b.status == "ok"
    assert (b.value, b.chars) == (a.value, a.chars)
    assert b.confidence == pytest.approx(a.confidence) and b.margin == pytest.approx(a.margin)


def test_con_recorte_el_offset_se_ignora(cfg, library):
    """Rompe: aplicar el corrimiento de camara sobre una imagen que ya es la ROI."""
    recorte = cfg.roi.crop(render_display("0.245"))
    base = read_frame(recorte, cfg, library, frames_roi=cfg.roi)
    movido = read_frame(recorte, cfg, library, frames_roi=cfg.roi, offset=(7, 5))
    assert (movido.value, movido.chars) == (base.value, base.chars)


def test_crop_for_reading_con_sidecar_devuelve_la_misma_imagen(cfg):
    """Rompe: el contrato de crop_for_reading (con sidecar no recorta; sin sidecar si)."""
    completo = render_display("0.245")
    recorte = cfg.roi.crop(completo)
    assert crop_for_reading(recorte, cfg, cfg.roi) is recorte
    assert crop_for_reading(completo, cfg).shape == recorte.shape


def test_slot_glyphs_con_recorte_es_igual_al_completo(cfg):
    """Rompe: que teach.slot_glyphs use otro camino de recorte que read_frame."""
    completo = render_display("1.789")
    a = T.slot_glyphs(completo, cfg)
    b = T.slot_glyphs(cfg.roi.crop(completo), cfg, frames_roi=cfg.roi)
    assert len(a) == len(b) == cfg.digits.n_digits
    for x, y in zip(a, b):
        assert np.array_equal(x, y)


def test_slot_glyphs_es_el_camino_de_read_frame(cfg):
    """Rompe: binarizar/cortar/normalizar distinto en teach que en la lectura."""
    img = render_display("0.245")
    roi = cfg.roi.crop(img)
    binary = binarize(roi, cfg.digits.polarity)
    esperados = [normalize_glyph(binary[:, x0:x1], cfg.templates.size)
                 for x0, x1 in slot_boxes(roi.shape[1], cfg.digits)]
    obtenidos = T.slot_glyphs(img, cfg)
    assert len(obtenidos) == len(esperados)
    for x, y in zip(obtenidos, esperados):
        assert np.array_equal(x, y)


def _escribir_sin_perdida(path, img):
    """PNG con nombre .jpg: OpenCV decodifica por contenido, asi no hay ruido de compresion."""
    ok, buf = cv2.imencode(".png", img)
    assert ok
    Path(path).write_bytes(buf.tobytes())


def _dos_directorios(tmp_path, cfg, textos):
    """El mismo contenido como fotogramas completos y como recortes con sidecar."""
    completos, recortados = tmp_path / "completos", tmp_path / "recortados"
    completos.mkdir()
    recortados.mkdir()
    for i, t in enumerate(textos):
        img = render_display(t)
        _escribir_sin_perdida(completos / _nombre(i), img)
        _escribir_sin_perdida(recortados / _nombre(i), cfg.roi.crop(img))
    (recortados / ".roi.json").write_text(json.dumps(vars(cfg.roi)), encoding="utf-8")
    return completos, recortados


def test_el_sidecar_se_carga_y_su_ausencia_es_none(cfg, tmp_path):
    completos, recortados = _dos_directorios(tmp_path, cfg, ["0.245"])
    assert load_roi_sidecar(completos) is None
    assert load_roi_sidecar(recortados) == cfg.roi


def test_build_pool_con_recortes_extrae_los_mismos_glifos(cfg, tmp_path):
    """Rompe: que build_pool/extract_sample ignore el sidecar de la carpeta de fotogramas."""
    completos, recortados = _dos_directorios(tmp_path, cfg, ["0.245", "1.789"])
    muestras = [T.Sample(_nombre(0), "0.245"), T.Sample(_nombre(1), "1.789")]
    pa, da, ea = T.build_pool(muestras, cfg, completos)
    pb, db, eb = T.build_pool(muestras, cfg, recortados)
    assert not ea and not eb and len(da) == len(db) == 2
    assert [g.label for g in pa] == [g.label for g in pb]
    for ga, gb in zip(pa, pb):                       # las etiquetas salen del valor: se comparan las imagenes
        assert np.array_equal(ga.image, gb.image)
    assert any(g.image.any() for g in pb)


def test_qc_y_read_sobre_recortes_dan_las_mismas_lecturas(cfg, library, tmp_path):
    """Rompe: el camino roi-only de qc/read (sin re-registro, sin ancla)."""
    valores = ["0.245", "0.246", "0.248"]
    resultados = []
    for sub, con_roi in (("c", False), ("r", True)):
        base = tmp_path / sub
        frames = base / "frames"
        frames.mkdir(parents=True)
        rows = []
        for i, v in enumerate(valores):
            nombre = f"t_{float(i):011.3f}.jpg"
            img = render_display(v)
            cv2.imwrite(str(frames / nombre), cfg.roi.crop(img) if con_roi else img)
            rows.append(FrameRow(nombre, float(i), i + 1))
        if con_roi:
            (frames / ".roi.json").write_text(json.dumps(vars(cfg.roi)), encoding="utf-8")
        write_frames_index(rows, base / "idx.csv")
        tpl = base / "templates"
        tpl.mkdir()
        for i, t in enumerate(library):
            cv2.imwrite(str(template_path(t.label, i, tpl)), t.image)
        cfg.qc.reference_frame = rows[0].file
        run_qc(cfg, frames, base / "idx.csv", base / "qc.csv", auto_thresholds=False, verbose=False)
        lecturas = run_read(cfg, frames, base / "qc.csv", tpl, base / "readings.csv", verbose=False)
        resultados.append([(r.value, r.status) for r in lecturas])
    assert resultados[0] == resultados[1]
    assert [v for v, _ in resultados[1]] == pytest.approx([float(v) for v in valores])


# ==========================================================================
# 4. sign_slot en read_frame
# ==========================================================================
def test_signo_con_tinta_y_sin_plantilla_menos_es_low_confidence(cfg_sign, library_sign):
    """Rompe: que la celda de signo con tinta se ignore o se lea positiva sin '-' disponible."""
    sin_menos = [t for t in library_sign if t.label != "-"]
    r = read_frame(render_display("-0.245"), cfg_sign, sin_menos)
    assert r.status == "low_confidence"
    assert r.value is None or r.value != pytest.approx(-0.245)


def test_signo_con_plantilla_menos_da_valor_negativo(cfg_sign, library_sign):
    """Rompe: la decision de negativo (tinta + etiqueta '-' + score/margen suficientes)."""
    r = read_frame(render_display("-0.245"), cfg_sign, library_sign)
    assert r.status == "ok" and r.value == pytest.approx(-0.245)
    assert r.chars == "-0.245"


def test_signo_vacio_da_valor_positivo(cfg_sign, library_sign):
    r = read_frame(render_display(" 1.789"), cfg_sign, library_sign)
    assert r.status == "ok" and r.value == pytest.approx(1.789)
    assert r.chars.startswith(" ")


def test_celda_de_signo_con_ruido_bajo_el_umbral_cuenta_como_vacia(cfg_sign, library_sign):
    """Rompe: el criterio por tinta (sign_max_ink) de la celda de signo."""
    img = render_display(" 1.789")
    img[cfg_sign.roi.y + 20, ROI_X + 2:ROI_X + 4] = 255          # 2 pixeles de ruido
    r = read_frame(img, cfg_sign, library_sign)
    assert r.status == "ok" and r.value == pytest.approx(1.789)


def test_la_lectura_negativa_por_run_read_conserva_el_signo(cfg_sign, library_sign, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    rows = []
    for i, v in enumerate(["-0.245", "-0.246", "-0.247"]):
        nombre = f"t_{float(i):011.3f}.jpg"
        cv2.imwrite(str(frames / nombre), render_display(v))
        rows.append(FrameRow(nombre, float(i), i + 1))
    write_frames_index(rows, tmp_path / "idx.csv")
    tpl = tmp_path / "templates"
    tpl.mkdir()
    for i, t in enumerate(library_sign):
        cv2.imwrite(str(template_path(t.label, i, tpl)), t.image)
    cfg_sign.qc.reference_frame = rows[0].file
    run_qc(cfg_sign, frames, tmp_path / "idx.csv", tmp_path / "qc.csv",
           auto_thresholds=False, verbose=False)
    lecturas = run_read(cfg_sign, frames, tmp_path / "qc.csv", tpl, tmp_path / "r.csv", verbose=False)
    assert [r.value for r in lecturas] == pytest.approx([-0.245, -0.246, -0.247])
