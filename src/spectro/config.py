"""Configuracion persistente del pipeline (``config.json``).

Este modulo es el unico lugar donde vive el esquema de configuracion. Todas las
etapas leen de aca, de modo que calibrar una vez alcanza para todas las
corridas posteriores. La referencia campo por campo esta en ``docs/CONFIG.md``.

Interfaz publica:
    Config.load(path)   -> Config
    Config.save(path)   -> None
    Config.default()    -> Config
    AcceptanceConfig    (umbrales opcionales del veredicto de batch)
    DEFAULT_CONFIG_PATH
    DEFAULT_MAX_PER_LABEL
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from .compat import normalize_config

DEFAULT_CONFIG_PATH = Path("config.json")

#: Tope de variantes por caracter en la biblioteca (lo usan el CLI de ``teach`` y la UI). Vive
#: aca, y no en ``teach.py``, para que el parser del CLI no importe cv2; ``teach`` lo reexporta.
DEFAULT_MAX_PER_LABEL = 3


@dataclass
class ROI:
    """Rectangulo de la region de interes, en pixeles del fotograma extraido."""

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def is_valid(self) -> bool:
        return self.w > 0 and self.h > 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def crop(self, image):
        """Recorta ``image`` (array HxW[xC] de numpy) a esta ROI."""
        return image[self.y : self.y + self.h, self.x : self.x + self.w]


@dataclass
class DigitsConfig:
    """Como se reparte la ROI en slots y donde va el punto decimal.

    ``n_digits`` cuenta **celdas de caracter**, no digitos: en la fuente
    monoespaciada del equipo el punto decimal ocupa su propia celda, asi que
    ``0.597`` son 5 slots. Los indices listados en ``separator_slots`` se leen
    igual (sirven de control) pero no aportan digitos al numero: el valor se
    arma con el punto decimal fijo de ``decimal_after``.
    """

    n_digits: int = 5
    #: Cortes verticales dentro de la ROI, en pixeles relativos a su borde
    #: izquierdo. Longitud n_digits+1. Vacio => reparto uniforme.
    splits: list[int] = field(default_factory=list)
    #: Indices de slot que son separadores (el punto decimal), no digitos.
    separator_slots: list[int] = field(default_factory=lambda: [1])
    #: Cantidad de digitos antes del punto decimal (0.597 -> 1).
    decimal_after: int = 1
    #: "light_on_dark" (display luminoso) o "dark_on_light" (LCD clasico).
    polarity: str = "light_on_dark"
    #: Indice de la celda del signo (normalmente 0), o None si el display no
    #: muestra signo. Esa celda queda vacia cuando el valor es positivo.
    sign_slot: int | None = None
    #: Fraccion de tinta por debajo de la cual la celda del signo se toma vacia.
    sign_max_ink: float = 0.03

    def resolved_splits(self, roi_width: int) -> list[int]:
        """Devuelve los cortes efectivos, generando el reparto uniforme si hace falta."""
        if self.splits and len(self.splits) == self.n_digits + 1:
            return list(self.splits)
        step = roi_width / self.n_digits
        return [round(i * step) for i in range(self.n_digits + 1)]

    def digit_slots(self) -> list[int]:
        """Indices de los slots que si aportan un digito al numero."""
        seps = set(self.separator_slots or [])
        if self.sign_slot is not None:
            seps.add(self.sign_slot)
        return [i for i in range(self.n_digits) if i not in seps]

    def expected_chars(self, slot: int) -> str:
        """Caracteres que puede mostrar el slot: ``-`` o vacio (signo), ``.`` (separador) o digitos."""
        if slot == self.sign_slot:
            return "- "
        if slot in (self.separator_slots or []):
            return "."
        return "0123456789"

    def required_chars(self) -> frozenset[str]:
        """Caracteres que la biblioteca tiene que poder leer con esta geometria.

        Sale de ``expected_chars`` de cada slot (sin el vacio). El punto se pide siempre,
        haya o no separadores configurados: es el criterio que ya aplicaba ``teach``.
        """
        chars = {c for i in range(self.n_digits) for c in self.expected_chars(i)}
        return frozenset(chars - {" "}) | {"."}


@dataclass
class TemplateConfig:
    """Parametros de la biblioteca de plantillas y del matcheo NCC."""

    #: Tamano (ancho, alto) al que se normaliza cada glifo antes de comparar.
    size: tuple[int, int] = (24, 40)
    #: NCC minima del mejor match para aceptar un digito.
    min_score: float = 0.60
    #: Margen minimo entre el mejor y el segundo mejor digito distinto.
    min_margin: float = 0.05


@dataclass
class QCConfig:
    """Umbrales del filtro de calidad. Se auto-sugieren desde la distribucion."""

    min_mean_luma: float = 15.0
    max_mean_luma: float = 245.0
    min_blur_var: float = 20.0
    min_contrast: float = 30.0
    min_ink_fraction: float = 0.01
    max_ink_fraction: float = 0.85
    #: Ancla estatica: una zona con estructura que no cambia con la medicion
    #: (texto fijo del display, serigrafia del equipo). Se usa para dos cosas:
    #: detectar que la camara se movio, y **re-registrar** la ROI fotograma a
    #: fotograma. Si w/h son 0, ambos chequeos se omiten.
    anchor: ROI = field(default_factory=ROI)
    #: NCC minima del ancla *ya alineada*. Por debajo, el fotograma no es
    #: comparable con la referencia (mano delante, desenfoque severo).
    min_anchor_ncc: float = 0.70
    #: Fotograma contra el que se registran todos los demas. Es el mismo sobre
    #: el que se calibro la ROI, asi que sus coordenadas son las de referencia.
    reference_frame: str = ""
    #: Corrimiento maximo tolerado, en pixeles. Tambien es el margen de busqueda:
    #: mas alla de esto se considera que la camara se movio de verdad.
    max_shift_px: int = 40
    #: Re-registrar la ROI compensando la deriva lenta de la camara.
    register: bool = True


@dataclass
class TimeConfig:
    """Alineacion de la escala temporal con el log manual del laboratorio."""

    #: Segundos a sumar a t_s para obtener t_exp. Admite negativos.
    offset_s: float = 0.0
    #: Opcional, ej. "2026-09-01 16:42:20". Si esta, se agrega hora de reloj ISO.
    absolute_start: str | None = None


@dataclass
class ReadConfig:
    """Chequeos posteriores a la lectura de digitos."""

    #: Maxima |delta absorbancia| / delta t admitida contra los vecinos.
    #: Por encima de esto la fila se marca "spike" y se descarta.
    max_rate: float = 0.5


@dataclass
class AcceptanceConfig:
    """Umbrales del veredicto ``accept`` / ``review`` del reporte de ``batch``.

    Son fracciones en [0, 1]. **No tienen valores por defecto**: ``None`` significa "sin
    umbral", y si ninguno esta fijado el veredicto queda vacio. Los fija el usuario con
    lo que midio (``calib/config.json``) o con los flags de ``batch``.
    """

    #: Exactitud minima sobre ``test.csv`` (correctas / muestras de prueba).
    min_accuracy: float | None = None
    #: Error maximo entre las lecturas aceptadas de ``test.csv`` (erroneas / aceptadas).
    max_error: float | None = None
    #: Cobertura minima de la corrida (lecturas ``ok`` / fotogramas extraidos).
    min_coverage: float | None = None

    def is_set(self) -> bool:
        return any(v is not None for v in (self.min_accuracy, self.max_error, self.min_coverage))


@dataclass
class Config:
    """Configuracion completa del proyecto, serializada como ``config.json``."""

    video: str = ""
    fps: float = 1.0
    #: Rotacion aplicada a cada fotograma al cargarlo (grados, antihorario) para
    #: dejar el numero horizontal. ROI y ancla estan en coordenadas ya rotadas.
    rotation_deg: float = 0.0
    roi: ROI = field(default_factory=ROI)
    digits: DigitsConfig = field(default_factory=DigitsConfig)
    templates: TemplateConfig = field(default_factory=TemplateConfig)
    qc: QCConfig = field(default_factory=QCConfig)
    time: TimeConfig = field(default_factory=TimeConfig)
    read: ReadConfig = field(default_factory=ReadConfig)
    #: Criterio de aceptacion del reporte de ``batch``; solo se lee de ``calib/config.json``.
    acceptance: AcceptanceConfig = field(default_factory=AcceptanceConfig)

    # -- serializacion ----------------------------------------------------
    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        return _build(cls, normalize_config(data))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG_PATH) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"No existe {path}. Corre primero: python -m spectro calibrate"
            )
        with path.open(encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def load_or_default(cls, path: Path | str = DEFAULT_CONFIG_PATH) -> "Config":
        try:
            return cls.load(path)
        except FileNotFoundError:
            return cls.default()

    def save(self, path: Path | str = DEFAULT_CONFIG_PATH) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return path


def _build(cls, data: Any):
    """Reconstruye recursivamente una dataclass anidada desde dicts de JSON."""
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if is_dataclass(f.type) or (isinstance(f.type, type) and is_dataclass(f.type)):
            kwargs[f.name] = _build(f.type, value)
        else:
            kwargs[f.name] = value
    # Las anotaciones son strings bajo `from __future__ import annotations`,
    # asi que resolvemos los sub-objetos conocidos a mano.
    nested = {
        "roi": ROI,
        "digits": DigitsConfig,
        "templates": TemplateConfig,
        "qc": QCConfig,
        "time": TimeConfig,
        "read": ReadConfig,
        "acceptance": AcceptanceConfig,
        "anchor": ROI,
    }
    for name, sub in nested.items():
        if name in kwargs and isinstance(kwargs[name], dict):
            kwargs[name] = _build(sub, kwargs[name])
    if cls is TemplateConfig and isinstance(kwargs.get("size"), list):
        kwargs["size"] = tuple(kwargs["size"])
    return cls(**kwargs)
