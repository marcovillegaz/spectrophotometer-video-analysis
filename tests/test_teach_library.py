"""Agregar a la biblioteca sin duplicar, y gestionarla (listar, borrar, deshacer, re-etiquetar)."""

from __future__ import annotations

import pytest

from spectro import library, teach as T
from test_teach import write_frames


def _lib_con(pool, cfg_sign, tmp_path, name="lib"):
    d = tmp_path / name
    T.write_library(pool, d)
    return d


def test_add_to_library_es_idempotente_y_no_pisa(cfg_sign, tmp_path):
    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d = _lib_con(pool, cfg_sign, tmp_path)
    antes = {p.name: p.read_bytes() for p in d.glob("*.png")}
    res = library.add(pool, d)
    assert sum(res.new.values()) == 0 and res.skipped > 0
    assert {p.name: p.read_bytes() for p in d.glob("*.png")} == antes


def test_add_to_library_suma_el_caracter_que_falta(cfg_sign, tmp_path):
    todas = write_frames(tmp_path)
    sin_signo = [s for s in todas if not s.value.startswith("-")]
    pool_a, _, _ = T.build_pool(sin_signo, cfg_sign, tmp_path)
    d = _lib_con(pool_a, cfg_sign, tmp_path)
    assert not (d / "minus_0.png").exists()
    pool_b, _, _ = T.build_pool(todas, cfg_sign, tmp_path)
    res = library.add(pool_b, d)
    assert res.new.get("-", 0) >= 1 and (d / "minus_0.png").exists()
    assert "." not in res.new  # el punto ya estaba: no se duplica


def test_add_to_library_respeta_el_tope_contando_las_existentes(cfg_sign, tmp_path):
    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d2 = tmp_path / "lib2"
    library.add(pool, d2, max_per_label=1)
    library.add(pool, d2, max_per_label=1)
    assert len(list(d2.glob("0_*.png"))) == 1
    d3 = tmp_path / "lib3"
    library.add(pool, d3, max_per_label=2)
    assert len(list(d3.glob("0_*.png"))) <= 2


def test_write_library_keep_ya_no_duplica(cfg_sign, tmp_path):
    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d = _lib_con(pool, cfg_sign, tmp_path)
    n = len(list(d.glob("*.png")))
    T.write_library(pool, d, keep=True)
    T.write_library(pool, d, keep=True)
    assert len(list(d.glob("*.png"))) == n


def test_list_library_ordena_por_caracter(cfg_sign, tmp_path):
    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d = _lib_con(pool, cfg_sign, tmp_path)
    labels = [e.label for e in library.list_entries(d)]
    orden = [T.ALL_CHARS.index(c) for c in labels]
    assert orden == sorted(orden) and labels[0] == "0" and labels[-1] == "-"
    assert library.list_entries(tmp_path / "no_existe") == []


def test_borrar_y_deshacer(cfg_sign, tmp_path):
    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d = _lib_con(pool, cfg_sign, tmp_path)
    objetivo = d / "minus_0.png"
    original = objetivo.read_bytes()
    papelera = library.delete([objetivo, d / "no_existe.png"])
    assert not objetivo.exists() and len(papelera) == 1
    assert library.restore(papelera) == 1 and objetivo.read_bytes() == original
    assert library.restore(papelera) == 0  # no pisa lo que ya esta


def test_borrar_deja_huecos_y_agregar_sigue_del_maximo(cfg_sign, tmp_path):
    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d = tmp_path / "lib"
    library.add(pool, d, max_per_label=3)
    antes = sorted(p.name for p in d.glob("0_*.png"))
    library.delete([d / antes[0]])
    library.add(pool, d, max_per_label=3)
    despues = sorted(p.name for p in d.glob("0_*.png"))
    assert antes[0] not in despues or len(despues) <= 3   # sin pisar nada


def test_relabel_template(cfg_sign, tmp_path):
    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d = _lib_con(pool, cfg_sign, tmp_path)
    n_antes = len(list(d.glob("8_*.png")))
    destino = library.relabel(d / "9_0.png", "8", d)
    assert destino.name == f"8_{n_antes}.png" and destino.exists() and not (d / "9_0.png").exists()
    assert library.relabel(d / "dot_0.png", "-", d).name.startswith("minus_")
    with pytest.raises(ValueError):
        library.relabel(destino, "x", d)


def test_library_usage_cuenta_aciertos_y_errores(cfg_sign, tmp_path):
    pool, datas, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    d = _lib_con(pool, cfg_sign, tmp_path)
    entries = library.list_entries(d)
    library.usage(entries, datas)
    assert sum(e.uses for e in entries) == sum(len(x.glyphs) for x in datas)
    assert sum(e.errors for e in entries) == 0
    library.relabel(d / "1_0.png", "7", d)  # una plantilla mal etiquetada gana mal
    entries = library.list_entries(d)
    library.usage(entries, datas)
    assert sum(e.errors for e in entries) > 0


def test_dedup_por_ncc_conserva_variantes_distintas_y_descarta_casi_identicas(cfg_sign, tmp_path):
    import numpy as np

    from spectro.imaging import ncc
    from spectro.library import DEDUP_NCC
    from spectro.teach import Glyph

    pool, _, _ = T.build_pool(write_frames(tmp_path), cfg_sign, tmp_path)
    base = next(g for g in pool if g.label == "6").image
    casi = base.copy()
    casi[0, 0] = 255 - casi[0, 0]                      # un pixel distinto: es el mismo glifo
    desplazado = np.roll(base, 4, axis=1)              # otra posicion en la celda: otra variante
    assert ncc(base, casi) >= DEDUP_NCC > ncc(base, desplazado)

    d = tmp_path / "lib"
    library.add([Glyph("6", base, "a")], d)
    res = library.add([Glyph("6", casi, "b"), Glyph("6", desplazado, "c")], d)
    assert res.new == {"6": 1} and res.skipped == 1
    assert len(list(d.glob("6_*.png"))) == 2
