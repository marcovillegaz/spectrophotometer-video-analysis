"""Configuracion de ``.claude/``: el guard de alcance por rol, los agentes, las skills y los permisos.

Si una de estas pruebas falla, la configuracion de agentes esta rota aunque el codigo del
proyecto funcione: por eso viven en la suite.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CLAUDE = RAIZ / ".claude"
GUARD = CLAUDE / "hooks" / "scope_guard.py"


def _cargar_guard():
    spec = importlib.util.spec_from_file_location("scope_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _cargar_guard()


def escribir(tool: str, ruta: str) -> dict:
    clave = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {"tool_name": tool, "tool_input": {clave: ruta}}


def bash(comando: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": comando}}


def permitido(rol: str, payload: dict) -> bool:
    return guard.check(rol, payload, str(RAIZ))[0]


# -- escritura: cada rol solo escribe en su zona -----------------------------------
@pytest.mark.parametrize("rol,ruta,esperado", [
    ("developer", "src/spectro/teach.py", True),
    ("developer", "pyproject.toml", True),
    ("developer", "tests/test_teach.py", False),
    ("developer", "README.md", False),
    ("developer", ".claude/agents/developer.md", False),
    ("test", "tests/test_nuevo.py", True),
    ("test", "tests/conftest.py", True),
    ("test", "src/spectro/read.py", False),
    ("test", "docs/GUIA_CALIBRACION.md", False),
    ("refactor", "src/spectro/cli.py", True),
    ("refactor", "tests/test_teach.py", True),
    ("refactor", "README.md", False),
    ("writer", "README.md", True),
    ("writer", "docs/ARQUITECTURA.md", True),
    ("writer", "PLAN_v6.md", True),
    ("writer", "CLAUDE.md", True),
    ("writer", "src/spectro/read.py", False),
    ("writer", "tests/test_teach.py", False),
    ("writer", ".claude/settings.json", False),
    ("writer", "notas.md", False),                       # un .md fuera de las zonas de documentacion
    ("writer", "docs/../src/spectro/read.py", False),    # no se escapa con ..
])
def test_cada_rol_escribe_solo_en_su_zona(rol, ruta, esperado):
    for tool in ("Edit", "Write", "MultiEdit"):
        assert permitido(rol, escribir(tool, ruta)) is esperado, (rol, tool, ruta)


def test_rutas_absolutas_y_con_barras_de_windows():
    assert permitido("test", escribir("Write", str(RAIZ / "tests" / "test_x.py")))
    assert not permitido("test", escribir("Write", str(RAIZ / "src" / "spectro" / "read.py")))
    assert permitido("writer", escribir("Edit", "docs\\GUIA_CALIBRACION.md"))
    assert not permitido("writer", escribir("Edit", "src\\spectro\\read.py"))


def test_fuera_del_proyecto_siempre_se_bloquea(tmp_path):
    for rol in guard.POLICIES:
        ok, msg = guard.check(rol, escribir("Write", str(tmp_path / "x.py")), str(RAIZ))
        assert not ok and "fuera del proyecto" in msg


def test_notebook_y_llamadas_sin_ruta():
    assert permitido("test", escribir("NotebookEdit", "tests/n.ipynb"))
    assert not permitido("test", escribir("NotebookEdit", "src/n.ipynb"))
    ok, msg = guard.check("test", {"tool_name": "Write", "tool_input": {}}, str(RAIZ))
    assert not ok and "ruta" in msg


def test_el_mensaje_dice_a_quien_le_toca():
    ok, msg = guard.check("writer", escribir("Edit", "src/spectro/read.py"), str(RAIZ))
    assert not ok and "developer" in msg
    assert "test" in guard.check("developer", escribir("Edit", "tests/t.py"), str(RAIZ))[1]
    assert "writer" in guard.check("developer", escribir("Edit", "README.md"), str(RAIZ))[1]
    assert "teach" in guard.check("developer", escribir("Edit", "calib/templates/0_0.png"), str(RAIZ))[1]
    assert "usuario" in guard.check("developer", escribir("Edit", ".claude/settings.json"), str(RAIZ))[1]
    assert all(ord(c) < 128 for c in msg)       # la consola de Windows no siempre lee UTF-8


def test_herramientas_que_no_escriben_pasan():
    for rol in guard.POLICIES:
        assert permitido(rol, {"tool_name": "Read", "tool_input": {"file_path": "src/x.py"}})
        assert permitido(rol, {"tool_name": "Grep", "tool_input": {"pattern": "x"}})


def test_rol_desconocido_se_bloquea():
    ok, msg = guard.check("hacker", escribir("Write", "tests/x.py"), str(RAIZ))
    assert not ok and "rol desconocido" in msg


# -- Bash: solo el writer esta limitado, y a comandos de lectura -------------------
@pytest.mark.parametrize("comando", [
    ".venv/Scripts/python -m pytest -q",
    ".venv/Scripts/python -m pytest -q tests/test_teach.py",
    ".venv/Scripts/python -m spectro --help",
    ".venv/Scripts/python -m spectro teach --help",
    ".venv/Scripts/python -m spectro teach lib clear --yes --help",
    ".venv/Scripts/python -m spectro doctor",
    ".venv/Scripts/python -m spectro teach status",
    ".venv/Scripts/python -m spectro teach lib list",
    ".venv/Scripts/python -m spectro teach lib list --usage",
    ".venv/Scripts/python -m spectro teach samples list",
    ".venv/Scripts/python -m spectro teach samples list img_8102",
    ".venv/Scripts/python -m spectro teach test list img_8102",
    ".venv/Scripts/python -m spectro teach test history img_8102",
    ".venv/Scripts/python -m spectro teach test eval",
    ".venv/Scripts/python .claude/skills/docs-sync/scripts/check_docs.py",
    "git status",
    "git diff --stat",
    "git log --oneline -5",
    "ls docs",
    "grep -n teach README.md",
    'grep -E "a|b" README.md',
    "cat docs/CONFIG.md | head -20",
    "git status && git diff --stat",
    ".venv/Scripts/python -m pytest -q 2>&1 | tail -3",
    "find docs -name '*.md'",
])
def test_el_writer_puede_correr_comandos_de_lectura(comando):
    ok, msg = guard.check_bash("writer", comando)
    assert ok, (comando, msg)


@pytest.mark.parametrize("comando", [
    "rm -rf docs",
    "rm README.md",
    "mv README.md x.md",
    "cp README.md x.md",
    "echo hola > README.md",
    "echo hola >> README.md",
    "cat docs/CONFIG.md > otro.md",
    "sed -i 's/a/b/' README.md",
    "tee README.md",
    "git commit -am x",
    "git push",
    "git reset --hard",
    "git checkout -- README.md",
    "git diff --output=x.patch",
    "find . -delete",
    "find . -name '*.md' -exec rm {} ;",
    ".venv/Scripts/python -m spectro teach train",
    ".venv/Scripts/python -m spectro teach lib clear --yes",
    ".venv/Scripts/python -m spectro teach lib delete 0_3",
    ".venv/Scripts/python -m spectro teach test eval img_8102",   # con corrida escribe informes
    ".venv/Scripts/python -m spectro read --run img_8102",
    ".venv/Scripts/python -m spectro batch videos/a.mov",
    ".venv/Scripts/python -c \"open('x','w')\"",
    "python script.py",
    "echo $(rm -rf docs)",
    "echo `rm -rf docs`",
    "ls; rm README.md",
    "ls && rm README.md",
    "ls | xargs rm",
    "curl http://example.com",
])
def test_el_writer_no_puede_correr_comandos_que_escriben(comando):
    ok, msg = guard.check_bash("writer", comando)
    assert not ok, comando
    assert all(ord(c) < 128 for c in msg)


def test_los_otros_roles_conservan_bash_libre():
    for rol in ("developer", "test", "refactor"):
        assert permitido(rol, bash("rm -rf /tmp/x"))
        assert permitido(rol, bash(".venv/Scripts/python -m pytest -q"))


# -- el script como hook real (stdin -> codigo de salida) --------------------------
def _hook(rol: str, payload: dict, cwd: Path = RAIZ):
    return subprocess.run(
        [sys.executable, str(GUARD), rol], input=json.dumps(payload), text=True,
        capture_output=True, cwd=cwd, env={"CLAUDE_PROJECT_DIR": str(RAIZ), "PATH": ""},
    )


def test_hook_real_codigo_de_salida_y_mensaje():
    ok = _hook("writer", escribir("Edit", "docs/CONFIG.md"))
    assert ok.returncode == 0 and ok.stderr == ""
    no = _hook("writer", escribir("Edit", "src/spectro/read.py"))
    assert no.returncode == 2 and "developer" in no.stderr
    assert _hook("writer", bash("rm -rf docs")).returncode == 2
    assert _hook("writer", bash("git status")).returncode == 0
    assert _hook("test", escribir("Write", "tests/test_x.py")).returncode == 0


def test_hook_real_tolera_el_bom_de_powershell_y_rutas_con_tildes():
    """PowerShell 5.1 antepone un BOM UTF-8 a lo que se envia por tuberia."""
    def correr(payload: dict, rol: str):
        datos = b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return subprocess.run([sys.executable, str(GUARD), rol], input=datos, capture_output=True, cwd=RAIZ,
                              env={"CLAUDE_PROJECT_DIR": str(RAIZ), "PATH": ""})

    assert correr(escribir("Edit", "docs/CONFIG.md"), "writer").returncode == 0
    assert correr(escribir("Edit", "src/spectro/read.py"), "writer").returncode == 2
    assert correr(escribir("Write", "docs/guía_añadida.md"), "writer").returncode == 0     # tildes y eñes
    assert correr(escribir("Write", "src/guía.py"), "writer").returncode == 2


def test_hook_real_con_entrada_invalida_bloquea():
    r = subprocess.run([sys.executable, str(GUARD), "writer"], input="esto no es json",
                       text=True, capture_output=True, cwd=RAIZ)
    assert r.returncode == 2 and "JSON" in r.stderr
    r = subprocess.run([sys.executable, str(GUARD)], input="{}", text=True, capture_output=True, cwd=RAIZ)
    assert r.returncode == 2 and "uso" in r.stderr
