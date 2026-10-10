"""Agentes, skills, reglas, permisos y memoria del proyecto (``.claude/`` y ``CLAUDE.md``).

Si una de estas pruebas falla, la configuracion de agentes esta rota aunque el codigo del
proyecto funcione. El guard de alcance por rol se prueba en ``test_claude_config.py``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from test_claude_config import CLAUDE, RAIZ, guard

AGENTES = {"developer": "sonnet", "test": "sonnet", "refactor": "sonnet", "writer": "opus"}
SKILLS = ["diagnose-reading", "testing-patterns", "docs-style", "ds-fundamentals", "docs-sync"]
HERRAMIENTAS = {"Read", "Grep", "Glob", "Edit", "Write", "Bash", "Skill", "MultiEdit", "NotebookEdit"}


def frontmatter(ruta) -> dict[str, str]:
    """Campos de primer nivel del frontmatter YAML; las lineas indentadas se acumulan en su campo."""
    texto = ruta.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n", texto, re.S)
    assert m, f"{ruta.name}: no empieza con un bloque ---"
    campos: dict[str, str] = {}
    clave = None
    for linea in m.group(1).splitlines():
        if re.match(r"^[A-Za-z_-]+:", linea):
            clave, _, valor = linea.partition(":")
            campos[clave] = valor.strip()
        elif clave is not None:
            campos[clave] = (campos[clave] + " " + linea.strip()).strip()
    return campos


def _agente(nombre: str) -> dict[str, str]:
    return frontmatter(CLAUDE / "agents" / f"{nombre}.md")


def _precargadas(nombre: str) -> list[str]:
    return re.findall(r"-\s*([\w-]+)", _agente(nombre).get("skills", ""))


# -- agentes ------------------------------------------------------------------------
def test_estan_los_cuatro_agentes_y_solo_esos():
    assert sorted(p.stem for p in (CLAUDE / "agents").glob("*.md")) == sorted(AGENTES)


@pytest.mark.parametrize("nombre,modelo", AGENTES.items())
def test_cada_agente_esta_bien_formado(nombre, modelo):
    f = _agente(nombre)
    assert f["name"] == nombre
    assert 80 <= len(f["description"]) <= 900, "la descripcion decide cuando se delega: ni vacia ni un tratado"
    assert f["model"] == modelo
    herramientas = {t.strip() for t in f["tools"].split(",")}
    assert herramientas <= HERRAMIENTAS and {"Read", "Grep", "Glob"} <= herramientas
    # la descripcion dice tambien cuando NO usarlo
    assert re.search(r"\b(?:No|Nunca) (?:escribe|modifica|agrega|edita)", f["description"]), nombre


@pytest.mark.parametrize("nombre", AGENTES)
def test_el_hook_del_agente_usa_su_propio_rol(nombre):
    f = _agente(nombre)
    roles = re.findall(r"scope_guard\.py (\w+)", f["hooks"])
    assert roles and set(roles) == {nombre}, "un agente no puede llevar la politica de otro"
    assert "Edit|Write|MultiEdit|NotebookEdit" in f["hooks"]
    assert nombre in guard.POLICIES


def test_solo_el_writer_tiene_el_hook_de_bash_y_solo_el_writer_esta_limitado():
    for nombre in AGENTES:
        texto = (CLAUDE / "agents" / f"{nombre}.md").read_text(encoding="utf-8")
        assert ('matcher: "Bash"' in texto) is (nombre == "writer")
        assert ("bash" in guard.POLICIES[nombre]) is (nombre == "writer")
    assert set(guard.POLICIES) == set(AGENTES)


def test_las_zonas_de_escritura_coinciden_con_el_plan():
    zonas = {"developer": {"src/**", "pyproject.toml", "requirements.txt"}, "test": {"tests/**"},
             "refactor": {"src/**", "tests/**"}, "writer": {"README.md", "docs/**", "PLAN*.md", "CLAUDE.md"}}
    for rol, esperado in zonas.items():
        assert set(guard.POLICIES[rol]["write"]) == esperado
    for politica in guard.POLICIES.values():  # ninguna zona toca la configuracion ni los datos
        for patron in politica["write"]:
            assert not patron.startswith((".claude", "calib", "runs"))


@pytest.mark.parametrize("nombre", AGENTES)
def test_las_skills_precargadas_existen(nombre):
    for s in _precargadas(nombre):
        assert s in SKILLS and (CLAUDE / "skills" / s / "SKILL.md").exists(), (nombre, s)


def test_toda_skill_la_precarga_algun_agente():
    assert {s for n in AGENTES for s in _precargadas(n)} == set(SKILLS)


# -- skills -------------------------------------------------------------------------
def test_estan_las_cinco_skills_y_solo_esas():
    assert sorted(p.name for p in (CLAUDE / "skills").iterdir() if p.is_dir()) == sorted(SKILLS)


@pytest.mark.parametrize("nombre", SKILLS)
def test_cada_skill_esta_bien_formada(nombre):
    carpeta = CLAUDE / "skills" / nombre
    ruta = carpeta / "SKILL.md"
    f = frontmatter(ruta)
    assert f["name"] == nombre
    assert 100 <= len(f["description"]) <= 1500  # el listado trunca en ~1.5k caracteres
    texto = ruta.read_text(encoding="utf-8")
    assert len(texto.splitlines()) < 500
    for destino in re.findall(r"\]\((references/[^)#]+)\)", texto):
        assert (carpeta / destino).exists(), (nombre, destino)
    for script in set(re.findall(r"((?:[\w.-]+/)*scripts/\w+\.py)", texto)):
        assert (carpeta / script).exists() or (RAIZ / script).exists(), (nombre, script)


def test_las_referencias_de_ds_fundamentals_son_consistentes():
    refs = CLAUDE / "skills" / "ds-fundamentals" / "references"
    glosario = (refs / "glosario.md").read_text(encoding="utf-8")
    conceptos = (refs / "conceptos.md").read_text(encoding="utf-8")
    for termino in ("Conjunto de prueba", "Fuga de datos", "Aprendizaje activo", "Abstención",
                    "Intervalo de Wilson", "Hold-out por video", "Ruido de etiquetas"):
        assert termino in glosario, termino
    assert len(re.findall(r"^## \d+\. ", conceptos, re.M)) == 14
    for entrada in re.split(r"^## \d+\. ", conceptos, flags=re.M)[1:]:
        assert "**En una frase:**" in entrada and "**Error típico:**" in entrada


@pytest.mark.parametrize("script", sorted(CLAUDE.glob("**/*.py")), ids=lambda p: p.name)
def test_los_scripts_de_claude_compilan(script):
    compile(script.read_text(encoding="utf-8"), str(script), "exec")


@pytest.mark.parametrize("script", sorted((CLAUDE / "skills").glob("*/scripts/[!_]*.py")), ids=lambda p: p.name)
def test_los_scripts_de_las_skills_responden_a_help(script):
    r = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, cwd=RAIZ)
    assert r.returncode == 0 and "usage" in r.stdout.lower(), r.stderr


# -- memoria del proyecto y reglas ---------------------------------------------------
def test_claude_md_es_corto_y_menciona_agentes_y_skills():
    texto = (RAIZ / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(texto.splitlines()) < 200
    for nombre in list(AGENTES) + SKILLS:
        assert f"`{nombre}`" in texto, nombre


@pytest.mark.parametrize("regla,patron", [("codigo.md", "src/**/*.py"), ("tests.md", "tests/**/*.py")])
def test_las_reglas_por_ruta_declaran_su_ruta(regla, patron):
    texto = (CLAUDE / "rules" / regla).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert re.search(rf'paths:\n\s*-\s*"{re.escape(patron)}"', texto)


# -- permisos -----------------------------------------------------------------------
@pytest.fixture(scope="module")
def permisos() -> dict:
    return json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))["permissions"]


def test_se_deniegan_las_ediciones_directas_de_los_datos(permisos):
    deny = set(permisos["deny"])
    for herramienta in ("Edit", "Write"):
        for ruta in ("calib/templates/**", "runs/**/truth.csv", "runs/**/test.csv"):
            assert f"{herramienta}({ruta})" in deny
    assert {"Bash(git push *)", "Bash(git reset --hard *)", "Read(videos/**)"} <= deny
    assert any(d.startswith("Bash(rm -rf calib") for d in deny)


def test_lo_permitido_sin_preguntar_es_solo_lectura(permisos):
    peligrosas = ("train", "delete", "relabel", "clear", "restore", "--build", "--add", "spectro read",
                  "report", "batch", "extract", "calibrate", " run", "rm ", "git commit", "git push")
    for regla in permisos["allow"]:
        assert not any(p in regla for p in peligrosas), regla
    assert "Bash(git commit *)" in permisos["ask"]


def test_ninguna_regla_permitida_esta_tambien_denegada(permisos):
    assert not set(permisos["allow"]) & set(permisos["deny"])


def test_settings_local_no_se_versiona():
    assert ".claude/settings.local.json" in (RAIZ / ".gitignore").read_text(encoding="utf-8")
