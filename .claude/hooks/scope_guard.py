"""Guarda de alcance de los agentes: un hook PreToolUse, con una politica por rol.

Se engancha desde el frontmatter de cada agente (``.claude/agents/<rol>.md``), donde
solo corre mientras ese agente esta activo::

    .venv/Scripts/python .claude/hooks/scope_guard.py <rol>

Lee por stdin el JSON del hook (``tool_name``, ``tool_input``, ``cwd``…).
Codigo de salida 0 = permitir; **2 = bloquear**, y el mensaje de stderr le llega al
agente diciendole a quien le toca lo que intento hacer.

Por que existe: ``disallowedTools: Edit(src/**)`` en un agente *quita la herramienta
Edit completa* en vez de restringir la ruta, y las reglas ``permissions.deny`` son
globales. Los hooks son lo unico que sabe *que agente* esta actuando.

Los mensajes son ASCII a proposito: la consola de Windows no siempre lee UTF-8.

Interfaz publica:
    POLICIES                              -> politica de cada rol
    check(rol, payload, project_dir)      -> (permitido, mensaje)
    main()                                -> lee stdin y sale con 0 o 2
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys

#: Herramientas que escriben archivos y llevan una ruta.
WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
               "NotebookEdit": "notebook_path"}

#: Comandos de solo lectura que el writer puede ejecutar para verificar la documentacion.
#: Cada patron tiene que calzar con el comando completo (sin argumentos extra salvo los
#: indicados). ``teach test eval`` va SIN corrida: con una corrida escribe informes.
_PY = r"(?:\.?/?\.venv/Scripts/python(?:\.exe)?|python3?(?:\.exe)?)"
_RUN = r"[\w.\-]+"
READONLY_BASH = [
    rf"{_PY} -m pytest(?: .*)?",
    rf"{_PY} -m spectro(?: [\w\-]+)*(?: --help| -h)",
    rf"{_PY} -m spectro doctor",
    rf"{_PY} -m spectro teach status",
    rf"{_PY} -m spectro teach lib list(?: --usage)?",
    rf"{_PY} -m spectro teach (?:samples|test) list(?: {_RUN})?",
    rf"{_PY} -m spectro teach test history {_RUN}",
    rf"{_PY} -m spectro teach test eval",
    rf"{_PY} \.claude/skills/docs-sync/scripts/check_docs\.py(?: .*)?",
    r"git (?:status|diff|log|show)(?: .*)?",
    r"(?:ls|dir|pwd|cat|head|tail|wc|grep|rg|echo|type)(?: .*)?",
    r"find [^;&|]*",
]
#: Aun dentro de un comando permitido, esto lo vuelve de escritura.
_PELIGROSOS = re.compile(r"(?:^|\s)(?:-delete|-exec|-execdir|-ok|-fprint\w*|--output|--hard)(?:\s|=|$)")

#: Politica por rol: donde puede escribir y, si se indica, que comandos Bash puede correr.
POLICIES = {
    "developer": {"write": ["src/**", "pyproject.toml", "requirements.txt"]},
    "test": {"write": ["tests/**"]},
    "refactor": {"write": ["src/**", "tests/**"]},
    "writer": {"write": ["README.md", "docs/**", "PLAN*.md", "CLAUDE.md"],
               "bash": READONLY_BASH},
}

#: A quien le toca cada zona: sirve para decirle al agente a donde derivar.
OWNERS = [
    ("src/**", "el agente developer"),
    ("pyproject.toml", "el agente developer"),
    ("requirements.txt", "el agente developer"),
    ("tests/**", "el agente test"),
    ("README.md", "el agente writer"),
    ("docs/**", "el agente writer"),
    ("PLAN*.md", "el agente writer"),
    ("CLAUDE.md", "el agente writer"),
    (".claude/**", "el usuario (la configuracion de agentes no la edita un agente)"),
    ("calib/templates/**", "los comandos de teach (la biblioteca no se edita a mano)"),
    ("runs/**/truth.csv", "los comandos de teach (las muestras no se editan a mano)"),
    ("runs/**/test.csv", "los comandos de teach (las muestras no se editan a mano)"),
]


def _match(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path.lower(), pattern.lower())


def _relative(path: str, project_dir: str) -> str | None:
    """Ruta relativa al proyecto, con ``/``. ``None`` si queda afuera del proyecto."""
    absoluta = path if os.path.isabs(path) else os.path.join(project_dir, path)
    try:
        rel = os.path.relpath(os.path.normpath(absoluta), os.path.normpath(project_dir))
    except ValueError:  # en Windows, otra unidad (D: vs C:) no tiene ruta relativa
        return None
    rel = rel.replace("\\", "/")
    return None if rel == ".." or rel.startswith("../") else rel


def _quien(rel: str) -> str:
    for pattern, owner in OWNERS:
        if _match(rel, pattern):
            return owner
    return "nadie en particular (no esta en la zona de ningun agente)"


def check_write(role: str, ruta: str, project_dir: str) -> tuple[bool, str]:
    rel = _relative(ruta, project_dir)
    if rel is None:
        return False, f"[{role}] {ruta} esta fuera del proyecto: no se puede escribir ahi."
    if any(_match(rel, p) for p in POLICIES[role]["write"]):
        return True, ""
    permitido = ", ".join(POLICIES[role]["write"])
    return False, (f"[{role}] no escribe en {rel}. Su zona es: {permitido}. "
                   f"Eso le toca a {_quien(rel)}: describile el cambio en vez de hacerlo vos.")


def _dividir(comando: str) -> list[str] | None:
    """Parte un comando en sub-comandos (``&&``, ``||``, ``;``, ``|``) respetando las comillas.

    Devuelve ``None`` si hay una redireccion de salida o una sustitucion de comandos
    fuera de comillas simples: son formas de escribir que ningun patron de lectura cubre.
    """
    comando = re.sub(r"\s2>\s*&1", " ", comando)
    comando = re.sub(r"\s2>\s*/dev/null", " ", comando)
    partes: list[str] = []
    actual: list[str] = []
    comilla = ""
    i = 0
    while i < len(comando):
        c = comando[i]
        if comilla:
            if c == comilla:
                comilla = ""
            elif comilla == '"' and (c == "`" or comando.startswith("$(", i)):
                return None
            actual.append(c)
        elif c in "'\"":
            comilla = c
            actual.append(c)
        elif c == "`" or comando.startswith("$(", i):
            return None
        elif c == ">" or comando.startswith("<(", i):
            return None
        elif c in ";|&" or c == "\n":
            if c == "&" and comando.startswith("&&", i):
                i += 1
            elif c == "|" and comando.startswith("||", i):
                i += 1
            partes.append("".join(actual).strip())
            actual = []
        else:
            actual.append(c)
        i += 1
    partes.append("".join(actual).strip())
    return [p for p in partes if p]


def check_bash(role: str, comando: str) -> tuple[bool, str]:
    patrones = POLICIES[role].get("bash")
    if patrones is None:
        return True, ""
    partes = _dividir(comando)
    if partes is None:
        return False, (f"[{role}] solo corre comandos de lectura: no uses redirecciones (>), "
                       "sustitucion de comandos ni escribas archivos por Bash. "
                       "Para cambiar un archivo usa Edit o Write dentro de tu zona.")
    for parte in partes:
        calza = any(re.fullmatch(p, parte) for p in patrones)
        if not calza or _PELIGROSOS.search(parte):
            return False, (f"[{role}] solo corre comandos de lectura y '{parte}' no esta en esa lista "
                           "(--help, doctor, teach status/lib list/samples list/test list, pytest, "
                           "git status/diff/log, ls/grep/cat). Si necesitas otro dato, pedile al "
                           "developer que lo obtenga.")
    return True, ""


def check(role: str, payload: dict, project_dir: str) -> tuple[bool, str]:
    """Decide si ``role`` puede hacer lo que describe ``payload`` (el JSON del hook)."""
    if role not in POLICIES:
        return False, f"scope_guard: rol desconocido {role!r} (validos: {', '.join(POLICIES)})."
    tool = payload.get("tool_name", "")
    entrada = payload.get("tool_input") or {}
    if tool in WRITE_TOOLS:
        ruta = entrada.get(WRITE_TOOLS[tool]) or ""
        if not ruta:
            return False, f"[{role}] la llamada a {tool} no trae ruta de archivo."
        return check_write(role, ruta, project_dir)
    if tool == "Bash":
        return check_bash(role, entrada.get("command") or "")
    return True, ""


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: scope_guard.py <rol>", file=sys.stderr)
        return 2
    try:
        # Bytes + utf-8-sig: PowerShell 5.1 antepone un BOM, y con la codificacion local de
        # Windows (cp1252) una ruta con tildes o eñes se decodificaria mal.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("scope_guard: el hook no recibio un JSON valido; se bloquea por seguridad.",
              file=sys.stderr)
        return 2
    proyecto = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    permitido, mensaje = check(sys.argv[1], payload, proyecto)
    if not permitido:
        print(mensaje, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
