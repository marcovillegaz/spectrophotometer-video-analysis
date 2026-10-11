"""La biblioteca de plantillas (``calib/templates/``): un solo lugar para leerla y modificarla.

La biblioteca es **compartida** por todos los videos, asi que una plantilla mal
etiquetada contamina a todos. Por eso todo lo que la toca vive aca y nada la
modifica por otro camino: cargarla para leer, escribirla desde las muestras
(reemplazando o sumando), listarla con su uso, borrar y deshacer, y cambiar la
etiqueta de una plantilla.

Una plantilla es un PNG ``<caracter>_<n>.png`` (el punto es ``dot`` y el signo
``minus``). Dos glifos del mismo caracter cuentan como "el mismo" si su NCC llega a
``DEDUP_NCC``: es la medida con la que el lector compara, asi que "duplicado"
significa "no le aporta nada".

Interfaz publica:
    Template, TEMPLATES_DIR, template_path(label, n, dir), label_from_filename(path)
    load(directory)                          -> list[Template]
    warn_missing_sign(cfg, library)          -> str | None
    fingerprint(directory)                   -> str    (huella de la biblioteca)
    write(pool, directory, mode, max_per_label) -> dict[str, int]   (replace | merge)
    add(pool, directory, max_per_label)      -> AddResult           (merge con conteo)
    dedup(pool, max_per_label)               -> list[Glyph]
    list_entries(directory)                  -> list[LibEntry]
    usage(entries, datas)                    -> None
    delete(paths, backup=True) / restore(trashed) -> list[Trashed] / int
    relabel(path, new_label, directory, backup=True) -> Path
    clear(directory)                         -> int
    backup(directory) -> Path | None / list_backups(directory) -> list[str]
    restore_backup(directory, name=None)     -> str

``write(replace)``, ``delete``, ``relabel`` y ``clear`` respaldan antes la biblioteca en
``<calib>/.backups/<YYYYmmdd_HHMMSS>/`` y conservan los ultimos 5.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .config import DEFAULT_MAX_PER_LABEL, Config
from .imaging import ncc

if TYPE_CHECKING:  # pragma: no cover
    from .teach import Glyph, SampleData

#: Dos glifos del mismo caracter cuentan como "el mismo" si su NCC llega a esto: casi
#: identicos pixel a pixel. El hash perceptual de 8x8 (``cluster_hamming``) agrupa de mas:
#: en img_8102 dejaba afuera, por "duplicado", un 6 con NCC 0,75 contra la plantilla 6
#: que el lector confundia con un 5 (NCC 0,84). La NCC es, ademas, la medida con la que
#: el lector compara, asi que "duplicado" significa "no le aporta nada".
DEDUP_NCC = 0.95

#: Caracteres que tiene que poder reconocer el lector.
ALL_CHARS = list("0123456789.-")

#: Los respaldos viven junto a las plantillas: ``<calib>/.backups/<YYYYmmdd_HHMMSS>/``.
BACKUPS_DIR = ".backups"
KEEP_BACKUPS = 5
_BACKUP_RE = re.compile(r"^\d{8}_\d{6}(_\d+)?$")

#: La biblioteca de glifos es **compartida** entre corridas: el display es el
#: mismo aunque la camara se re-monte. Vive en calib/, no en runs/<id>/.
TEMPLATES_DIR = Path("calib/templates")

#: El punto decimal no puede ir literal en un nombre de archivo.
LABEL_TO_FILE = {".": "dot", "-": "minus"}
FILE_TO_LABEL = {v: k for k, v in LABEL_TO_FILE.items()}


@dataclass
class Template:
    """Una plantilla etiquetada de la biblioteca."""

    label: str
    image: np.ndarray
    path: Path | None
    #: Muestra de la que salio (``teach``), para la validacion leave-one-out.
    source: str = ""


def template_path(label: str, n: int, directory: Path | str = TEMPLATES_DIR) -> Path:
    stem = LABEL_TO_FILE.get(label, label)
    return Path(directory) / f"{stem}_{n}.png"


def label_from_filename(path: Path | str) -> str:
    stem = Path(path).stem.rsplit("_", 1)[0]
    return FILE_TO_LABEL.get(stem, stem)


@dataclass
class AddResult:
    new: dict[str, int]
    skipped: int


@dataclass
class LibEntry:
    label: str
    n: int
    path: Path
    image: np.ndarray
    #: Veces que fue la mejor coincidencia de una celda con **su** caracter.
    uses: int = 0
    #: Veces que gano una celda de **otro** caracter: una plantilla danina.
    errors: int = 0


@dataclass
class Trashed:
    path: Path
    data: bytes


def template_index(path: Path) -> int:
    """El ``n`` de ``<caracter>_<n>.png`` (0 si el nombre no lo trae)."""
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


# --------------------------------------------------------------------------
# Leer
# --------------------------------------------------------------------------
def load(directory: Path | str = TEMPLATES_DIR) -> list[Template]:
    """Carga la biblioteca etiquetada desde disco."""
    directory = Path(directory)
    paths = sorted(directory.glob("*.png"))
    if not paths:
        raise FileNotFoundError(
            f"No hay plantillas en {directory}. Corre primero: python -m spectro teach train"
        )
    out: list[Template] = []
    for p in paths:
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        out.append(Template(label=label_from_filename(p), image=img, path=p))
    return out


def warn_missing_sign(cfg: Config, library: list[Template]) -> str | None:
    """Aviso (o ``None``) si la config tiene celda de signo y falta la plantilla ``-``.

    Sin esa plantilla las lecturas negativas se descartan. Solo avisa: no cambia
    ninguna lectura. Quien llama decide donde imprimirlo.
    """
    if cfg.digits.sign_slot is None or any(t.label == "-" for t in library):
        return None
    return (
        "aviso: la config tiene celda de signo pero no hay plantilla '-'. Las lecturas\n"
        "       negativas se descartaran. Etiqueta muestras con valores negativos\n"
        "       (python -m spectro teach samples label <id>) y reconstrui la biblioteca:\n"
        "       python -m spectro teach train"
    )


def fingerprint(directory: Path | str = TEMPLATES_DIR) -> str:
    """Huella de la biblioteca: 12 hex del SHA-256 de los nombres y bytes de las plantillas.

    Cambia si se agrega, borra, renombra o modifica cualquier plantilla. Es ``""`` si no
    hay ninguna. ``read`` la guarda en ``out/read_meta.json`` para saber con que
    biblioteca se produjo cada ``readings.csv``.
    """
    import hashlib

    h = hashlib.sha256()
    files = sorted(Path(directory).glob("*.png")) if Path(directory).is_dir() else []
    for f in files:
        h.update(f.name.encode("utf-8") + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()[:12] if files else ""


def list_entries(directory: Path | str) -> list[LibEntry]:
    """Las plantillas en disco, ordenadas por caracter (0-9 . -) y numero."""
    out: list[LibEntry] = []
    d = Path(directory)
    if not d.is_dir():
        return out
    for p in d.glob("*.png"):
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        out.append(LibEntry(label_from_filename(p), template_index(p), p, img))

    def key(e: LibEntry):
        return (ALL_CHARS.index(e.label) if e.label in ALL_CHARS else len(ALL_CHARS), e.n)

    return sorted(out, key=key)


def usage(entries: list[LibEntry], datas: list[SampleData]) -> None:
    """Cuenta, sobre las muestras, que plantilla gana cada celda (``uses`` / ``errors``)."""
    for e in entries:
        e.uses = e.errors = 0
    if not entries:
        return
    for d in datas:
        for g in d.glyphs:
            best = max(entries, key=lambda e: ncc(g.image, e.image))
            if best.label == g.label:
                best.uses += 1
            else:
                best.errors += 1


# --------------------------------------------------------------------------
# Escribir
# --------------------------------------------------------------------------
def dedup(pool: list[Glyph], max_per_label: int = DEFAULT_MAX_PER_LABEL) -> list[Glyph]:
    """Deduplica por NCC dentro de cada etiqueta y conserva las variantes mas frecuentes."""
    out: list[Glyph] = []
    for label in sorted({g.label for g in pool}):
        clusters: list[list] = []  # [glyph, count]
        for g in (g for g in pool if g.label == label):
            for c in clusters:
                if ncc(g.image, c[0].image) >= DEDUP_NCC:
                    c[1] += 1
                    break
            else:
                clusters.append([g, 1])
        clusters.sort(key=lambda c: -c[1])
        out.extend(c[0] for c in clusters[:max_per_label])
    return out


def write(
    pool: list[Glyph], directory: Path | str, mode: str = "replace", max_per_label: int = DEFAULT_MAX_PER_LABEL,
) -> dict[str, int]:
    """Escribe la biblioteca en ``directory``: ``replace`` la reemplaza, ``merge`` le suma."""
    if mode not in ("replace", "merge"):
        raise ValueError(f"mode debe ser 'replace' o 'merge', no {mode!r}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if mode == "merge":
        return add(pool, directory, max_per_label).new
    backup(directory)
    for old in directory.glob("*.png"):
        old.unlink()
    counts: dict[str, int] = {}
    added: dict[str, int] = {}
    for g in dedup(pool, max_per_label):
        n = counts.get(g.label, 0)
        cv2.imwrite(str(template_path(g.label, n, directory)), g.image)
        counts[g.label] = n + 1
        added[g.label] = added.get(g.label, 0) + 1
    return added


def add(pool: list[Glyph], directory: Path | str, max_per_label: int = DEFAULT_MAX_PER_LABEL) -> AddResult:
    """Suma a la biblioteca existente **sin duplicar** y sin pisar archivos.

    Descarta los glifos que ya estan (mismo caracter y NCC >= ``DEDUP_NCC`` contra una
    plantilla existente) y respeta el tope por caracter contando las que ya hay. Es
    idempotente: repetirlo no agrega nada.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    have: dict[str, list] = {}        # etiqueta -> imagenes de las plantillas existentes
    next_n: dict[str, int] = {}
    for p in directory.glob("*.png"):
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        lab = label_from_filename(p)
        have.setdefault(lab, []).append(img)
        next_n[lab] = max(next_n.get(lab, 0), template_index(p) + 1)
    added: dict[str, int] = {}
    skipped = 0
    for g in dedup(pool, max_per_label):
        existing = have.setdefault(g.label, [])
        if len(existing) >= max_per_label or any(
            ncc(g.image, e) >= DEDUP_NCC for e in existing
        ):
            skipped += 1
            continue
        n = next_n.get(g.label, 0)
        cv2.imwrite(str(template_path(g.label, n, directory)), g.image)
        next_n[g.label] = n + 1
        existing.append(g.image)
        added[g.label] = added.get(g.label, 0) + 1
    return AddResult(added, skipped)


# --------------------------------------------------------------------------
# Borrar, deshacer, cambiar la etiqueta
# --------------------------------------------------------------------------
def delete(paths: list[Path], backup: bool = True) -> list[Trashed]:
    """Borra los archivos y devuelve lo necesario para deshacer.

    Antes respalda la biblioteca de la que salen (ver ``backup``), salvo con
    ``backup=False``: la UI toma un solo respaldo por sesion y lo reutiliza.
    """
    if paths and backup:
        _backup_dir(Path(paths[0]).parent)
    out: list[Trashed] = []
    for p in paths:
        p = Path(p)
        if p.exists():
            out.append(Trashed(p, p.read_bytes()))
            p.unlink()
    return out


def restore(trashed: list[Trashed]) -> int:
    """Deshace un ``delete``: reescribe los archivos que ya no estan. Devuelve cuantos."""
    n = 0
    for t in trashed:
        if not t.path.exists():
            t.path.write_bytes(t.data)
            n += 1
    return n


def relabel(path: Path | str, new_label: str, directory: Path | str, backup: bool = True) -> Path:
    """Cambia la etiqueta de una plantilla: la renombra al proximo indice libre.

    Respalda antes la biblioteca, salvo con ``backup=False`` (un respaldo por sesion de UI).
    """
    if new_label not in ALL_CHARS:
        raise ValueError(f"etiqueta invalida {new_label!r}; usa uno de {''.join(ALL_CHARS)}")
    directory = Path(directory)
    if backup:
        _backup_dir(directory)
    nxt = max(
        (template_index(p) + 1 for p in directory.glob("*.png") if label_from_filename(p) == new_label),
        default=0,
    )
    dest = template_path(new_label, nxt, directory)
    Path(path).rename(dest)
    return dest


def clear(directory: Path | str) -> int:
    """Vacia la biblioteca (respaldandola antes). Devuelve cuantas plantillas borro."""
    directory = Path(directory)
    backup(directory)
    n = 0
    for p in directory.glob("*.png"):
        p.unlink()
        n += 1
    return n


# --------------------------------------------------------------------------
# Respaldos
# --------------------------------------------------------------------------
def backups_root(directory: Path | str) -> Path:
    """Donde van los respaldos de ``<calib>/templates``: ``<calib>/.backups``."""
    return Path(directory).parent / BACKUPS_DIR


def backup(directory: Path | str, keep: int = KEEP_BACKUPS) -> Path | None:
    """Copia las plantillas a ``<calib>/.backups/<YYYYmmdd_HHMMSS>/`` y conserva las ultimas ``keep``.

    No hace nada (devuelve ``None``) si la biblioteca esta vacia. Solo poda los
    respaldos con nombre de fecha: los que se nombraron a mano no se tocan.
    """
    directory = Path(directory)
    files = sorted(directory.glob("*.png")) if directory.is_dir() else []
    if not files:
        return None
    root = backups_root(directory)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Dos respaldos en el mismo segundo: el sufijo es (maximo ya usado)+1, no el primero libre,
    # porque la poda puede haber borrado el nombre base y reusarlo ordenaria como el mas viejo.
    usados = [_backup_key(n)[1] for n in list_backups(directory) if _backup_key(n)[0] == stamp.replace("_", "")]
    dest = root / stamp if not usados else root / f"{stamp}_{max(usados) + 1}"
    dest.mkdir()
    for f in files:
        shutil.copy2(f, dest / f.name)
    if keep > 0:
        for old in list_backups(directory)[:-keep]:
            shutil.rmtree(root / old, ignore_errors=True)
    return dest


# Envoltorio de ``backup`` para ``delete`` y ``relabel``, cuyo parametro ``backup`` tapa la funcion.
def _backup_dir(directory: Path | str) -> Path | None:
    return backup(directory)


def _backup_key(name: str) -> tuple[str, int]:
    """Orden natural: la fecha y despues el sufijo numerico (``_10`` va despues de ``_2``)."""
    parts = name.split("_")
    k = int(parts[2]) if len(parts) > 2 else 1
    return (parts[0] + parts[1], k)


def list_backups(directory: Path | str) -> list[str]:
    """Nombres de los respaldos, del mas viejo al mas nuevo."""
    root = backups_root(directory)
    if not root.is_dir():
        return []
    names = [p.name for p in root.iterdir() if p.is_dir() and _BACKUP_RE.match(p.name)]
    return sorted(names, key=_backup_key)


def restore_backup(directory: Path | str, name: str | None = None) -> str:
    """Restaura el ultimo respaldo (o ``name``). Respalda antes el estado actual.

    Devuelve el nombre del respaldo restaurado.
    """
    directory = Path(directory)
    names = list_backups(directory)
    if name is None:
        if not names:
            raise FileNotFoundError(f"No hay respaldos en {backups_root(directory)}")
        name = names[-1]
    elif name not in names:
        raise FileNotFoundError(
            f"No existe el respaldo {name!r} en {backups_root(directory)}. "
            f"Disponibles: {', '.join(names) or 'ninguno'}"
        )
    src = backups_root(directory) / name
    backup(directory, keep=0)  # sin podar: podria llevarse el respaldo que se va a restaurar
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.png"):
        old.unlink()
    for f in src.glob("*.png"):
        shutil.copyfile(f, directory / f.name)  # mtime nuevo: las plantillas restauradas cuentan como cambio
    for old in list_backups(directory)[:-KEEP_BACKUPS]:
        if old != name:
            shutil.rmtree(backups_root(directory) / old, ignore_errors=True)
    return name
