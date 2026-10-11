"""``teach`` por areas (Fase 2): sintaxis nueva, rechazo de la vieja y cada verbo en un proyecto de juguete.

Arbol: ``teach status | lib {list,delete,relabel,clear,backups,restore} | train | check |
samples {list,add,remove,suggest,label} | test {list,add,remove,suggest,label,eval,history}``.
El id de la corrida va como argumento posicional; ``--run`` y ``--config`` se rechazan.
"""

from __future__ import annotations

import csv
import os
import time

import cv2
import pytest

from conftest import make_config, render_display
from spectro import library as L
from spectro import teach as T
from spectro.cli import main
from spectro.config import AcceptanceConfig, Config
from spectro.qc import QCRow, write_qc_report
from spectro.teach_cli import AREAS, MIGRACION, legacy_error

TRAIN = ["-0.123", " 4.567", "-8.901", " 2.345", " 6.789", "-0.246", " 1.357", " 9.048"]
TEST = [" 3.456", "-7.890"]


def _nombre(t: int) -> str:
    return f"t_{t:07d}.000.jpg"


def _corrida(base, run_id, train=TRAIN, test=TEST, sign=True):
    run = base / "runs" / run_id
    (run / "frames").mkdir(parents=True)
    make_config(sign=sign).save(run / "config.json")
    muestras_t, muestras_p = [], []
    for i, t in enumerate(train):
        cv2.imwrite(str(run / "frames" / _nombre(i * 10)), render_display(t))
        muestras_t.append(T.Sample(_nombre(i * 10), t.strip()))
    for i, t in enumerate(test):
        cv2.imwrite(str(run / "frames" / _nombre(100 + i * 10)), render_display(t))
        muestras_p.append(T.Sample(_nombre(100 + i * 10), t.strip()))
    if muestras_t:
        T.save_truth(run / "truth.csv", muestras_t)
    if muestras_p:
        T.save_truth(run / "test.csv", muestras_p)
    return run


@pytest.fixture
def p(tmp_path):
    run = _corrida(tmp_path, "r1")
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    return {"glob": glob, "run": run, "tmp": tmp_path, "calib": tmp_path / "calib",
            "lib": tmp_path / "calib" / "templates", "runs": tmp_path / "runs"}


def teach(p, *args):
    return main(p["glob"] + ["teach", *args])


def entrenar(p):
    assert teach(p, "train", "r1") == 0


def pngs(p):
    return {f.name: f.read_bytes() for f in p["lib"].glob("*.png")}


def instantanea(raiz):
    """Todos los archivos bajo ``raiz`` con su contenido: para probar que algo no escribe nada."""
    return {str(f.relative_to(raiz)): f.read_bytes() for f in raiz.rglob("*") if f.is_file()}


# ==========================================================================
# legacy_error: la sintaxis vieja
# ==========================================================================
@pytest.mark.parametrize("argv", [
    ["teach"],
    ["teach", "--build"],
    ["teach", "--run", "r1", "--build"],
    ["--run", "r1", "teach", "--check"],
    ["--runs-dir", "x", "--calib-dir", "y", "teach", "--eval-all"],
    ["--runs-dir=x", "teach", "--all-runs", "--build"],
    ["teach", "--run=r1", "--add", "a.jpg=0.1"],
    ["teach", "--library"],
    ["teach", "--suggest", "5", "--for", "test"],
    ["teach", "--delete", "0_3"],
])
def test_legacy_error_devuelve_la_tabla_de_migracion_para_la_sintaxis_vieja(argv):
    """Rompe: que `teach --flag` siga pareciendo valido (o que el prefijo global confunda al detector)."""
    assert legacy_error(argv) == MIGRACION
    assert "teach train ID" in MIGRACION and "teach test eval" in MIGRACION


@pytest.mark.parametrize("argv", [
    [],
    ["doctor"],
    ["qc", "--run", "x"],
    ["--run", "x", "qc"],
    ["teach", "status"],
    ["teach", "-h"],
    ["teach", "--help"],
    ["--run", "r1", "teach", "status"],
    ["teach", "--run", "r1", "status"],
    ["teach", "--runs-dir=x", "lib", "list"],
    ["--calib-dir", "c", "teach", "train", "r1", "--keep"],
] + [["teach", a] for a in AREAS])
def test_legacy_error_no_toca_lo_que_no_es_la_sintaxis_vieja(argv):
    assert legacy_error(argv) is None


def test_la_tabla_de_migracion_nombra_todas_las_areas_y_no_usa_tildes():
    for area in AREAS:
        assert area in MIGRACION
    assert all(ord(c) < 128 for c in MIGRACION)


def test_main_rechaza_la_sintaxis_vieja_con_codigo_2_y_sin_escribir_nada(p, capsys):
    antes = instantanea(p["tmp"])
    assert teach(p, "--run", "r1", "--build") == 2
    captura = capsys.readouterr()
    assert captura.err.startswith("ERROR:") and "teach train ID" in captura.err
    assert captura.out == ""
    assert instantanea(p["tmp"]) == antes and not p["lib"].exists()


def test_main_sin_argv_mira_sys_argv(p, monkeypatch, capsys):
    """main() sin argumentos lee sys.argv: el detector tiene que verlo tambien por ahi."""
    monkeypatch.setattr("sys.argv", ["spectro", *p["glob"], "teach", "--build"])
    assert main() == 2
    assert "teach train ID" in capsys.readouterr().err


def test_teach_sin_area_da_la_tabla_de_migracion_con_codigo_2(p, capsys):
    assert teach(p) == 2
    assert "teach train ID" in capsys.readouterr().err


def test_area_desconocida_nombra_el_area_y_lista_las_validas(p, capsys):
    """Rompe: tratar `teach foo` como sintaxis vieja (tabla de migracion) en vez de decir que el area no existe."""
    assert teach(p, "foo") == 2
    err = capsys.readouterr().err
    assert "area desconocida 'foo'" in err
    assert all(a in err for a in AREAS) and "teach train ID" not in err
    assert legacy_error(["--run", "r1", "teach", "foo", "x"]).startswith("area desconocida 'foo'")
    assert legacy_error(["teach", "--run", "r1", "foo"]).startswith("area desconocida 'foo'")


def test_cada_area_exige_un_verbo(p):
    for area in ("lib", "samples", "test"):
        with pytest.raises(SystemExit) as exc:
            teach(p, area)
        assert exc.value.code == 2


# ==========================================================================
# --run y --config se rechazan (el id va como argumento)
# ==========================================================================
VERBOS = [
    ["status"],
    ["lib", "list"],
    ["lib", "backups"],
    ["lib", "restore"],
    ["lib", "clear", "--yes"],
    ["lib", "delete", "0_0"],
    ["lib", "relabel", "0_0", "1"],
    ["train", "r1"],
    ["check", "r1"],
    ["samples", "list", "r1"],
    ["samples", "add", "r1", "t_0000000.000.jpg=-0.123"],
    ["samples", "remove", "r1", "t_0000000.000.jpg"],
    ["samples", "suggest", "r1", "3"],
    ["test", "list", "r1"],
    ["test", "add", "r1", "t_0000100.000.jpg=3.456"],
    ["test", "remove", "r1", "t_0000100.000.jpg"],
    ["test", "suggest", "r1", "3"],
    ["test", "eval", "r1"],
    ["test", "history", "r1"],
]


@pytest.mark.parametrize("verbo", VERBOS, ids=lambda v: " ".join(v))
def test_run_global_se_rechaza_en_cada_verbo_y_no_escribe_nada(p, verbo, capsys):
    """Rompe: que un verbo se olvide de llamar a _guard y acepte --run (mezclaria corridas)."""
    entrenar(p)
    capsys.readouterr()
    antes = instantanea(p["tmp"])
    assert main(p["glob"] + ["--run", "r1", "teach", *verbo]) == 1
    err = capsys.readouterr().err
    assert "teach no usa --run" in err and "teach samples list r1" in err
    assert instantanea(p["tmp"]) == antes


@pytest.mark.parametrize("verbo", VERBOS, ids=lambda v: " ".join(v))
def test_run_despues_del_verbo_tambien_se_rechaza(p, verbo, capsys):
    assert main(p["glob"] + ["teach", *verbo, "--run", "r1"]) == 1
    assert "teach no usa --run" in capsys.readouterr().err


@pytest.mark.parametrize("verbo", VERBOS, ids=lambda v: " ".join(v))
def test_config_se_rechaza_en_cada_verbo(p, verbo, capsys):
    assert main(p["glob"] + ["teach", *verbo, "--config", str(p["run"] / "config.json")]) == 1
    assert "teach no usa --config" in capsys.readouterr().err


# ==========================================================================
# status
# ==========================================================================
def test_status_sin_corridas_ni_biblioteca_sugiere_crear_una(tmp_path, capsys):
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(glob + ["teach", "status"]) == 0
    salida = capsys.readouterr().out
    assert "0 plantillas" in salida and "(ninguna)" in salida and "spectro new" in salida
    assert not (tmp_path / "calib").exists()          # mirar no crea carpetas


def test_status_con_muestras_y_sin_biblioteca_sugiere_entrenar(p, capsys):
    assert teach(p, "status") == 0
    salida = capsys.readouterr().out
    assert "0 plantillas" in salida and "la biblioteca esta vacia: python -m spectro teach train" in salida
    fila = next(x for x in salida.splitlines() if x.strip().startswith("r1"))
    assert fila.split()[1:3] == ["8", "2"]          # entrenamiento, prueba
    assert "sin_lectura" in fila


def test_status_no_escribe_nada(p):
    entrenar(p)
    antes = instantanea(p["tmp"])
    assert teach(p, "status") == 0
    assert instantanea(p["tmp"]) == antes


def test_status_sin_muestras_ni_biblioteca_manda_a_etiquetar(tmp_path, capsys):
    _corrida(tmp_path, "r1", train=[], test=[])
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(glob + ["teach", "status"]) == 0
    assert "teach samples label <id>" in capsys.readouterr().out


def test_status_con_biblioteca_lista_huella_cobertura_y_respaldos(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "status") == 0
    salida = capsys.readouterr().out
    assert f"{len(L.load(p['lib']))} plantillas" in salida
    assert f"huella {L.fingerprint(p['lib'])}" in salida
    assert "faltan: ninguno" in salida and "respaldos: 0" in salida


def test_status_avisa_la_falta_del_menos_y_propone_etiquetar_negativos(tmp_path, capsys):
    _corrida(tmp_path, "r1", train=[" 0.123", " 4.567", " 8.901", " 2.345", " 6.789", " 1.357"], test=[])
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(glob + ["teach", "train", "r1"]) == 0
    capsys.readouterr()
    assert main(glob + ["teach", "status"]) == 0
    salida = capsys.readouterr().out
    assert "no hay plantilla '-'" in salida
    assert "falta la plantilla '-'" in salida and "faltan: '-'" in salida


def test_status_cuenta_roi_fuera_en_la_tabla_de_descartes(p, capsys):
    """Rompe: dejar roi_fuera fuera de la tabla de motivos de descarte de status."""
    write_qc_report([QCRow(_nombre(0), 0.0, 1), QCRow(_nombre(10), 10.0, 2, estado="roi_fuera"),
                     QCRow(_nombre(20), 20.0, 3, estado="roi_fuera")], p["run"] / "out" / "qc_report.csv")
    assert teach(p, "status") == 0
    salida = capsys.readouterr().out
    cab = next(x for x in salida.splitlines() if x.split()[-1:] == ["roi_fuera"])
    fila = salida.splitlines()[salida.splitlines().index(cab) + 1].split()
    columnas = cab.split()
    assert fila[0] == "r1" and fila[columnas.index("roi_fuera")] == "2"


def test_status_de_una_corrida_sin_qc_lo_dice(p, capsys):
    assert teach(p, "status") == 0
    assert "(sin qc_report.csv)" in capsys.readouterr().out


def test_status_marca_las_salidas_desactualizadas_y_propone_releer(p, capsys):
    entrenar(p)
    out = p["run"] / "out"
    (out / "readings.csv").write_text("archivo\n", encoding="utf-8")
    (out / "read_meta.json").write_text('{"huella": "000000000000"}', encoding="utf-8")
    capsys.readouterr()
    assert teach(p, "status") == 0
    salida = capsys.readouterr().out
    assert "desactualizadas" in salida
    assert "las salidas de r1 son anteriores a la biblioteca" in salida and "read --run r1" in salida


def test_status_con_salidas_al_dia_no_pide_releer(p, capsys):
    from spectro.read import write_read_meta

    entrenar(p)
    out = p["run"] / "out"
    (out / "readings.csv").write_text("archivo\n", encoding="utf-8")
    write_read_meta(out / "read_meta.json", p["lib"], len(L.load(p["lib"])))
    capsys.readouterr()
    assert teach(p, "status") == 0
    salida = capsys.readouterr().out
    assert "al_dia" in salida and "son anteriores a la biblioteca" not in salida


def test_status_pide_evaluar_la_prueba_y_deja_de_pedirlo_tras_evaluar(p, capsys):
    entrenar(p)
    for f in p["lib"].glob("*.png"):                 # biblioteca claramente anterior a la evaluacion
        t = time.time() - 3600
        os.utime(f, (t, t))
    capsys.readouterr()
    assert teach(p, "status") == 0
    assert "la prueba de r1 no se evaluo con la biblioteca vigente" in capsys.readouterr().out
    assert teach(p, "test", "eval", "r1") == 0
    capsys.readouterr()
    assert teach(p, "status") == 0
    salida = capsys.readouterr().out
    assert "no se evaluo con la biblioteca vigente" not in salida and "exactitud 100.0%" in salida


def test_status_no_pide_evaluar_si_no_hay_prueba(p, capsys):
    (p["run"] / "test.csv").unlink()
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "status") == 0
    assert "no se evaluo" not in capsys.readouterr().out


# ==========================================================================
# lib list / delete / relabel / clear / backups / restore
# ==========================================================================
def test_lib_list_muestra_plantillas_por_caracter_y_los_que_faltan(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "lib", "list") == 0
    salida = capsys.readouterr().out
    assert "12 plantillas" in salida and f"huella {L.fingerprint(p['lib'])}" in salida
    assert "'7'" in salida and "7_0" in salida and "faltan: ninguno" in salida
    L.delete([p["lib"] / "minus_0.png"])
    capsys.readouterr()
    assert teach(p, "lib", "list") == 0
    assert "faltan: '-'" in capsys.readouterr().out


def test_lib_list_sin_biblioteca_dice_que_faltan_todos_y_sale_con_0(p, capsys):
    assert teach(p, "lib", "list") == 0
    salida = capsys.readouterr().out
    assert "0 plantillas" in salida and "huella -" in salida and "faltan: '-'" in salida


def test_lib_list_usage_mide_uso_sin_modificar_la_biblioteca(p, capsys):
    entrenar(p)
    antes = pngs(p)
    capsys.readouterr()
    assert teach(p, "lib", "list", "--usage") == 0
    salida = capsys.readouterr().out
    assert "uso medido sobre" in salida and "de 1 corridas" in salida and "gana bien" in salida
    assert pngs(p) == antes


def test_lib_delete_borra_las_plantillas_y_deja_un_respaldo(p, capsys):
    entrenar(p)
    antes = pngs(p)
    capsys.readouterr()
    assert teach(p, "lib", "delete", "0_0", "5_0") == 0
    salida = capsys.readouterr().out
    assert "2 plantillas borradas" in salida and "lib restore" in salida
    assert set(antes) - set(pngs(p)) == {"0_0.png", "5_0.png"}
    (nombre,) = L.list_backups(p["lib"])
    assert len(list((L.backups_root(p["lib"]) / nombre).glob("*.png"))) == len(antes)


def test_lib_delete_con_un_nombre_inexistente_no_borra_nada(p, capsys):
    """Rompe: validar nombre por nombre mientras se borra (dejaria la biblioteca a medias)."""
    entrenar(p)
    antes = pngs(p)
    capsys.readouterr()
    assert teach(p, "lib", "delete", "0_0", "9_9") == 1
    assert "No existe la plantilla '9_9'" in capsys.readouterr().err
    assert pngs(p) == antes and L.list_backups(p["lib"]) == []


def test_lib_delete_acepta_el_nombre_con_extension(p):
    entrenar(p)
    assert teach(p, "lib", "delete", "0_0.png") == 0
    assert "0_0.png" not in pngs(p)


def test_lib_relabel_renombra_al_proximo_indice_libre_y_respalda(p, capsys):
    entrenar(p)
    antes = pngs(p)
    capsys.readouterr()
    assert teach(p, "lib", "relabel", "0_0", "5") == 0
    assert "0_0.png -> 5_1.png" in capsys.readouterr().out
    despues = pngs(p)
    assert "0_0.png" not in despues and despues["5_1.png"] == antes["0_0.png"]
    assert len(L.list_backups(p["lib"])) == 1


def test_lib_relabel_con_caracter_invalido_o_plantilla_inexistente_no_toca_nada(p, capsys):
    entrenar(p)
    antes = pngs(p)
    capsys.readouterr()
    assert teach(p, "lib", "relabel", "0_0", "x") == 1
    assert "etiqueta invalida" in capsys.readouterr().err
    assert teach(p, "lib", "relabel", "9_9", "1") == 1
    assert "No existe la plantilla" in capsys.readouterr().err
    assert pngs(p) == antes


def test_lib_clear_sin_yes_se_niega_y_no_toca_nada(p, capsys):
    """Rompe: que clear borre sin --yes (la biblioteca es compartida por todos los videos)."""
    entrenar(p)
    antes = pngs(p)
    capsys.readouterr()
    assert teach(p, "lib", "clear") == 1
    assert "--yes" in capsys.readouterr().err
    assert pngs(p) == antes and L.list_backups(p["lib"]) == []


def test_lib_clear_con_yes_vacia_y_deja_un_respaldo_completo(p, capsys):
    entrenar(p)
    antes = pngs(p)
    capsys.readouterr()
    assert teach(p, "lib", "clear", "--yes") == 0
    assert f"{len(antes)} plantillas borradas" in capsys.readouterr().out
    assert pngs(p) == {}
    (nombre,) = L.list_backups(p["lib"])
    respaldo = L.backups_root(p["lib"]) / nombre
    assert {f.name: f.read_bytes() for f in respaldo.glob("*.png")} == antes


def test_lib_clear_sobre_una_biblioteca_vacia_no_falla_ni_crea_respaldo(p, capsys):
    assert teach(p, "lib", "clear", "--yes") == 0
    assert "0 plantillas borradas" in capsys.readouterr().out
    assert L.list_backups(p["lib"]) == []


def test_lib_backups_sin_respaldos_y_con_respaldos(p, capsys):
    assert teach(p, "lib", "backups") == 0
    assert "(ninguno)" in capsys.readouterr().out
    entrenar(p)
    n = len(pngs(p))
    teach(p, "lib", "delete", "0_0")
    capsys.readouterr()
    assert teach(p, "lib", "backups") == 0
    salida = capsys.readouterr().out
    assert L.list_backups(p["lib"])[0] in salida and f"{n} plantillas" in salida


def test_lib_restore_recupera_la_biblioteca_exacta_tras_un_clear(p, capsys):
    """Rompe: que restore devuelva archivos distintos (otro contenido) o no los devuelva."""
    entrenar(p)
    antes = pngs(p)
    teach(p, "lib", "clear", "--yes")
    capsys.readouterr()
    assert teach(p, "lib", "restore") == 0
    assert "biblioteca restaurada desde el respaldo" in capsys.readouterr().out
    assert pngs(p) == antes


def test_lib_restore_respalda_antes_el_estado_actual(p, capsys):
    entrenar(p)
    original = pngs(p)
    teach(p, "lib", "delete", "0_0")                    # respaldo 1: la original
    capsys.readouterr()
    assert teach(p, "lib", "restore") == 0
    salida = capsys.readouterr().out
    assert "el estado anterior quedo respaldado como" in salida
    assert pngs(p) == original
    nombres = L.list_backups(p["lib"])
    assert len(nombres) == 2
    ultimo = L.backups_root(p["lib"]) / nombres[-1]
    assert "0_0.png" not in {f.name for f in ultimo.glob("*.png")}      # el estado de antes de restaurar


def test_lib_restore_de_un_respaldo_por_nombre(p):
    entrenar(p)
    original = pngs(p)
    teach(p, "lib", "delete", "0_0")
    (primero,) = L.list_backups(p["lib"])
    teach(p, "lib", "delete", "1_0")                      # segundo respaldo: ya sin 0_0
    assert "0_0.png" not in pngs(p) and "1_0.png" not in pngs(p)
    assert teach(p, "lib", "restore", primero) == 0
    assert pngs(p) == original


def test_lib_restore_sin_respaldos_o_con_nombre_inexistente_falla_sin_tocar_nada(p, capsys):
    assert teach(p, "lib", "restore") == 1
    assert "No hay respaldos" in capsys.readouterr().err
    entrenar(p)
    teach(p, "lib", "delete", "0_0")
    antes, respaldos = pngs(p), L.list_backups(p["lib"])
    capsys.readouterr()
    assert teach(p, "lib", "restore", "20000101_000000") == 1
    err = capsys.readouterr().err
    assert "No existe el respaldo" in err and respaldos[0] in err
    assert pngs(p) == antes and L.list_backups(p["lib"]) == respaldos


# ==========================================================================
# train / check
# ==========================================================================
def test_train_sobre_una_biblioteca_existente_la_respalda_y_la_reemplaza(p, capsys):
    entrenar(p)
    anterior = pngs(p)
    capsys.readouterr()
    assert teach(p, "train", "r1") == 0
    assert "respaldo de la biblioteca anterior:" in capsys.readouterr().out
    (nombre,) = L.list_backups(p["lib"])
    respaldo = L.backups_root(p["lib"]) / nombre
    assert {f.name: f.read_bytes() for f in respaldo.glob("*.png")} == anterior


def test_train_dos_veces_da_la_misma_biblioteca(p):
    """Idempotencia: las mismas muestras producen la misma huella."""
    entrenar(p)
    huella = L.fingerprint(p["lib"])
    entrenar(p)
    assert L.fingerprint(p["lib"]) == huella


def test_train_primero_en_vacio_no_crea_respaldo(p, capsys):
    capsys.readouterr()
    entrenar(p)
    assert "respaldo de la biblioteca anterior" not in capsys.readouterr().out
    assert L.list_backups(p["lib"]) == []


def test_check_no_escribe_plantillas_ni_respaldos_con_biblioteca_existente(p):
    entrenar(p)
    antes = pngs(p)
    assert teach(p, "check", "r1") == 0
    assert pngs(p) == antes and L.list_backups(p["lib"]) == []


def test_check_compara_leave_one_out_con_la_biblioteca_vigente(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "check", "r1") == 0
    salida = capsys.readouterr().out
    assert "== teach check ==" in salida and "biblioteca vigente" in salida
    fila = next(x for x in salida.splitlines() if x.strip().startswith("r1") and "/" in x)
    assert fila.split()[1] == "8/8" and fila.split()[2] == "8/8"


def test_train_con_una_corrida_inexistente_falla_con_las_disponibles(p, capsys):
    assert teach(p, "train", "r9") == 1
    err = capsys.readouterr().err
    assert "No existe la corrida 'r9'" in err and "r1" in err
    assert not p["lib"].exists()


def test_train_con_una_corrida_sin_muestras_nombra_la_corrida(p, capsys):
    _corrida(p["tmp"], "r2", train=[], test=[])
    assert teach(p, "train", "r1", "r2") == 1
    assert "La corrida r2 no tiene muestras de entrenamiento" in capsys.readouterr().err
    assert not p["lib"].exists()


def test_train_sin_ids_ignora_las_corridas_sin_muestras(p, capsys):
    _corrida(p["tmp"], "r2", train=[], test=[])
    assert teach(p, "train") == 0
    salida = capsys.readouterr().out
    assert "r1" in salida and "r2" not in salida


def test_train_con_un_id_repetido_lo_cuenta_una_vez(p, capsys):
    assert teach(p, "train", "r1", "r1") == 0
    assert capsys.readouterr().out.count("muestras de entrenamiento") == 1


def test_train_exclude_deja_la_corrida_afuera(p, capsys):
    _corrida(p["tmp"], "r2", train=["0.333", "4.567", "8.901", "2.045", "6.789"], test=[], sign=False)
    assert teach(p, "train", "--exclude", "r2") == 0
    assert "excluidas (quedan como prueba): r2" in capsys.readouterr().out
    assert not (p["tmp"] / "runs" / "r2" / "out" / "teach_report.csv").exists()


def test_train_avisa_si_una_prueba_esta_pegada_al_entrenamiento(p, capsys):
    """Entrenamiento hasta t=70 y prueba en t=100: a --gap 40 s esta demasiado cerca."""
    assert teach(p, "train", "r1", "--gap", "40") == 0
    assert "fotogramas de prueba de r1 estan a menos de 40 s" in capsys.readouterr().out
    assert teach(p, "train", "r1", "--gap", "5") == 0
    assert "estan a menos de" not in capsys.readouterr().out


def test_train_avisa_si_falta_el_menos_en_una_geometria_con_signo(tmp_path, capsys):
    _corrida(tmp_path, "r1", train=[" 0.123", " 4.567", " 8.901", " 2.345", " 6.789", " 1.357"], test=[])
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(glob + ["teach", "train", "r1"]) == 0
    salida = capsys.readouterr().out
    assert "no hay plantilla '-'" in salida and "faltan ejemplos de -" in salida


def test_train_con_muestras_que_no_se_pueden_procesar_falla_y_no_deja_biblioteca(p, capsys):
    """Los fotogramas de las muestras no existen: ninguna muestra se procesa."""
    for f in (p["run"] / "frames").glob("*.jpg"):
        f.unlink()
    assert teach(p, "train", "r1") == 1
    assert "Ninguna muestra se pudo procesar" in capsys.readouterr().err
    assert not p["lib"].exists() or not list(p["lib"].glob("*.png"))


def test_train_no_usa_las_pruebas(p, monkeypatch):
    """Rompe: que train cuele test.csv en el pool (la prueba nunca entra a la biblioteca)."""
    vistos = []
    original = T.build_pool

    def espia(samples, *a, **k):
        vistos.extend(s.archivo for s in samples)
        return original(samples, *a, **k)

    monkeypatch.setattr(T, "build_pool", espia)
    entrenar(p)
    probadas = {s.archivo for s in T.load_truth(p["run"] / "test.csv")}
    assert vistos and not probadas & set(vistos)


# ==========================================================================
# samples / test: list, add, remove, suggest, label
# ==========================================================================
@pytest.mark.parametrize("area, archivo, n", [("samples", "truth.csv", 8), ("test", "test.csv", 2)])
def test_list_de_una_corrida_muestra_cada_muestra_y_su_cobertura(p, capsys, area, archivo, n):
    assert teach(p, area, "list", "r1") == 0
    salida = capsys.readouterr().out
    assert f"{n} muestras de" in salida and archivo in salida
    assert sum(1 for x in salida.splitlines() if x.strip().startswith("t_")) == n
    assert "cobertura:" in salida and "no hay plantillas todavia" in salida


def test_list_con_biblioteca_dice_cuantas_lee_bien(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "samples", "list", "r1") == 0
    assert "lee bien 8/8" in capsys.readouterr().out
    assert teach(p, "test", "list", "r1") == 0
    assert "lee bien 2/2" in capsys.readouterr().out


def test_list_sin_corrida_da_una_tabla_por_corrida(p, capsys):
    _corrida(p["tmp"], "r2", train=["0.333", "4.567"], test=[], sign=False)
    assert teach(p, "samples", "list") == 0
    salida = capsys.readouterr().out
    r1 = next(x for x in salida.splitlines() if x.strip().startswith("r1")).split()
    r2 = next(x for x in salida.splitlines() if x.strip().startswith("r2")).split()
    assert r1[1] == "8" and r2[1] == "2"
    assert teach(p, "test", "list") == 0
    salida = capsys.readouterr().out
    assert next(x for x in salida.splitlines() if x.strip().startswith("r1")).split()[1] == "2"
    assert next(x for x in salida.splitlines() if x.strip().startswith("r2")).split()[1] == "0"


def test_list_de_una_corrida_sin_muestras_lo_dice(tmp_path, capsys):
    _corrida(tmp_path, "r1", train=[], test=[])
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(glob + ["teach", "samples", "list", "r1"]) == 0
    assert "(sin muestras)" in capsys.readouterr().out


def test_list_avisa_si_la_corrida_no_tiene_qc(p, capsys):
    assert teach(p, "samples", "list", "r1") == 0
    assert "python -m spectro qc --run r1" in capsys.readouterr().out


def test_samples_add_agrega_y_es_idempotente(p):
    nuevo = _nombre(500)
    cv2.imwrite(str(p["run"] / "frames" / nuevo), render_display("-3.333"))
    assert teach(p, "samples", "add", "r1", f"{nuevo}=-3.333") == 0
    assert teach(p, "samples", "add", "r1", f"{nuevo}=-3.333") == 0
    muestras = T.load_truth(p["run"] / "truth.csv")
    assert len(muestras) == 9 and sum(1 for s in muestras if s.archivo == nuevo) == 1


def test_samples_add_acepta_coma_decimal_y_normaliza(p):
    nuevo = _nombre(500)
    cv2.imwrite(str(p["run"] / "frames" / nuevo), render_display(" 3.333"))
    assert teach(p, "samples", "add", "r1", f"{nuevo}=3,333") == 0
    assert {s.archivo: s.valor for s in T.load_truth(p["run"] / "truth.csv")}[nuevo] == "3.333"


@pytest.mark.parametrize("valor, mensaje", [
    ("12.5", "no calza"),
    ("abc", "valor invalido"),
    ("-", "valor invalido"),
])
def test_samples_add_con_un_valor_mal_formado_falla_y_no_escribe(p, capsys, valor, mensaje):
    antes = (p["run"] / "truth.csv").read_bytes()
    assert teach(p, "samples", "add", "r1", f"{_nombre(0)}={valor}") == 1
    assert mensaje in capsys.readouterr().err
    assert (p["run"] / "truth.csv").read_bytes() == antes


def test_samples_add_con_un_item_malo_entre_buenos_no_guarda_ninguno(p, capsys):
    """Rompe: guardar los items que ya se procesaron cuando uno posterior falla."""
    nuevo = _nombre(500)
    cv2.imwrite(str(p["run"] / "frames" / nuevo), render_display("-3.333"))
    antes = (p["run"] / "truth.csv").read_bytes()
    assert teach(p, "samples", "add", "r1", f"{nuevo}=-3.333", "t_9999999.000.jpg=1.111") == 1
    assert (p["run"] / "truth.csv").read_bytes() == antes


def test_samples_add_con_un_valor_negativo_sin_celda_de_signo_falla(tmp_path, capsys):
    _corrida(tmp_path, "r1", train=["0.333", "4.567"], test=[], sign=False)
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(glob + ["teach", "samples", "add", "r1", f"{_nombre(0)}=-0.333"]) == 1
    assert "sin celda de signo" in capsys.readouterr().err


def test_test_add_no_toca_truth_csv(p):
    nuevo = _nombre(500)
    cv2.imwrite(str(p["run"] / "frames" / nuevo), render_display("-3.333"))
    antes = (p["run"] / "truth.csv").read_bytes()
    assert teach(p, "test", "add", "r1", f"{nuevo}=-3.333") == 0
    assert (p["run"] / "truth.csv").read_bytes() == antes
    assert nuevo in {s.archivo for s in T.load_truth(p["run"] / "test.csv")}


def test_samples_add_de_un_fotograma_de_prueba_lo_pasa_a_entrenamiento_con_aviso(p, capsys):
    archivo = _nombre(100)
    capsys.readouterr()
    assert teach(p, "samples", "add", "r1", f"{archivo}=3.456") == 0
    assert "estaba en la prueba y paso a entrenamiento" in capsys.readouterr().out
    assert archivo in {s.archivo for s in T.load_truth(p["run"] / "truth.csv")}
    assert archivo not in {s.archivo for s in T.load_truth(p["run"] / "test.csv")}


def test_un_fotograma_nunca_queda_en_los_dos_conjuntos(p):
    """Rompe: assign (un fotograma en un solo conjunto); se mueve ida y vuelta."""
    a = _nombre(0)
    for area in ("test", "samples", "test", "samples"):
        assert teach(p, area, "add", "r1", f"{a}=-0.123") == 0
        tr = {s.archivo for s in T.load_truth(p["run"] / "truth.csv")}
        te = {s.archivo for s in T.load_truth(p["run"] / "test.csv")}
        assert not tr & te


def test_los_nombres_repetidos_entre_corridas_no_se_mezclan(p):
    """Rompe: identificar muestras solo por nombre de fotograma."""
    r2 = _corrida(p["tmp"], "r2", train=[" 1.111"], test=[], sign=True)
    antes_r2 = (r2 / "truth.csv").read_bytes()
    assert teach(p, "test", "add", "r1", f"{_nombre(0)}=-0.123") == 0        # el mismo nombre existe en r2
    assert (r2 / "truth.csv").read_bytes() == antes_r2
    assert not (r2 / "test.csv").exists()


def test_add_a_una_corrida_inexistente_falla_sin_crear_nada(p, capsys):
    assert teach(p, "samples", "add", "nueva", f"{_nombre(0)}=0.1") == 1
    assert "No existe la corrida 'nueva'" in capsys.readouterr().err
    assert not (p["runs"] / "nueva").exists()


def test_remove_quita_solo_del_conjunto_pedido(p, capsys):
    capsys.readouterr()
    assert teach(p, "samples", "remove", "r1", _nombre(0), _nombre(10)) == 0
    assert "2 muestras quitadas; quedan 6" in capsys.readouterr().out
    assert len(T.load_truth(p["run"] / "truth.csv")) == 6 and len(T.load_truth(p["run"] / "test.csv")) == 2


def test_remove_de_un_fotograma_que_esta_en_el_otro_conjunto_falla_sin_tocar_nada(p, capsys):
    """Rompe: que `samples remove` borre tambien de la prueba (o al reves)."""
    antes_tr, antes_te = (p["run"] / "truth.csv").read_bytes(), (p["run"] / "test.csv").read_bytes()
    assert teach(p, "samples", "remove", "r1", _nombre(100)) == 1          # esta en la prueba
    assert "Ninguno de esos fotogramas" in capsys.readouterr().err
    assert teach(p, "test", "remove", "r1", _nombre(0)) == 1               # esta en entrenamiento
    assert (p["run"] / "truth.csv").read_bytes() == antes_tr
    assert (p["run"] / "test.csv").read_bytes() == antes_te


def test_remove_con_un_fotograma_desconocido_avisa_y_quita_el_resto(p, capsys):
    assert teach(p, "samples", "remove", "r1", _nombre(0), "t_9.jpg") == 0
    salida = capsys.readouterr().out
    assert "aviso: t_9.jpg no esta en las muestras de entrenamiento" in salida
    assert "1 muestras quitadas" in salida


def test_remove_ultima_muestra_deja_un_conjunto_vacio_y_list_lo_tolera(p, capsys):
    assert teach(p, "test", "remove", "r1", _nombre(100), _nombre(110)) == 0
    assert T.load_truth(p["run"] / "test.csv") == []
    capsys.readouterr()
    assert teach(p, "test", "list", "r1") == 0
    assert "(sin muestras)" in capsys.readouterr().out


def _sugeridos(salida):
    return [x.split()[0] for x in salida.splitlines() if x.strip().startswith("t_")]


def test_samples_suggest_no_repite_lo_ya_etiquetado(p, capsys):
    for i in range(20):
        cv2.imwrite(str(p["run"] / "frames" / _nombre(1000 + i * 10)), render_display(" 1.111"))
    assert teach(p, "samples", "suggest", "r1", "5", "--gap", "0") == 0
    nombres = _sugeridos(capsys.readouterr().out)
    etiquetados = {s.archivo for s in T.load_truth(p["run"] / "truth.csv") + T.load_truth(p["run"] / "test.csv")}
    assert len(nombres) == 5 and not set(nombres) & etiquetados


def test_suggest_con_todo_etiquetado_no_sugiere_nada_y_sale_con_0(p, capsys):
    for f in list((p["run"] / "frames").glob("*.jpg")):
        if f.name not in {_nombre(i * 10) for i in range(8)} | {_nombre(100), _nombre(110)}:
            f.unlink()
    assert teach(p, "samples", "suggest", "r1", "5") == 0
    assert _sugeridos(capsys.readouterr().out) == []


def test_suggest_pide_mas_de_los_que_hay_y_devuelve_los_que_hay(p, capsys):
    for i in range(3):
        cv2.imwrite(str(p["run"] / "frames" / _nombre(1000 + i * 10)), render_display(" 1.111"))
    assert teach(p, "samples", "suggest", "r1", "50", "--gap", "0") == 0
    assert len(_sugeridos(capsys.readouterr().out)) == 3


def test_suggest_la_misma_semilla_da_las_mismas_sugerencias(p, capsys):
    for i in range(30):
        cv2.imwrite(str(p["run"] / "frames" / _nombre(1000 + i * 10)), render_display(" 1.111"))
    teach(p, "samples", "suggest", "r1", "6", "--strategy", "random", "--seed", "3", "--gap", "0")
    a = _sugeridos(capsys.readouterr().out)
    teach(p, "samples", "suggest", "r1", "6", "--strategy", "random", "--seed", "3", "--gap", "0")
    assert _sugeridos(capsys.readouterr().out) == a


def test_suggest_no_escribe_nada(p):
    for i in range(5):
        cv2.imwrite(str(p["run"] / "frames" / _nombre(1000 + i * 10)), render_display(" 1.111"))
    antes = instantanea(p["tmp"])
    assert teach(p, "samples", "suggest", "r1", "3") == 0
    assert teach(p, "test", "suggest", "r1", "3") == 0
    assert instantanea(p["tmp"]) == antes


def test_test_suggest_dice_como_cargarlas_con_test_label(p, capsys):
    for i in range(5):
        cv2.imwrite(str(p["run"] / "frames" / _nombre(1000 + i * 10)), render_display(" 1.111"))
    assert teach(p, "test", "suggest", "r1", "2") == 0
    assert "teach test label r1 --queue 2" in capsys.readouterr().out
    assert teach(p, "samples", "suggest", "r1", "2") == 0
    assert "teach samples label r1 --queue 2" in capsys.readouterr().out


@pytest.fixture
def ui_espia(monkeypatch):
    """Reemplaza el loop de OpenCV: guarda con que se lo llamo y no abre ninguna ventana."""
    llamadas = []

    def falsa(cfg, args, names, offsets, truth, test=None, motivos=None, target="train"):
        llamadas.append({"cfg": cfg, "args": args, "names": list(names), "truth": truth,
                         "test": test, "motivos": motivos, "target": target})
        return 0

    monkeypatch.setattr("spectro.teach_ui.run_teach_ui", falsa)
    return llamadas


def test_samples_label_abre_la_ventana_con_el_conjunto_de_entrenamiento(p, ui_espia):
    assert teach(p, "samples", "label", "r1") == 0
    (ll,) = ui_espia
    assert ll["target"] == "train" and len(ll["truth"]) == 8 and len(ll["test"]) == 2
    assert ll["args"].truth == str(p["run"] / "truth.csv") and ll["args"].test == str(p["run"] / "test.csv")
    assert ll["args"].frames_dir == str(p["run"] / "frames")
    assert ll["args"].templates_dir == str(p["lib"])
    assert len(ll["names"]) == 10


def test_test_label_abre_la_ventana_con_el_conjunto_de_prueba(p, ui_espia):
    assert teach(p, "test", "label", "r1") == 0
    assert ui_espia[0]["target"] == "test"


def test_label_con_queue_pasa_solo_los_sugeridos_con_su_motivo(p, ui_espia):
    for i in range(10):
        cv2.imwrite(str(p["run"] / "frames" / _nombre(1000 + i * 10)), render_display(" 1.111"))
    assert teach(p, "samples", "label", "r1", "--queue", "3", "--gap", "0") == 0
    (ll,) = ui_espia
    assert len(ll["names"]) == 3 and set(ll["motivos"]) == set(ll["names"])
    etiquetados = {_nombre(i * 10) for i in range(8)} | {_nombre(100), _nombre(110)}
    assert not set(ll["names"]) & etiquetados


def test_label_con_queue_y_nada_que_sugerir_falla_sin_abrir_la_ventana(p, ui_espia, capsys):
    for f in list((p["run"] / "frames").glob("*.jpg")):
        if f.name not in {_nombre(i * 10) for i in range(8)} | {_nombre(100), _nombre(110)}:
            f.unlink()
    assert teach(p, "samples", "label", "r1", "--queue", "3") == 1
    assert "No hay fotogramas que sugerir" in capsys.readouterr().err
    assert ui_espia == []


def test_label_de_una_corrida_inexistente_no_abre_la_ventana(p, ui_espia, capsys):
    assert teach(p, "samples", "label", "nope") == 1
    assert ui_espia == [] and "No existe la corrida" in capsys.readouterr().err


# ==========================================================================
# test eval / history
# ==========================================================================
def test_test_history_vacio_sugiere_el_comando_de_eval(p, capsys):
    assert teach(p, "test", "history", "r1") == 0
    salida = capsys.readouterr().out
    assert "(vacio)" in salida and "teach test eval r1" in salida


def test_test_history_lista_una_fila_por_evaluacion_con_el_cambio(p, capsys):
    entrenar(p)
    teach(p, "test", "eval", "r1")
    teach(p, "test", "eval", "r1")
    capsys.readouterr()
    assert teach(p, "test", "history", "r1") == 0
    salida = capsys.readouterr().out
    filas = [x for x in salida.splitlines() if "misma_corrida" in x]
    assert len(filas) == 2
    assert "100.0%" in filas[0] and "+0.0 pt" in filas[1] and "pt" not in filas[0]


def test_test_history_de_una_corrida_inexistente_falla(p, capsys):
    assert teach(p, "test", "history", "nope") == 1
    assert "No existe la corrida" in capsys.readouterr().err


def test_test_history_exige_el_id(p):
    with pytest.raises(SystemExit):
        teach(p, "test", "history")


def test_test_eval_una_corrida_detalla_y_agrega_la_fila_del_veredicto(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "test", "eval", "r1") == 0
    salida = capsys.readouterr().out
    assert "veredicto" in salida                                 # la tabla al final del informe
    assert "sin umbrales" not in salida                           # eso es solo de batch
    fila = next(x for x in salida.splitlines() if x.strip().startswith("r1"))
    assert "2 misma" in fila and "100.0%" in fila


def test_test_eval_varias_corridas_da_una_tabla_sin_escribir_historial(p, capsys):
    r2 = _corrida(p["tmp"], "r2", train=[], test=[" 3.456"])
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "test", "eval", "r1", "r2", "r1") == 0
    salida = capsys.readouterr().out
    assert sum(1 for x in salida.splitlines() if x.strip().startswith("r1")) == 1      # sin duplicados
    assert any(x.strip().startswith("r2") for x in salida.splitlines())
    assert not (r2 / "out" / "teach_history.csv").exists()
    assert not (p["run"] / "out" / "teach_history.csv").exists()


def test_test_eval_sin_ids_omite_las_corridas_sin_prueba(p, capsys):
    _corrida(p["tmp"], "r2", train=[], test=[])
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "test", "eval") == 0
    salida = capsys.readouterr().out
    assert any(x.strip().startswith("r1") for x in salida.splitlines())
    assert not any(x.strip().startswith("r2") for x in salida.splitlines())


def test_test_eval_con_un_id_inexistente_entre_varios_falla(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "test", "eval", "r1", "nope") == 1
    assert "No existe la corrida 'nope'" in capsys.readouterr().err


def con_lectura(p, n=4):
    """qc_report.csv, readings.csv y read_meta.json con la huella vigente: salidas al dia."""
    from spectro.read import Reading, write_read_meta, write_readings

    out = p["run"] / "out"
    write_qc_report([QCRow(_nombre(i), float(i), i + 1) for i in range(n)], out / "qc_report.csv")
    write_readings([Reading(_nombre(i), float(i), i + 1, 0.1, 0.9, "0.100") for i in range(n)],
                   out / "readings.csv")
    write_read_meta(out / "read_meta.json", p["lib"], len(L.load(p["lib"])))


def test_test_eval_usa_los_umbrales_de_calib_config_y_el_flag_les_gana(p, capsys):
    entrenar(p)
    con_lectura(p)
    cfg = Config.default()
    cfg.acceptance = AcceptanceConfig(min_exactitud=0.5)
    cfg.save(p["calib"] / "config.json")
    capsys.readouterr()
    assert teach(p, "test", "eval") == 0
    assert "acepta" in capsys.readouterr().out
    assert teach(p, "test", "eval", "--min-exactitud", "1.0") == 0
    assert "acepta" in capsys.readouterr().out                    # 100%: justo en el umbral
    assert teach(p, "test", "eval", "--min-cobertura", "1.0") == 0
    assert "acepta" in capsys.readouterr().out                    # cobertura 4/4, tambien justo
    cfg.acceptance = AcceptanceConfig(min_exactitud=0.5, max_error=0.0)
    cfg.save(p["calib"] / "config.json")
    assert teach(p, "test", "eval", "--max-error", "0.5") == 0
    assert "acepta" in capsys.readouterr().out


def test_test_eval_sin_readings_manda_a_revisar_aunque_haya_umbral(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "test", "eval", "--min-exactitud", "0.5") == 0
    assert "revisar (la corrida no tiene readings.csv)" in capsys.readouterr().out


def test_test_eval_sin_umbrales_deja_el_veredicto_vacio(p, capsys):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "test", "eval") == 0
    salida = capsys.readouterr().out
    assert "acepta" not in salida and "revisar" not in salida


def test_test_eval_con_un_umbral_inalcanzable_manda_a_revisar(p, capsys):
    entrenar(p)
    # una pregunta de la prueba que el lector no puede acertar: se cambia el valor esperado
    T.save_truth(p["run"] / "test.csv", [T.Sample(_nombre(100), "3.457"), T.Sample(_nombre(110), "-7.891")])
    capsys.readouterr()
    assert teach(p, "test", "eval", "--min-exactitud", "0.9") == 0
    salida = capsys.readouterr().out
    assert "revisar" in salida and "exactitud 0.0% < 90.0%" in salida


@pytest.mark.parametrize("flag", ["--min-exactitud", "--max-error", "--min-cobertura"])
def test_test_eval_con_umbral_fuera_de_rango_falla(p, capsys, flag):
    entrenar(p)
    capsys.readouterr()
    assert teach(p, "test", "eval", "r1", flag, "95") == 1
    assert flag in capsys.readouterr().err
    assert not (p["run"] / "out" / "teach_history.csv").exists()          # nada a medias


def test_test_eval_no_escribe_batch_report(p):
    entrenar(p)
    teach(p, "test", "eval")
    assert not (p["runs"] / "batch_report.csv").exists()


def test_test_eval_escribe_solo_test_report_e_historial(p):
    entrenar(p)
    antes = set(instantanea(p["tmp"]))
    teach(p, "test", "eval", "r1")
    nuevos = set(instantanea(p["tmp"])) - antes
    assert {x.replace("\\", "/") for x in nuevos} == {"runs/r1/out/test_report.csv", "runs/r1/out/teach_history.csv"}


# ==========================================================================
# el parser
# ==========================================================================
def test_los_valores_por_defecto_del_parser():
    from spectro.cli import build_parser

    a = build_parser().parse_args(["teach", "train"])
    assert a.runs == [] and a.exclude is None and a.keep is False and a.gap == 5.0
    assert a.max_per_label == 3
    s = build_parser().parse_args(["teach", "samples", "suggest", "r1"])
    assert (s.n, s.strategy, s.seed, s.gap, s.which) == (20, "mixed", 0, 5.0, "train")
    e = build_parser().parse_args(["teach", "test", "eval"])
    assert (e.min_exactitud, e.max_error, e.min_cobertura) == (None, None, None)


def test_las_flags_de_modo_ya_no_existen_en_ningun_verbo():
    from spectro.cli import build_parser

    parser = build_parser()
    for flag in ("--build", "--check", "--eval", "--eval-all", "--all-runs", "--library", "--add"):
        with pytest.raises(SystemExit):
            parser.parse_args(["teach", "train", "r1", flag])


def test_templates_ya_no_es_un_comando():
    from spectro.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["templates"])
