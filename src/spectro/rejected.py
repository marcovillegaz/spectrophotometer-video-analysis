"""Fotogramas descartados al etiquetar: el registro ``runs/<id>/teach/rejected.csv``.

Al etiquetar con ``teach`` hay fotogramas que no sirven (el digito esta a medio dibujar,
hay una mano, esta desenfocado). Descartarlos los saca de la cola y deja constancia para
que ``suggest`` y ``label --queue`` no los vuelvan a proponer. El registro es por corrida
y compartido entre entrenamiento y prueba; cada fila dice de que conjunto venia el
descarte (``set``: ``train`` o ``test``) y cuando se hizo.

**Solo lo usa el etiquetado.** ``read``, ``qc``, ``train``, ``check``, ``test eval`` y
``batch`` no lo leen: una lectura dudosa se sigue descartando en la lectura, no aca.
Un archivo ausente carga como vacio y una columna ausente carga como ``""``.

Interfaz publica:
    Rejection(file, which, date)
    load_rejected(path)                               -> list[Rejection]
    save_rejected(path, rows)                         -> Path
    rejected_files(rows)                              -> set[str]
    add_rejected(rows, file, which, date)             -> list[Rejection]   (idempotente)
    remove_rejected(rows, files)                      -> (quedan, estaban)
    now_text()                                        -> str
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .compat import read_csv_rows

SETS = ("train", "test")


@dataclass(frozen=True)
class Rejection:
    file: str
    #: Conjunto del que se descarto: ``train`` o ``test`` (``""`` si el CSV no lo trae).
    which: str = ""
    date: str = ""


def now_text() -> str:
    """La fecha y hora actuales como se guardan en el CSV."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_rejected(path: Path | str) -> list[Rejection]:
    """Los descartados de ``path``; un archivo ausente da ``[]`` y si un ``file`` se repite gana el ultimo."""
    path = Path(path)
    if not path.exists():
        return []
    by_file: dict[str, Rejection] = {}
    for r in read_csv_rows(path):
        file = (r.get("file") or "").strip()
        if file:
            by_file[file] = Rejection(file, (r.get("set") or "").strip(), (r.get("date") or "").strip())
    return list(by_file.values())


def save_rejected(path: Path | str, rows: list[Rejection]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "set", "date"])
        for r in sorted(rows, key=lambda r: r.file):
            writer.writerow([r.file, r.which, r.date])
    return path


def rejected_files(rows: list[Rejection]) -> set[str]:
    return {r.file for r in rows}


def add_rejected(rows: list[Rejection], file: str, which: str, date: str) -> list[Rejection]:
    """``rows`` mas el descarte de ``file``; si ya estaba, queda tal cual (sin duplicar)."""
    if which not in SETS:
        raise ValueError("which debe ser 'train' o 'test'")
    if file in rejected_files(rows):
        return list(rows)
    return [*rows, Rejection(file, which, date)]


def remove_rejected(rows: list[Rejection], files) -> tuple[list[Rejection], set[str]]:
    """``(quedan, estaban)``: los descartados sin ``files`` y cuales de ellos estaban."""
    files = set(files)
    was = rejected_files(rows) & files
    return [r for r in rows if r.file not in was], was
