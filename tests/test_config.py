"""``Config``: los ``config.json`` viejos siguen cargando aunque se retiren campos.

Cada test dice en su docstring que cambio en ``src/`` lo haria fallar.
"""

from __future__ import annotations

import json

from conftest import make_config
from spectro.config import Config, TemplateConfig
from spectro.project import RunPaths


def _json_viejo(tmp_path, **extra_templates):
    d = make_config().to_dict()
    d["templates"].update(extra_templates)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_config_con_cluster_hamming_viejo_carga_y_lo_ignora(tmp_path):
    """Rompe: que ``from_dict`` pase claves desconocidas al constructor (``TypeError``) o que vuelva a pedir el campo."""
    cfg = Config.load(_json_viejo(tmp_path, cluster_hamming=6))
    assert cfg.templates.size == make_config().templates.size
    assert not hasattr(cfg.templates, "cluster_hamming")


def test_config_con_otras_claves_viejas_tambien_carga(tmp_path):
    """Rompe: una validacion estricta de claves (los ``config.json`` existentes dejarian de cargar)."""
    cfg = Config.load(_json_viejo(tmp_path, min_count=2, clave_que_nunca_existio="x"))
    assert cfg.templates.min_score == make_config().templates.min_score


def test_config_con_claves_viejas_en_la_raiz_carga(tmp_path):
    """Rompe: ignorar claves desconocidas solo en las secciones anidadas."""
    d = make_config().to_dict()
    d["campo_retirado"] = 1
    p = tmp_path / "config.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    assert Config.load(p).roi == make_config().roi


def test_config_guardada_no_vuelve_a_escribir_cluster_hamming(tmp_path):
    """Rompe: que ``to_dict``/``save`` sigan emitiendo el campo retirado."""
    sucio = Config.load(_json_viejo(tmp_path, cluster_hamming=9))
    salida = sucio.save(tmp_path / "limpio.json")
    assert "cluster_hamming" not in json.loads(salida.read_text(encoding="utf-8"))["templates"]
    assert Config.load(salida) == sucio


def test_template_config_ya_no_tiene_cluster_hamming():
    """Rompe: reintroducir el campo huerfano."""
    assert not hasattr(TemplateConfig(), "cluster_hamming")
    assert "cluster_hamming" not in make_config().to_dict()["templates"]


def test_run_paths_ya_no_tiene_glyph_sheet(tmp_path):
    """Rompe: reintroducir ``RunPaths.glyph_sheet`` (la hoja de glifos se retiro)."""
    run = RunPaths.for_run("r1", base=tmp_path)
    assert not hasattr(run, "glyph_sheet")
    assert run.preview.name == "calibracion.png"  # el resto de las salidas sigue
