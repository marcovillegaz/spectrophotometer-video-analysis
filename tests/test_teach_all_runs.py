"""``teach train`` (sin corridas = todas): una biblioteca compartida con las muestras de todas las corridas."""

from __future__ import annotations

import csv

import cv2
import pytest

from conftest import make_config, render_display
from spectro import teach as T
from spectro.cli import main

# r1: display con signo (6 celdas). Cubre todos los digitos y el signo.
TEXTS_R1 = ["-0.333", " 4.567", "-8.901", " 2.045", " 6.789", "-0.246"]
# r2: otro video, SIN signo (5 celdas): otra geometria. Mismos nombres de fotograma que r1.
TEXTS_R2 = ["0.333", "4.567", "8.901", "2.045", "6.789", "0.246"]


def _corrida(base, run_id, texts, sign):
    run = base / "runs" / run_id
    (run / "frames").mkdir(parents=True)
    make_config(sign=sign).save(run / "config.json")
    muestras = []
    for i, t in enumerate(texts):
        name = f"t_{i * 10:07d}.000.jpg"          # los dos videos usan los mismos nombres
        cv2.imwrite(str(run / "frames" / name), render_display(t))
        muestras.append(T.Sample(name, t.strip()))
    T.save_truth(run / "teach" / "truth.csv", muestras)
    return run


@pytest.fixture
def proyecto(tmp_path):
    r1 = _corrida(tmp_path, "r1", TEXTS_R1, sign=True)
    r2 = _corrida(tmp_path, "r2", TEXTS_R2, sign=False)
    base = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    return {"base": base, "r1": r1, "r2": r2, "lib": tmp_path / "calib" / "templates", "tmp": tmp_path}


def cli(p, *args):
    return main(p["base"] + ["teach", *args])


def test_junta_las_muestras_de_todas_las_corridas_sin_pedir_run(proyecto, capsys):
    p = proyecto
    assert cli(p, "train") == 0
    salida = capsys.readouterr().out
    assert "r1" in salida and "r2" in salida and "12 lecturas exactas" in salida.replace(
        "leave-one-out sobre todas las corridas: ", "")
    assert (p["lib"] / "minus_0.png").exists() and (p["lib"] / "dot_0.png").exists()
    letras = {f.name.split("_")[0] for f in p["lib"].glob("*.png")}
    assert set("0123456789") <= letras


def test_nombres_repetidos_entre_corridas_no_se_pisan_en_el_leave_one_out(proyecto, capsys):
    """r1 y r2 tienen `t_0000000.000.jpg` y el `3` solo aparece en esos dos primeros
    fotogramas: sin identificador por corrida, validar el de r1 descartaria tambien el `3`
    de r2 y diria que "missing" ejemplos."""
    p = proyecto
    cli(p, "train")
    salida = capsys.readouterr().out
    assert "sin ejemplos" not in salida
    with (p["r1"] / "teach" / "teach_report.csv").open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    assert [f["file"] for f in filas] == [f"t_{i * 10:07d}.000.jpg" for i in range(6)]  # sin prefijo
    assert all(f["matches"] == "1" for f in filas)
    assert (p["r2"] / "teach" / "teach_report.csv").exists()


def test_cada_corrida_se_recorta_con_su_propia_config(proyecto):
    from spectro.sampling import assign  # noqa: F401  (el modulo carga sin ciclos)

    runs = T.gather_runs(proyecto["tmp"] / "runs", proyecto["tmp"] / "calib")
    assert [r.run_id for r in runs] == ["r1", "r2"]
    assert runs[0].cfg.digits.n_digits == 6 and runs[1].cfg.digits.n_digits == 5
    pool, datas, errores = T.build_pool_runs(runs)
    assert not errores and len(datas) == 12
    assert {d.ident.split("/")[0] for d in datas} == {"r1", "r2"}
    assert len({d.ident for d in datas}) == 12          # identificadores unicos
    assert all(d.cfg is not None for d in datas)


def test_excluir_una_corrida_la_reserva_como_prueba(proyecto, capsys):
    p = proyecto
    assert cli(p, "train", "--exclude", "r2") == 0
    salida = capsys.readouterr().out
    assert "excluidas" in salida and "r2" in salida
    assert not (p["r2"] / "teach" / "teach_report.csv").exists()
    assert T.gather_runs(p["tmp"] / "runs", p["tmp"] / "calib", ["r1", "r2"]) == []


def test_la_prueba_nunca_entra(proyecto, monkeypatch):
    p = proyecto
    nombre = "t_0000999.000.jpg"
    cv2.imwrite(str(p["r1"] / "frames" / nombre), render_display("-3.333"))
    T.save_truth(p["r1"] / "test" / "test.csv", [T.Sample(nombre, "-3.333")])
    vistos: list[str] = []
    original = T.build_pool

    def espia(samples, *a, **k):
        vistos.extend(s.file for s in samples)
        return original(samples, *a, **k)

    monkeypatch.setattr(T, "build_pool", espia)
    assert cli(p, "train") == 0
    assert vistos and nombre not in vistos


def test_check_valida_sin_escribir_la_biblioteca(proyecto):
    assert cli(proyecto, "check") == 0
    assert not proyecto["lib"].exists() or not list(proyecto["lib"].glob("*.png"))


def test_keep_suma_sin_duplicar_entre_corridas(proyecto):
    p = proyecto
    cli(p, "train")
    antes = sorted(f.name for f in p["lib"].glob("*.png"))
    cli(p, "train", "--keep")
    assert sorted(f.name for f in p["lib"].glob("*.png")) == antes


def test_errores_claros(proyecto, tmp_path, capsys):
    p = proyecto
    assert cli(p, "train", "--exclude", "r1", "r2") == 1          # todo excluido: nada que entrenar
    assert "muestras de entrenamiento" in capsys.readouterr().err
    assert not p["lib"].exists() or not list(p["lib"].glob("*.png"))
    vacio = ["--runs-dir", str(tmp_path / "vacio"), "--calib-dir", str(tmp_path / "calib")]
    assert main(vacio + ["teach", "train"]) == 1
    assert "muestras de entrenamiento" in capsys.readouterr().err
