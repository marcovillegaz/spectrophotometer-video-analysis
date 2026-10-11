"""Fotogramas sinteticos oscuro / borroso / ocluido -> el estado esperado."""

import numpy as np
import pytest

from conftest import render_display
from spectro.config import QCConfig
from spectro.imaging import estimate_shift
from spectro.qc import QCRow, classify, measure, suggest_thresholds


def fila(cfg, frame, qc: QCConfig | None = None) -> QCRow:
    row = QCRow(file="t_0000000.000.jpg", t_s=0.0, index=1)
    for k, v in measure(frame, cfg).items():
        setattr(row, k, v)
    row.status = classify(row, qc or QCConfig())
    return row


def test_fotograma_bueno_pasa(cfg):
    assert fila(cfg, render_display("0.245")).status == "ok"


def test_fotograma_oscuro(cfg):
    oscuro = (render_display("0.245") * 0.1).astype(np.uint8)
    assert fila(cfg, oscuro).status == "dark"


def test_fotograma_quemado(cfg):
    quemado = np.full_like(render_display("0.245"), 252)
    assert fila(cfg, quemado).status in ("blown", "low_contrast")


def test_fotograma_borroso(cfg):
    borroso = render_display("0.245", blur=31)
    qc = QCConfig(min_blur_var=200.0)
    assert fila(cfg, borroso, qc).status == "blur"


def test_pantalla_vacia(cfg):
    vacio = np.full_like(render_display("0.245"), 30)
    assert fila(cfg, vacio).status in ("blank", "low_contrast")


def test_ocluido(cfg):
    """Una mano delante deja la ROI casi toda "tinta"."""
    ocluido = render_display("0.245")
    ocluido[:, :] = 30
    ocluido[cfg.roi.y : cfg.roi.y + cfg.roi.h, cfg.roi.x : cfg.roi.x + cfg.roi.w] = 240
    assert fila(cfg, ocluido).status in ("occluded", "blown", "low_contrast")


def test_metricas_se_calculan_sobre_la_roi(cfg):
    """Oscurecer todo *menos* la ROI no debe cambiar las metricas."""
    limpio = render_display("0.245")
    con_penumbra = limpio.copy()
    con_penumbra[100:, :] = 0
    assert measure(limpio, cfg)["mean_luma"] == pytest.approx(
        measure(con_penumbra, cfg)["mean_luma"]
    )


def test_umbrales_auto_no_rechazan_la_poblacion_normal(cfg):
    rows = []
    for i in range(30):
        row = QCRow(file=f"f{i}", t_s=float(i), index=i)
        for k, v in measure(render_display("0.245", brightness=190 + i % 10), cfg).items():
            setattr(row, k, v)
        rows.append(row)
    qc = suggest_thresholds(rows, QCConfig())
    assert all(classify(r, qc) == "ok" for r in rows)


def test_registro_mide_el_corrimiento(cfg):
    frame = render_display("0.245")
    corrido = np.roll(np.roll(frame, 3, axis=0), 2, axis=1)
    dx, dy, score = estimate_shift(cfg.qc.anchor.crop(frame), corrido, cfg.qc.anchor, margin=20)
    assert (dx, dy) == (2, 3)
    assert score > 0.9


def test_corrimiento_excesivo_es_camera_moved(cfg):
    row = QCRow(file="f", t_s=0.0, index=1, mean_luma=100, contrast=100,
                blur_var=1000, ink_fraction=0.2, anchor_ncc=1.0, dx=0, dy=99)
    assert classify(row, QCConfig(max_shift_px=40)) == "camera_moved"


# ==========================================================================
# run_qc: descartes al medir (carga fallida, ROI fuera) y formato del reporte
# ==========================================================================
def _corrida_qc(tmp_path, cfg, archivos, config_path=None):
    """Carpeta de fotogramas ``{nombre: imagen | bytes}`` y la corrida de ``run_qc`` sin registro."""
    import cv2

    from spectro.qc import run_qc

    cfg.qc.register = False
    frames = tmp_path / "frames"
    frames.mkdir(parents=True)
    for nombre, contenido in archivos.items():
        if isinstance(contenido, bytes):
            (frames / nombre).write_bytes(contenido)
        else:
            cv2.imwrite(str(frames / nombre), contenido)
    rows = run_qc(cfg, frames, tmp_path / "no_hay.csv", tmp_path / "out" / "qc.csv",
                   config_path=config_path, verbose=False)
    return frames, {r.file: r for r in rows}, rows


BUENO = "t_0000001.000.jpg"


def test_un_fotograma_que_no_carga_queda_blank_y_no_pasa_a_dark(cfg, tmp_path):
    """Rompe: reclasificar los descartados al medir (``classify`` los dejaba en ``dark`` por tener todo en cero)."""
    _, por, _ = _corrida_qc(tmp_path, cfg, {BUENO: render_display("0.245"),
                                            "t_0000002.000.jpg": b"esto no es un jpg"})
    assert por["t_0000002.000.jpg"].status == "blank"
    assert por[BUENO].status != "blank"


def test_el_blank_por_carga_fallida_no_pasa_qc_ni_tiene_metricas(cfg, tmp_path):
    """Rompe: medir un fotograma que no cargo (las metricas serian inventadas)."""
    _, por, _ = _corrida_qc(tmp_path, cfg, {BUENO: render_display("0.245"),
                                            "t_0000002.000.jpg": b""})
    r = por["t_0000002.000.jpg"]
    assert not r.passed_qc and (r.mean_luma, r.contrast, r.dx, r.dy) == (0.0, 0.0, 0, 0)


def test_roi_fuera_se_conserva_y_no_pasa_qc(cfg, tmp_path):
    """Rompe: que el reclasificado pise ``roi_fuera`` con ``dark``/``low_contrast``."""
    _, por, _ = _corrida_qc(tmp_path, cfg, {BUENO: render_display("0.245"),
                                            "t_0000002.000.jpg": np.full((10, 10), 90, np.uint8)})
    assert por["t_0000002.000.jpg"].status == "roi_outside" and not por["t_0000002.000.jpg"].passed_qc


def test_roi_fuera_y_blank_conviven_con_un_fotograma_bueno_y_no_abortan(cfg, tmp_path):
    """Rompe: que un fotograma malo aborte la corrida o contamine los umbrales de los buenos."""
    nombres = {f"t_{i:07d}.000.jpg": render_display("0.245", brightness=190 + i) for i in range(1, 6)}
    nombres["t_0000010.000.jpg"] = b"basura"
    nombres["t_0000011.000.jpg"] = np.full((10, 10), 90, np.uint8)
    _, por, rows = _corrida_qc(tmp_path, cfg, nombres)
    assert len(rows) == 7
    assert por["t_0000010.000.jpg"].status == "blank" and por["t_0000011.000.jpg"].status == "roi_outside"
    assert all(por[n].status == "ok" for n in list(nombres)[:5])


def test_los_umbrales_automaticos_no_usan_los_fotogramas_descartados(cfg, tmp_path):
    """Rompe: que los blank/roi_fuera (metricas en cero) entren a ``suggest_thresholds``.

    Compara los umbrales sugeridos (no solo los estados): con basura incluida tienen que
    ser identicos a los de la corrida sin basura.
    """
    from dataclasses import asdict

    nombres = {f"t_{i:07d}.000.jpg": render_display("0.245", brightness=190 + i) for i in range(1, 8)}
    sin_malos = _corrida_qc(tmp_path / "a", cfg, nombres, config_path=tmp_path / "a.json")[2]
    umbrales_a = asdict(cfg.qc)
    nombres["t_0000010.000.jpg"] = b"basura"
    nombres["t_0000011.000.jpg"] = np.full((10, 10), 90, np.uint8)
    con_malos = _corrida_qc(tmp_path / "b", cfg, nombres, config_path=tmp_path / "b.json")[2]
    assert asdict(cfg.qc) == umbrales_a
    assert [r.status for r in con_malos[:7]] == [r.status for r in sin_malos]


def test_fotograma_chico_con_sidecar_valido_se_mide_y_no_es_roi_fuera(cfg, tmp_path):
    """Rompe: validar el tamano contra la ROI cuando ``.roi.json`` dice que el fotograma ya es la ROI."""
    import json

    import cv2

    from spectro.qc import run_qc

    cfg.qc.register = False
    frames = tmp_path / "frames"
    frames.mkdir()
    r = cfg.roi
    (frames / ".roi.json").write_text(json.dumps({"x": r.x, "y": r.y, "w": r.w, "h": r.h}), encoding="utf-8")
    recorte = cfg.roi.crop(render_display("0.245"))
    assert recorte.shape[0] < 140  # mas chico que el fotograma completo (140 de alto)
    cv2.imwrite(str(frames / "t_0000001.000.jpg"), recorte)
    filas = run_qc(cfg, frames, tmp_path / "no_hay.csv", tmp_path / "qc.csv", auto_thresholds=False, verbose=False)
    (fila,) = filas
    assert fila.status == "ok" and fila.mean_luma > 0 and fila.contrast > 50


def test_fotograma_mas_chico_que_la_roi_con_sidecar_valido_no_es_roi_fuera(cfg, tmp_path):
    """Rompe: validar el tamano contra la ROI aun con ``.roi.json`` (el sidecar manda: el fotograma ya es la ROI)."""
    import json

    import cv2

    from spectro.qc import run_qc

    cfg.qc.register = False
    frames = tmp_path / "frames"
    frames.mkdir()
    r = cfg.roi
    (frames / ".roi.json").write_text(json.dumps({"x": r.x, "y": r.y, "w": r.w, "h": r.h}), encoding="utf-8")
    cv2.imwrite(str(frames / "t_0000001.000.jpg"), np.tile(np.arange(0, 240, 12, dtype=np.uint8), (10, 1)))
    (fila,) = run_qc(cfg, frames, tmp_path / "no_hay.csv", tmp_path / "qc.csv", auto_thresholds=False, verbose=False)
    assert fila.status != "roi_outside" and fila.mean_luma > 0


def test_qc_report_conserva_el_formato(cfg, tmp_path):
    """Rompe: cambiar columnas, orden o decimales del reporte (lo leen ``read``, ``teach`` y los CSV viejos)."""
    import csv
    import re

    nombres = {f"t_{i:07d}.000.jpg": render_display("0.245", brightness=190 + i) for i in range(1, 4)}
    nombres["t_0000010.000.jpg"] = b"basura"
    _corrida_qc(tmp_path, cfg, nombres)
    with (tmp_path / "out" / "qc.csv").open(encoding="utf-8", newline="") as fh:
        filas = list(csv.reader(fh))
    assert filas[0] == ["file", "t_s", "index", "mean_luma", "p05", "p95", "contrast", "blur_var",
                        "ink_fraction", "anchor_ncc", "dx", "dy", "status"]
    assert len(filas) == 5 and all(len(f) == 13 for f in filas)
    patrones = [r"t_\d{7}\.000\.jpg", r"\d+\.\d{3}", r"\d+", r"\d+\.\d{2}", r"\d+\.\d", r"\d+\.\d",
                r"\d+\.\d{2}", r"\d+\.\d{2}", r"\d\.\d{4}", r"-?\d+\.\d{4}", r"-?\d+", r"-?\d+", r"[a-z_]+"]
    for fila in filas[1:]:
        for valor, pat in zip(fila, patrones):
            assert re.fullmatch(pat, valor), (valor, pat)
    assert [f[0] for f in filas[1:]] == sorted(f[0] for f in filas[1:])  # orden del indice


def test_qc_report_se_puede_releer_y_conserva_estados_y_corrimientos(cfg, tmp_path):
    """Rompe: que ``load_qc_report`` no devuelva lo que ``write_qc_report`` escribio."""
    from spectro.qc import load_qc_report

    nombres = {BUENO: render_display("0.245"), "t_0000002.000.jpg": b"x",
               "t_0000003.000.jpg": np.full((10, 10), 90, np.uint8)}
    _, _, rows = _corrida_qc(tmp_path, cfg, nombres)
    leidas = load_qc_report(tmp_path / "out" / "qc.csv")
    assert [(r.file, r.status, r.offset) for r in leidas] == [(r.file, r.status, r.offset) for r in rows]
    assert [r.status for r in leidas][1:] == ["blank", "roi_outside"]


def test_measure_row_devuelve_el_estado_de_descarte(cfg, tmp_path):
    """Rompe: que ``_measure_row`` devuelva ``ok`` ante un fallo de carga o de ROI."""
    import cv2

    from spectro.qc import _measure_row

    cv2.imwrite(str(tmp_path / "ok.jpg"), render_display("0.245"))
    cv2.imwrite(str(tmp_path / "chico.jpg"), np.full((10, 10), 90, np.uint8))
    (tmp_path / "roto.jpg").write_bytes(b"no")

    def estado(nombre):
        fila = QCRow(file=nombre, t_s=0.0, index=1)
        return _measure_row(fila, tmp_path / nombre, cfg, None, None), fila

    e, fila = estado("ok.jpg")
    assert e == "ok" and fila.mean_luma > 0
    assert estado("roto.jpg")[0] == "blank" and estado("chico.jpg")[0] == "roi_outside"
    assert estado("no_existe.jpg")[0] == "blank"


def test_referencia_inexistente_cae_al_primer_fotograma_y_el_resumen_cuenta_los_descartes(cfg, tmp_path, capsys):
    """Rompe: abortar si ``reference_frame`` no existe, o no informar los descartados en el resumen."""
    import cv2

    from spectro.qc import run_qc

    cfg.qc.register = True
    cfg.qc.reference_frame = "no_existe.jpg"
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in (1, 2):
        cv2.imwrite(str(frames / f"t_{i:07d}.000.jpg"), render_display("0.245"))
    (frames / "t_0000003.000.jpg").write_bytes(b"roto")
    rows = run_qc(cfg, frames, tmp_path / "no_hay.csv", tmp_path / "qc.csv", auto_thresholds=False)
    out = capsys.readouterr().out
    assert "re-registro activo contra no_existe.jpg" in out
    assert "descartados por blank: 1" in out and "2/3 fotogramas pasan QC" in out
    assert [r.status for r in rows][2] == "blank" and rows[0].status == "ok"


def test_referencia_ilegible_no_aborta_y_se_mide_sin_registro(cfg, tmp_path):
    """Rompe: no atrapar el ``RuntimeError`` de ``_reference_patch`` (un primer fotograma roto abortaria el qc)."""
    from spectro.qc import run_qc
    import cv2

    cfg.qc.register = True
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "t_0000001.000.jpg").write_bytes(b"roto")
    cv2.imwrite(str(frames / "t_0000002.000.jpg"), render_display("0.245"))
    rows = run_qc(cfg, frames, tmp_path / "no_hay.csv", tmp_path / "qc.csv", verbose=False)
    assert [r.status for r in rows][0] == "blank" and rows[1].status == "ok" and rows[1].offset == (0, 0)


def test_con_sidecar_el_resumen_avisa_que_no_hay_registro(cfg, tmp_path, capsys):
    """Rompe: perder el aviso de que los fotogramas ya recortados no se re-registran."""
    import json

    import cv2

    from spectro.qc import run_qc

    frames = tmp_path / "frames"
    frames.mkdir()
    r = cfg.roi
    (frames / ".roi.json").write_text(json.dumps({"x": r.x, "y": r.y, "w": r.w, "h": r.h}), encoding="utf-8")
    cv2.imwrite(str(frames / "t_0000001.000.jpg"), cfg.roi.crop(render_display("0.245")))
    run_qc(cfg, frames, tmp_path / "no_hay.csv", tmp_path / "qc.csv")
    assert "sin re-registro ni ancla" in capsys.readouterr().out
