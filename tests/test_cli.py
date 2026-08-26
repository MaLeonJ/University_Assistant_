import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import asistente.cli as cli
import asistente.indexer as indexer

runner = CliRunner()


@pytest.fixture(autouse=True)
def aislado(tmp_path, monkeypatch):
    """Redirige índice, cache y contador a temporales."""
    import asistente.cache as cache_mod
    import asistente.usage as usage

    db = tmp_path / "data" / "search.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(indexer, "INDEX_DB", str(db))
    monkeypatch.setattr(cache_mod, "CACHE_DB", str(db.parent / "cache.db"))
    usage_path = db.parent / "usage.json"
    monkeypatch.setattr(usage, "USAGE_FILE", usage_path)
    return tmp_path


@pytest.fixture
def biblioteca(output_dirs):
    origen = output_dirs["out"] / "2026" / "08-agosto"
    origen.mkdir(parents=True, exist_ok=True)
    (origen / "24_1000_derivadas.md").write_text(
        "# Derivadas\n\ncálculo diferencial aplicado.\n", encoding="utf-8"
    )
    return output_dirs["out"]


# ---------- investigar ----------


def test_investigar_sin_config_sale_con_error(monkeypatch):

    monkeypatch.setattr(cli, "validate", lambda: ["Falta TELEGRAM_TOKEN"])
    resultado = runner.invoke(cli.app, ["investigar", "tema x"])
    assert resultado.exit_code == 1
    assert "Configuración incompleta" in resultado.output


def test_investigar_termino_invalido(monkeypatch):
    monkeypatch.setattr(cli, "validate", lambda: [])
    resultado = runner.invoke(cli.app, ["investigar", ""])
    assert resultado.exit_code == 1
    assert "No pude interpretar" in resultado.output


def test_investigar_genera_documento(monkeypatch):
    monkeypatch.setattr(cli, "validate", lambda: [])

    async def fake_pipeline(topics, max_results=None):
        return [f"sección-{t}" for t in topics], {t: [] for t in topics}

    monkeypatch.setattr(cli, "research_topics", fake_pipeline)

    resultado = runner.invoke(cli.app, ["investigar", "corte 1: bases de datos, modelo e-r"])

    assert resultado.exit_code == 0, resultado.output
    assert "✅" in resultado.output
    assert "2 tema(s)" in resultado.output


def test_investigar_auto_sync_drive_exitoso(monkeypatch):
    import asistente.drive as drive

    sincronizado = []
    monkeypatch.setattr(cli, "validate", lambda: [])
    monkeypatch.setattr(drive, "estado", lambda: None)
    monkeypatch.setattr(drive, "sync_drive", lambda: sincronizado.append(True))

    async def fake_pipeline(topics, max_results=None):
        return [f"sección-{t}" for t in topics], {t: [] for t in topics}

    monkeypatch.setattr(cli, "research_topics", fake_pipeline)

    resultado = runner.invoke(cli.app, ["investigar", "corte 1: bases de datos"])

    assert resultado.exit_code == 0, resultado.output
    assert sincronizado == [True]
    assert "Sincronizado a Google Drive" in resultado.output


# ---------- buscar ----------


def test_buscar_encuentra(biblioteca, monkeypatch):
    monkeypatch.setattr(indexer, "OUTPUT_DIR", biblioteca)
    resultado = runner.invoke(cli.app, ["buscar", "derivadas"])

    assert resultado.exit_code == 0
    assert "Derivadas" in resultado.output


def test_buscar_sin_resultados(biblioteca, monkeypatch):
    monkeypatch.setattr(indexer, "OUTPUT_DIR", biblioteca)
    resultado = runner.invoke(cli.app, ["buscar", "zzz-nada"])
    assert resultado.exit_code == 1
    assert "Sin resultados" in resultado.output


# ---------- exportar ----------


def test_exportar_formato_invalido():
    resultado = runner.invoke(cli.app, ["exportar", "xlsx"])
    assert resultado.exit_code == 1
    assert "Formato inválido" in resultado.output


def test_exportar_llama_pandoc(biblioteca, monkeypatch):
    import asistente.exporter as exporter

    monkeypatch.setattr(exporter, "OUTPUT_DIR", biblioteca)
    monkeypatch.setattr(indexer, "OUTPUT_DIR", biblioteca)
    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: True)
    llamados = {}

    def fake_run(cmd, **kwargs):
        llamados["cmd"] = cmd
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"data")
        from types import SimpleNamespace

        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(exporter.subprocess, "run", fake_run)
    resultado = runner.invoke(cli.app, ["exportar", "docx", "derivadas"])

    assert resultado.exit_code == 0, resultado.output
    assert llamados["cmd"][0] == "pandoc"


def test_exportar_sin_pandoc_muestra_error_de_proveedor(biblioteca, monkeypatch):
    import asistente.exporter as exporter

    monkeypatch.setattr(exporter, "OUTPUT_DIR", biblioteca)
    monkeypatch.setattr(indexer, "OUTPUT_DIR", biblioteca)
    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: False)
    resultado = runner.invoke(cli.app, ["exportar", "pdf"])
    assert resultado.exit_code == 1
    assert "no está instalado" in resultado.output


# ---------- uso / stats ----------


def test_uso_salida_plana(aislado, monkeypatch):
    import asistente.usage as usage

    hoy = usage._hoy()
    usage.USAGE_FILE.write_text(json.dumps({"days": {hoy: 3}}))
    resultado = runner.invoke(cli.app, ["uso"])
    assert resultado.exit_code == 0
    assert "*" not in resultado.output
    assert "Usadas hoy: 3" in resultado.output


def test_stats_resumen(biblioteca, monkeypatch):

    resultado = runner.invoke(cli.app, ["stats"])
    assert resultado.exit_code == 0
    assert "1 documento(s)" in resultado.output
    assert "Cache:" in resultado.output


def test_plano_quita_marcado():
    assert cli._plano("**negrita** y `codigo`") == "negrita y codigo"


# ---------- drive-auth ----------


def test_drive_auth_sin_credentials_falla(monkeypatch, tmp_path):
    import asistente.drive as drive

    monkeypatch.setattr(drive, "GDRIVE_CREDENTIALS_FILE", tmp_path / "no-existe.json")
    resultado = runner.invoke(cli.app, ["drive-auth"])
    assert resultado.exit_code == 1
    assert "credentials.json" in resultado.output


def test_drive_auth_exitoso_guarda_token(monkeypatch, tmp_path):
    import asistente.drive as drive

    cred = tmp_path / "credentials.json"
    cred.write_text("{}")
    token = tmp_path / "data" / "token.json"
    monkeypatch.setattr(drive, "GDRIVE_CREDENTIALS_FILE", cred)
    monkeypatch.setattr(drive, "GDRIVE_TOKEN_FILE", token)

    class FakeCreds:
        def to_json(self):
            return "{}"

    class FakeFlow:
        def __init__(self, *a, **k):
            pass

        @classmethod
        def from_client_secrets_file(cls, *a, **k):
            return cls()

        def run_local_server(self, port=0, prompt=None):
            return FakeCreds()

    fake_mod = types.SimpleNamespace(InstalledAppFlow=FakeFlow)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", fake_mod)
    monkeypatch.setitem(
        sys.modules,
        "google_auth_oauthlib",
        types.SimpleNamespace(flow=fake_mod),
    )

    resultado = runner.invoke(cli.app, ["drive-auth"])
    assert resultado.exit_code == 0, resultado.output
    assert "Token guardado" in resultado.output
    assert token.read_text() == "{}"
