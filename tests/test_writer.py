import re
from datetime import datetime

from asistente.writer import (
    _doc_title,
    _docs_in,
    _hora,
    _sources_section,
    list_months,
    month_dir,
    month_label,
    update_index,
    write_document,
)

RESULTADOS = {
    "tema 1": [
        {"title": "Fuente A", "url": "https://a.com", "snippet": "s1"},
        {"title": "Fuente B", "url": "https://b.com", "snippet": "s2"},
        {"title": "Duplicada", "url": "https://a.com", "snippet": "s3"},
    ],
}


def test_month_dir_formato():
    d = month_dir(datetime(2026, 8, 23))
    assert d.parent.name == "2026"
    assert d.name == "08-agosto"


def test_month_label():
    ruta = month_dir(datetime(2026, 8, 23))
    assert month_label(ruta) == "Agosto 2026"


def test_write_document_estructura_completa(output_dirs):
    path = write_document("Diagrama de Pareto", ["tema 1"], ["contenido"], RESULTADOS)

    assert path.parent == output_dirs["out"] / "2026" / "08-agosto"
    assert re.match(r"\d{2}_\d{2}-\d{2}_diagrama-de-pareto\.md", path.name)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "tags: [universidad, investigacion]" in text
    assert "# Diagrama de Pareto" in text
    assert "## 1. tema 1" in text
    assert "[Fuente A](https://a.com)" in text
    assert "[Duplicada](https://a.com)" not in text


def test_write_document_duplicado_sufijo_incremental(output_dirs):
    primera = write_document("Tema X", ["t"], ["s"], {})
    segunda = write_document("Tema X", ["t"], ["s"], {})
    assert primera != segunda
    assert "-2.md" in segunda.name


def test_indice_se_genera_con_dataview_y_wikilinks(output_dirs):
    path = write_document("Índices de BD", ["tema 1"], ["contenido"], RESULTADOS)
    indice = path.parent / "00_Índice.md"
    contenido = indice.read_text(encoding="utf-8")

    assert "```dataview" in contenido
    assert f"[[{path.stem}|" in contenido
    assert "Agosto 2026" in contenido


def test_indice_autosanable_al_borrar_documento(output_dirs):
    a = write_document("Doc A", ["t"], ["s"], {})
    b = write_document("Doc B", ["t"], ["s"], {})
    a.unlink()

    update_index(b.parent)
    contenido = (b.parent / "00_Índice.md").read_text(encoding="utf-8")

    assert a.stem not in contenido
    assert b.stem in contenido


def test_list_months_ordena_descendente(output_dirs):
    out = output_dirs["out"]
    write_document("Doc Viejo", ["t"], ["s"], {})
    viejo = next(iter((out / "2026" / "08-agosto").glob("*doc-viejo*")))

    mes_anterior = out / "2025" / "12-diciembre"
    mes_anterior.mkdir(parents=True)
    (mes_anterior / "01_10-00_doc.md").write_text("# Doc Antiguo\n")

    meses = list_months()
    assert len(meses) == 2
    assert meses[0][0] == viejo.parent
    assert _docs_in(meses[0][0])


def test_sources_section_sin_fuentes_devuelve_vacio():
    assert _sources_section({}) == []
    assert _sources_section({"t": [{"title": "", "url": "", "snippet": ""}]}) == []


def test_sources_section_deduplica_urls():
    lineas = _sources_section(RESULTADOS)
    urls = [x for x in lineas if x.startswith(("1.", "2."))]
    assert len(urls) == 2


def test_update_index_mes_vacio(output_dirs):
    vacio = output_dirs["out"] / "2026" / "01-enero"
    vacio.mkdir(parents=True)
    indice = update_index(vacio)
    assert "Aún no hay documentos" in indice.read_text(encoding="utf-8")


def test_doc_title_y_hora_desde_frontmatter(tmp_path):
    f = tmp_path / "y.md"
    f.write_text("---\nhora: 09-30\n---\n# Mi Título\n", encoding="utf-8")
    assert _doc_title(f) == "Mi Título"
    assert _hora(f) == "09:30"


def test_doc_title_y_hora_con_fallbacks(tmp_path):
    f = tmp_path / "sin-nada.md"
    f.write_text("texto sin encabezado ni frontmatter", encoding="utf-8")
    assert _doc_title(f) == "sin-nada"
    assert _hora(f) == ""
