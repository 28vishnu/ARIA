"""Security-focused tests for ARIA request logging and background task cleanup."""
import asyncio
import logging

import main


def test_telegram_bot_token_is_redacted_from_api_urls():
    token = "123456:ABC-secret-token"
    value = f"request failed https://api.telegram.org/bot{token}/sendMessage?chat_id=1"
    sanitized = main._sanitize_log_text(value)
    assert token not in sanitized
    assert "[REDACTED]" in sanitized
    assert "/sendMessage" in sanitized


def test_sensitive_log_filter_removes_token_from_rendered_record():
    token = "123456:ABC-secret-token"
    record = logging.LogRecord(
        name="aria", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="failed URL https://api.telegram.org/bot%s/getMe", args=(token,),
        exc_info=None,
    )
    assert main.SensitiveLogFilter().filter(record) is True
    rendered = record.getMessage()
    assert token not in rendered
    assert "[REDACTED]" in rendered


def test_background_task_manager_removes_completed_task():
    async def run_test():
        manager = main.BackgroundTaskManager()

        async def work():
            return "ok"

        task = manager.schedule(work())
        assert await task == "ok"
        await asyncio.sleep(0)
        assert task not in manager.tasks
        await manager.shutdown()

    asyncio.run(run_test())
