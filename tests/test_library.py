"""``library``: respaldos (poda, sufijos en el mismo segundo) y el parametro ``backup`` de ``delete``/``relabel``.

Cada test dice en su docstring que cambio en ``src/`` lo haria fallar.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

from spectro import library as L


@pytest.fixture
def tpl(tmp_path):
    """``calib/templates`` con cuatro plantillas chicas y distintas."""
    d = tmp_path / "calib" / "templates"
    d.mkdir(parents=True)
    for label, n, v in (("1", 0, 50), ("1", 1, 90), ("2", 0, 130), ("minus", 0, 200)):
        cv2.imwrite(str(d / f"{label}_{n}.png"), np.full((6, 4), v, np.uint8))
    return d


def reloj(monkeypatch, instantes):
    """Fija ``datetime.now()`` de ``library`` a una lista de instantes (el ultimo se repite)."""
    it = iter(instantes)
    ultimo = [instantes[-1]]

    class Falso:
        @staticmethod
        def now():
            ultimo[0] = next(it, ultimo[0])
            return ultimo[0]

    monkeypatch.setattr(L, "datetime", Falso)


T0 = datetime(2026, 1, 1, 12, 0, 0)


# ==========================================================================
# backup: contenido, poda, sufijos
# ==========================================================================
def test_backup_copia_las_plantillas_a_una_carpeta_con_fecha(tpl, monkeypatch):
    """Rompe: copiar a otra carpeta o con otro nombre (el formato ``YYYYmmdd_HHMMSS``)."""
    reloj(monkeypatch, [T0])
    dest = L.backup(tpl)
    assert dest == L.backups_root(tpl) / "20260101_120000"
    assert {f.name: f.read_bytes() for f in dest.glob("*.png")} == {f.name: f.read_bytes() for f in tpl.glob("*.png")}
    assert L.list_backups(tpl) == ["20260101_120000"]


def test_backup_de_biblioteca_vacia_o_inexistente_no_hace_nada(tmp_path):
    """Rompe: crear una carpeta de respaldo vacia."""
    d = tmp_path / "calib" / "templates"
    assert L.backup(d) is None
    d.mkdir(parents=True)
    assert L.backup(d) is None
    assert not L.backups_root(d).exists()


def test_backup_en_el_mismo_segundo_agrega_sufijo_2_a_10(tpl, monkeypatch):
    """Rompe: pisar el respaldo existente o arrancar el sufijo en otro numero."""
    reloj(monkeypatch, [T0])
    destinos = [L.backup(tpl, keep=0) for _ in range(10)]
    assert [d.name for d in destinos] == ["20260101_120000"] + [f"20260101_120000_{k}" for k in range(2, 11)]
    assert len(set(destinos)) == 10 and all(d.is_dir() for d in destinos)
    assert L.list_backups(tpl) == [d.name for d in destinos]  # _10 va despues de _2


def test_backup_no_pisa_los_archivos_de_un_respaldo_anterior(tpl, monkeypatch):
    """Rompe: reusar la carpeta del segundo anterior (copiar encima)."""
    reloj(monkeypatch, [T0])
    primero = L.backup(tpl, keep=0)
    (tpl / "1_0.png").unlink()
    L.backup(tpl, keep=0)
    assert (primero / "1_0.png").exists()


def test_backup_conserva_los_ultimos_5(tpl, monkeypatch):
    """Rompe: ``KEEP_BACKUPS`` distinto de 5 o podar los mas nuevos."""
    assert L.KEEP_BACKUPS == 5
    reloj(monkeypatch, [T0 + timedelta(seconds=i) for i in range(8)])
    for _ in range(8):
        L.backup(tpl)
    assert L.list_backups(tpl) == [(T0 + timedelta(seconds=i)).strftime("%Y%m%d_%H%M%S") for i in range(3, 8)]


def test_la_poda_respeta_el_orden_natural_del_mismo_segundo(tpl, monkeypatch):
    """Rompe: ordenar los respaldos como texto (``_10`` quedaria antes de ``_2`` y la poda borraria el nuevo)."""
    root = L.backups_root(tpl)
    for nombre in ["20260101_120000"] + [f"20260101_120000_{k}" for k in range(2, 10)]:
        (root / nombre).mkdir(parents=True)
    reloj(monkeypatch, [T0])
    nuevo = L.backup(tpl)
    assert nuevo.name == "20260101_120000_10"
    assert L.list_backups(tpl) == [f"20260101_120000_{k}" for k in range(6, 11)]


def test_respaldos_repetidos_en_el_mismo_segundo_conservan_siempre_el_mas_nuevo(tpl, monkeypatch):
    """Caso minimo del bug: 7 ``backup`` en el mismo segundo con ``keep=5``.

    La poda borra el nombre base (``20260101_120000``); el 7mo respaldo lo vuelve a usar,
    ordena como el mas viejo (k=1) y se poda al nacer: el estado mas reciente se pierde.
    """
    reloj(monkeypatch, [T0])
    ultimo = None
    for _ in range(7):
        ultimo = L.backup(tpl)
    assert ultimo.exists() and ultimo.name in L.list_backups(tpl)


def test_la_poda_no_toca_carpetas_con_nombre_a_mano(tpl, monkeypatch):
    """Rompe: podar todo lo que haya en ``.backups`` (solo se podan los nombres de fecha)."""
    manual = L.backups_root(tpl) / "antes_de_probar"
    manual.mkdir(parents=True)
    (manual / "x.png").write_bytes(b"x")
    reloj(monkeypatch, [T0 + timedelta(seconds=i) for i in range(7)])
    for _ in range(7):
        L.backup(tpl)
    assert manual.is_dir() and len(L.list_backups(tpl)) == 5
    assert "antes_de_probar" not in L.list_backups(tpl)


def test_backup_con_keep_cero_no_poda(tpl, monkeypatch):
    """Rompe: tratar ``keep=0`` como conservar cero (``restore_backup`` lo usa para no perder el respaldo a restaurar)."""
    reloj(monkeypatch, [T0 + timedelta(seconds=i) for i in range(7)])
    for _ in range(7):
        L.backup(tpl, keep=0)
    assert len(L.list_backups(tpl)) == 7


def test_restore_backup_funciona_con_respaldos_del_mismo_segundo(tpl, monkeypatch):
    """Rompe: que la restauracion tome el respaldo equivocado entre varios del mismo segundo."""
    reloj(monkeypatch, [T0])
    L.backup(tpl, keep=0)                 # 20260101_120000
    (tpl / "2_0.png").unlink()
    L.backup(tpl, keep=0)                 # _2: sin la '2'
    assert L.restore_backup(tpl, "20260101_120000") == "20260101_120000"
    assert (tpl / "2_0.png").exists()


# ==========================================================================
# delete / relabel con el parametro backup
# ==========================================================================
def test_delete_respalda_por_defecto(tpl):
    """Rompe: que el valor por defecto de ``backup`` sea ``False`` (el CLI quedaria sin red de seguridad)."""
    L.delete([tpl / "1_0.png"])
    (nombre,) = L.list_backups(tpl)
    assert (L.backups_root(tpl) / nombre / "1_0.png").exists() and not (tpl / "1_0.png").exists()


def test_delete_con_respaldar_false_no_respalda_pero_borra_y_se_puede_deshacer(tpl):
    """Rompe: ignorar ``backup=False`` (la UI rotaria los 5 respaldos con cada borrado)."""
    trash = L.delete([tpl / "1_0.png", tpl / "2_0.png"], backup=False)
    assert L.list_backups(tpl) == [] and not L.backups_root(tpl).exists()
    assert not (tpl / "1_0.png").exists() and not (tpl / "2_0.png").exists()
    assert L.restore(trash) == 2 and (tpl / "1_0.png").exists()


def test_delete_de_nada_no_respalda(tpl):
    """Rompe: respaldar con la lista vacia (``paths[0]`` fallaria)."""
    assert L.delete([]) == [] and L.list_backups(tpl) == []


def test_delete_de_un_archivo_inexistente_no_rompe(tpl):
    """Rompe: ``delete`` que lance con un archivo que ya no esta."""
    L.delete([tpl / "no_esta_0.png"], backup=False)
    assert len(list(tpl.glob("*.png"))) == 4


def test_relabel_respalda_por_defecto_y_no_con_respaldar_false(tpl):
    """Rompe: ignorar ``backup`` en ``relabel``."""
    L.relabel(tpl / "1_0.png", "7", tpl, backup=False)
    assert L.list_backups(tpl) == []
    L.relabel(tpl / "1_1.png", "8", tpl)
    assert len(L.list_backups(tpl)) == 1


def test_relabel_renombra_al_proximo_indice_libre(tpl):
    """Rompe: reusar un indice existente (pisaria una plantilla)."""
    dest = L.relabel(tpl / "1_0.png", "2", tpl, backup=False)
    assert dest.name == "2_1.png" and dest.exists() and not (tpl / "1_0.png").exists()
    assert (tpl / "2_0.png").exists()


def test_relabel_con_etiqueta_invalida_falla_sin_respaldar_ni_mover(tpl):
    """Rompe: respaldar o mover antes de validar la etiqueta."""
    antes = sorted(p.name for p in tpl.glob("*.png"))
    with pytest.raises(ValueError, match="etiqueta invalida"):
        L.relabel(tpl / "1_0.png", "x", tpl)
    assert sorted(p.name for p in tpl.glob("*.png")) == antes and L.list_backups(tpl) == []


def test_varios_borrados_sin_respaldar_no_rotan_los_respaldos_existentes(tpl, monkeypatch):
    """Rompe: que ``backup=False`` se ignore (se perderia el estado previo a la sesion de UI)."""
    reloj(monkeypatch, [T0])
    previo = L.backup(tpl)
    for p in sorted(tpl.glob("*.png")):
        L.delete([p], backup=False)
    assert L.list_backups(tpl) == [previo.name] and len(list(previo.glob("*.png"))) == 4


def test_delete_y_relabel_llaman_a_backup_del_modulo(tpl, monkeypatch):
    """Rompe: que ``delete``/``relabel`` no usen ``backup`` (el parametro ``backup`` lo tapa)."""
    llamadas = []
    monkeypatch.setattr(L, "backup", lambda d, *a, **k: llamadas.append(d))
    L.delete([tpl / "1_0.png"])
    L.relabel(tpl / "1_1.png", "5", tpl)
    L.delete([tpl / "2_0.png"], backup=False)
    assert llamadas == [tpl, tpl]


# ==========================================================================
# tope por defecto y respaldo de write
# ==========================================================================
def test_el_tope_por_defecto_por_caracter_es_3():
    """Rompe: cambiar ``DEFAULT_MAX_PER_LABEL`` (decision de diseno: 3 variantes por caracter)."""
    from spectro.config import DEFAULT_MAX_PER_LABEL

    assert DEFAULT_MAX_PER_LABEL == 3


def _pool(n):
    from spectro.teach import Glyph

    rng = np.random.default_rng(0)
    return [Glyph("5", rng.integers(0, 255, (8, 6), dtype=np.uint8), f"s{i}") for i in range(n)]


def test_write_y_dedup_usan_el_tope_por_defecto(tmp_path):
    """Rompe: que ``write``/``dedup`` ignoren el tope por defecto (se escribirian las 6 variantes)."""
    pool = _pool(6)
    assert len(L.dedup(pool)) == 3
    d = tmp_path / "calib" / "templates"
    assert L.write(pool, d, "replace") == {"5": 3} and len(list(d.glob("*.png"))) == 3


def test_write_replace_respalda_la_biblioteca_previa_y_merge_no(tpl):
    """Rompe: que ``replace`` no respalde (se perderia la biblioteca) o que ``merge`` respalde (ruido)."""
    L.write(_pool(2), tpl, "merge")
    assert L.list_backups(tpl) == []
    L.write(_pool(2), tpl, "replace")
    (nombre,) = L.list_backups(tpl)
    assert (L.backups_root(tpl) / nombre / "2_0.png").exists() and not (tpl / "2_0.png").exists()


def test_write_con_modo_invalido_falla_sin_tocar_nada(tpl):
    """Rompe: validar el modo despues de respaldar o borrar."""
    antes = sorted(p.name for p in tpl.glob("*.png"))
    with pytest.raises(ValueError, match="mode"):
        L.write(_pool(1), tpl, "otro")
    assert sorted(p.name for p in tpl.glob("*.png")) == antes and L.list_backups(tpl) == []
