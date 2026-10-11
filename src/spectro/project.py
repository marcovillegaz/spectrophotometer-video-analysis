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
    require_run(run_id, ...)                -> RunPaths   (falla si la corrida no existe)
    seed_run_config(calib_cfg, video, fps)  -> Config
    calib_recipe(run_cfg)                   -> Config
    RunContext.load(run_paths, calib_paths) -> RunContext
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import ROI, AcceptanceConfig, Config, QCConfig

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
#: Centinela de "todavia no calculado" (distinto de "calculado y vacio").
_NOT_COMPUTED = object()

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
        return self.out / "absorbance.csv"

    @property
    def legacy_absorbance(self) -> Path:
        """Nombre viejo de la salida (``absorbancia.csv``): solo se lee como respaldo, nunca se escribe."""
        return self.out / "absorbancia.csv"

    @property
    def existing_absorbance(self) -> Path:
        """La salida que existe: ``absorbance.csv`` o, si falta, el ``absorbancia.csv`` viejo."""
        if not self.absorbance.exists() and self.legacy_absorbance.exists():
            return self.legacy_absorbance
        return self.absorbance

    @property
    def preview(self) -> Path:
        return self.out / "calibracion.png"

    @property
    def truth(self) -> Path:
        """Valores reales escritos a mano por ``teach`` (``file,value``)."""
        return self.root / "truth.csv"

    @property
    def teach_report(self) -> Path:
        return self.out / "teach_report.csv"

    @property
    def test(self) -> Path:
        """Conjunto de prueba (``file,value``): nunca entra a la biblioteca."""
        return self.root / "test.csv"

    @property
    def test_report(self) -> Path:
        return self.out / "test_report.csv"

    @property
    def history(self) -> Path:
        """Una fila por evaluacion: la curva de aprendizaje de las rondas."""
        return self.out / "teach_history.csv"

    def exists(self) -> bool:
        return self.config.exists()

    def is_done(self) -> bool:
        """Ya produjo el entregable: ``batch --skip-existing`` la saltea."""
        return self.existing_absorbance.exists()

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


def require_run(
    run_id: str, runs_dir: Path | str = RUNS_DIR, calib_dir: Path | str = CALIB_DIR
) -> RunPaths:
    """Las rutas de una corrida que **existe**; si no, el error lista las disponibles.

    Adivinar la corrida mezclaria datos de dos experimentos en silencio, asi que el id
    siempre es explicito y un id mal tipeado se rechaza con las opciones a la vista.
    """
    run = RunPaths.for_run(run_id, runs_dir=runs_dir, calib_dir=calib_dir)
    if not run.exists():
        runs = list_runs(runs_dir=runs_dir)
        available = ", ".join(runs) if runs else "ninguna"
        raise ValueError(f"No existe la corrida {run_id!r} en {runs_dir}/. Disponibles: {available}")
    return run


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
    cfg.acceptance = AcceptanceConfig()  # el criterio de aceptacion es de la calib, no de la corrida
    clean_qc = QCConfig()
    for field_name in _PER_RUN_QC_FIELDS:
        setattr(cfg.qc, field_name, getattr(clean_qc, field_name))
    return cfg


def calib_recipe(run_config: Config) -> Config:
    """La receta compartida extraida de un config de corrida.

    Es la inversa de ``seed_run_config``: conserva ROI y ancla **como
    referencia** (van junto a ``calib/reference.jpg``) y descarta lo que es
    propio de la corrida: video, fps, offset de tiempo y umbrales de QC.
    """
    cfg = Config.from_dict(run_config.to_dict())
    empty_cfg = Config.default()
    cfg.video = ""
    cfg.fps = empty_cfg.fps
    cfg.time = empty_cfg.time
    clean_qc = QCConfig()
    for field_name in _PER_RUN_QC_FIELDS:
        setattr(cfg.qc, field_name, getattr(clean_qc, field_name))
    return cfg


@dataclass
class RunContext:
    """Todo lo que ``teach`` necesita de una corrida, cargado por un solo camino.

    Junta la config de la corrida, la carpeta de fotogramas, el corrimiento de camara
    que midio ``qc`` y las muestras de entrenamiento y de prueba. Las rutas salen de
    ``RunPaths``; los argumentos con nombre permiten apuntar una a otra carpeta, como
    un flag explicito que le gana a lo derivado.
    """

    paths: RunPaths | None
    cfg: Config
    frames_dir: Path
    qc_report: Path
    #: ``{fotograma: (dx, dy)}`` de ``qc``; vacio si no hay reporte.
    offsets: dict[str, tuple[int, int]]
    train: list
    test: list
    templates_dir: Path
    #: Fotogramas que pasaron QC; ``_NOT_COMPUTED`` hasta que ``names()`` los resuelve.
    _names: object = field(default=_NOT_COMPUTED, repr=False)

    @property
    def run_id(self) -> str:
        return self.paths.id if self.paths is not None else ""

    @property
    def has_qc(self) -> bool:
        """Hay un reporte de QC con filas: sin el no se compensa la deriva de camara."""
        return bool(self.offsets)

    @classmethod
    def load(
        cls,
        run_paths: RunPaths | None,
        calib_paths: CalibPaths | None = None,
        *,
        config: Path | str | None = None,
        frames_dir: Path | str | None = None,
        qc_report: Path | str | None = None,
        truth: Path | str | None = None,
        test: Path | str | None = None,
        templates_dir: Path | str | None = None,
    ) -> "RunContext":
        from .qc import load_qc_report
        from .teach import load_truth

        qc_path = Path(qc_report) if qc_report is not None else run_paths.qc_report
        templates = templates_dir if templates_dir is not None else (
            calib_paths.templates if calib_paths is not None else run_paths.templates
        )
        # El reporte se parsea una sola vez: de ahi salen los corrimientos y los que pasaron QC.
        rows = load_qc_report(qc_path) if qc_path.exists() else []
        passed = [r.file for r in rows if r.passed_qc]
        return cls(
            paths=run_paths,
            cfg=Config.load(config if config is not None else run_paths.config),
            frames_dir=Path(frames_dir if frames_dir is not None else run_paths.frames),
            qc_report=qc_path,
            offsets={r.file: r.offset for r in rows},
            train=load_truth(truth if truth is not None else run_paths.truth),
            test=load_truth(test if test is not None else run_paths.test),
            templates_dir=Path(templates),
            _names=passed if passed else _NOT_COMPUTED,  # ninguno paso: names() cae a la carpeta
        )

    def names(self) -> list[str]:
        """Los fotogramas que pasaron QC; sin reporte (o sin ninguno aprobado), los de la carpeta."""
        from .extract import index_from_dir

        if self._names is _NOT_COMPUTED:
            self._names = [e.file for e in index_from_dir(self.frames_dir)]
        return self._names

    def items(self) -> list[tuple[str, float]]:
        """``(fotograma, segundo)`` de ``names()``, la entrada de las sugerencias."""
        from .extract import time_from_name

        return [(n, time_from_name(n)) for n in self.names()]
