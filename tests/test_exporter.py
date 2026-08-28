import types
from pathlib import Path

import pytest

import asistente.exporter as exporter

# ---------- validación de entrada ----------


def test_formato_invalido_lanza_valueerror():
    with pytest.raises(ValueError):
        exporter.exportar(Path("x.md"), "xlsx")


# ---------- pandoc ausente / falla / éxito ----------


def test_sin_pandoc_lanza_runtimeerror(md_doc, monkeypatch):
    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: False)
    with pytest.raises(RuntimeError, match="no está instalado"):
        exporter.exportar(md_doc, "docx")


def test_exportar_invoca_pandoc_y_devuelve_salida(md_doc, monkeypatch):
    llamados = {}

    def fake_run(cmd, **kwargs):
        llamados["cmd"] = cmd
        Path(cmd[3]).write_bytes(b"docx-falso")
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: True)
    monkeypatch.setattr(exporter.subprocess, "run", fake_run)
    salida = exporter.exportar(md_doc, "docx")

    assert llamados["cmd"] == ["pandoc", str(md_doc), "-o", str(salida)]
    assert salida == md_doc.with_suffix(".docx")
    assert salida.exists()


def test_pdf_usa_xelatex_y_limpia_el_temporal(md_doc, monkeypatch):
    capturado = {}

    def fake_run(cmd, **kwargs):
        capturado["cmd"] = cmd
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"%PDF")
        return types.SimpleNamespace(returncode=0, stderr="")

    md_doc.write_text("# Título 📚\n\ncon emoji ⚠️ y matemática ≤ ≈ ∈\n", encoding="utf-8")
    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: True)
    monkeypatch.setattr(exporter.subprocess, "run", fake_run)

    salida = exporter.exportar(md_doc, "pdf")

    cmd = capturado["cmd"]
    assert "--pdf-engine=xelatex" in cmd
    fuente = Path(cmd[cmd.index("-o") - 1])
    assert not fuente.exists()
    assert salida == md_doc.with_suffix(".pdf")


def test_sin_emojis_conserva_matematica(md_doc):
    md_doc.write_text("# T 📚\n\n⚠️ si a ≤ b y x ≈ y entonces x ∈ A\n", encoding="utf-8")
    temporal = exporter._sin_emojis(md_doc)
    try:
        texto = temporal.read_text(encoding="utf-8")
        assert "≤" in texto and "≈" in texto and "∈" in texto
        assert "📚" not in texto and "⚠️" not in texto
    finally:
        temporal.unlink(missing_ok=True)


def test_error_de_pandoc_expone_ultima_linea(md_doc, monkeypatch):
    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=2, stderr="aviso\nerror final de LaTeX")

    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: True)
    monkeypatch.setattr(exporter.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="error final de LaTeX"):
        exporter.exportar(md_doc, "pdf")


def test_timeout_de_pandoc_se_convierte_en_runtimeerror(md_doc, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise exporter.subprocess.TimeoutExpired(cmd=cmd, timeout=120)

    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: True)
    monkeypatch.setattr(exporter.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="tardó demasiado"):
        exporter.exportar(md_doc, "pdf")


# ---------- resolución del documento objetivo ----------


def test_resolver_sin_termino_devuelve_el_mas_reciente(output_dirs, monkeypatch):
    import asistente.indexer as indexer

    monkeypatch.setattr(indexer, "INDEX_DB", str(output_dirs["out"] / ".." / "s.db"))

    viejo = write_doc("2026", "07-julio", "10_0900_viejo")
    nuevo = write_doc("2026", "08-agosto", "24_1800_nuevo")

    assert exporter.resolver_documento() == nuevo
    assert viejo != nuevo


def test_resolver_con_termino_usa_el_indice(output_dirs, monkeypatch):
    import asistente.exporter as exporter
    import asistente.indexer as indexer

    db = output_dirs["out"].parent / "s.db"
    monkeypatch.setattr(indexer, "INDEX_DB", str(db))
    monkeypatch.setattr(indexer, "OUTPUT_DIR", output_dirs["out"])
    monkeypatch.setattr(exporter, "OUTPUT_DIR", output_dirs["out"])

    write_doc("2026", "08-agosto", "24_1800_otro", contenido="# Otro\n\nnada útil.\n")
    objetivo = write_doc(
        "2026", "08-agosto", "23_1000_derivadas", contenido="# Derivadas\n\ncálculo diferencial.\n"
    )

    assert exporter.resolver_documento("derivadas") == objetivo
    assert exporter.resolver_documento("inexistente-xyz") is None


def test_resolver_biblioteca_vacia(output_dirs):
    assert exporter.resolver_documento() is None


# ---------- helpers ----------


@pytest.fixture
def md_doc(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Título\n\ncontenido\n", encoding="utf-8")
    return doc


def write_doc(
    anio: str, mes: str, nombre: str, contenido: str = "# X\nhola\n", materia: str = "General"
) -> Path:
    from asistente.writer import OUTPUT_DIR

    carpeta = OUTPUT_DIR / materia / anio / mes
    carpeta.mkdir(parents=True, exist_ok=True)
    doc = carpeta / f"{nombre}.md"
    doc.write_text(contenido, encoding="utf-8")
    return doc
