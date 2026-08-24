import pytest

from asistente import config


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "tok")
    monkeypatch.setattr(config, "AI_API_KEY", "key")
    monkeypatch.setattr(config, "AUTHORIZED_USER_ID", 1)
    monkeypatch.setattr(config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(config, "AI_MODEL", config.DEFAULT_MODELS["gemini"])


def test_configuracion_completa_no_reporta_errores():
    assert config.validate() == []


def test_falta_token_y_clave(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", None)
    monkeypatch.setattr(config, "AI_API_KEY", None)
    errores = config.validate()
    assert any("TELEGRAM_TOKEN" in e for e in errores)
    assert any("AI_API_KEY" in e for e in errores)


def test_falta_id_de_usuario(monkeypatch):
    monkeypatch.setattr(config, "AUTHORIZED_USER_ID", 0)
    errores = config.validate()
    assert any("AUTHORIZED_USER_ID" in e for e in errores)


def test_proveedor_invalido_se_rechaza(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "claude")
    errores = config.validate()
    assert any("no válido" in e for e in errores)
    assert any("gemini" in e and "openrouter" in e for e in errores)


def test_proveedor_sin_modelo_definido(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "AI_MODEL", "")
    errores = config.validate()
    assert any("Sin modelo" in e for e in errores)


def test_cada_proveedor_tiene_modelo_por_defecto():
    for proveedor in config.VALID_PROVIDERS:
        assert config.DEFAULT_MODELS.get(proveedor)
