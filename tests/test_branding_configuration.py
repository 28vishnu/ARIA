from core.configuration import APP_FULL_NAME, APP_NAME, load_config


def test_product_identity_is_centralized():
    assert APP_NAME == "JARVIS"
    assert APP_FULL_NAME == "JUST A RATHER VERY INTELLIGENT SYSTEM"


def test_jarvis_configuration_takes_precedence_over_legacy_aliases(monkeypatch):
    monkeypatch.setenv("JARVIS_ENVIRONMENT", "staging")
    monkeypatch.setenv("AR_ENVIRONMENT", "legacy")
    monkeypatch.setenv("JARVIS_TIMEOUT", "21")
    monkeypatch.setenv("AR_TIMEOUT", "7")
    monkeypatch.setenv("JARVIS_PERMISSION_MODE", "approval")
    monkeypatch.setenv("AR_PERMISSION_MODE", "autonomous")

    config = load_config()

    assert config.environment == "staging"
    assert config.timeout_seconds == 21
    assert config.permission_mode == "approval"


def test_legacy_configuration_remains_a_fallback(monkeypatch):
    monkeypatch.delenv("JARVIS_ENVIRONMENT", raising=False)
    monkeypatch.delenv("JARVIS_TIMEOUT", raising=False)
    monkeypatch.delenv("JARVIS_PERMISSION_MODE", raising=False)
    monkeypatch.setenv("AR_ENVIRONMENT", "legacy-env")
    monkeypatch.setenv("AR_TIMEOUT", "11")
    monkeypatch.setenv("AR_PERMISSION_MODE", "legacy-mode")

    config = load_config()

    assert config.environment == "legacy-env"
    assert config.timeout_seconds == 11
    assert config.permission_mode == "legacy-mode"
