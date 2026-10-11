"""Compatibilidad con los nombres en espanol de versiones anteriores.

Unico lugar con el mapa de alias: los lectores de CSV/JSON/config aceptan los
encabezados, claves y estados viejos y los traducen a los nuevos (ingles); los
escritores emiten siempre los nuevos. Solo hay alias para lo que el codigo lee de
vuelta; las salidas que solo se escriben no los necesitan. Asi los archivos que ya existen
(``truth.csv``, ``test.csv``, ``frames_index.csv``, ``qc_report.csv``,
``readings.csv``, ``teach_history.csv``, ``read_meta.json``, ``config.json``)
siguen cargando sin reescribirse.

Interfaz publica:
    HEADER_ALIASES, VALUE_ALIASES, CONFIG_KEY_ALIASES, LEGACY_FLAGS
    normalize_row(row)          -> dict   (una fila de ``csv.DictReader``)
    read_csv_rows(path)         -> list[dict]
    normalize_keys(data)        -> dict   (claves de un JSON, p. ej. ``read_meta.json``)
    normalize_config(data)      -> dict   (claves de ``config.json``)
    normalize_status(value)     -> str
"""

from __future__ import annotations

import csv
from pathlib import Path

#: encabezado viejo -> nuevo. Solo los de archivos que el codigo lee: ``truth.csv``,
#: ``test.csv``, ``frames_index.csv``, ``qc_report.csv``, ``readings.csv``,
#: ``teach_history.csv`` y las claves de ``read_meta.json`` (``huella``, ``fecha``,
#: ``plantillas``). Los CSV que ``spectro`` solo escribe (``teach_report.csv``,
#: ``test_report.csv``, ``absorbancia.csv``) no tienen alias.
HEADER_ALIASES: dict[str, str] = {
    "archivo": "file", "valor": "value", "indice": "index", "estado": "status",
    "confianza": "confidence", "margen": "margin", "caracteres": "chars",
    "contraste": "contrast", "fecha": "date", "tipo": "kind", "plantillas": "templates",
    "entrenamiento": "training", "prueba": "test", "valores_distintos": "distinct_values",
    "correctas": "correct", "erroneas": "wrong", "descartadas": "discarded",
    "exactitud": "accuracy", "error_aceptadas": "accepted_error", "cobertura": "coverage",
    "huella": "fingerprint",
}

#: valor viejo -> nuevo, solo en las columnas de estado (``STATUS_COLUMNS``).
VALUE_ALIASES: dict[str, str] = {
    "roi_fuera": "roi_outside", "misma_corrida": "same_run", "otro_video": "other_video",
}
STATUS_COLUMNS = ("status", "kind")

#: clave vieja -> nueva dentro de ``config.json`` (seccion ``acceptance``).
CONFIG_KEY_ALIASES: dict[str, str] = {
    "min_exactitud": "min_accuracy", "min_cobertura": "min_coverage",
}

#: flags viejos -> nuevos (fallan mostrando la tabla de migracion).
LEGACY_FLAGS: dict[str, str] = {
    "--min-exactitud": "--min-accuracy", "--min-cobertura": "--min-coverage",
}


def normalize_status(value: str) -> str:
    """Un estado/resultado/tipo viejo (``roi_fuera``...) como el nuevo (``roi_outside``...)."""
    return VALUE_ALIASES.get(value, value)


def normalize_keys(data: dict) -> dict:
    """Las claves de un dict (p. ej. ``read_meta.json``) con los alias viejos traducidos."""
    return {HEADER_ALIASES.get(k, k): v for k, v in data.items()}


def normalize_row(row: dict) -> dict:
    """Una fila de CSV con encabezados y estados viejos traducidos."""
    out = normalize_keys(row)
    for col in STATUS_COLUMNS:
        if isinstance(out.get(col), str):
            out[col] = normalize_status(out[col])
    return out


def read_csv_rows(path: Path | str) -> list[dict]:
    """Lee un CSV como lista de dicts, aceptando encabezados y estados viejos."""
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return [normalize_row(r) for r in csv.DictReader(fh)]


def normalize_config(data: dict) -> dict:
    """``config.json`` con las claves viejas de ``acceptance`` traducidas (no modifica ``data``)."""
    acc = data.get("acceptance")
    if not isinstance(acc, dict):
        return data
    new = dict(data)
    new["acceptance"] = {CONFIG_KEY_ALIASES.get(k, k): v for k, v in acc.items()}
    return new
