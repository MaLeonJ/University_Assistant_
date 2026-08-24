import hashlib

import pytest

from asistente.syncer import _igual, _md5, sync_documents, sync_text


@pytest.fixture
def biblioteca(output_dirs):
    origen = output_dirs["out"] / "2026" / "08-agosto"
    destino = output_dirs["vault"] / "2026" / "08-agosto"
    origen.mkdir(parents=True)
    (origen / "a.md").write_text("contenido A", encoding="utf-8")
    return {"origen": origen, "destino": destino}


def test_sync_inicial_copia_todo(biblioteca):
    resultado = sync_documents()
    assert resultado == {"nuevos": 1, "actualizados": 0, "total": 1}
    assert (biblioteca["destino"] / "a.md").read_text() == "contenido A"


def test_sync_sin_cambios_no_hace_nada(biblioteca):
    sync_documents()
    assert sync_documents() == {"nuevos": 0, "actualizados": 0, "total": 1}


def test_sync_detecta_contenido_modificado(biblioteca):
    sync_documents()
    (biblioteca["origen"] / "a.md").write_text("contenido A modificado", encoding="utf-8")
    assert sync_documents() == {"nuevos": 0, "actualizados": 1, "total": 1}
    assert (biblioteca["destino"] / "a.md").read_text() == "contenido A modificado"


def test_sync_nunca_borra_del_vault(biblioteca):
    sync_documents()
    (biblioteca["origen"] / "a.md").unlink()
    assert sync_documents()["total"] == 0
    assert (biblioteca["destino"] / "a.md").exists()


def test_sync_sin_directorio_origen(output_dirs):
    assert sync_documents() == {"nuevos": 0, "actualizados": 0, "total": 0}


def test_sync_text_reporte():
    texto = sync_text({"nuevos": 2, "actualizados": 1, "total": 3})
    assert "2" in texto and "1" in texto and "3" in texto


def test_sync_text_biblioteca_vacia(output_dirs):
    assert "No hay documentos" in sync_text({"nuevos": 0, "actualizados": 0, "total": 0})


def test_igual_compara_por_tamano_y_md5(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(b"datos")
    b.write_bytes(b"datos")
    assert _igual(a, b)

    b.write_bytes(b"otro")
    assert not _igual(a, b)

    c = tmp_path / "c.txt"
    c.write_bytes(b"x")
    assert not _igual(a, c)


def test_igual_con_destino_inexistente(tmp_path):
    a = tmp_path / "a.txt"
    a.write_bytes(b"datos")
    assert not _igual(a, tmp_path / "no-existe.txt")


def test_md5_conocido(tmp_path):
    f = tmp_path / "f.txt"
    f.write_bytes(b"hola")
    assert _md5(f) == hashlib.md5(b"hola").hexdigest()
