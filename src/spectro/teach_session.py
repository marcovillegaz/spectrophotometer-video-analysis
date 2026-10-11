"""Sesion de ``teach``: el estado, el reducer y los efectos de la UI, sin ventana.

``teach_ui`` dibuja y lee eventos; todo lo que decide vive aca para poder testearlo
sin pantalla ni OpenCV: el estado (``TeachState``), el reducer unico de acciones
(``apply_action``), las muestras de entrenamiento y prueba, la biblioteca, los pedidos
que tocan archivos (agregar/reemplazar/validar/evaluar, borrar/restaurar/reetiquetar)
y la traduccion de teclas a acciones.

Flujo de una accion: ``TeachSession.act(accion)`` aplica ``apply_action``; si el
reducer deja un ``request`` de datos (``add``, ``remove``) la sesion lo ejecuta en el
acto; los demas pedidos (``validate``, ``add_lib``, ``replace``, ``eval``, ``del_one``,
...) los toma el loop con ``begin_request`` / ``run_request`` para poder dibujar
``trabajando...`` antes de los lentos (``SLOW_REQUESTS``).

Interfaz publica:
    TeachState, apply_action(state, action, n_names, n_lib, value_of, rng) -> TeachState
    go_to(state, samples, names, index) -> TeachState
    add_sample(train, test, file, text, digits, which) -> AddResult
    AddResult(train, test, message, added)            remove_sample(samples, file) -> samples
    TeachParams(frames_dir, templates_dir, ..., seed)  TeachParams.from_context(ctx, max_per_label, gap, seed)
    TeachSession(cfg, params, names, offsets, samples, test, reasons, target)
        .act(action)  .on_key(k)  .begin_request() -> str  .is_slow(kind) -> bool  .run_request(kind)
        .frame(index)  .persist()  .refresh_library() -> list[str]
        .state .samples .test .library .result .entries .trash .backup_path
    key_to_action(k, lib_mode) -> str | None
    COLS, ROWS, PER_PAGE (grilla de la biblioteca)    SLOW_REQUESTS, CONFIRM_ACTIONS
    KEY_BACKSPACE, KEY_LEFT, KEY_RIGHT (teclas; KEY_ESC y KEY_ENTER vienen de ui_common)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

from . import library as lib_mod
from . import teach as T
from .config import Config, DigitsConfig
from .extract import load_roi_sidecar
from .imaging import load_frame
from .read import read_frame
from .ui_common import KEY_ENTER, KEY_ESC

# grilla de la biblioteca (el layout la dibuja; el reducer pagina con ella)
COLS, ROWS = 9, 6
PER_PAGE = COLS * ROWS

#: Acciones destructivas: el primer clic arma la confirmacion y el segundo ejecuta.
CONFIRM_ACTIONS = ("replace", "del_one", "del_label")

#: Pedidos lentos: el loop dibuja ``trabajando...`` antes de ejecutarlos.
SLOW_REQUESTS = ("eval", "validate", "add_lib", "replace")

KEY_BACKSPACE = 8
KEY_LEFT, KEY_RIGHT = 2424832, 2555904

# tecla -> (accion en muestras, accion en biblioteca); ``None`` = sin efecto en ese modo
_ARROW_KEYS = {KEY_LEFT: ("prev", "page-"), KEY_RIGHT: ("next", "page+")}
_BYTE_KEYS = {KEY_ESC: ("save", "samples"), KEY_ENTER: ("add", None), KEY_BACKSPACE: ("back", None)}


# --------------------------------------------------------------------------
# Estado y reducer (puros)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TeachState:
    index: int = 0
    text: str = ""
    color: bool = False
    done: bool = False
    #: Pedido para el loop (build/validate/borrar/...): lo que toca archivos.
    request: str = ""
    message: str = ""
    mode: str = "samples"      # "samples" | "library"
    sel: int = 0                # plantilla elegida (indice global en la biblioteca)
    page: int = 0
    confirm: str = ""           # accion destructiva esperando el segundo clic
    target: str = "train"       # conjunto al que va "Agregar muestra": train | test


def go_to(state: TeachState, samples: list[T.Sample], names: list[str], index: int) -> TeachState:
    """Cambia de fotograma y precarga el valor si ya tiene muestra."""
    index = max(0, min(index, len(names) - 1)) if names else 0
    existing = next((s.value for s in samples if names and s.file == names[index]), "")
    return replace(state, index=index, text=existing, message="")


_NAV = {"prev": -1, "next": 1, "jump-10": -10, "jump+10": 10}


def apply_action(
    state: TeachState, action: str, n_names: int, n_lib: int = 0, value_of=None, rng=None,
) -> TeachState:
    """Reducer unico de las acciones. Las que tocan archivos o muestras dejan un ``request``.

    ``value_of(index) -> str`` (opcional) precarga el valor ya etiquetado al cambiar de
    fotograma; sin el, la navegacion solo mueve el indice. ``rng(n)`` reemplaza a
    ``random.randrange`` para ``random``.
    """
    # Cualquier accion distinta de la destructiva pendiente cancela la confirmacion.
    if action not in CONFIRM_ACTIONS and state.confirm:
        state = replace(state, confirm="")
    if action in CONFIRM_ACTIONS:
        if action != "replace" and not n_lib:
            return state
        if state.confirm == action:
            return replace(state, confirm="", request=action)
        return replace(state, confirm=action, message="")

    if action.startswith("key:"):
        ch = action[4:]
        if len(state.text) < 12 and ch in "0123456789.-":
            return replace(state, text=state.text + ch, message="")
        return state
    if action == "back":
        return replace(state, text=state.text[:-1], message="")
    if action == "clear":
        return replace(state, text="", message="")
    if state.mode == "samples" and n_names and (action in _NAV or action == "random"):
        if action == "random":
            idx = (rng or random.randrange)(n_names)
        else:
            idx = state.index + _NAV[action]
        state = replace(state, index=max(0, min(idx, n_names - 1)), message="")
        return replace(state, text=value_of(state.index)) if value_of else state
    if action in _NAV and n_names:
        return replace(state, index=max(0, min(state.index + _NAV[action], n_names - 1)), message="")
    if action == "color":
        return replace(state, color=not state.color)
    if action in ("validate", "add_lib", "undo", "eval"):
        return replace(state, request=action)
    if state.mode == "samples" and action in ("add", "remove"):
        return replace(state, request=action)
    if action == "target":
        return replace(state, target="test" if state.target == "train" else "train", message="")
    if action == "save":
        return replace(state, done=True)
    # -- modo biblioteca
    if action == "lib":
        return replace(state, mode="library", sel=0, page=0, request="refresh_lib", message="")
    if action == "samples":
        return replace(state, mode="samples", message="")
    if action in ("page+", "page-"):
        last = max((n_lib - 1) // PER_PAGE, 0)
        page = min(state.page + 1, last) if action == "page+" else max(state.page - 1, 0)
        return replace(state, page=page)
    if action.startswith("tile:"):
        idx = state.page * PER_PAGE + int(action[5:])
        return replace(state, sel=idx) if idx < n_lib else state
    if action.startswith("relabel:") and n_lib:
        return replace(state, request=action)
    return state


def remove_sample(samples: list[T.Sample], file: str) -> list[T.Sample]:
    return [s for s in samples if s.file != file]


@dataclass(frozen=True)
class AddResult:
    train: list[T.Sample]
    test: list[T.Sample]
    message: str
    #: ``False`` si el valor no calza con la config y no cambio nada.
    added: bool


def add_sample(
    train: list[T.Sample], test: list[T.Sample], file: str, text: str, digits: DigitsConfig,
    which: str,
) -> AddResult:
    """Agrega la muestra a ``which`` (``train`` o ``test``) sin que quede en los dos conjuntos.

    Si el valor no calza con la config no cambia nada. Mover una muestra de
    entrenamiento a prueba avisa que ya aporto glifos a la biblioteca.
    """
    from .sampling import assign

    try:
        value = T.parse_value(text, digits)
    except ValueError as exc:
        return AddResult(train, test, str(exc), False)
    was_in_train = any(s.file == file for s in train)
    train, test = assign(train, test, T.Sample(file, value), which)
    if which == "test" and was_in_train:
        msg = "agregada a prueba (ya habia aportado glifos: reemplaza la biblioteca)"
    else:
        msg = "muestra agregada" if which == "train" else "muestra de prueba agregada"
    return AddResult(train, test, msg, True)


def key_to_action(k: int, lib_mode: bool) -> str | None:
    """La accion de una tecla (codigo de ``waitKeyEx``), o ``None`` si no hace nada."""
    if k in _ARROW_KEYS:
        return _ARROW_KEYS[k][lib_mode]
    kk = k & 0xFF
    if kk in _BYTE_KEYS and (kk == KEY_ESC or not lib_mode):
        return _BYTE_KEYS[kk][lib_mode]
    if not lib_mode and 0 < kk < 128 and chr(kk) in "0123456789.-":
        return f"key:{chr(kk)}"
    return None


# --------------------------------------------------------------------------
# Sesion
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TeachParams:
    """Rutas y parametros de la sesion (antes un ``Namespace`` armado a mano)."""

    frames_dir: str
    templates_dir: str
    max_per_label: int
    gap: float
    truth: str
    test: str
    teach_report: str
    test_report: str
    history: str
    #: Semilla del boton ``Aleatorio``; ``None`` = no determinista.
    seed: int | None = None

    @classmethod
    def from_context(cls, ctx, max_per_label: int, gap: float, seed: int | None = None) -> TeachParams:
        """Los parametros de una corrida cargada (``project.RunContext``)."""
        run = ctx.paths
        return cls(
            frames_dir=str(ctx.frames_dir), templates_dir=str(ctx.templates_dir),
            max_per_label=max_per_label, gap=gap, truth=str(run.truth), test=str(run.test),
            teach_report=str(run.teach_report), test_report=str(run.test_report),
            history=str(run.history), seed=seed,
        )


class TeachSession:
    """Todo lo que `teach` hace en la ventana salvo dibujar y leer eventos."""

    def __init__(
        self,
        cfg: Config,
        params: TeachParams,
        names: list[str],
        offsets: dict,
        samples: list[T.Sample],
        test: list[T.Sample] | None = None,
        reasons: dict[str, str] | None = None,
        target: str = "train",
    ) -> None:
        self.cfg, self.params, self.names, self.offsets = cfg, params, names, offsets
        self.reasons = reasons or {}
        self.frames_dir = Path(params.frames_dir)
        self.frames_roi = load_roi_sidecar(self.frames_dir)
        self.samples, self.test = list(samples), list(test or [])
        self.library = self._load_library()
        self.result: list[str] = []
        self.entries: list[lib_mod.LibEntry] = []
        self.trash: list = []
        self._frame = None
        #: ``rng(n)`` del boton ``Aleatorio``: reproducible con ``seed``, si no ``random.randrange``.
        self._rng = random.Random(params.seed).randrange if params.seed is not None else None
        #: Respaldo unico de la sesion (nombre de carpeta); se toma antes del primer borrado/cambio.
        self.backup_path: Path | None = None
        self._backed_up = False
        #: Cache de ``build_pool`` por muestras: no depende de la biblioteca, solo de las muestras.
        self._pool_cache: tuple | None = None
        mid = len(names) // 2
        self.state = go_to(TeachState(index=mid, target=target), self.samples + self.test, names, mid)
        self._slow = {
            "eval": self._run_eval,
            **{k: partial(self._run_build, k) for k in ("validate", "add_lib", "replace")},
        }
        self._data = {"add": self._add, "remove": self._remove}
        self._lib_ops = {
            "del_one": (self._del_one, True), "del_label": (self._del_label, True),
            "undo": (self._undo, False), "relabel": (self._relabel, True),
        }

    # -- lectura
    def _load_library(self):
        try:
            return lib_mod.load(self.params.templates_dir)
        except FileNotFoundError:
            return []

    def frame(self, index: int):
        """``(gray, color, offset, lectura)`` del fotograma ``index`` (con cache de uno)."""
        if self._frame is None or self._frame[0] != index:
            path = self.frames_dir / self.names[index]
            gray = load_frame(path, self.cfg)
            color = load_frame(path, self.cfg, color=True)
            off = self.offsets.get(self.names[index], (0, 0))
            reading = read_frame(gray, self.cfg, self.library, self.frames_roi, off) if self.library else None
            self._frame = (index, gray, color, off, reading)
        return self._frame[1:]

    def persist(self) -> None:
        T.save_truth(self.params.truth, self.samples)
        if self.test or Path(self.params.test).exists():
            T.save_truth(self.params.test, self.test)

    def refresh_library(self) -> list[str]:
        """Recarga la biblioteca y mide su efecto sobre las muestras (usos, errores, exactitud)."""
        self.library, self._frame = self._load_library(), None
        self.entries = lib_mod.list_entries(self.params.templates_dir)
        lines: list[str] = []
        _, datas, _ = self._pool()
        lib_mod.usage(self.entries, datas)
        if datas and self.library:
            current_report = T.evaluate_library(datas, self.library, self.cfg)
            lines = T.format_report(current_report, "biblioteca vigente")[:3]
        return lines

    def _pool(self):
        """``build_pool`` de las muestras de entrenamiento, recalculado solo si cambiaron."""
        if self._cold_pool():
            key = tuple((s.file, s.value) for s in self.samples)
            self._pool_cache = (key, T.build_pool(self.samples, self.cfg, self.frames_dir, self.offsets))
        return self._pool_cache[1]

    def _ensure_backup(self) -> None:
        """Toma UN respaldo por sesion, antes del primer cambio a la biblioteca.

        Cubre cualquier cambio (agregar, reemplazar, borrar, reetiquetar): el respaldo es
        el estado previo a la sesion. Las operaciones (``delete``, ``relabel``) van despues
        con ``backup=False``: borrar muchas plantillas seguidas no rota los respaldos.
        Abrir la ventana solo para etiquetar muestras no respalda nada. La sesion solo
        da el respaldo por tomado si ``backup`` devolvio una ruta o si no habia nada que
        respaldar (biblioteca vacia); si falla, se reintenta en el cambio siguiente.
        """
        if self._backed_up:
            return
        self.backup_path = lib_mod.backup(self.params.templates_dir)
        if self.backup_path is not None or not self._has_templates():
            self._backed_up = True

    def _has_templates(self) -> bool:
        directory = Path(self.params.templates_dir)
        return directory.is_dir() and any(directory.glob("*.png"))

    def _cold_pool(self) -> bool:
        """``True`` si el proximo ``_pool()`` tiene que reconstruirse (lento)."""
        key = tuple((s.file, s.value) for s in self.samples)
        return self._pool_cache is None or self._pool_cache[0] != key

    def is_slow(self, kind: str) -> bool:
        """Si el loop debe dibujar ``trabajando...`` antes de ejecutar ``kind``.

        Los pedidos de ``SLOW_REQUESTS`` siempre; los de biblioteca (``refresh_lib``,
        borrar, reetiquetar, deshacer) solo si hay que reconstruir el pool de muestras.
        """
        return kind in SLOW_REQUESTS or (bool(kind) and self._cold_pool())

    # -- acciones
    def _value_of(self, index: int) -> str:
        return next((s.value for s in self.samples + self.test if s.file == self.names[index]), "")

    def act(self, action: str) -> None:
        """Aplica una accion con el reducer; ejecuta en el acto las de datos (``add``, ``remove``)."""
        st = self.state
        self.state = new = apply_action(
            st, action, len(self.names), len(self.entries), self._value_of, self._rng)
        kind = new.request
        if kind in self._data:
            self.state = replace(new, request="")
            self._data[kind](self.state)

    def on_key(self, k: int) -> None:
        action = key_to_action(k, self.state.mode == "library")
        if action:
            self.act(action)

    def _add(self, st: TeachState) -> None:
        res = add_sample(self.samples, self.test, self.names[st.index], st.text, self.cfg.digits, st.target)
        self.samples, self.test = res.train, res.test
        self.state = replace(st, message=res.message)
        self.persist()
        if res.added:
            self.state = go_to(self.state, self.samples + self.test, self.names, st.index + 1)
            self.state = replace(self.state, message=res.message)

    def _remove(self, st: TeachState) -> None:
        name = self.names[st.index]
        self.samples = remove_sample(self.samples, name)
        self.test = remove_sample(self.test, name)
        self.state = replace(st, text="", message="muestra quitada")
        self.persist()

    # -- pedidos que tocan archivos
    def begin_request(self) -> str:
        """Toma el pedido pendiente (``""`` si no hay) y deja ``trabajando...``."""
        st = self.state
        if not st.request:
            return ""
        self.state = replace(st, request="", message="trabajando...")
        return st.request

    def run_request(self, kind: str) -> None:
        """Ejecuta el pedido que devolvio ``begin_request`` y deja el estado listo para dibujar."""
        st = self.state
        if kind in self._slow:
            self._slow[kind]()
            self.state = replace(st, message="")
        else:
            self.state = self._library_request(kind, replace(st, message=""))

    def _run_build(self, kind: str) -> None:
        p = self.params
        pool, datas, errors = self._pool()
        lines = [f"muestra descartada: {e}" for e in errors]
        if not datas:
            self.result = lines + ["No hay muestras validas."]
            return
        if kind in ("add_lib", "replace"):
            self._ensure_backup()
        if kind == "add_lib":
            res = lib_mod.add(pool, p.templates_dir, p.max_per_label)
            lines.append(f"+{sum(res.new.values())} plantillas nuevas, {res.skipped} ya estaban")
        elif kind == "replace":
            added = lib_mod.write(pool, p.templates_dir, "replace", p.max_per_label)
            lines.append(f"biblioteca reemplazada: {sum(added.values())} plantillas")
            self.trash = []
        loo = T.validate(datas, pool, self.cfg)
        T.write_report(loo, p.teach_report)
        self.result = lines + T.format_report(loo, "leave-one-out")[:3]
        if kind != "validate":
            self.result += self.refresh_library()[:1]

    def _run_eval(self) -> None:
        from .evaluation import append_history, evaluate_test, summary_lines, write_test_report

        p = self.params
        if not self.test:
            self.result = ["No hay muestras de prueba.", "Pone 'Conjunto: Prueba' y agrega algunas."]
            return
        lib = self._load_library()
        if not lib:
            self.result = ["No hay biblioteca vigente: agrega muestras a la biblioteca primero."]
            return
        rep = evaluate_test(self.test, self.cfg, self.frames_dir, self.offsets, lib, self.samples, p.gap)
        write_test_report(rep, p.test_report)
        append_history(p.history, rep, fingerprint=lib_mod.fingerprint(p.templates_dir))
        self.result = summary_lines(rep)

    # -- operaciones de la biblioteca: devuelven (mensaje, ruta destino o None)
    def _del_one(self, sel, kind):
        self._ensure_backup()
        self.trash.append(lib_mod.delete([sel.path], backup=False))
        return f"borrada {sel.path.name}", None

    def _del_label(self, sel, kind):
        paths = [e.path for e in self.entries if e.label == sel.label]
        self._ensure_backup()
        self.trash.append(lib_mod.delete(paths, backup=False))
        return f"borradas {len(paths)} plantillas de '{sel.label}'", None

    def _undo(self, sel, kind):
        if self.trash:
            return f"restauradas {lib_mod.restore(self.trash.pop())} plantillas", None
        return "nada que deshacer", None

    def _relabel(self, sel, kind):
        try:
            if kind[8:] in lib_mod.ALL_CHARS:  # una etiqueta invalida falla antes de respaldar
                self._ensure_backup()
            dest = lib_mod.relabel(sel.path, kind[8:], self.params.templates_dir, backup=False)
            return f"{sel.path.name} -> {dest.name}", dest
        except ValueError as exc:
            return str(exc), None

    def _library_request(self, kind: str, st: TeachState) -> TeachState:
        sel = self.entries[st.sel] if 0 <= st.sel < len(self.entries) else None
        msg, dest = "", None
        if kind == "refresh_lib":
            self.result = self.refresh_library()
        else:
            op, needs_sel = self._lib_ops.get(kind.partition(":")[0], (None, False))
            if op and (sel or not needs_sel):
                msg, dest = op(sel, kind)
            self.result = self.refresh_library()
            st = replace(st, sel=self._reselect(st, dest))
        last = max((len(self.entries) - 1) // PER_PAGE, 0)
        return replace(st, message=msg, page=min(st.page, last))

    def _reselect(self, st: TeachState, dest) -> int:
        """Despues de un cambio, deja elegida una plantilla razonable."""
        if not self.entries:
            return 0
        if dest is not None:
            for i, e in enumerate(self.entries):
                if e.path == dest:
                    return i
        return min(st.sel, len(self.entries) - 1)
