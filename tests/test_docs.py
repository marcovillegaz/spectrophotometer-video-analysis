"""La documentacion no puede desactualizarse en silencio.

Usa el verificador de la skill ``docs-sync`` (``.claude/skills/docs-sync/scripts/check_docs.py``):

* cada comando ``python -m spectro ...`` de la documentacion se parsea en seco contra el
  parser real, asi que un flag eliminado o mal escrito hace fallar esta prueba;
* cada enlace relativo apunta a un archivo y a un encabezado que existen.

Si falla despues de cambiar el CLI: hay que actualizar la documentacion (agente ``writer``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / ".claude" / "skills" / "docs-sync" / "scripts" / "check_docs.py"

spec = importlib.util.spec_from_file_location("check_docs", SCRIPT)
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


# -- la documentacion real -------------------------------------------------------------
def test_todos_los_comandos_documentados_son_validos():
    problemas, revisados, _ = check_docs.revisar_comandos(RAIZ)
    assert revisados > 30, "el verificador deberia encontrar decenas de comandos en la documentacion"
    assert not problemas, "\n".join(problemas)


def test_todos_los_enlaces_de_la_documentacion_existen():
    problemas, revisados = check_docs.revisar_enlaces(RAIZ)
    assert revisados >= 5
    assert not problemas, "\n".join(problemas)


# -- el verificador en si ---------------------------------------------------------------
BLOQUE = """\
Texto con `python -m spectro nada` en prosa: no cuenta.

```powershell
python -m spectro doctor
python -m spectro --run <id> calibrate --auto   # comentario final
.venv/Scripts/python -m spectro teach --help
# python -m spectro comando-citado-en-un-comentario
python -m spectro templates --run <id> --labels ".,0,..."
python -m spectro read --run <id> | tail -3
```

Fuera del bloque: python -m spectro otra-cosa
"""


def test_extrae_solo_comandos_que_empiezan_la_linea_dentro_de_bloques():
    comandos = [c for _, c in check_docs.extraer_comandos(BLOQUE)]
    assert comandos == [
        "python -m spectro doctor",
        "python -m spectro --run <id> calibrate --auto   # comentario final",
        ".venv/Scripts/python -m spectro teach --help",
        'python -m spectro templates --run <id> --labels ".,0,..."',
        "python -m spectro read --run <id> | tail -3",
    ]


def test_plantillas_y_placeholders():
    a = check_docs.a_argv
    assert a("python -m spectro --run <id> calibrate --auto   # comentario") == ["--run", "demo", "calibrate", "--auto"]
    assert a(".venv/Scripts/python -m spectro doctor") == ["doctor"]
    assert a('python -m spectro templates --labels ".,0,..."') is None       # contiene ...
    assert a("python -m spectro read --run <id> | tail -3") is None          # tuberia
    assert a("python -m spectro batch videos/*.MOV --fps 4") == ["batch", "videos/*.MOV", "--fps", "4"]
    assert a("python -m spectro # ...solo comentario") == []                 # el '...' esta en el comentario


def test_el_parser_acepta_lo_valido_y_rechaza_un_flag_inexistente():
    assert check_docs.parsear(["doctor"]) is None
    assert check_docs.parsear(["--help"]) is None
    assert check_docs.parsear(["batch", "a.mov", "--until", "qc"]) is None
    error = check_docs.parsear(["doctor", "--flag-que-no-existe"])
    assert error and "unrecognized" in error


def _raiz(tmp_path: Path, readme: str, otros: dict[str, str] | None = None) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    for nombre, texto in (otros or {}).items():
        (tmp_path / nombre).write_text(texto, encoding="utf-8")
    return tmp_path


def test_detecta_un_flag_eliminado_en_la_documentacion(tmp_path):
    raiz = _raiz(tmp_path, "```powershell\npython -m spectro doctor --flag-viejo\npython -m spectro doctor\n```\n")
    problemas, revisados, omitidos = check_docs.revisar_comandos(raiz)
    assert revisados == 2 and omitidos == 0
    assert len(problemas) == 1 and "README.md:2" in problemas[0] and "--flag-viejo" in problemas[0]


def test_detecta_enlaces_y_anclas_rotos(tmp_path):
    raiz = _raiz(
        tmp_path,
        "# Titulo\n[guia](docs/GUIA.md#paso-uno) [roto](docs/NO_EXISTE.md) [ancla](docs/GUIA.md#no-hay) "
        "[web](https://example.com) [propia](#titulo)\n",
        {"docs/GUIA.md": "# Guia\n\n## Paso uno\n"},
    )
    problemas, revisados = check_docs.revisar_enlaces(raiz)
    assert revisados == 4  # los de internet no se revisan
    assert len(problemas) == 2
    assert any("NO_EXISTE" in p for p in problemas) and any("no-hay" in p for p in problemas)


def test_los_enlaces_dentro_de_bloques_de_codigo_no_se_revisan(tmp_path):
    raiz = _raiz(tmp_path, "```\n[x](no/existe.md)\n```\n")
    assert check_docs.revisar_enlaces(raiz) == ([], 0)


@pytest.mark.parametrize("titulo,slug", [
    ("Referencia de comandos", "referencia-de-comandos"),
    ("`teach` — calibrar el lector", "teach--calibrar-el-lector"),
    ("Cómo re-calibrar una sola corrida", "cómo-re-calibrar-una-sola-corrida"),
])
def test_anclas_al_estilo_github(titulo, slug):
    assert check_docs._slug(titulo) == slug


def test_el_script_corre_como_programa_y_sale_con_cero():
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=RAIZ)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "todo en orden" in r.stdout
