"""Etapa 1 del pipeline: video -> fotogramas JPEG con nombre temporal.

Produce ``runs/<id>/frames/t_0000001.000.jpg`` (segundos desde el inicio del video,
7 digitos enteros y 3 decimales, de modo que el orden alfabetico sea el orden
temporal) mas un indice ``runs/<id>/frames_index.csv`` con ``archivo,t_s,indice``.

La eleccion del binario de ffmpeg no esta cableada: :func:`resolve_ffmpeg`
prefiere el del PATH del sistema y cae al de ``imageio-ffmpeg`` (dentro del
venv) si no lo encuentra. Ver ``docs/ARQUITECTURA.md``.

Interfaz publica:
    resolve_ffmpeg() -> FFmpegTools
    probe_video(path, tools) -> VideoInfo
    frame_time(index, fps, start) -> float
    frame_name(t_s) -> str
    time_from_name(name) -> float
    extract_frames(...) -> list[FrameRow]
    load_frames_index(path) -> list[FrameRow]
    load_roi_sidecar(frames_dir) -> ROI | None
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import ROI

#: Defaults de ultima instancia de las funciones de este modulo, relativos a
#: la raiz de una corrida (``runs/<id>/``). La CLI siempre pasa las rutas ya
#: resueltas desde ``RunPaths``; ver ``project.py``.
FRAMES_DIR = Path("frames")
FRAMES_INDEX = Path("frames_index.csv")
ROI_SIDECAR = ".roi.json"


# --------------------------------------------------------------------------
# Resolucion del binario
# --------------------------------------------------------------------------
@dataclass
class FFmpegTools:
    """Binarios resueltos y de donde salieron."""

    ffmpeg: str
    ffprobe: str | None
    source: str  # "system" | "imageio-ffmpeg"
    version: str = ""

    @property
    def has_ffprobe(self) -> bool:
        return self.ffprobe is not None


def _binary_version(exe: str) -> str:
    try:
        out = subprocess.run(
            [exe, "-version"], capture_output=True, text=True, timeout=30
        ).stdout
        return out.splitlines()[0].strip() if out else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve_ffmpeg() -> FFmpegTools:
    """Devuelve el ffmpeg a usar: primero el del sistema, si no el del venv.

    Orden de preferencia:
      1. ``ffmpeg``/``ffprobe`` en el PATH (trae ffprobe y aceleracion por hardware).
      2. ``imageio_ffmpeg.get_ffmpeg_exe()`` (sin ffprobe; metadatos por stderr).
    """
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        system_ffprobe = shutil.which("ffprobe")
        return FFmpegTools(
            ffmpeg=system_ffmpeg,
            ffprobe=system_ffprobe,
            source="system",
            version=_binary_version(system_ffmpeg),
        )
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - solo si faltan las dos vias
        raise RuntimeError(
            "No se encontro ffmpeg en el PATH ni el respaldo imageio-ffmpeg.\n"
            "Instala uno de los dos:\n"
            "  winget install Gyan.FFmpeg    (recomendado, trae ffprobe)\n"
            "  pip install imageio-ffmpeg    (respaldo dentro del venv)"
        ) from exc
    return FFmpegTools(
        ffmpeg=exe, ffprobe=None, source="imageio-ffmpeg", version=_binary_version(exe)
    )


def has_hwaccel(tools: FFmpegTools) -> list[str]:
    """Lista los aceleradores por hardware que soporta el build (puede ser vacia)."""
    try:
        out = subprocess.run(
            [tools.ffmpeg, "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]


# --------------------------------------------------------------------------
# Metadatos del video
# --------------------------------------------------------------------------
@dataclass
class VideoInfo:
    """Metadatos reales del video, leidos y no asumidos."""

    path: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration_s: float = 0.0
    n_frames: int = 0
    codec: str = ""
    rotation: float = 0.0
    source: str = ""  # "ffprobe" | "ffmpeg-stderr"

    def describe(self) -> str:
        rot = f", rotacion {self.rotation:g}deg" if self.rotation else ""
        return (
            f"{Path(self.path).name}: {self.width}x{self.height} {self.codec} "
            f"{self.fps:.3f} fps, {self.duration_s:.2f} s, {self.n_frames} fotogramas"
            f"{rot}  [metadatos via {self.source}]"
        )


def _parse_rate(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def probe_video(path: Path | str, tools: FFmpegTools | None = None) -> VideoInfo:
    """Lee los metadatos del video: ffprobe si esta, si no el stderr de ffmpeg."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el video: {path}")
    tools = tools or resolve_ffmpeg()
    if tools.has_ffprobe:
        return _probe_with_ffprobe(path, tools)
    return _probe_with_ffmpeg_stderr(path, tools)


def _probe_with_ffprobe(path: Path, tools: FFmpegTools) -> VideoInfo:
    cmd = [
        tools.ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    raw = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(raw)
    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    fps = _parse_rate(stream.get("avg_frame_rate")) or _parse_rate(
        stream.get("r_frame_rate")
    )
    duration = float(
        stream.get("duration") or data.get("format", {}).get("duration") or 0.0
    )
    n_frames = int(stream.get("nb_frames") or 0) or int(round(duration * fps))
    rotation = 0.0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = float(sd["rotation"])
    if not rotation:
        rotation = float((stream.get("tags") or {}).get("rotate") or 0.0)
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if abs(rotation) in (90.0, 270.0):
        # ffmpeg aplica la display matrix al decodificar: el fotograma sale rotado.
        width, height = height, width
    return VideoInfo(
        path=str(path),
        width=width,
        height=height,
        fps=fps,
        duration_s=duration,
        n_frames=n_frames,
        codec=stream.get("codec_name", ""),
        rotation=rotation,
        source="ffprobe",
    )


def _probe_with_ffmpeg_stderr(path: Path, tools: FFmpegTools) -> VideoInfo:
    """Respaldo sin ffprobe: parsea la linea Stream del stderr de ffmpeg."""
    out = subprocess.run(
        [tools.ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    ).stderr
    info = VideoInfo(path=str(path), source="ffmpeg-stderr")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if m:
        h, mi, s = m.groups()
        info.duration_s = int(h) * 3600 + int(mi) * 60 + float(s)
    m = re.search(r"Stream #\d+:\d+.*?Video:\s*(\w+).*?(\d{2,5})x(\d{2,5})", out, re.S)
    if m:
        info.codec = m.group(1)
        info.width, info.height = int(m.group(2)), int(m.group(3))
    m = re.search(r"(\d+\.?\d*)\s*fps", out)
    if m:
        info.fps = float(m.group(1))
    m = re.search(r"rotation of\s*(-?\d+\.?\d*)", out)
    if m:
        info.rotation = float(m.group(1))
    info.n_frames = int(round(info.duration_s * info.fps)) if info.fps else 0
    return info


# --------------------------------------------------------------------------
# Convencion de nombres  (contrato de datos entre etapas)
# --------------------------------------------------------------------------
NAME_RE = re.compile(r"^t_(\d{7}\.\d{3})\.jpg$")


def frame_time(index: int, fps: float, start: float = 0.0) -> float:
    """Tiempo real (s desde el inicio del video) del fotograma ``index`` (1-based)."""
    if index < 1:
        raise ValueError("El indice de fotograma es 1-based")
    if fps <= 0:
        raise ValueError("fps debe ser > 0")
    return start + (index - 1) / fps


def frame_name(t_s: float) -> str:
    """Nombre canonico del fotograma para el tiempo ``t_s``: ``t_0000001.000.jpg``."""
    return f"t_{t_s:011.3f}.jpg"


def time_from_name(name: str) -> float:
    """Inversa de :func:`frame_name`. Lanza ValueError si el nombre no encaja."""
    m = NAME_RE.match(Path(name).name)
    if not m:
        raise ValueError(f"Nombre de fotograma fuera de convencion: {name}")
    return float(m.group(1))


def format_hhmmss(t_s: float) -> str:
    """``hh:mm:ss.mmm`` — para volver al fotograma exacto en el reproductor."""
    h = int(t_s // 3600)
    m = int((t_s % 3600) // 60)
    s = t_s % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


# --------------------------------------------------------------------------
# Extraccion
# --------------------------------------------------------------------------
@dataclass
class FrameRow:
    """Una fila de ``frames_index.csv``."""

    archivo: str
    t_s: float
    indice: int

    def path(self, frames_dir: Path | str = FRAMES_DIR) -> Path:
        return Path(frames_dir) / self.archivo


def extract_frames(
    video: Path | str,
    fps: float = 1.0,
    output: Path | str = FRAMES_DIR,
    start: float = 0.0,
    duration: float | None = None,
    scale: float | None = None,
    jpeg_quality: int = 2,
    roi: ROI | None = None,
    index_path: Path | str | None = FRAMES_INDEX,
    tools: FFmpegTools | None = None,
    clean: bool = True,
    verbose: bool = True,
) -> list[FrameRow]:
    """Extrae fotogramas a ``fps`` Hz y los nombra por su tiempo real.

    Un solo pase de decodificacion con el filtro ``fps`` (no escribe los 36 000
    fotogramas del video) y ``-hwaccel auto``, que degrada solo a software si el
    build no soporta aceleracion.

    ``roi`` no vacia activa el modo ``--roi-only``: se guarda unicamente el
    recorte (~2 KB por fotograma en vez de ~400 KB) y se deja un sidecar
    ``.roi.json`` para que las etapas siguientes sepan que ya viene recortado.
    """
    video = Path(video)
    output = Path(output)
    tools = tools or resolve_ffmpeg()
    info = probe_video(video, tools)
    if verbose:
        print(f"  {info.describe()}")
        print(f"  ffmpeg: {tools.version or tools.ffmpeg}  [{tools.source}]")

    if clean and output.exists():
        for pattern in ("t_*.jpg", "f_*.jpg"):
            for old in output.glob(pattern):
                old.unlink()
    output.mkdir(parents=True, exist_ok=True)

    filters = [f"fps={fps}"]
    if roi is not None and roi.is_valid():
        filters.append(f"crop={roi.w}:{roi.h}:{roi.x}:{roi.y}")
    if scale:
        filters.append(f"scale=iw*{scale}:ih*{scale}")

    cmd = [tools.ffmpeg, "-hide_banner", "-loglevel", "error", "-hwaccel", "auto"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video)]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += [
        "-vf",
        ",".join(filters),
        "-q:v",
        str(jpeg_quality),
        "-y",
        str(output / "f_%06d.jpg"),
    ]
    if verbose:
        print("  $ " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg fallo ({proc.returncode}):\n{proc.stderr.strip()}")

    rows: list[FrameRow] = []
    for i, tmp in enumerate(sorted(output.glob("f_*.jpg")), start=1):
        t = frame_time(i, fps, start)
        final = output / frame_name(t)
        tmp.replace(final)
        rows.append(FrameRow(archivo=final.name, t_s=round(t, 3), indice=i))

    sidecar = output / ROI_SIDECAR
    if roi is not None and roi.is_valid():
        sidecar.write_text(json.dumps(vars(roi)), encoding="utf-8")
    elif sidecar.exists():
        sidecar.unlink()

    if index_path is not None:
        write_frames_index(rows, index_path)
    if verbose:
        print(f"  {len(rows)} fotogramas en {output}/")
    return rows


def write_frames_index(rows: list[FrameRow], path: Path | str = FRAMES_INDEX) -> Path:
    """Escribe el indice ``archivo,t_s,indice`` que consumen las etapas siguientes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["archivo", "t_s", "indice"])
        for r in rows:
            writer.writerow([r.archivo, f"{r.t_s:.3f}", r.indice])
    return path


def load_frames_index(path: Path | str = FRAMES_INDEX) -> list[FrameRow]:
    """Lee ``frames_index.csv``."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No existe {path}. Corre primero: python -m spectro extract"
        )
    with path.open(encoding="utf-8") as fh:
        return [
            FrameRow(archivo=r["archivo"], t_s=float(r["t_s"]), indice=int(r["indice"]))
            for r in csv.DictReader(fh)
        ]


def index_from_dir(frames_dir: Path | str = FRAMES_DIR) -> list[FrameRow]:
    """Reconstruye el indice mirando los nombres de archivo (que llevan el tiempo)."""
    frames_dir = Path(frames_dir)
    return [
        FrameRow(archivo=p.name, t_s=time_from_name(p.name), indice=i)
        for i, p in enumerate(sorted(frames_dir.glob("t_*.jpg")), start=1)
    ]


def load_roi_sidecar(frames_dir: Path | str = FRAMES_DIR) -> ROI | None:
    """ROI ya aplicada por ``--roi-only``, o None si los fotogramas son completos."""
    p = Path(frames_dir) / ROI_SIDECAR
    if not p.exists():
        return None
    return ROI(**json.loads(p.read_text(encoding="utf-8")))
