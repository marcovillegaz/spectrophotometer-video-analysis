"""La convencion de nombres es el contrato entre ``extract`` y el resto.

Si el nombre de archivo deja de reflejar el tiempo del fotograma, toda la serie
temporal queda mal, asi que se prueba la ida y la vuelta a varios ``--fps``.
"""

import pytest

from spectro.extract import format_hhmmss, frame_name, frame_time, time_from_name


@pytest.mark.parametrize("fps", [0.5, 1.0, 4.0, 29.97])
@pytest.mark.parametrize("index", [1, 2, 37, 1203])
def test_ida_y_vuelta(fps, index):
    t = frame_time(index, fps)
    assert time_from_name(frame_name(t)) == pytest.approx(t, abs=1e-3)


def test_primer_fotograma_es_t_cero():
    assert frame_time(1, 1.0) == 0.0
    assert frame_name(0.0) == "t_0000000.000.jpg"


def test_start_desplaza_la_escala():
    assert frame_time(1, 1.0, start=600) == 600.0
    assert frame_time(5, 4.0, start=600) == 601.0


def test_orden_alfabetico_es_orden_temporal():
    nombres = [frame_name(frame_time(i, 4.0)) for i in range(1, 60)]
    assert nombres == sorted(nombres)


def test_nombre_fuera_de_convencion():
    with pytest.raises(ValueError):
        time_from_name("f_000123.jpg")


def test_indice_es_1_based():
    with pytest.raises(ValueError):
        frame_time(0, 1.0)


def test_fps_invalido():
    with pytest.raises(ValueError):
        frame_time(1, 0.0)


@pytest.mark.parametrize(
    "t_s, esperado",
    [(0.0, "00:00:00.000"), (61.5, "00:01:01.500"), (3723.25, "01:02:03.250")],
)
def test_formato_hhmmss(t_s, esperado):
    assert format_hhmmss(t_s) == esperado
