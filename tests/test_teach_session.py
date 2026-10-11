"""``TeachSession`` y el reducer de ``teach``: todo lo que la ventana decide, sin ventana.

Cada test dice en su docstring que cambio en ``src/`` lo haria fallar (la mutacion se
verifico con un parche en memoria, sin tocar ``src/``).
"""

from __future__ import annotations

import random
import shutil
from types import SimpleNamespace

import cv2
import pytest

from conftest import make_config, render_display
from spectro import library as L
from spectro import teach as T
from spectro.project import RunPaths
from spectro.teach_session import (
    CONFIRM_ACTIONS,
    KEY_BACKSPACE,
    KEY_ENTER,
    KEY_ESC,
    KEY_LEFT,
    KEY_RIGHT,
    PER_PAGE,
    SLOW_REQUESTS,
    TeachParams,
    TeachSession,
    TeachState,
    add_sample,
    apply_action,
    go_to,
    key_to_action,
)

TEXTOS = ["-0.123", " 4.567", "-8.901", " 2.345", " 6.789", "-0.246", " 1.357", " 9.048",
          " 3.456", "-7.890"]


def _nombre(i: int) -> str:
    return f"t_{i * 10:07d}.000.jpg"


NOMBRES = [_nombre(i) for i in range(len(TEXTOS))]


def _params(base, seed=None) -> TeachParams:
    return TeachParams(
        frames_dir=str(base / "frames"), templates_dir=str(base / "calib" / "templates"),
        max_per_label=3, gap=0.0, truth=str(base / "truth.csv"), test=str(base / "test.csv"),
        teach_report=str(base / "out" / "teach_report.csv"),
        test_report=str(base / "out" / "test_report.csv"),
        history=str(base / "out" / "teach_history.csv"), seed=seed,
    )


def _sesion(base, n_train=8, n_test=0, con_biblioteca=True, seed=None, target="train"):
    """Una sesion sobre un proyecto de juguete: 10 fotogramas, las primeras ``n_train`` etiquetadas."""
    (base / "frames").mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(TEXTOS):
        cv2.imwrite(str(base / "frames" / _nombre(i)), render_display(t))
    cfg = make_config(sign=True)
    train = [T.Sample(_nombre(i), TEXTOS[i].strip()) for i in range(n_train)]
    test = [T.Sample(_nombre(8 + i), TEXTOS[8 + i].strip()) for i in range(n_test)]
    params = _params(base, seed)
    if con_biblioteca and train:
        pool, _, _ = T.build_pool(train, cfg, base / "frames")
        L.write(pool, params.templates_dir, "replace", 3)
    return TeachSession(cfg, params, list(NOMBRES), {}, train, test, target=target)


def _escribir(s: TeachSession, texto: str) -> None:
    for ch in texto:
        s.act(f"key:{ch}")


def _ir_a(s: TeachSession, idx: int) -> None:
    s.state = go_to(s.state, s.samples + s.test, s.names, idx)


def _pedido(s: TeachSession, accion: str, confirmar: bool = False) -> str:
    """Dispara una accion y, si dejo un pedido, lo ejecuta como lo hace el loop."""
    s.act(accion)
    if confirmar:
        s.act(accion)
    kind = s.begin_request()
    if kind:
        s.run_request(kind)
    return kind


def _a_biblioteca(s: TeachSession) -> None:
    assert _pedido(s, "lib") == "refresh_lib"


# ==========================================================================
# add / remove / persist
# ==========================================================================
def test_add_agrega_la_muestra_y_avanza_al_siguiente_fotograma(tmp_path):
    """Rompe: ``_add`` que no llame a ``go_to`` (no avanza) o que ignore ``res.added``."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _ir_a(s, 3)
    _escribir(s, "2.345")
    s.act("add")
    assert [x.file for x in s.samples] == [NOMBRES[3]] and s.samples[0].value == "2.345"
    assert s.state.index == 4 and s.state.message == "muestra agregada"
    assert s.state.request == ""


def test_add_con_valor_invalido_no_avanza_ni_agrega_pero_avisa(tmp_path):
    """Rompe: avanzar siempre tras ``add`` (el avance debe depender de ``AddResult.added``)."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _ir_a(s, 3)
    _escribir(s, "12.345")  # fuera del formato del display
    s.act("add")
    assert s.samples == [] and s.state.index == 3
    assert s.state.message and s.state.message != "muestra agregada"
    assert s.state.text == "12.345"  # lo tipeado no se pierde


def test_add_sin_texto_no_agrega(tmp_path):
    """Rompe: aceptar el texto vacio como valor."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _ir_a(s, 2)
    s.act("add")
    assert s.samples == [] and s.state.index == 2


def test_add_en_el_ultimo_fotograma_no_se_sale_del_rango(tmp_path):
    """Rompe: ``go_to`` sin acotar el indice."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _ir_a(s, len(NOMBRES) - 1)
    _escribir(s, "-7.890")
    s.act("add")
    assert len(s.samples) == 1 and s.state.index == len(NOMBRES) - 1


def test_add_persiste_truth_csv_y_no_crea_test_csv_si_no_hay_prueba(tmp_path):
    """Rompe: que ``persist`` no escriba ``truth.csv`` o que cree siempre ``test.csv``."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _ir_a(s, 1)
    _escribir(s, "4.567")
    s.act("add")
    assert [x.file for x in T.load_truth(tmp_path / "truth.csv")] == [NOMBRES[1]]
    assert not (tmp_path / "test.csv").exists()


def test_add_con_conjunto_prueba_escribe_test_csv_y_no_entra_a_entrenamiento(tmp_path):
    """Rompe: ``add_sample`` que ignore ``which`` y deje la prueba en ``train``."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False, target="test")
    _ir_a(s, 9)
    _escribir(s, "-7.890")
    s.act("add")
    assert s.samples == [] and [x.file for x in s.test] == [NOMBRES[9]]
    assert [x.file for x in T.load_truth(tmp_path / "test.csv")] == [NOMBRES[9]]
    assert T.load_truth(tmp_path / "truth.csv") == []


def test_target_alterna_y_mover_de_entrenamiento_a_prueba_avisa(tmp_path):
    """Rompe: perder el aviso de que la muestra ya aporto glifos, o dejarla en los dos conjuntos."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _ir_a(s, 2)
    _escribir(s, "-8.901")
    s.act("add")
    _ir_a(s, 2)
    s.act("target")
    assert s.state.target == "test" and s.state.text == "-8.901"  # precargado
    s.act("add")
    assert s.samples == [] and [x.file for x in s.test] == [NOMBRES[2]]
    assert "reemplaza la biblioteca" in s.state.message


def test_remove_quita_de_los_dos_conjuntos_y_persiste(tmp_path):
    """Rompe: ``_remove`` que solo quite de ``samples`` o que no persista."""
    s = _sesion(tmp_path, n_train=3, n_test=2)
    _ir_a(s, 1)
    s.act("remove")
    assert NOMBRES[1] not in [x.file for x in s.samples]
    assert s.state.message == "muestra quitada" and s.state.text == ""
    assert NOMBRES[1] not in [x.file for x in T.load_truth(tmp_path / "truth.csv")]
    _ir_a(s, 8)
    s.act("remove")
    assert NOMBRES[8] not in [x.file for x in s.test]
    assert NOMBRES[8] not in [x.file for x in T.load_truth(tmp_path / "test.csv")]


def test_remove_de_un_fotograma_sin_muestra_no_rompe_nada(tmp_path):
    """Rompe: ``remove_sample`` que lance si el archivo no esta."""
    s = _sesion(tmp_path, n_train=2)
    _ir_a(s, 6)
    s.act("remove")
    assert len(s.samples) == 2 and s.state.message == "muestra quitada"


def test_persist_con_prueba_vacia_pero_archivo_existente_lo_deja_vacio(tmp_path):
    """Rompe: no reescribir ``test.csv`` cuando se quitan todas las muestras de prueba."""
    s = _sesion(tmp_path, n_train=0, n_test=1, con_biblioteca=False)
    s.persist()
    assert len(T.load_truth(tmp_path / "test.csv")) == 1
    _ir_a(s, 8)
    s.act("remove")
    assert T.load_truth(tmp_path / "test.csv") == []


def test_persist_escribe_los_dos_archivos(tmp_path):
    """Rompe: ``persist`` que olvide uno de los dos conjuntos."""
    s = _sesion(tmp_path, n_train=2, n_test=2, con_biblioteca=False)
    s.persist()
    assert len(T.load_truth(tmp_path / "truth.csv")) == 2
    assert len(T.load_truth(tmp_path / "test.csv")) == 2


# ==========================================================================
# precarga de valor, random y seed
# ==========================================================================
def test_navegar_a_un_fotograma_etiquetado_precarga_su_valor(tmp_path):
    """Rompe: no pasar ``value_of`` al reducer (la navegacion no precarga)."""
    s = _sesion(tmp_path, n_train=4, n_test=1, con_biblioteca=False)
    _ir_a(s, 0)
    s.act("next")
    assert s.state.index == 1 and s.state.text == "4.567"
    _ir_a(s, 7)
    s.act("next")  # el 8 es de prueba pero tambien precarga
    assert s.state.text == "3.456"
    s.act("prev")
    assert s.state.text == ""  # el 7 no tiene muestra
    s.act("jump-10")
    assert s.state.index == 0 and s.state.text == "-0.123"


def test_valor_de_incluye_entrenamiento_y_prueba(tmp_path):
    """Rompe: ``_value_of`` que mire solo ``samples``."""
    s = _sesion(tmp_path, n_train=1, n_test=1, con_biblioteca=False)
    assert s._value_of(0) == "-0.123" and s._value_of(8) == "3.456" and s._value_of(5) == ""


def test_random_usa_el_rng_inyectado():
    """Rompe: ignorar ``rng`` y usar siempre ``random.randrange``."""
    s = apply_action(TeachState(), "random", 10, rng=lambda n: 7)
    assert s.index == 7
    pedidos = []
    apply_action(TeachState(), "random", 10, rng=lambda n: (pedidos.append(n), 0)[1])
    assert pedidos == [10]


def test_random_acota_y_precarga_el_valor():
    """Rompe: no acotar el indice del rng, o no precargar con ``value_of``."""
    s = apply_action(TeachState(), "random", 5, value_of=lambda i: f"v{i}", rng=lambda n: 99)
    assert s.index == 4 and s.text == "v4"


def test_random_sin_fotogramas_no_hace_nada():
    """Rompe: llamar al rng con ``n_names == 0`` (``randrange(0)`` lanza)."""
    assert apply_action(TeachState(), "random", 0, rng=lambda n: 1 // 0).index == 0


def test_navegar_en_modo_biblioteca_mueve_el_indice_sin_precargar_valor():
    """Rompe: perder la rama de navegacion fuera del modo muestras (o que precargue ``value_of`` ahi)."""
    s = TeachState(mode="library", index=3, text="1.1")
    n = apply_action(s, "next", 10, value_of=lambda i: "x")
    assert n.index == 4 and n.text == "1.1"
    assert apply_action(s, "jump+10", 10).index == 9 and apply_action(s, "jump-10", 10).index == 0
    assert apply_action(s, "next", 0).index == 3  # sin fotogramas no se mueve


def test_random_en_modo_biblioteca_no_cambia_de_fotograma():
    """Rompe: dejar que ``random`` actue fuera del modo muestras."""
    s = TeachState(mode="library", index=3)
    assert apply_action(s, "random", 10, rng=lambda n: 0).index == 3


def _secuencia(s: TeachSession, n=12) -> list[int]:
    out = []
    for _ in range(n):
        s.act("random")
        out.append(s.state.index)
    return out


def test_la_misma_semilla_da_la_misma_secuencia_de_aleatorio(tmp_path):
    """Rompe: ignorar ``params.seed`` o crear el ``Random`` de nuevo en cada clic."""
    a = _sesion(tmp_path / "a", seed=5)
    b = _sesion(tmp_path / "b", seed=5)
    esperado = random.Random(5)
    seq = _secuencia(a)
    assert seq == _secuencia(b)
    assert seq == [esperado.randrange(len(NOMBRES)) for _ in range(12)]
    assert len(set(seq)) > 1  # avanza: no devuelve siempre lo mismo


def test_semillas_distintas_dan_secuencias_distintas(tmp_path):
    """Rompe: una semilla fija e independiente del parametro."""
    assert _secuencia(_sesion(tmp_path / "a", seed=1)) != _secuencia(_sesion(tmp_path / "b", seed=2))


def test_sin_semilla_el_aleatorio_usa_el_random_global(tmp_path):
    """Rompe: tratar ``seed=None`` como una semilla fija (la secuencia dejaria de seguir al ``random`` global)."""
    s = _sesion(tmp_path, seed=None)
    assert s._rng is None
    random.seed(7)
    esperado = [random.randrange(len(NOMBRES)) for _ in range(8)]
    random.seed(7)
    assert _secuencia(s, 8) == esperado
    random.seed()


def test_seed_cero_tambien_es_una_semilla(tmp_path):
    """Rompe: ``if params.seed`` (trata el 0 como 'sin semilla')."""
    s = _sesion(tmp_path, seed=0)
    assert s._rng is not None
    r = random.Random(0)
    assert _secuencia(s, 5) == [r.randrange(len(NOMBRES)) for _ in range(5)]


# ==========================================================================
# TeachParams
# ==========================================================================
def test_params_from_context_toma_las_rutas_de_la_corrida(tmp_path):
    """Rompe: mapear mal un campo (p. ej. ``test_report`` por ``teach_report``) o perder la semilla."""
    run = RunPaths.for_run("r1", tmp_path / "runs", tmp_path / "calib")
    ctx = SimpleNamespace(paths=run, frames_dir=run.frames, templates_dir=run.templates)
    prm = TeachParams.from_context(ctx, 4, 2.5, 9)
    assert prm.frames_dir == str(run.frames) and prm.templates_dir == str(run.templates)
    assert (prm.max_per_label, prm.gap, prm.seed) == (4, 2.5, 9)
    assert prm.truth == str(run.truth) and prm.test == str(run.test)
    assert prm.teach_report == str(run.teach_report) and prm.test_report == str(run.test_report)
    assert prm.history == str(run.history)
    assert TeachParams.from_context(ctx, 4, 2.5).seed is None


def test_seed_llega_desde_samples_label_a_la_sesion(tmp_path, monkeypatch):
    """Rompe: que ``cmd_set_label`` no reenvie ``args.seed`` a ``TeachParams``."""
    from spectro.cli import main

    run = tmp_path / "runs" / "r1"
    (run / "frames").mkdir(parents=True)
    make_config(sign=True).save(run / "config.json")
    for i, t in enumerate(TEXTOS):
        cv2.imwrite(str(run / "frames" / _nombre(i)), render_display(t))
    vistos = []
    monkeypatch.setattr("spectro.teach_ui.run_teach_ui",
                        lambda cfg, args, *a, **k: (vistos.append(args), 0)[1])
    glob = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(glob + ["teach", "samples", "label", "r1", "--seed", "11"]) == 0
    assert main(glob + ["teach", "samples", "label", "r1"]) == 0
    assert [a.seed for a in vistos] == [11, None]
    assert isinstance(vistos[0], TeachParams)


# ==========================================================================
# confirmaciones
# ==========================================================================
@pytest.mark.parametrize("accion", ["random", "next", "prev", "jump+10", "add", "remove", "color",
                                    "back", "clear", "key:1", "target", "lib", "samples",
                                    "validate", "eval", "undo", "page+", "tile:0"])
def test_cualquier_otra_accion_cancela_una_confirmacion_armada(accion):
    """Rompe: que el reducer cancele la confirmacion solo en algunas acciones (hoy es una regla unica)."""
    for conf in CONFIRM_ACTIONS:
        armado = TeachState(confirm=conf)
        nuevo = apply_action(armado, accion, 10, n_lib=5, rng=lambda n: 0)
        assert nuevo.confirm == "", f"{accion} no cancelo {conf}"
        assert nuevo.request != conf


def test_una_confirmacion_cancelada_no_se_ejecuta_con_el_segundo_clic(tmp_path):
    """Rompe: que ``random`` (o ``add``/``remove``) dejen ``confirm`` armado y el 2do clic borre."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    antes = len(list((tmp_path / "calib" / "templates").glob("*.png")))
    s.act("del_one")
    assert s.state.confirm == "del_one"
    s.state = TeachState(**{**s.state.__dict__, "mode": "samples"})
    s.act("random")
    assert s.state.confirm == ""
    s.act("del_one")  # vuelve a armar, no ejecuta
    assert s.state.request == "" and s.state.confirm == "del_one"
    assert len(list((tmp_path / "calib" / "templates").glob("*.png"))) == antes


def test_agregar_y_quitar_tambien_cancelan_la_confirmacion_en_la_sesion(tmp_path):
    """Rompe: ``act`` que salte el reducer para ``add``/``remove`` (dejaria la confirmacion viva)."""
    s = _sesion(tmp_path, n_train=3)
    _a_biblioteca(s)
    for accion in ("add", "remove"):
        s.act("replace")
        assert s.state.confirm == "replace"
        s.state = TeachState(**{**s.state.__dict__, "mode": "samples"})
        s.act(accion)
        assert s.state.confirm == ""


def test_del_one_y_del_label_sin_biblioteca_no_arman_confirmacion():
    """Rompe: armar el borrado cuando no hay nada que borrar."""
    for acc in ("del_one", "del_label"):
        s = TeachState(mode="library")
        assert apply_action(s, acc, 3, n_lib=0) == s
    assert apply_action(TeachState(), "replace", 3, n_lib=0).confirm == "replace"


# ==========================================================================
# pedidos: validate / add_lib / replace / eval
# ==========================================================================
def test_begin_request_toma_el_pedido_y_deja_trabajando(tmp_path):
    """Rompe: ``begin_request`` que no limpie ``request`` (el loop correria el pedido en bucle)."""
    s = _sesion(tmp_path)
    assert s.begin_request() == ""
    s.act("validate")
    assert s.state.request == "validate"
    assert s.begin_request() == "validate"
    assert s.state.request == "" and s.state.message == "trabajando..."
    assert s.begin_request() == ""


def test_los_pedidos_lentos_son_los_que_dibujan_trabajando():
    """Rompe: sacar un pedido lento de ``SLOW_REQUESTS``."""
    assert set(SLOW_REQUESTS) == {"eval", "validate", "add_lib", "replace"}


def test_validate_deja_el_resultado_y_el_reporte_sin_tocar_la_biblioteca(tmp_path):
    """Rompe: que ``validate`` escriba plantillas o no escriba ``teach_report.csv``."""
    s = _sesion(tmp_path)
    antes = {f.name: f.read_bytes() for f in (tmp_path / "calib" / "templates").glob("*.png")}
    assert _pedido(s, "validate") == "validate"
    assert any("leave-one-out" in ln for ln in s.result)
    assert s.state.message == "" and (tmp_path / "out" / "teach_report.csv").exists()
    assert {f.name: f.read_bytes() for f in (tmp_path / "calib" / "templates").glob("*.png")} == antes
    assert L.list_backups(tmp_path / "calib" / "templates") == []


def test_validate_sin_muestras_validas_lo_dice(tmp_path):
    """Rompe: validar con un pool vacio (dividiria por cero o inventaria un resultado)."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _pedido(s, "validate")
    assert s.result == ["No hay muestras validas."]
    assert not (tmp_path / "out" / "teach_report.csv").exists()


def test_validate_informa_las_muestras_descartadas(tmp_path):
    """Rompe: tragarse los errores de ``build_pool``."""
    s = _sesion(tmp_path)
    s.samples.append(T.Sample("t_9999999.000.jpg", "1.111"))  # no existe en disco
    _pedido(s, "validate")
    assert any(ln.startswith("muestra descartada: t_9999999") for ln in s.result)


def test_add_lib_suma_plantillas_y_refresca_la_biblioteca(tmp_path):
    """Rompe: que ``add_lib`` no llame a ``refresh_library`` (la sesion seguiria con la biblioteca vieja)."""
    s = _sesion(tmp_path, n_train=3, con_biblioteca=False)
    assert s.library == []
    _pedido(s, "add_lib")
    assert any("plantillas nuevas" in ln for ln in s.result)
    assert len(s.library) > 0 and len(s.entries) == len(s.library)


def test_add_lib_dos_veces_no_duplica(tmp_path):
    """Rompe: ``add`` que no deduplique."""
    s = _sesion(tmp_path, n_train=4, con_biblioteca=False)
    _pedido(s, "add_lib")
    n = len(s.library)
    _pedido(s, "add_lib")
    assert len(s.library) == n and any("+0 plantillas nuevas" in ln for ln in s.result)


def test_replace_reemplaza_la_biblioteca_y_vacia_la_papelera(tmp_path):
    """Rompe: ``replace`` que no limpie ``trash`` (restauraria plantillas de la biblioteca vieja)."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    _pedido(s, "del_one", confirmar=True)
    assert len(s.trash) == 1
    assert _pedido(s, "replace", confirmar=True) == "replace"
    assert s.trash == []
    assert any("biblioteca reemplazada" in ln for ln in s.result)


def test_replace_sin_confirmar_no_toca_nada(tmp_path):
    """Rompe: ejecutar ``replace`` al primer clic."""
    s = _sesion(tmp_path)
    antes = {f.name: f.read_bytes() for f in (tmp_path / "calib" / "templates").glob("*.png")}
    s.act("replace")
    assert s.begin_request() == ""
    assert {f.name: f.read_bytes() for f in (tmp_path / "calib" / "templates").glob("*.png")} == antes


def test_eval_sin_muestras_de_prueba_lo_dice(tmp_path):
    """Rompe: evaluar con la prueba vacia."""
    s = _sesion(tmp_path)
    _pedido(s, "eval")
    assert s.result[0] == "No hay muestras de prueba."
    assert not (tmp_path / "out" / "test_report.csv").exists()


def test_eval_sin_biblioteca_lo_dice(tmp_path):
    """Rompe: dejar pasar el ``FileNotFoundError`` o evaluar contra una biblioteca vacia."""
    s = _sesion(tmp_path, n_train=2, n_test=2, con_biblioteca=False)
    _pedido(s, "eval")
    assert s.result == ["No hay biblioteca vigente: agrega muestras a la biblioteca primero."]
    assert not (tmp_path / "out" / "test_report.csv").exists()


def test_eval_escribe_reporte_e_historial_con_huella(tmp_path):
    """Rompe: no pasar ``huella`` al historial o no escribir ``test_report.csv``."""
    s = _sesion(tmp_path, n_train=8, n_test=2)
    _pedido(s, "eval")
    assert (tmp_path / "out" / "test_report.csv").exists()
    hist = (tmp_path / "out" / "teach_history.csv").read_text(encoding="utf-8")
    assert L.fingerprint(tmp_path / "calib" / "templates") in hist
    assert s.result and s.state.message == ""


def test_eval_no_agrega_la_prueba_a_la_biblioteca(tmp_path):
    """Rompe: que evaluar construya plantillas con las muestras de prueba (la prueba nunca entra)."""
    s = _sesion(tmp_path, n_train=8, n_test=2)
    antes = {f.name: f.read_bytes() for f in (tmp_path / "calib" / "templates").glob("*.png")}
    _pedido(s, "eval")
    assert {f.name: f.read_bytes() for f in (tmp_path / "calib" / "templates").glob("*.png")} == antes


def test_la_prueba_no_entra_al_pool_de_validate_ni_add_lib(tmp_path, monkeypatch):
    """Rompe: ``_pool`` que construya con ``samples + test``."""
    s = _sesion(tmp_path, n_train=3, n_test=2, con_biblioteca=False)
    vistos = []
    original = T.build_pool
    monkeypatch.setattr(T, "build_pool",
                        lambda muestras, *a, **k: (vistos.extend(m.file for m in muestras),
                                                   original(muestras, *a, **k))[1])
    _pedido(s, "add_lib")
    _pedido(s, "validate")
    assert vistos and not set(vistos) & {NOMBRES[8], NOMBRES[9]}


# ==========================================================================
# biblioteca: refresh, borrar, deshacer, reetiquetar
# ==========================================================================
def test_refresh_library_carga_entradas_usos_y_resumen(tmp_path):
    """Rompe: no recargar ``entries`` o no calcular los usos."""
    s = _sesion(tmp_path)
    lines = s.refresh_library()
    assert s.entries and len(s.entries) == len(s.library)
    assert sum(e.uses + e.errors for e in s.entries) > 0
    assert 0 < len(lines) <= 3 and "biblioteca vigente" in lines[0]


def test_refresh_library_sin_biblioteca_ni_muestras_no_rompe(tmp_path):
    """Rompe: ``_load_library`` que no atrape ``FileNotFoundError``."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    assert s.refresh_library() == [] and s.entries == [] and s.library == []


def test_refresh_library_descarta_el_cache_del_fotograma(tmp_path):
    """Rompe: dejar ``_frame`` viejo (la lectura mostraria la biblioteca anterior)."""
    s = _sesion(tmp_path)
    s.frame(0)
    assert s._frame is not None
    s.refresh_library()
    assert s._frame is None


def test_frame_devuelve_la_lectura_con_la_biblioteca(tmp_path):
    """Rompe: ``frame`` que no lea o que no cachee por indice."""
    s = _sesion(tmp_path)
    gray, color, off, lectura = s.frame(0)
    assert gray.ndim == 2 and color.ndim == 3 and off == (0, 0) and lectura is not None
    assert s.frame(0)[0] is gray  # cache de uno
    assert s.frame(1)[0] is not gray
    sin = _sesion(tmp_path / "otra", con_biblioteca=False)
    assert sin.frame(0)[3] is None


def test_entrar_a_la_biblioteca_deja_la_seleccion_en_cero(tmp_path):
    """Rompe: ``lib`` que no pida ``refresh_lib`` o no reinicie ``sel``/``page``."""
    s = _sesion(tmp_path)
    s.state = TeachState(**{**s.state.__dict__, "sel": 4, "page": 2})
    _a_biblioteca(s)
    assert s.state.mode == "library" and s.state.sel == 0 and s.state.page == 0
    assert len(s.entries) > 0


def test_del_one_borra_la_seleccionada_y_la_papelera_permite_deshacer(tmp_path):
    """Rompe: ``_del_one`` que borre otra plantilla o no guarde en ``trash``."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    n = len(s.entries)
    s.act("tile:2")
    elegida = s.entries[2].path
    assert s.state.sel == 2
    assert _pedido(s, "del_one", confirmar=True) == "del_one"
    assert not elegida.exists() and len(s.entries) == n - 1
    assert s.state.message == f"borrada {elegida.name}" and len(s.trash) == 1
    assert _pedido(s, "undo") == "undo"
    assert elegida.exists() and len(s.entries) == n and s.trash == []
    assert s.state.message.startswith("restauradas 1")


def test_undo_sin_nada_que_deshacer_avisa(tmp_path):
    """Rompe: ``_undo`` que lance con la papelera vacia."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    _pedido(s, "undo")
    assert s.state.message == "nada que deshacer"


def test_del_label_borra_todas_las_de_esa_etiqueta(tmp_path):
    """Rompe: ``_del_label`` que borre solo la elegida o toda la biblioteca."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    etiqueta = s.entries[0].label
    n_etq = sum(e.label == etiqueta for e in s.entries)
    n = len(s.entries)
    _pedido(s, "del_label", confirmar=True)
    assert all(e.label != etiqueta for e in s.entries) and len(s.entries) == n - n_etq
    assert s.state.message == f"borradas {n_etq} plantillas de '{etiqueta}'"
    _pedido(s, "undo")
    assert len(s.entries) == n


def test_borrar_un_lote_se_deshace_de_a_una_operacion(tmp_path):
    """Rompe: una papelera que mezcle operaciones (el undo restauraria todo junto)."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    n = len(s.entries)
    _pedido(s, "del_one", confirmar=True)
    _pedido(s, "del_one", confirmar=True)
    assert len(s.entries) == n - 2
    _pedido(s, "undo")
    assert len(s.entries) == n - 1


def test_relabel_cambia_la_etiqueta_y_reselecciona_el_destino(tmp_path):
    """Rompe: ``_reselect`` que ignore ``dest`` (la seleccion quedaria en otra plantilla)."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    origen = s.entries[0]
    nueva = "9" if origen.label != "9" else "8"
    _pedido(s, f"relabel:{nueva}")
    assert not origen.path.exists()
    elegida = s.entries[s.state.sel]
    assert elegida.label == nueva
    assert s.state.message.startswith(f"{origen.path.name} -> ")
    assert s.state.message.endswith(elegida.path.name)


def test_relabel_a_si_misma_o_a_punto_funciona(tmp_path):
    """Rompe: ``relabel`` que acepte solo digitos (el punto y el menos son etiquetas validas)."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    _pedido(s, "relabel:.")
    assert s.entries[s.state.sel].label == "."


def test_relabel_con_etiqueta_invalida_da_mensaje_y_no_cambia_nada(tmp_path):
    """Rompe: no atrapar el ``ValueError`` de ``library.relabel``."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    antes = sorted(e.path.name for e in s.entries)
    _pedido(s, "relabel:x")
    assert "etiqueta invalida" in s.state.message
    assert sorted(e.path.name for e in s.entries) == antes


def test_operacion_con_biblioteca_vacia_no_rompe(tmp_path):
    """Rompe: indexar ``entries[st.sel]`` sin comprobar el rango."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    s.state = TeachState(mode="library")
    for kind in ("del_one", "del_label", "relabel:3", "undo"):
        s.state = TeachState(mode="library", request=kind)
        s.run_request(s.begin_request())
    assert s.entries == [] and s.state.sel == 0
    assert L.list_backups(tmp_path / "calib" / "templates") == []


def _biblioteca_larga(base, sesion):
    """54 plantillas '0' + 2 '1' (la pagina 2 tiene solo dos)."""
    d = base / "calib" / "templates"
    modelo = next(d.glob("*.png")).read_bytes()
    for f in d.glob("*.png"):
        f.unlink()
    for n in range(PER_PAGE):
        (d / L.template_path("0", n, d).name).write_bytes(modelo)
    for n in range(2):
        (d / L.template_path("1", n, d).name).write_bytes(modelo)


def test_paginacion_se_acota_al_borrar_la_ultima_pagina(tmp_path):
    """Rompe: no recalcular ``page`` con el nuevo total (quedaria una pagina vacia)."""
    s = _sesion(tmp_path)
    _biblioteca_larga(tmp_path, s)
    _a_biblioteca(s)
    assert len(s.entries) == PER_PAGE + 2
    s.act("page+")
    assert s.state.page == 1
    s.act("tile:0")
    assert s.state.sel == PER_PAGE and s.entries[s.state.sel].label == "1"
    _pedido(s, "del_label", confirmar=True)  # borra las 2 de la pagina 2
    assert len(s.entries) == PER_PAGE
    assert s.state.page == 0 and s.state.sel == PER_PAGE - 1


def test_reselect_deja_una_plantilla_valida_al_borrar_la_ultima(tmp_path):
    """Rompe: ``_reselect`` que devuelva ``sel`` sin acotar."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    ultima = len(s.entries) - 1
    s.act(f"tile:{ultima}")
    assert s.state.sel == ultima
    _pedido(s, "del_one", confirmar=True)
    assert s.state.sel == len(s.entries) - 1


def test_reselect_con_biblioteca_vacia_devuelve_cero(tmp_path):
    """Rompe: ``_reselect`` que no contemple ``entries`` vacio."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    assert s._reselect(TeachState(sel=7), None) == 0


def test_paginacion_del_reducer():
    """Rompe: el tope de ``page+`` o la cuenta de paginas (``(n_lib-1)//PER_PAGE``)."""
    s = TeachState(mode="library")
    assert apply_action(s, "page+", 3, n_lib=PER_PAGE).page == 0  # justo una pagina
    assert apply_action(s, "page+", 3, n_lib=PER_PAGE + 1).page == 1
    assert apply_action(s, "page+", 3, n_lib=0).page == 0
    assert apply_action(s, "tile:5", 3, n_lib=5) == s  # indice 5 de 5: no existe
    assert apply_action(s, "tile:4", 3, n_lib=5).sel == 4


# ==========================================================================
# un solo respaldo por sesion
# ==========================================================================
def _respaldos(base):
    return L.list_backups(base / "calib" / "templates")


def test_varios_borrados_seguidos_toman_un_solo_respaldo(tmp_path):
    """Rompe: ``_ensure_backup`` sin la marca ``_backed_up`` (o ``backup=True`` en ``delete``)."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    antes = {f.name: f.read_bytes() for f in (tmp_path / "calib" / "templates").glob("*.png")}
    assert s.backup_path is None
    for _ in range(4):
        _pedido(s, "del_one", confirmar=True)
    assert len(_respaldos(tmp_path)) == 1 and s.backup_path is not None
    assert s.backup_path.parent == L.backups_root(tmp_path / "calib" / "templates")
    # el respaldo conserva el estado previo a la sesion, no un estado intermedio
    guardado = {f.name: f.read_bytes() for f in s.backup_path.glob("*.png")}
    assert guardado == antes


def test_borrar_y_reetiquetar_en_la_misma_sesion_comparten_el_respaldo(tmp_path):
    """Rompe: respaldar por separado en ``_relabel`` y ``_del_label``."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    _pedido(s, "del_one", confirmar=True)
    primero = s.backup_path
    _pedido(s, "relabel:9")
    _pedido(s, "del_label", confirmar=True)
    assert len(_respaldos(tmp_path)) == 1 and s.backup_path == primero


def test_sin_operaciones_destructivas_no_hay_respaldo(tmp_path):
    """Sin borrar/reemplazar/agregar a la biblioteca (``add_lib``) no hay respaldo: ``add_lib``
    SI respalda (ver los tests de ``add_lib``). Rompe: respaldar al abrir la sesion o al refrescar."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    s.act("tile:1")
    _pedido(s, "undo")
    _pedido(s, "validate")
    s.act("samples")
    assert s.backup_path is None and _respaldos(tmp_path) == []


def test_deshacer_no_toma_otro_respaldo(tmp_path):
    """Red de seguridad: que ``undo`` llame a ``_ensure_backup`` es una mutacion equivalente
    (la papelera solo se llena despues de un borrado, que ya respaldo), asi que no puede fallar."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    _pedido(s, "del_one", confirmar=True)
    _pedido(s, "undo")
    assert len(_respaldos(tmp_path)) == 1


def test_etiqueta_invalida_en_relabel_falla_antes_de_respaldar(tmp_path):
    """Rompe: llamar a ``_ensure_backup`` antes de validar la etiqueta."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    _pedido(s, "relabel:x")
    assert s.backup_path is None and _respaldos(tmp_path) == []
    _pedido(s, "relabel:9")  # una valida si respalda
    assert s.backup_path is not None and len(_respaldos(tmp_path)) == 1


def test_el_respaldo_se_toma_antes_de_borrar(tmp_path, monkeypatch):
    """Rompe: respaldar despues de ``delete`` (el respaldo ya no tendria la plantilla)."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    n = len(s.entries)
    _pedido(s, "del_one", confirmar=True)
    assert len(list(s.backup_path.glob("*.png"))) == n


def test_una_sesion_nueva_toma_su_propio_respaldo(tmp_path):
    """Rompe: guardar la marca ``_backed_up`` a nivel de modulo o de clase."""
    a = _sesion(tmp_path)
    _a_biblioteca(a)
    _pedido(a, "del_one", confirmar=True)
    b = TeachSession(a.cfg, a.params, a.names, {}, a.samples)
    _a_biblioteca(b)
    assert b.backup_path is None
    _pedido(b, "del_one", confirmar=True)
    assert b.backup_path is not None and b.backup_path != a.backup_path
    assert len(_respaldos(tmp_path)) == 2


# ==========================================================================
# cache del pool
# ==========================================================================
@pytest.fixture
def cuenta_pool(monkeypatch):
    llamadas = []
    original = T.build_pool

    def espia(muestras, *a, **k):
        llamadas.append([m.file for m in muestras])
        return original(muestras, *a, **k)

    monkeypatch.setattr(T, "build_pool", espia)
    return llamadas


def test_refresh_library_no_reconstruye_el_pool_si_las_muestras_no_cambiaron(tmp_path, cuenta_pool):
    """Rompe: ``_pool`` sin cache (cada borrado reconstruiria todos los glifos)."""
    s = _sesion(tmp_path)
    cuenta_pool.clear()  # la sesion armo la biblioteca con el mismo build_pool
    s.refresh_library()
    s.refresh_library()
    _a_biblioteca(s)
    _pedido(s, "del_one", confirmar=True)
    _pedido(s, "undo")
    assert len(cuenta_pool) == 1


def test_el_pool_se_reconstruye_al_agregar_una_muestra(tmp_path, cuenta_pool):
    """Rompe: una clave de cache que no mire las muestras (cache eterno)."""
    s = _sesion(tmp_path, n_train=3)
    cuenta_pool.clear()  # la sesion armo la biblioteca con el mismo build_pool
    s.refresh_library()
    _ir_a(s, 5)
    _escribir(s, "-0.246")
    s.act("add")
    s.refresh_library()
    assert len(cuenta_pool) == 2 and NOMBRES[5] in cuenta_pool[1]


def test_el_pool_se_reconstruye_al_quitar_una_muestra(tmp_path, cuenta_pool):
    """Rompe: una clave que solo mire la cantidad o los nombres de las muestras de entrenamiento."""
    s = _sesion(tmp_path, n_train=4)
    cuenta_pool.clear()  # la sesion armo la biblioteca con el mismo build_pool
    s.refresh_library()
    _ir_a(s, 1)
    s.act("remove")
    s.refresh_library()
    assert len(cuenta_pool) == 2 and NOMBRES[1] not in cuenta_pool[1]


def test_el_pool_se_reconstruye_si_cambia_el_valor_de_una_muestra(tmp_path, cuenta_pool):
    """Rompe: una clave con solo los nombres (el glifo etiquetado cambia con el valor)."""
    s = _sesion(tmp_path, n_train=4)
    cuenta_pool.clear()  # la sesion armo la biblioteca con el mismo build_pool
    s.refresh_library()
    _ir_a(s, 3)  # la ultima: reetiquetarla no cambia el orden de las muestras
    assert s.state.text == "2.345"
    s.state = TeachState(**{**s.state.__dict__, "text": "2.346"})
    s.act("add")
    assert [x.file for x in s.samples] == NOMBRES[:4] and s.samples[3].value == "2.346"
    s.refresh_library()
    assert len(cuenta_pool) == 2


def test_agregar_una_muestra_de_prueba_no_reconstruye_el_pool(tmp_path, cuenta_pool):
    """Rompe: una clave que incluya ``self.test`` (la prueba no alimenta el pool)."""
    s = _sesion(tmp_path, n_train=3)
    cuenta_pool.clear()  # la sesion armo la biblioteca con el mismo build_pool
    s.refresh_library()
    s.state = TeachState(**{**s.state.__dict__, "target": "test"})
    _ir_a(s, 9)
    _escribir(s, "-7.890")
    s.act("add")
    s.refresh_library()
    assert len(cuenta_pool) == 1


def test_validate_y_refresh_comparten_el_pool(tmp_path, cuenta_pool):
    """Rompe: que ``_run_build`` llame a ``build_pool`` directo en vez de ``_pool``."""
    s = _sesion(tmp_path)
    cuenta_pool.clear()  # la sesion armo la biblioteca con el mismo build_pool
    s.refresh_library()
    _pedido(s, "validate")
    _pedido(s, "validate")
    assert len(cuenta_pool) == 1


def test_el_pool_cacheado_no_deja_usos_viejos_tras_cambiar_la_biblioteca(tmp_path):
    """Rompe: cachear tambien ``usage`` (los usos dependen de la biblioteca, no solo de las muestras)."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    total = sum(e.uses + e.errors for e in s.entries)
    _pedido(s, "del_one", confirmar=True)
    assert sum(e.uses + e.errors for e in s.entries) == total  # las celdas siguen y las gana otra plantilla


# ==========================================================================
# teclas
# ==========================================================================
def test_teclas_en_modo_muestras():
    """Rompe: el mapa de teclas del modo muestras."""
    assert key_to_action(KEY_LEFT, False) == "prev" and key_to_action(KEY_RIGHT, False) == "next"
    assert key_to_action(KEY_ENTER, False) == "add"
    assert key_to_action(KEY_BACKSPACE, False) == "back"
    assert key_to_action(KEY_ESC, False) == "save"
    assert key_to_action(ord("7"), False) == "key:7"
    assert key_to_action(ord("."), False) == "key:." and key_to_action(ord("-"), False) == "key:-"
    assert key_to_action(ord("a"), False) is None and key_to_action(-1, False) is None
    assert key_to_action(0, False) is None


def test_teclas_en_modo_biblioteca():
    """Rompe: dejar que el tipeo o Enter actuen en la biblioteca, o que ESC guarde en vez de volver."""
    assert key_to_action(KEY_LEFT, True) == "page-" and key_to_action(KEY_RIGHT, True) == "page+"
    assert key_to_action(KEY_ESC, True) == "samples"
    assert key_to_action(KEY_ENTER, True) is None
    assert key_to_action(KEY_BACKSPACE, True) is None
    assert key_to_action(ord("7"), True) is None


def test_la_tecla_con_bits_altos_se_reduce_al_byte(tmp_path):
    """Rompe: no enmascarar con ``0xFF`` (``waitKeyEx`` devuelve bits altos en algunas plataformas)."""
    assert key_to_action(0x100000 | ord("3"), False) == "key:3"


def test_esc_en_modo_muestras_guarda_y_termina(tmp_path):
    """Rompe: que ESC no marque ``done`` (la ventana no se cerraria)."""
    s = _sesion(tmp_path)
    s.on_key(KEY_ESC)
    assert s.state.done is True


def test_esc_en_biblioteca_vuelve_a_muestras_sin_terminar(tmp_path):
    """Rompe: que ESC en biblioteca guarde y salga."""
    s = _sesion(tmp_path)
    _a_biblioteca(s)
    s.on_key(KEY_ESC)
    assert s.state.mode == "samples" and s.state.done is False


def test_on_key_tipea_y_agrega(tmp_path):
    """Rompe: ``on_key`` que no pase por ``act`` (Enter no agregaria)."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    _ir_a(s, 0)
    for ch in "-0.123":
        s.on_key(ord(ch))
    s.on_key(KEY_BACKSPACE)
    assert s.state.text == "-0.12"
    s.on_key(ord("3"))
    s.on_key(KEY_ENTER)
    assert s.samples == [T.Sample(NOMBRES[0], "-0.123")] and s.state.index == 1


def test_on_key_ignora_teclas_sin_accion(tmp_path):
    """Rompe: ``on_key`` que lance con una tecla desconocida."""
    s = _sesion(tmp_path)
    antes = s.state
    s.on_key(ord("z"))
    assert s.state == antes


# ==========================================================================
# funciones puras
# ==========================================================================
def test_tipeo_limitado_a_12_y_solo_caracteres_validos():
    """Rompe: el largo maximo o el conjunto de caracteres."""
    s = TeachState()
    for _ in range(20):
        s = apply_action(s, "key:1", 3)
    assert len(s.text) == 12
    assert apply_action(TeachState(), "key:x", 3).text == ""


def test_go_to_sin_nombres_y_acota():
    """Rompe: ``go_to`` que lance con lista vacia o no acote."""
    assert go_to(TeachState(index=4), [], [], 3).index == 0
    assert go_to(TeachState(), [], ["a", "b"], 99).index == 1
    assert go_to(TeachState(), [], ["a", "b"], -5).index == 0


def test_add_sample_no_deja_la_muestra_en_los_dos_conjuntos(cfg_sign):
    """Rompe: ``assign`` que no quite del otro conjunto."""
    r = add_sample([T.Sample("a", "1.111")], [], "a", "1.111", cfg_sign.digits, "test")
    assert r.train == [] and [x.file for x in r.test] == ["a"] and r.added
    r = add_sample(r.train, r.test, "a", "1.111", cfg_sign.digits, "train")
    assert r.test == [] and [x.file for x in r.train] == ["a"]


def test_add_sample_invalida_no_cambia_nada_y_no_dice_agregada(cfg_sign):
    """Rompe: ``AddResult.added`` siempre verdadero."""
    train = [T.Sample("b", "2.222")]
    r = add_sample(train, [], "a", "99", cfg_sign.digits, "train")
    assert not r.added and r.train == train and r.test == []
    assert "agregada" not in r.message


def test_la_biblioteca_respaldada_por_la_sesion_se_puede_restaurar(tmp_path):
    """Rompe: un respaldo vacio o en otra carpeta (``restore_backup`` no encontraria el estado previo)."""
    s = _sesion(tmp_path)
    d = tmp_path / "calib" / "templates"
    antes = {f.name: f.read_bytes() for f in d.glob("*.png")}
    _a_biblioteca(s)
    for _ in range(3):
        _pedido(s, "del_one", confirmar=True)
    L.restore_backup(d)
    assert {f.name: f.read_bytes() for f in d.glob("*.png")} == antes
    shutil.rmtree(tmp_path / "calib" / ".backups")


# ==========================================================================
# respaldo en add_lib y is_slow
# ==========================================================================
def test_add_lib_toma_el_respaldo_antes_de_agregar(tmp_path, monkeypatch):
    """Rompe: sacar ``_ensure_backup`` de ``_run_build`` para ``add_lib`` (o llamarlo despues de ``add``)."""
    s = _sesion(tmp_path)
    orden = []

    def espiar(nombre):
        original = getattr(L, nombre)
        monkeypatch.setattr(L, nombre, lambda *a, **k: (orden.append(nombre), original(*a, **k))[1])

    espiar("backup")
    espiar("add")
    _pedido(s, "add_lib")
    assert orden[:2] == ["backup", "add"]
    assert s.backup_path is not None and len(_respaldos(tmp_path)) == 1


def test_con_biblioteca_vacia_se_marca_respaldado_y_no_hay_ruta(tmp_path):
    """Rompe: no marcar ``_backed_up`` cuando no hay nada que respaldar (reintentaria en cada cambio)."""
    s = _sesion(tmp_path, con_biblioteca=False)
    s._ensure_backup()
    assert s._backed_up and s.backup_path is None and _respaldos(tmp_path) == []


def test_si_backup_devuelve_none_con_plantillas_no_se_marca_respaldado(tmp_path, monkeypatch):
    """Rompe: marcar ``_backed_up`` sin comprobar que haya plantillas (un fallo dejaria sin red de seguridad)."""
    s = _sesion(tmp_path)
    monkeypatch.setattr(L, "backup", lambda *a, **k: None)
    s._ensure_backup()
    assert not s._backed_up and s.backup_path is None


def test_is_slow_refresh_lib_depende_del_pool_en_cache(tmp_path):
    """Rompe: tratar ``refresh_lib`` siempre como rapido, o ignorar el cache del pool."""
    s = _sesion(tmp_path)
    assert s._pool_cache is None and s.is_slow("refresh_lib")
    s._pool()
    assert not s.is_slow("refresh_lib")
    s.samples = s.samples[:-1]  # cambian las muestras: el cache queda viejo
    assert s.is_slow("refresh_lib")


def test_is_slow_con_pedido_vacio_es_falso(tmp_path):
    """Rompe: quitar el ``bool(kind)`` (sin pedido el loop dibujaria ``trabajando...`` siempre que el pool este frio)."""
    s = _sesion(tmp_path)
    assert s._cold_pool() and not s.is_slow("")


def test_el_teclado_fisico_emite_key_y_back_aunque_no_haya_botones(tmp_path, monkeypatch):
    """Rompe: que ``on_key`` deje de traducir digitos, ``.``, ``-`` o Backspace a acciones
    (al quitar los botones numericos de ``layout_teach`` seria la unica forma de tipear)."""
    s = _sesion(tmp_path, n_train=0, con_biblioteca=False)
    emitidas = []
    monkeypatch.setattr(s, "act", lambda a: emitidas.append(a))
    for ch in "0123456789.-":
        s.on_key(ord(ch))
    s.on_key(KEY_BACKSPACE)
    assert emitidas == [f"key:{c}" for c in "0123456789.-"] + ["back"]
