"""Huella de la biblioteca, ``read_meta.json``, ``outputs_state`` y ``require_run`` (Fase 2).

La huella dice con que biblioteca se produjo cada ``readings.csv``: si cambia una
plantilla, las salidas quedan marcadas como ``desactualizadas`` en vez de pasar por buenas.
"""

from __future__ import annotations

import json
import os
import re
import time

import cv2
import numpy as np
import pytest

from conftest import render_display
from spectro import library as L
from spectro.extract import FrameRow, write_frames_index
from spectro.project import require_run
from spectro.qc import run_qc
from spectro.read import (
    UP_TO_DATE,
    STALE,
    NO_FINGERPRINT,
    NO_READING,
    load_read_meta,
    outputs_state,
    run_read,
    write_read_meta,
)


def _plantillas(directorio, textos=("0", "1", "2")):
    """Una biblioteca minima de PNG de verdad (no importa que dibujen)."""
    directorio.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(textos):
        img = np.full((20, 12), 0, np.uint8)
        img[3 + i : 12, 2 : 4 + i] = 255
        cv2.imwrite(str(directorio / f"{t}_0.png"), img)
    return directorio


def _envejecer(path, segundos=3600):
    t = time.time() - segundos
    os.utime(path, (t, t))


# ==========================================================================
# library.fingerprint
# ==========================================================================
def test_la_huella_de_una_biblioteca_vacia_o_inexistente_es_vacia(tmp_path):
    assert L.fingerprint(tmp_path / "no_existe") == ""
    (tmp_path / "vacia").mkdir()
    assert L.fingerprint(tmp_path / "vacia") == ""


def test_la_huella_son_12_hex_y_es_determinista(tmp_path):
    d = _plantillas(tmp_path / "t")
    h = L.fingerprint(d)
    assert re.fullmatch(r"[0-9a-f]{12}", h)
    assert L.fingerprint(d) == h


def test_la_huella_no_depende_de_la_fecha_de_los_archivos(tmp_path):
    """Rompe: una huella que mezcle mtime (cambiaria con solo copiar la carpeta)."""
    d = _plantillas(tmp_path / "t")
    h = L.fingerprint(d)
    for f in d.glob("*.png"):
        _envejecer(f, 99999)
    assert L.fingerprint(d) == h


def test_la_huella_cambia_si_cambia_el_contenido_de_una_plantilla(tmp_path):
    """Rompe: una huella que solo hashee los nombres."""
    d = _plantillas(tmp_path / "t")
    h = L.fingerprint(d)
    cv2.imwrite(str(d / "1_0.png"), np.full((20, 12), 77, np.uint8))
    assert L.fingerprint(d) != h


def test_la_huella_cambia_si_se_agrega_se_borra_o_se_renombra(tmp_path):
    """Rompe: una huella que solo hashee los bytes (ignorando a que etiqueta pertenece cada uno)."""
    d = _plantillas(tmp_path / "t")
    h0 = L.fingerprint(d)
    img = cv2.imread(str(d / "0_0.png"), cv2.IMREAD_GRAYSCALE)
    cv2.imwrite(str(d / "9_0.png"), img)
    h_agregada = L.fingerprint(d)
    assert h_agregada != h0
    (d / "9_0.png").unlink()
    assert L.fingerprint(d) == h0                       # volver al estado anterior vuelve a la huella
    (d / "0_0.png").rename(d / "5_0.png")                # mismos bytes, otra etiqueta
    assert L.fingerprint(d) not in (h0, h_agregada)
    (d / "5_0.png").unlink()
    assert L.fingerprint(d) not in (h0, h_agregada)


def test_la_huella_ignora_lo_que_no_es_png(tmp_path):
    d = _plantillas(tmp_path / "t")
    h = L.fingerprint(d)
    (d / "notas.txt").write_text("hola", encoding="utf-8")
    (d / "subcarpeta").mkdir()
    assert L.fingerprint(d) == h


# ==========================================================================
# read_meta.json y outputs_state
# ==========================================================================
def test_write_read_meta_guarda_huella_fecha_y_cantidad(tmp_path):
    d = _plantillas(tmp_path / "t")
    ruta = write_read_meta(tmp_path / "out" / "read_meta.json", d, 3)
    meta = load_read_meta(ruta)
    assert meta["fingerprint"] == L.fingerprint(d) and meta["templates"] == 3
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", meta["date"])


@pytest.mark.parametrize("contenido", [None, "esto no es json", "[1, 2, 3]", ""])
def test_load_read_meta_tolera_ausente_corrupto_o_que_no_es_un_objeto(tmp_path, contenido):
    ruta = tmp_path / "read_meta.json"
    if contenido is not None:
        ruta.write_text(contenido, encoding="utf-8")
    assert load_read_meta(ruta) is None


def test_outputs_state_sin_lecturas(tmp_path):
    d = _plantillas(tmp_path / "t")
    assert outputs_state(tmp_path / "out" / "readings.csv", d) == NO_READING


def test_outputs_state_al_dia_y_desactualizadas_segun_la_huella(tmp_path):
    """Rompe: comparar solo fechas (con la huella, tocar una plantilla sin cambiarla no invalida)."""
    d = _plantillas(tmp_path / "t")
    lecturas = tmp_path / "out" / "readings.csv"
    lecturas.parent.mkdir()
    lecturas.write_text("archivo\n", encoding="utf-8")
    write_read_meta(lecturas.with_name("read_meta.json"), d, 3)
    assert outputs_state(lecturas, d) == UP_TO_DATE
    # tocar la fecha sin cambiar los bytes no invalida: manda la huella
    (d / "0_0.png").write_bytes((d / "0_0.png").read_bytes())
    assert outputs_state(lecturas, d) == UP_TO_DATE
    cv2.imwrite(str(d / "2_0.png"), np.full((20, 12), 9, np.uint8))
    assert outputs_state(lecturas, d) == STALE


def test_outputs_state_con_biblioteca_vacia_y_huella_vacia_esta_al_dia(tmp_path):
    (tmp_path / "t").mkdir()
    lecturas = tmp_path / "out" / "readings.csv"
    lecturas.parent.mkdir()
    lecturas.write_text("archivo\n", encoding="utf-8")
    write_read_meta(lecturas.with_name("read_meta.json"), tmp_path / "t", 0)
    assert outputs_state(lecturas, tmp_path / "t") == UP_TO_DATE


def test_outputs_state_sin_meta_se_juzga_por_fecha(tmp_path):
    """Un readings.csv anterior a la huella: mas viejo que la plantilla mas nueva = desactualizadas."""
    d = _plantillas(tmp_path / "t")
    lecturas = tmp_path / "out" / "readings.csv"
    lecturas.parent.mkdir()
    lecturas.write_text("archivo\n", encoding="utf-8")
    for f in d.glob("*.png"):
        _envejecer(f, 7200)
    _envejecer(lecturas, 3600)
    assert outputs_state(lecturas, d) == NO_FINGERPRINT          # plantillas mas viejas: no se sabe
    nueva = d / "7_0.png"
    cv2.imwrite(str(nueva), np.full((20, 12), 5, np.uint8))
    assert outputs_state(lecturas, d) == STALE     # una plantilla mas nueva que la lectura


def test_outputs_state_con_meta_corrupto_cae_en_la_fecha(tmp_path):
    d = _plantillas(tmp_path / "t")
    lecturas = tmp_path / "out" / "readings.csv"
    lecturas.parent.mkdir()
    lecturas.write_text("archivo\n", encoding="utf-8")
    lecturas.with_name("read_meta.json").write_text("{roto", encoding="utf-8")
    for f in d.glob("*.png"):
        _envejecer(f, 7200)
    _envejecer(lecturas, 3600)
    assert outputs_state(lecturas, d) == NO_FINGERPRINT


# ==========================================================================
# run_read escribe read_meta.json
# ==========================================================================
def _leer(tmp_path, cfg, library, nombre="r"):
    base = tmp_path / nombre
    frames = base / "frames"
    frames.mkdir(parents=True)
    rows = []
    for i, v in enumerate(["0.245", "0.246"]):
        n = f"t_{float(i):011.3f}.jpg"
        cv2.imwrite(str(frames / n), render_display(v))
        rows.append(FrameRow(n, float(i), i + 1))
    write_frames_index(rows, base / "idx.csv")
    tpl = base / "templates"
    tpl.mkdir()
    for i, t in enumerate(library):
        cv2.imwrite(str(L.template_path(t.label, i, tpl)), t.image)
    cfg.qc.reference_frame = rows[0].file
    run_qc(cfg, frames, base / "idx.csv", base / "out" / "qc.csv", auto_thresholds=False, verbose=False)
    lecturas = run_read(cfg, frames, base / "out" / "qc.csv", tpl, base / "out" / "readings.csv",
                        verbose=False)
    return base, tpl, lecturas


def test_run_read_escribe_read_meta_junto_a_readings(cfg, library, tmp_path):
    """Rompe: que read no deje la huella (o la deje en otra carpeta que readings.csv)."""
    base, tpl, _ = _leer(tmp_path, cfg, library)
    meta = load_read_meta(base / "out" / "read_meta.json")
    assert meta is not None
    assert meta["fingerprint"] == L.fingerprint(tpl) and meta["fingerprint"] != ""
    assert meta["templates"] == len(library)
    assert outputs_state(base / "out" / "readings.csv", tpl) == UP_TO_DATE


def test_run_read_no_cambia_el_formato_de_readings_csv(cfg, library, tmp_path):
    base, _, _ = _leer(tmp_path, cfg, library)
    cabecera = (base / "out" / "readings.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "fingerprint" not in cabecera and cabecera.startswith("file,t_s,index,value")


def test_cambiar_la_biblioteca_despues_de_leer_deja_las_salidas_desactualizadas(cfg, library, tmp_path):
    base, tpl, _ = _leer(tmp_path, cfg, library)
    L.delete([next(tpl.glob("*.png"))])
    assert outputs_state(base / "out" / "readings.csv", tpl) == STALE


def test_releer_actualiza_la_huella(cfg, library, tmp_path):
    base, tpl, _ = _leer(tmp_path, cfg, library)
    antes = load_read_meta(base / "out" / "read_meta.json")["fingerprint"]
    L.delete([next(tpl.glob("*.png"))])
    run_read(cfg, base / "frames", base / "out" / "qc.csv", tpl, base / "out" / "readings.csv",
             verbose=False)
    meta = load_read_meta(base / "out" / "read_meta.json")
    assert meta["fingerprint"] != antes and meta["fingerprint"] == L.fingerprint(tpl)
    assert outputs_state(base / "out" / "readings.csv", tpl) == UP_TO_DATE


def test_read_sin_biblioteca_falla_y_no_deja_read_meta(cfg, tmp_path):
    """Rompe: escribir una huella para una lectura que no se hizo."""
    base = tmp_path / "r"
    (base / "frames").mkdir(parents=True)
    (base / "templates").mkdir()
    with pytest.raises(FileNotFoundError):
        run_read(cfg, base / "frames", base / "out" / "qc.csv", base / "templates",
                 base / "out" / "readings.csv", verbose=False)
    assert not (base / "out" / "read_meta.json").exists()


# ==========================================================================
# project.require_run
# ==========================================================================
def test_require_run_devuelve_las_rutas_de_una_corrida_que_existe(tmp_path):
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    (tmp_path / "runs" / "r1" / "config.json").write_text("{}", encoding="utf-8")
    run = require_run("r1", tmp_path / "runs", tmp_path / "calib")
    assert run.id == "r1" and run.config == tmp_path / "runs" / "r1" / "config.json"


def test_require_run_con_id_inexistente_lista_las_disponibles(tmp_path):
    """Rompe: adivinar la corrida o devolver rutas de una que no existe."""
    for r in ("img_1", "img_2"):
        (tmp_path / "runs" / r).mkdir(parents=True)
        (tmp_path / "runs" / r / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        require_run("img_3", tmp_path / "runs", tmp_path / "calib")
    assert "img_3" in str(exc.value) and "img_1, img_2" in str(exc.value)


def test_require_run_sin_ninguna_corrida_dice_ninguna(tmp_path):
    with pytest.raises(ValueError, match="Disponibles: ninguna"):
        require_run("x", tmp_path / "no_hay", tmp_path / "calib")


def test_require_run_exige_config_json_no_basta_la_carpeta(tmp_path):
    """Una carpeta runs/x/ sin config.json no es una corrida dada de alta."""
    (tmp_path / "runs" / "x" / "frames").mkdir(parents=True)
    with pytest.raises(ValueError, match="No existe la corrida"):
        require_run("x", tmp_path / "runs", tmp_path / "calib")


def test_require_run_no_acepta_un_id_parcial(tmp_path):
    (tmp_path / "runs" / "img_8102").mkdir(parents=True)
    (tmp_path / "runs" / "img_8102" / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        require_run("8102", tmp_path / "runs", tmp_path / "calib")
    with pytest.raises(ValueError):
        require_run("img_81", tmp_path / "runs", tmp_path / "calib")
