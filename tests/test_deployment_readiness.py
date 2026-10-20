from core.deployment_readiness import audit_environment, render_report


def test_reports_required_settings_without_revealing_secrets():
    env = {
        "TELEGRAM_BOT_TOKEN": "12345:TOP_SECRET_TOKEN",
        "ALLOWED_TELEGRAM_USER_ID": "123456789",
        "PORT": "10000",
        "ARIA_OPEN_KNOWLEDGE_DB": "data/test.sqlite3",
        "GEMINI_API_KEY": "SECRET_GEMINI_KEY",
        "RENDER_EXTERNAL_URL": "https://aria.example.com",
    }
    checks = audit_environment(env)
    report = render_report(checks)
    assert all(check.status == "PASS" for check in checks)
    assert "TOP_SECRET_TOKEN" not in report
    assert "SECRET_GEMINI_KEY" not in report


def test_missing_required_settings_are_failures():
    checks = audit_environment({})
    by_name = {check.name: check for check in checks}
    assert by_name["Telegram bot token"].status == "FAIL"
    assert by_name["Owner allowlist"].status == "FAIL"
    assert by_name["Gemini provider"].status == "WARN"


def test_invalid_port_is_rejected():
    checks = audit_environment({"PORT": "not-a-port"})
    port_check = next(check for check in checks if check.name == "HTTP port")
    assert port_check.status == "FAIL"


def test_blank_database_path_is_rejected():
    checks = audit_environment({"ARIA_OPEN_KNOWLEDGE_DB": "   "})
    db_check = next(check for check in checks if check.name == "Knowledge database path")
    assert db_check.status == "FAIL"
