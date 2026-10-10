"""``teach``: valores escritos -> celdas -> plantillas -> validacion leave-one-out."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from conftest import make_config, render_display
from spectro import teach as T
from spectro.imaging import ncc
from spectro.library import dedup

TEXTS = ["-0.123", " 4.567", "-8.901", " 2.345", " 6.789", "-0.246", " 1.357", " 9.048"]


def shift(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)


def write_frames(tmp_path, texts=TEXTS, dx=0, dy=0):
    samples = []
    for i, text in enumerate(texts):
        name = f"t_{i:07d}.000.jpg"
        cv2.imwrite(str(tmp_path / name), shift(render_display(text), dx, dy))
        samples.append(T.Sample(name, text.strip()))
    return samples


# -- valores -> celdas ---------------------------------------------------
def test_value_to_cells_con_y_sin_signo(cfg_sign):
    assert T.value_to_cells("-0.245", cfg_sign.digits) == ["-", "0", ".", "2", "4", "5"]
    assert T.value_to_cells("0.245", cfg_sign.digits) == [" ", "0", ".", "2", "4", "5"]
    assert T.value_to_cells("0,245", cfg_sign.digits) == [" ", "0", ".", "2", "4", "5"]


def test_value_to_cells_sin_celda_de_signo(cfg):
    assert T.value_to_cells("0.245", cfg.digits) == ["0", ".", "2", "4", "5"]
    with pytest.raises(ValueError, match="signo"):
        T.value_to_cells("-0.245", cfg.digits)


@pytest.mark.parametrize("bad", ["12.345", "0.24", "abc", "-", ".", "", "0.2455"])
def test_value_to_cells_rechaza_formato(cfg_sign, bad):
    with pytest.raises(ValueError):
        T.value_to_cells(bad, cfg_sign.digits)


def test_truth_conserva_texto_y_signo(tmp_path):
    p = tmp_path / "truth.csv"
    T.save_truth(p, [T.Sample("b.jpg", "-0.000"), T.Sample("a.jpg", "0.500")])
    got = T.load_truth(p)
    assert [(s.archivo, s.valor) for s in got] == [("a.jpg", "0.500"), ("b.jpg", "-0.000")]
    assert T.load_truth(tmp_path / "no_existe.csv") == []


def test_coverage_y_suggest(cfg_sign):
    cov = T.coverage([T.Sample("a", "-0.123"), T.Sample("b", "1.000"), T.Sample("c", "zzz")],
                     cfg_sign.digits)
    assert cov["-"] == 1 and cov["0"] == 4 and cov["."] == 2 and cov["9"] == 0
    names = [f"t_{i}" for i in range(100)]
    sug = T.suggest_frames(names, 10)
    assert len(sug) == 10 and sug[0] == "t_0" and sug[-1] == "t_99"
    assert T.suggest_frames([], 5) == [] and len(T.suggest_frames(names[:3], 10)) == 3


# -- biblioteca ----------------------------------------------------------
def test_build_y_leave_one_out_perfecto(cfg_sign, tmp_path):
    samples = write_frames(tmp_path)
    pool, datas, errores = T.build_pool(samples, cfg_sign, tmp_path)
    assert not errores and len(datas) == len(TEXTS)
    # la celda de signo vacia no genera plantilla
    assert all(g.label != " " for g in pool)
    rep = T.validate(datas, pool, cfg_sign)
    assert rep.exact == rep.total == len(TEXTS), T.format_report(rep)


def test_offset_alinea_los_glifos(cfg_sign, tmp_path):
    samples = write_frames(tmp_path, dx=5, dy=-3)
    (tmp_path / "ref").mkdir()
    ref = write_frames(tmp_path / "ref", texts=["-0.123"])  # sin desplazar
    con, _, _ = T.build_pool(samples[:1], cfg_sign, tmp_path, {samples[0].archivo: (5, -3)})
    sin, _, _ = T.build_pool(samples[:1], cfg_sign, tmp_path, None)
    limpio, _, _ = T.build_pool(ref, cfg_sign, tmp_path / "ref")
    n_con = min(ncc(a.image, b.image) for a, b in zip(con, limpio))
    n_sin = min(ncc(a.image, b.image) for a, b in zip(sin, limpio))
    assert n_con > n_sin


def test_write_library_reemplaza_y_keep_no_pisa(cfg_sign, tmp_path):
    samples = write_frames(tmp_path)
    pool, _, _ = T.build_pool(samples, cfg_sign, tmp_path)
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "viejo_0.png").write_bytes(b"x")
    nuevas = T.write_library(pool, lib, cfg_sign)
    assert not (lib / "viejo_0.png").exists()
    assert (lib / "minus_0.png").exists() and (lib / "dot_0.png").exists()
    assert set(nuevas) == set("0123456789.-")
    antes = {p.name: p.read_bytes() for p in lib.glob("*.png")}
    T.write_library(pool, lib, cfg_sign, keep=True)
    despues = {p.name: p.read_bytes() for p in lib.glob("*.png")}
    assert all(despues[k] == v for k, v in antes.items())  # nada pisado
    assert len(despues) >= len(antes)


def test_max_per_label(cfg_sign, tmp_path):
    samples = write_frames(tmp_path)
    pool, _, _ = T.build_pool(samples, cfg_sign, tmp_path)
    assert all(
        sum(1 for g in dedup(pool, 1) if g.label == c) == 1
        for c in "0123456789.-"
    )


def test_validate_senala_el_valor_mal_escrito(cfg_sign, tmp_path):
    samples = write_frames(tmp_path)
    samples[0] = T.Sample(samples[0].archivo, "7.123")  # el display dice -0.123
    pool, datas, _ = T.build_pool(samples, cfg_sign, tmp_path)
    rep = T.validate(datas, pool, cfg_sign)
    assert samples[0].archivo in [r.archivo for r in rep.mismatches]
    assert rep.confusion  # alguna confusion registrada


def test_validate_avisa_caracter_sin_ejemplos(cfg_sign, tmp_path):
    samples = write_frames(tmp_path, texts=["-0.123", " 4.567"])
    pool, datas, _ = T.build_pool(samples, cfg_sign, tmp_path)
    rep = T.validate(datas, pool, cfg_sign)
    r = next(r for r in rep.results if r.escrito == "-0.123")
    assert "-" in r.faltan and not r.coincide


def test_evaluate_library_y_report(cfg_sign, library_sign, tmp_path):
    samples = write_frames(tmp_path, texts=["-0.245", " 1.789"])
    _, datas, _ = T.build_pool(samples, cfg_sign, tmp_path)
    rep = T.evaluate_library(datas, library_sign, cfg_sign)
    assert rep.exact == rep.total == 2
    out = T.write_report(rep, tmp_path / "out" / "teach_report.csv")
    assert out.exists() and "coincide" in out.read_text(encoding="utf-8")


def test_muestra_con_valor_de_otra_geometria_se_descarta(cfg_sign, tmp_path):
    samples = write_frames(tmp_path, texts=["-0.123"]) + [T.Sample("t_0000000.000.jpg", "12.5")]
    _, datas, errores = T.build_pool(samples, cfg_sign, tmp_path)
    assert len(errores) == 1 and len(datas) == 1
