import pytest

import asistente.indexer as indexer


@pytest.fixture
def biblioteca(tmp_path, monkeypatch):
    docs = tmp_path / "documentos" / "2026" / "08-agosto"
    docs.mkdir(parents=True)
    (docs / "01_1200_ecuaciones.md").write_text(
        "---\ntags: [x]\n---\n# Ecuaciones Diferenciales\n\n"
        "Una ecuación diferencial relaciona una función con sus derivadas.\n",
        encoding="utf-8",
    )
    (docs / "02_1500_logica.md").write_text(
        "# Lógica Proposicional\n\nLos conectivos lógicos unen proposiciones.\n",
        encoding="utf-8",
    )
    (docs / "00_Índice.md").write_text("# Índice\n", encoding="utf-8")
    db = tmp_path / "data" / "search.db"
    db.parent.mkdir(exist_ok=True)
    monkeypatch.setattr(indexer, "OUTPUT_DIR", tmp_path / "documentos")
    monkeypatch.setattr(indexer, "INDEX_DB", str(db))
    return docs


def test_sync_inicial_cuenta_altas_e_ignora_indices(biblioteca):
    altas, actualizadas, bajas = indexer.sync_index()
    assert (altas, actualizadas, bajas) == (2, 0, 0)


def test_sync_idempotente(biblioteca):
    indexer.sync_index()
    assert indexer.sync_index() == (0, 0, 0)


def test_sync_detecta_actualizacion_y_baja(biblioteca):
    indexer.sync_index()

    objetivo = biblioteca / "01_1200_ecuaciones.md"
    objetivo.write_text("# Ecuaciones Diferenciales v2\n\nContenido nuevo.\n", encoding="utf-8")
    assert indexer.sync_index() == (0, 1, 0)

    objetivo.unlink()
    assert indexer.sync_index() == (0, 0, 1)

    resultados = indexer.search("derivadas")
    assert resultados == []


def test_busqueda_encuentra_y_extrae_titulo_mes(biblioteca):
    indexer.sync_index()
    resultados = indexer.search("ecuaciones diferenciales")
    assert len(resultados) == 1
    r = resultados[0]
    assert r["title"] == "Ecuaciones Diferenciales"
    assert r["month"] == "2026/08-agosto"
    assert "«" in r["snippet"] and "»" in r["snippet"]


def test_busqueda_insensible_a_acentos(biblioteca):
    indexer.sync_index()
    assert indexer.search("ecuacion derivada") != []
    assert indexer.search("logica conectivos") != []


def test_consulta_rara_no_explota(biblioteca):
    indexer.sync_index()
    assert indexer.search('"--* OR (') == []
    assert indexer.search("!!! ???") == []
    assert indexer.search("") == []


def test_limit_funciona(biblioteca):
    indexer.sync_index()
    amplio = biblioteca / "03_1800_comun.md"
    amplio.write_text(
        "# Común\n\nproposiciones con derivadas y ecuación compartida.\n", encoding="utf-8"
    )
    indexer.sync_index()
    assert len(indexer.search("ecuación derivadas", limit=10)) == 2
    assert len(indexer.search("ecuación derivadas", limit=1)) == 1
