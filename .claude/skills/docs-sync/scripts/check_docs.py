"""Verifica que la documentacion siga alineada con el CLI y entre si (solo lectura).

Hace tres comprobaciones sobre ``README.md``, ``CLAUDE.md`` y ``docs/*.md``:

1. **Comandos.** Cada linea ``python -m spectro ...`` de un bloque de codigo se *parsea en seco*
   con ``build_parser()``: no se ejecuta nada, pero un flag eliminado o mal escrito falla.
   Tambien se revisan los comandos citados en prosa entre backticks (``python -m spectro ...`` o
   ``teach ... --flag``): ahi solo cuentan los flags o subcomandos inexistentes, no los
   argumentos obligatorios que falten, porque en prosa se citan abreviados.
2. **Ids de corrida.** Un ``img_NNNN`` o ``AAAAMMDD_HHMMSS`` citado que no exista en ``runs/`` se
   avisa (AVISO: no cambia el codigo de salida; puede ser un ejemplo historico).
3. **Enlaces.** Cada enlace relativo ``[texto](ruta#ancla)`` apunta a un archivo que existe y,
   si trae ancla, a un encabezado que existe en ese archivo.

    python .claude/skills/docs-sync/scripts/check_docs.py            # revisa y resume
    python .claude/skills/docs-sync/scripts/check_docs.py --list     # lista los comandos encontrados

Los ``PLAN*.md`` no se revisan: describen comandos futuros o ya reemplazados.
Para que un ejemplo de documentacion no se analice (porque es una plantilla y no un comando
real), usa una forma que contenga ``...``, ``…``, ``[`` o ``|``; esas lineas se omiten y se
cuentan aparte.

Codigo de salida: 0 sin problemas, 1 si hay alguno.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import shlex
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
DOCUMENTOS = ["README.md", "CLAUDE.md"]
_CERCA = re.compile(r"^\s*(`{3,}|~{3,})")
_OMITIR = ("...", "…", "[", "|")
_COMANDO = re.compile(
    r"^\s*(?:PS[^>]*>\s*|\$\s*|>\s*)?((?:\.?/?\.venv/Scripts/)?python(?:\.exe)? -m spectro\b.*)$"
)
_ENLACE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
_PLACEHOLDER = re.compile(r"<[^<>\s]+>")


def documentos(raiz: Path = RAIZ) -> list[Path]:
    """Los .md que se revisan: README, CLAUDE y todo ``docs/``."""
    out = [raiz / n for n in DOCUMENTOS if (raiz / n).exists()]
    out += sorted((raiz / "docs").glob("*.md")) if (raiz / "docs").is_dir() else []
    return out


def extraer_comandos(texto: str) -> list[tuple[int, str]]:
    """``(numero_de_linea, comando)`` de cada ``python -m spectro ...`` dentro de bloques de codigo."""
    out: list[tuple[int, str]] = []
    dentro = False
    for n, linea in enumerate(texto.splitlines(), 1):
        if _CERCA.match(linea):
            dentro = not dentro
            continue
        if not dentro:
            continue
        # solo cuenta si el comando empieza la linea (tras un prompt opcional): un comando
        # citado dentro de un comentario `# ...` no es un ejemplo ejecutable
        m = _COMANDO.match(linea)
        if m:
            out.append((n, m.group(1).strip()))
    return out


_EN_LINEA = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_ID_CORRIDA = re.compile(r"\b(img_\d{4}|\d{8}_\d{6})\b")


def extraer_comandos_en_linea(texto: str) -> list[tuple[int, str]]:
    """``(linea, comando)`` de los comandos citados en prosa entre backticks, fuera de bloques.

    Cuenta un fragmento que empieza con ``python -m spectro`` o con ``teach `` y trae un flag.
    """
    out: list[tuple[int, str]] = []
    dentro = False
    for n, linea in enumerate(texto.splitlines(), 1):
        if _CERCA.match(linea):
            dentro = not dentro
            continue
        if dentro:
            continue
        for m in _EN_LINEA.finditer(linea):
            frag = m.group(1).strip()
            if re.match(r"python(?:\.exe)? -m spectro\b", frag):
                out.append((n, frag))
            elif frag.startswith("teach ") and " --" in frag:
                out.append((n, f"python -m spectro {frag}"))
    return out


def a_argv(comando: str) -> list[str] | None:
    """Argumentos del comando listos para el parser; ``None`` si es una plantilla que se omite."""
    try:
        # ``comments=True`` descarta el comentario final (`# ...`) antes de buscar plantillas
        partes = shlex.split(_PLACEHOLDER.sub("demo", comando), comments=True, posix=True)
    except ValueError:
        return None
    if any(marca in parte for parte in partes for marca in _OMITIR):
        return None
    # ``python[.exe] -m spectro <argv>``; si no calza esa forma, no es un comando analizable
    for i in range(len(partes) - 2):
        if partes[i + 1] == "-m" and partes[i + 2] == "spectro":
            return partes[i + 3:]
    return None


def parsear(argv: list[str]) -> str | None:
    """Mensaje de error si el parser rechaza ``argv``; ``None`` si lo acepta."""
    from spectro.cli import build_parser

    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            build_parser().parse_args(argv)
    except SystemExit as e:
        if e.code in (0, None):  # --help termina con 0: es valido
            return None
        ultima = [l for l in err.getvalue().splitlines() if l.strip()]
        return ultima[-1] if ultima else f"codigo de salida {e.code}"
    return None


def revisar_comandos(raiz: Path = RAIZ) -> tuple[list[str], int, int]:
    """``(problemas, comandos_revisados, omitidos)`` sobre todos los documentos."""
    problemas: list[str] = []
    revisados = omitidos = 0
    for doc in documentos(raiz):
        for n, comando in extraer_comandos(doc.read_text(encoding="utf-8")):
            argv = a_argv(comando)
            if argv is None:
                omitidos += 1
                continue
            revisados += 1
            error = parsear(argv)
            if error:
                problemas.append(f"{doc.relative_to(raiz)}:{n}: `{comando}` -> {error}")
        for n, comando in extraer_comandos_en_linea(doc.read_text(encoding="utf-8")):
            argv = a_argv(comando)
            if argv is None:
                omitidos += 1
                continue
            revisados += 1
            error = parsear(argv)
            # en prosa se cita abreviado: faltar un argumento obligatorio no es un error
            if error and "required" not in error:
                problemas.append(f"{doc.relative_to(raiz)}:{n}: `{comando}` (en prosa) -> {error}")
    return problemas, revisados, omitidos


def revisar_ids(raiz: Path = RAIZ) -> list[str]:
    """Avisos por cada id de corrida citado que no existe en ``runs/`` (no son fallos)."""
    runs = raiz / "runs"
    existentes = {d.name for d in runs.iterdir() if d.is_dir()} if runs.is_dir() else set()
    avisos: list[str] = []
    for doc in documentos(raiz):
        vistos: set[str] = set()
        for n, linea in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for m in _ID_CORRIDA.finditer(linea):
                ident = m.group(1)
                if ident not in existentes and ident not in vistos:
                    vistos.add(ident)
                    avisos.append(f"{doc.relative_to(raiz)}:{n}: la corrida '{ident}' no existe en runs/")
    return avisos


def _slug(titulo: str) -> str:
    """Ancla al estilo GitHub: minusculas, sin signos, espacios por guiones."""
    limpio = re.sub(r"[`*_~]", "", titulo.strip().lower())
    return re.sub(r"[^\w\- ]", "", limpio).replace(" ", "-")


def _anclas(texto: str) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", texto, re.M)}


def revisar_enlaces(raiz: Path = RAIZ) -> tuple[list[str], int]:
    """``(problemas, enlaces_revisados)``: archivo y ancla de cada enlace relativo."""
    problemas: list[str] = []
    revisados = 0
    for doc in documentos(raiz):
        texto = doc.read_text(encoding="utf-8")
        sin_codigo = re.sub(r"```.*?```", "", texto, flags=re.S)
        for m in _ENLACE.finditer(sin_codigo):
            destino = m.group(1)
            if re.match(r"^[a-z]+:", destino) or destino.startswith("mailto:"):
                continue
            ruta, _, ancla = destino.partition("#")
            objetivo = (doc.parent / ruta).resolve() if ruta else doc
            revisados += 1
            if not objetivo.exists():
                problemas.append(f"{doc.relative_to(raiz)}: el enlace a '{destino}' no existe")
            elif ancla and objetivo.suffix == ".md":
                if _slug(ancla) not in _anclas(objetivo.read_text(encoding="utf-8")):
                    problemas.append(f"{doc.relative_to(raiz)}: '{destino}': no hay un encabezado '{ancla}'")
    return problemas, revisados


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--list", action="store_true", help="listar los comandos encontrados y salir")
    p.add_argument("--root", default=str(RAIZ), help="raiz del proyecto (default: la de este repo)")
    args = p.parse_args()
    raiz = Path(args.root)

    if args.list:
        for doc in documentos(raiz):
            for n, comando in extraer_comandos(doc.read_text(encoding="utf-8")):
                marca = "omitido" if a_argv(comando) is None else "revisable"
                print(f"{doc.relative_to(raiz)}:{n}  [{marca}]  {comando}")
        return 0

    sys.path.insert(0, str(raiz / "src"))
    cmd_problemas, revisados, omitidos = revisar_comandos(raiz)
    link_problemas, enlaces = revisar_enlaces(raiz)
    print(f"comandos: {revisados} revisados, {omitidos} omitidos (plantillas); enlaces: {enlaces} revisados")
    for linea in cmd_problemas + link_problemas:
        print("  PROBLEMA", linea)
    for linea in revisar_ids(raiz):
        print("  AVISO", linea)
    if not (cmd_problemas or link_problemas):
        print("  todo en orden")
    return 1 if (cmd_problemas or link_problemas) else 0


if __name__ == "__main__":
    sys.exit(main())
