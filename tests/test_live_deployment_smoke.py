import pytest

from scripts.verify_live_deployment import _base_url, assess_health, assess_webhook, render


def test_base_url_requires_https_and_no_credentials():
    assert _base_url("https://aria.example.com/") == "https://aria.example.com"
    with pytest.raises(ValueError):
        _base_url("http://aria.example.com")
    with pytest.raises(ValueError):
        _base_url("https://user:pass@aria.example.com")


def test_healthy_endpoint_passes_and_unhealthy_warns():
    assert assess_health(200, {"status": "healthy"}).status == "PASS"
    assert assess_health(503, {"status": "healthy"}).status == "FAIL"
    assert assess_health(200, {"status": "starting"}).status == "WARN"


def test_webhook_matches_expected_url_and_checks_queue_and_error():
    results = assess_webhook({"ok": True, "result": {
        "url": "https://aria.example.com/telegram-webhook",
        "pending_update_count": 0,
    }}, "https://aria.example.com/telegram-webhook")
    assert [r.status for r in results] == ["PASS", "PASS", "PASS", "PASS"]


def test_webhook_mismatch_and_recent_error_are_reported_without_error_text():
    results = assess_webhook({"ok": True, "result": {
        "url": "https://wrong.example.com/hook",
        "pending_update_count": 4,
        "last_error_message": "secret or private diagnostic text",
    }}, "https://aria.example.com/telegram-webhook")
    report = render(results)
    assert results[1].status == "FAIL"
    assert results[2].status == "WARN"
    assert results[3].status == "WARN"
    assert "secret or private diagnostic text" not in report


def test_bad_telegram_response_fails():
    results = assess_webhook({"ok": False, "description": "invalid token"}, "https://aria.example.com/telegram-webhook")
    assert len(results) == 1
    assert results[0].status == "FAIL"
