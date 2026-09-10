"""Armado del numero con el punto decimal fijo, y casos borde."""

import pytest

from spectro.config import DigitsConfig
from spectro.read import assemble


@pytest.mark.parametrize(
    "digitos, decimal_after, esperado",
    [
        ("0245", 1, 0.245),
        ("1789", 1, 1.789),
        ("0000", 1, 0.0),
        ("9999", 1, 9.999),
        ("245", 0, 0.245),
        ("1234", 2, 12.34),
        ("42", 2, 42.0),
    ],
)
def test_assemble(digitos, decimal_after, esperado):
    assert assemble(digitos, decimal_after) == pytest.approx(esperado)


@pytest.mark.parametrize("digitos", ["", "12a4", "0.24", "-123"])
def test_assemble_rechaza_basura(digitos):
    with pytest.raises(ValueError):
        assemble(digitos, 1)


def test_assemble_rechaza_decimal_fuera_de_rango():
    with pytest.raises(ValueError):
        assemble("0245", 9)


def test_slots_uniformes():
    d = DigitsConfig(n_digits=5)
    assert d.resolved_splits(130) == [0, 26, 52, 78, 104, 130]


def test_slots_manuales_mandan():
    d = DigitsConfig(n_digits=2, splits=[0, 10, 30])
    assert d.resolved_splits(100) == [0, 10, 30]


def test_slots_manuales_de_largo_incorrecto_se_ignoran():
    d = DigitsConfig(n_digits=2, splits=[0, 10])
    assert d.resolved_splits(100) == [0, 50, 100]


def test_separadores_no_son_digitos():
    d = DigitsConfig(n_digits=5, separator_slots=[1])
    assert d.digit_slots() == [0, 2, 3, 4]
