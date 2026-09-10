"""El layout de datos como codigo: ``calib/`` compartida y ``runs/<id>/`` aislados.

Unico lugar que sabe donde va cada cosa. Sin estado escondido: todas las rutas de
una corrida se derivan de su id, y el id se deriva del nombre del video.

La camara se re-monta en cada sesion, asi que el encuadre cambia entre videos
pero el equipo y el display son los mismos. Eso parte los datos en dos mitades:

* **Compartido** (``calib/``): la biblioteca de glifos, la geometria del numero
  (celdas, punto decimal, polaridad) y los parametros de matcheo. Se calibra una
  vez y se versiona.
* **Por corrida** (``runs/<id>/``): el video, el fps, la ROI, el ancla, el
  fotograma de referencia, los umbrales de QC auto-sugeridos y el offset de
  tiempo. Todo lo que depende de como quedo montada la camara *esa* vez.

Interfaz publica:
    run_id_from_video(video, name=None)     -> str
    RunPaths.for_run(run_id, ...)           -> RunPaths
    CalibPaths.at(...)                      -> CalibPaths
    list_runs(...)                          -> list[str]
    seed_run_config(calib_cfg, video, fps)  -> Config
    calib_recipe(run_cfg)                   -> Config
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import ROI, Config, QCConfig

#: Nombres por defecto de las tres carpetas de primer nivel.
CALIB_DIR = Path("calib")
RUNS_DIR = Path("runs")
VIDEOS_DIR = Path("videos")

#: Los videos de iPhone vienen como ``20260901_164220000_iOS.MOV``: fecha, hora
#: y milisegundos. Nos quedamos con ``YYYYMMDD_HHMMSS``, que es legible, ordena
#: cronologicamente y no colisiona entre sesiones.
_IOS_VIDEO = re.compile(r"^(\d{8})_(\d{6})\d*_iOS$", re.IGNORECASE)

#: Umbrales que ``qc`` auto-sugiere desde la distribucion de cada corrida. No se
#: heredan de la calib porque dependen de la iluminacion de la sesion.
_PER_RUN_QC_FIELDS = (
    "min_mean_luma",
    "max_mean_luma",
    "min_blur_var",
    "min_contrast",
    "min_ink_fraction",
    "max_ink_fraction",
)


def sanitize_id(text: str) -> str:
    """Minusculas, no alfanumerico -> ``_``, sin repetidos ni bordes sueltos."""
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def run_id_from_video(video: Path | str, name: str | None = None) -> str:
    """Id de corrida a partir del video. ``name`` overridea la derivacion.

    Para los videos de iPhone se aplica la regla documentada
    ``^(\\d{8})_(\\d{6})\\d*_iOS$`` -> ``YYYYMMDD_HHMMSS``, asi
    ``20260901_164220000_iOS.MOV`` da ``20260901_164220``. Cualquier otro nombre
    cae en el saneado generico del stem.
    """
    if name is not None and str(name).strip():
        run_id = sanitize_id(name)
        if not run_id:
            raise ValueError(f"--name no deja ningun caracter usable: {name!r}")
        return run_id
    stem = Path(video).stem
    ios = _IOS_VIDEO.match(stem)
    if ios:
        return f"{ios.group(1)}_{ios.group(2)}"
    run_id = sanitize_id(stem)
    if not run_id:
        raise ValueError(f"No se puede derivar un id del video {video!r}; usa --name")
    return run_id


def _under(base: Path | str, directory: Path | str) -> Path:
    """``directory`` tal cual si es absoluta, si no colgando de ``base``."""
    d = Path(directory)
    return d if d.is_absolute() else Path(base) / d


@dataclass(frozen=True)
class CalibPaths:
    """La receta compartida: geometria, plantillas y fotograma de referencia."""

    root: Path
    config: Path
    reference: Path
    templates: Path

    @classmethod
    def at(
        cls, calib_dir: Path | str = CALIB_DIR, base: Path | str = Path(".")
    ) -> "CalibPaths":
        root = _under(base, calib_dir)
        return cls(
            root=root,
            config=root / "config.json",
            reference=root / "reference.jpg",
            templates=root / "templates",
        )

    def n_templates(self) -> int:
        return len(list(self.templates.glob("*.png"))) if self.templates.is_dir() else 0

    def is_ready(self) -> bool:
        """Hay receta y glifos: alcanza para sembrar corridas y leer."""
        return self.config.exists() and self.n_templates() > 0


@dataclass(frozen=True)
class RunPaths:
    """Las rutas de una corrida. Todo se deriva de ``id``; nada se guarda aparte."""

    id: str
    root: Path        # runs/<id>
    config: Path      # runs/<id>/config.json
    frames: Path      # runs/<id>/frames
    index: Path       # runs/<id>/frames_index.csv
    out: Path         # runs/<id>/out
    templates: Path   # calib/templates   (compartida)

    @classmethod
    def for_run(
        cls,
        run_id: str,
        base: Path | str = Path("."),
        runs_dir: Path | str = RUNS_DIR,
        calib_dir: Path | str = CALIB_DIR,
    ) -> "RunPaths":
        root = _under(base, runs_dir) / run_id
        return cls(
            id=run_id,
            root=root,
            config=root / "config.json",
            frames=root / "frames",
            index=root / "frames_index.csv",
            out=root / "out",
            templates=CalibPaths.at(calib_dir, base).templates,
        )

    # Salidas dentro de out/. Son derivadas, no campos: el layout manda.
    @property
    def qc_report(self) -> Path:
        return self.out / "qc_report.csv"

    @property
    def readings(self) -> Path:
        return self.out / "readings.csv"

    @property
    def absorbance(self) -> Path:
        return self.out / "absorbancia.csv"

    @property
    def preview(self) -> Path:
        return self.out / "calibracion.png"

    @property
    def glyph_sheet(self) -> Path:
        return self.out / "glifos.png"

    def exists(self) -> bool:
        return self.config.exists()

    def is_done(self) -> bool:
        """Ya produjo el entregable: ``batch --skip-existing`` la saltea."""
        return self.absorbance.exists()

    def create(self) -> "RunPaths":
        """Crea el arbol de la corrida. Idempotente."""
        for d in (self.root, self.frames, self.out):
            d.mkdir(parents=True, exist_ok=True)
        return self


def list_runs(base: Path | str = Path("."), runs_dir: Path | str = RUNS_DIR) -> list[str]:
    """Ids de las corridas dadas de alta, en orden alfabetico (= cronologico)."""
    root = _under(base, runs_dir)
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")
    )


def seed_run_config(calib_config: Config, video: Path | str, fps: float) -> Config:
    """Config inicial de una corrida: la receta compartida + su video y fps.

    Hereda geometria de digitos, plantillas y parametros de lectura. **No**
    hereda ROI, ancla ni fotograma de referencia: esos son del encuadre de esta
    sesion y los fija ``calibrate`` (a mano o con ``--auto``). Tampoco hereda los
    umbrales de calidad, que dependen de la iluminacion y se auto-sugieren en
    ``qc``.
    """
    cfg = Config.from_dict(calib_config.to_dict())  # copia profunda
    cfg.video = str(video)
    cfg.fps = float(fps)
    cfg.roi = ROI()
    cfg.qc.anchor = ROI()
    cfg.qc.reference_frame = ""
    limpios = QCConfig()
    for campo in _PER_RUN_QC_FIELDS:
        setattr(cfg.qc, campo, getattr(limpios, campo))
    return cfg


def calib_recipe(run_config: Config) -> Config:
    """La receta compartida extraida de un config de corrida.

    Es la inversa de ``seed_run_config``: conserva ROI y ancla **como
    referencia** (van junto a ``calib/reference.jpg``) y descarta lo que es
    propio de la corrida: video, fps, offset de tiempo y umbrales de QC.
    """
    cfg = Config.from_dict(run_config.to_dict())
    vacio = Config.default()
    cfg.video = ""
    cfg.fps = vacio.fps
    cfg.time = vacio.time
    limpios = QCConfig()
    for campo in _PER_RUN_QC_FIELDS:
        setattr(cfg.qc, campo, getattr(limpios, campo))
    return cfg
