"""El layout multi-video: id de corrida, derivacion de rutas y calibracion auto.

Todo corre sobre las fixtures sinteticas de ``conftest.py``: no hace falta el
video real ni la corrida migrada.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from conftest import make_config, render_display
from spectro.cli import build_parser, main, resolve_paths
from spectro.config import Config
from spectro.project import (
    CalibPaths,
    RunPaths,
    calib_recipe,
    list_runs,
    run_id_from_video,
    seed_run_config,
)


# --------------------------------------------------------------------------
# Id de corrida
# --------------------------------------------------------------------------
def test_id_de_video_de_iphone():
    """La regla documentada: YYYYMMDD_HHMMSS, sin los milisegundos ni el sufijo."""
    assert run_id_from_video("videos/20260901_164220000_iOS.MOV") == "20260901_164220"


def test_id_de_iphone_no_depende_de_la_carpeta_ni_la_extension():
    assert run_id_from_video("20260903_101500123_iOS.mov") == "20260903_101500"


def test_id_generico_se_sanea():
    assert run_id_from_video("Cinetica Fe (2).MOV") == "cinetica_fe_2"


def test_name_overridea_la_derivacion():
    assert run_id_from_video("20260901_164220000_iOS.MOV", "cinetica-fe-02") == "cinetica_fe_02"


def test_name_vacio_cae_en_la_derivacion():
    assert run_id_from_video("20260901_164220000_iOS.MOV", "  ") == "20260901_164220"


def test_id_imposible_da_error():
    with pytest.raises(ValueError):
        run_id_from_video("---.MOV")


# --------------------------------------------------------------------------
# RunPaths / CalibPaths
# --------------------------------------------------------------------------
def test_run_paths_arma_las_ocho_rutas(tmp_path):
    run = RunPaths.for_run("r1", base=tmp_path)
    raiz = tmp_path / "runs" / "r1"
    assert run.root == raiz
    assert run.config == raiz / "config.json"
    assert run.frames == raiz / "frames"
    assert run.index == raiz / "frames_index.csv"
    assert run.out == raiz / "out"
    assert run.qc_report == raiz / "out" / "qc_report.csv"
    assert run.readings == raiz / "out" / "readings.csv"
    # La biblioteca es compartida: sale de calib/, no de la corrida.
    assert run.templates == tmp_path / "calib" / "templates"


def test_list_runs_encuentra_las_corridas(tmp_path):
    assert list_runs(base=tmp_path) == []
    for run_id in ("20260903_101500", "20260901_164220"):
        RunPaths.for_run(run_id, base=tmp_path).create()
    # Alfabetico es cronologico con el id derivado de la fecha.
    assert list_runs(base=tmp_path) == ["20260901_164220", "20260903_101500"]


def test_run_is_done_mira_el_entregable(tmp_path):
    run = RunPaths.for_run("r1", base=tmp_path).create()
    assert not run.is_done()
    run.absorbance.write_text("t_s,absorbancia\n", encoding="utf-8")
    assert run.is_done()


# --------------------------------------------------------------------------
# seed_run_config
# --------------------------------------------------------------------------
def test_seed_hereda_la_receta_y_deja_la_roi_sin_fijar():
    calib = calib_recipe(make_config())
    cfg = seed_run_config(calib, "videos/nuevo.MOV", fps=4.0)

    assert cfg.video == "videos/nuevo.MOV" and cfg.fps == 4.0
    # Geometria y matcheo se heredan: el display es el mismo.
    assert cfg.digits.n_digits == calib.digits.n_digits
    assert cfg.digits.separator_slots == calib.digits.separator_slots
    assert cfg.digits.decimal_after == calib.digits.decimal_after
    assert cfg.templates.size == calib.templates.size
    # Encuadre y umbrales son de la sesion: los fija calibrate / qc.
    assert not cfg.roi.is_valid()
    assert not cfg.qc.anchor.is_valid()
    assert cfg.qc.reference_frame == ""
    assert cfg.qc.min_mean_luma == Config.default().qc.min_mean_luma


def test_seed_no_muta_la_calib():
    calib = calib_recipe(make_config())
    antes = calib.roi.as_tuple()
    seed_run_config(calib, "videos/nuevo.MOV", fps=4.0)
    assert calib.roi.as_tuple() == antes


def test_calib_recipe_descarta_lo_propio_de_la_corrida():
    cfg = make_config()
    cfg.video, cfg.fps = "videos/viejo.MOV", 4.0
    cfg.time.offset_s = -12.5
    cfg.qc.min_mean_luma = 27.96
    receta = calib_recipe(cfg)

    assert receta.video == "" and receta.time.offset_s == 0.0
    assert receta.qc.min_mean_luma == Config.default().qc.min_mean_luma
    # ROI y ancla si se conservan: son la referencia contra la que registra --auto.
    assert receta.roi == cfg.roi and receta.qc.anchor == cfg.qc.anchor


# --------------------------------------------------------------------------
# Precedencia de rutas en la CLI
# --------------------------------------------------------------------------
def _args(tmp_path, *argv):
    """Parsea con las carpetas del proyecto apuntando a ``tmp_path``."""
    globales = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    return build_parser().parse_args(globales + list(argv))


def test_run_deriva_las_rutas_de_la_etapa(tmp_path):
    args = _args(tmp_path, "--run", "r1", "qc")
    assert resolve_paths(args) is None
    run = RunPaths.for_run("r1", base=tmp_path)
    assert args.frames_dir == str(run.frames)
    assert args.index == str(run.index)
    assert args.qc_report == str(run.qc_report)
    assert args.config == str(run.config)


def test_flag_explicito_le_gana_a_lo_derivado(tmp_path):
    """Es lo que mantiene vivos los usos que pasan rutas a mano."""
    otro = tmp_path / "otro_lado"
    args = _args(tmp_path, "--run", "r1", "qc", "--frames-dir", str(otro))
    assert resolve_paths(args) is None
    assert args.frames_dir == str(otro)
    # Lo que no se paso a mano se sigue derivando.
    assert args.qc_report == str(RunPaths.for_run("r1", base=tmp_path).qc_report)


def test_config_explicito_le_gana_a_lo_derivado(tmp_path):
    mio = tmp_path / "mi_config.json"
    args = _args(tmp_path, "--run", "r1", "--config", str(mio), "read")
    assert resolve_paths(args) is None
    assert args.config == str(mio)


def test_templates_salen_de_calib_no_de_la_corrida(tmp_path):
    args = _args(tmp_path, "--run", "r1", "read")
    assert resolve_paths(args) is None
    assert args.templates_dir == str(CalibPaths.at(tmp_path / "calib").templates)


def test_sin_run_el_error_lista_las_corridas(tmp_path):
    RunPaths.for_run("20260901_164220", base=tmp_path).create()
    args = _args(tmp_path, "qc")
    error = resolve_paths(args)
    assert error is not None
    assert "falta --run" in error
    assert "20260901_164220" in error


def test_sin_run_y_sin_corridas_sugiere_new(tmp_path):
    error = resolve_paths(_args(tmp_path, "qc"))
    assert error is not None and "spectro new" in error


def test_sin_run_pero_con_todas_las_rutas_a_mano_funciona(tmp_path):
    """Sin --run, pero con las cuatro rutas de la etapa puestas: no hay nada que derivar."""
    args = _args(
        tmp_path,
        "--config", str(tmp_path / "c.json"),   # --config es global: va antes del subcomando
        "qc",
        "--frames-dir", str(tmp_path / "f"),
        "--index", str(tmp_path / "i.csv"),
        "--qc-report", str(tmp_path / "qc.csv"),
    )
    assert resolve_paths(args) is None


def test_doctor_no_exige_run(tmp_path):
    assert resolve_paths(_args(tmp_path, "doctor")) is None


def test_run_funciona_antes_y_despues_del_subcomando(tmp_path):
    """La posicion del flag no puede ser una trampa: los dos ordenes valen.

    ``--run`` es global, y argparse exige los globales antes del subcomando. Pero
    ``spectro extract --run X`` es como se lee natural y es lo que documenta el
    README, asi que cada subcomando repite los flags del layout.
    """
    runs = str(tmp_path / "runs")
    calib = str(tmp_path / "calib")
    esperado = str(RunPaths.for_run("r1", base=tmp_path).frames)

    for argv in (
        ["--runs-dir", runs, "--calib-dir", calib, "--run", "r1", "qc"],
        ["--runs-dir", runs, "--calib-dir", calib, "qc", "--run", "r1"],
    ):
        args = build_parser().parse_args(argv)
        assert resolve_paths(args) is None
        assert args.run == "r1"
        assert args.frames_dir == esperado


def test_si_run_va_en_los_dos_lados_gana_el_del_subcomando(tmp_path):
    args = build_parser().parse_args(
        ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib"),
         "--run", "vieja", "qc", "--run", "nueva"]
    )
    assert resolve_paths(args) is None
    assert args.run == "nueva"


# --------------------------------------------------------------------------
# calibrate --auto
# --------------------------------------------------------------------------
@pytest.fixture
def proyecto_calibrado(tmp_path):
    """``calib/`` con la receta y la referencia, y una corrida sin calibrar."""
    calib = CalibPaths.at(tmp_path / "calib")
    calib.root.mkdir(parents=True)
    referencia = render_display("0.245")
    cv2.imwrite(str(calib.reference), referencia)
    calib_recipe(make_config()).save(calib.config)
    return {"base": tmp_path, "calib": calib, "referencia": referencia}


def _corrida_con_fotograma(base, run_id, frame):
    run = RunPaths.for_run(run_id, base=base).create()
    cv2.imwrite(str(run.frames / "t_0000000.000.jpg"), frame)
    return run


def _calibrar_auto(base, run_id, *extra):
    globales = ["--runs-dir", str(base / "runs"), "--calib-dir", str(base / "calib")]
    return main(globales + ["--run", run_id, "calibrate", "--auto", *extra])


def test_auto_engancha_la_roi_sobre_los_digitos(proyecto_calibrado, library):
    """El encuadre se corrio: la ROI tiene que seguir cayendo sobre el numero."""
    from spectro.read import read_frame

    base = proyecto_calibrado["base"]
    corrido = np.roll(np.roll(render_display("0.245"), 5, axis=0), 7, axis=1)
    run = _corrida_con_fotograma(base, "r1", corrido)

    assert _calibrar_auto(base, "r1", "--search-px", "20") == 0

    cfg = Config.load(run.config)
    original = make_config().roi
    assert (cfg.roi.x, cfg.roi.y) == (original.x + 7, original.y + 5)
    assert (cfg.roi.w, cfg.roi.h) == (original.w, original.h)
    assert cfg.qc.reference_frame == "t_0000000.000.jpg"
    # La prueba que importa: con esa ROI el numero se lee bien.
    assert read_frame(corrido, cfg, library).value == pytest.approx(0.245)


def test_auto_hereda_la_geometria_de_la_calib(proyecto_calibrado):
    base = proyecto_calibrado["base"]
    run = _corrida_con_fotograma(base, "r1", render_display("0.245"))
    assert _calibrar_auto(base, "r1", "--search-px", "20") == 0

    cfg = Config.load(run.config)
    receta = Config.load(proyecto_calibrado["calib"].config)
    assert cfg.digits.separator_slots == receta.digits.separator_slots
    assert cfg.digits.decimal_after == receta.digits.decimal_after
    assert cfg.templates.size == receta.templates.size


def test_auto_escribe_el_overlay_de_verificacion(proyecto_calibrado):
    base = proyecto_calibrado["base"]
    run = _corrida_con_fotograma(base, "r1", render_display("0.245"))
    assert _calibrar_auto(base, "r1", "--search-px", "20") == 0
    assert run.preview.exists()


def test_auto_fuera_de_rango_falla_en_vez_de_devolver_una_roi_mala(proyecto_calibrado):
    """Un salto de encuadre mayor al margen de busqueda no se adivina."""
    base = proyecto_calibrado["base"]
    muy_corrido = np.roll(render_display("0.245"), 90, axis=1)
    run = _corrida_con_fotograma(base, "r1", muy_corrido)

    assert _calibrar_auto(base, "r1", "--search-px", "8") != 0
    # Lo importante no es el codigo de salida sino que no dejo una ROI puesta.
    assert not run.config.exists() or not Config.load(run.config).roi.is_valid()


def test_auto_sin_referencia_da_mensaje_util(tmp_path):
    calib = CalibPaths.at(tmp_path / "calib")
    calib.root.mkdir(parents=True)
    calib_recipe(make_config()).save(calib.config)  # receta si, reference.jpg no
    _corrida_con_fotograma(tmp_path, "r1", render_display("0.245"))
    assert _calibrar_auto(tmp_path, "r1") != 0


def test_auto_con_otra_resolucion_se_niega(proyecto_calibrado):
    """El registro corrige traslacion, no escala: cambiar de distancia no se arregla solo."""
    base = proyecto_calibrado["base"]
    chico = cv2.resize(render_display("0.245"), None, fx=0.5, fy=0.5)
    run = _corrida_con_fotograma(base, "r1", chico)
    assert _calibrar_auto(base, "r1") != 0
    assert not run.config.exists() or not Config.load(run.config).roi.is_valid()


def test_promote_sube_la_calibracion_a_calib(proyecto_calibrado):
    base, calib = proyecto_calibrado["base"], proyecto_calibrado["calib"]
    corrido = np.roll(render_display("0.245"), 7, axis=1)
    _corrida_con_fotograma(base, "r1", corrido)

    assert _calibrar_auto(base, "r1", "--search-px", "20", "--promote") == 0

    receta = Config.load(calib.config)
    assert receta.roi.x == make_config().roi.x + 7
    assert receta.video == ""  # la receta no arrastra el video de la corrida
    # La referencia ahora es el fotograma de esta corrida.
    assert np.array_equal(cv2.imread(str(calib.reference), cv2.IMREAD_GRAYSCALE).shape, corrido.shape)


# --------------------------------------------------------------------------
# new
# --------------------------------------------------------------------------
def test_new_crea_la_corrida_y_siembra_el_config(tmp_path, proyecto_calibrado):
    base = proyecto_calibrado["base"]
    video = base / "videos" / "20260903_101500000_iOS.MOV"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"no es un video de verdad, new no lo abre")

    globales = ["--runs-dir", str(base / "runs"), "--calib-dir", str(base / "calib")]
    assert main(globales + ["new", str(video), "--fps", "4"]) == 0

    run = RunPaths.for_run("20260903_101500", base=base)
    assert run.config.exists() and run.frames.is_dir() and run.out.is_dir()
    cfg = Config.load(run.config)
    assert cfg.fps == 4.0 and Path(cfg.video).name == video.name
    assert cfg.digits.n_digits == 5      # heredado de la calib
    assert not cfg.roi.is_valid()        # lo fija calibrate


def test_new_con_name_usa_ese_id(tmp_path, proyecto_calibrado):
    base = proyecto_calibrado["base"]
    video = base / "videos" / "20260903_101500000_iOS.MOV"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    globales = ["--runs-dir", str(base / "runs"), "--calib-dir", str(base / "calib")]
    assert main(globales + ["new", str(video), "--name", "cinetica-fe-02"]) == 0
    assert RunPaths.for_run("cinetica_fe_02", base=base).config.exists()


def test_extract_hereda_el_fps_de_la_corrida(proyecto_calibrado, monkeypatch):
    """``new --fps 4`` fija el fps de la corrida; ``extract`` tiene que usarlo.

    Sin esto, ``extract --run <id>`` cae en su propio default de 1 Hz y extrae
    un cuarto de los fotogramas sin decir nada.
    """
    import spectro.extract as extract_mod

    base = proyecto_calibrado["base"]
    video = base / "videos" / "20260903_101500000_iOS.MOV"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"x")
    globales = ["--runs-dir", str(base / "runs"), "--calib-dir", str(base / "calib")]
    assert main(globales + ["new", str(video), "--fps", "4"]) == 0

    visto = {}

    def falso_extract(**kwargs):
        visto.update(kwargs)
        return [object()]  # una fila cualquiera: extract solo mira si hubo salida

    monkeypatch.setattr(extract_mod, "extract_frames", falso_extract)

    assert main(globales + ["extract", "--run", "20260903_101500"]) == 0
    assert visto["fps"] == 4.0

    # Y un --fps explicito sigue ganando.
    assert main(globales + ["extract", "--run", "20260903_101500", "--fps", "2"]) == 0
    assert visto["fps"] == 2.0


def test_new_con_video_inexistente_falla(tmp_path):
    globales = ["--runs-dir", str(tmp_path / "runs"), "--calib-dir", str(tmp_path / "calib")]
    assert main(globales + ["new", str(tmp_path / "no_existe.MOV")]) != 0


# ==========================================================================
# RunContext: el reporte de qc se parsea una sola vez y names() coincide
# ==========================================================================
def _ctx_corrida(tmp_path, filas, con_reporte=True, frames=()):
    """Una corrida de juguete con ``qc_report.csv`` (``filas`` = ``[(archivo, estado, dx, dy)]``)."""
    from spectro.qc import QCRow, write_qc_report

    run = RunPaths.for_run("r1", base=tmp_path).create()
    make_config().save(run.config)
    for nombre in frames:
        (run.frames / nombre).write_bytes(b"x")
    if con_reporte:
        write_qc_report([QCRow(file=a, t_s=float(i), index=i + 1, status=e, dx=dx, dy=dy)
                         for i, (a, e, dx, dy) in enumerate(filas)], run.qc_report)
    return run


FILAS = [("t_0000030.000.jpg", "ok", 1, 2), ("t_0000010.000.jpg", "dark", 0, 0),
         ("t_0000020.000.jpg", "ok", -3, 4), ("t_0000040.000.jpg", "roi_outside", 0, 0)]


def test_run_context_load_parsea_el_reporte_de_qc_una_sola_vez(tmp_path, monkeypatch):
    """Rompe: volver a llamar a ``load_qc_report`` desde ``names()``/``items()`` (parsear el CSV de nuevo)."""
    import spectro.qc as qc
    from spectro.project import RunContext

    run = _ctx_corrida(tmp_path, FILAS)
    llamadas = []
    original = qc.load_qc_report
    monkeypatch.setattr(qc, "load_qc_report", lambda *a, **k: (llamadas.append("load_qc_report"), original(*a, **k))[1])
    ctx = RunContext.load(run)
    ctx.names()
    ctx.names()
    ctx.items()
    assert llamadas == ["load_qc_report"]


def test_names_conserva_el_orden_del_reporte_y_solo_los_que_pasaron_qc(tmp_path):
    """Rompe: ordenar alfabeticamente, incluir los descartados o cambiar el orden respecto del reporte de QC."""
    from spectro.project import RunContext
    from spectro.qc import load_qc_report

    run = _ctx_corrida(tmp_path, FILAS)
    ctx = RunContext.load(run)
    assert ctx.names() == ["t_0000030.000.jpg", "t_0000020.000.jpg"]
    filas = load_qc_report(run.qc_report)
    assert ctx.names() == [r.file for r in filas if r.status == "ok"]
    assert ctx.offsets == {"t_0000030.000.jpg": (1, 2), "t_0000010.000.jpg": (0, 0),
                           "t_0000020.000.jpg": (-3, 4), "t_0000040.000.jpg": (0, 0)}
    assert ctx.offsets == {r.file: (r.dx, r.dy) for r in filas}
    assert ctx.has_qc


def test_names_sin_reporte_usa_los_fotogramas_de_la_carpeta(tmp_path):
    """Rompe: ``names()`` vacio cuando no hay reporte (``None or []``)."""
    from spectro.project import RunContext

    run = _ctx_corrida(tmp_path, [], con_reporte=False, frames=["t_0000002.000.jpg", "t_0000001.000.jpg"])
    ctx = RunContext.load(run)
    assert ctx.offsets == {} and not ctx.has_qc
    assert ctx.names() == ["t_0000001.000.jpg", "t_0000002.000.jpg"]


def test_names_con_reporte_sin_filas_que_pasaron_cae_a_la_carpeta(tmp_path):
    """Rompe: devolver una lista vacia cuando el reporte descarto todo (comportamiento previo: fotogramas de la carpeta)."""
    from spectro.project import RunContext

    run = _ctx_corrida(tmp_path, [("t_0000001.000.jpg", "dark", 0, 0)], frames=["t_0000001.000.jpg", "t_0000005.000.jpg"])
    assert RunContext.load(run).names() == ["t_0000001.000.jpg", "t_0000005.000.jpg"]


def test_names_con_reporte_solo_con_encabezado_no_rompe(tmp_path):
    """Rompe: indexar la primera fila de un reporte vacio."""
    from spectro.project import RunContext

    run = _ctx_corrida(tmp_path, [], frames=["t_0000001.000.jpg"])
    ctx = RunContext.load(run)
    assert ctx.offsets == {} and ctx.names() == ["t_0000001.000.jpg"]


def test_run_context_con_reporte_explicito_gana_al_derivado(tmp_path):
    """Rompe: ignorar el argumento ``qc_report`` al armar los corrimientos y los nombres."""
    from spectro.project import RunContext
    from spectro.qc import QCRow, write_qc_report

    run = _ctx_corrida(tmp_path, FILAS)
    otro = tmp_path / "otro_qc.csv"
    write_qc_report([QCRow(file="t_0000099.000.jpg", t_s=99.0, index=1, dx=5, dy=6)], otro)
    ctx = RunContext.load(run, qc_report=otro)
    assert ctx.names() == ["t_0000099.000.jpg"] and ctx.offsets == {"t_0000099.000.jpg": (5, 6)}
    assert ctx.qc_report == otro
