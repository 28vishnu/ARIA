"""Read-only live deployment smoke check for ARIA.

Checks the configured public /health endpoint and Telegram getWebhookInfo.
It never changes the webhook, sends a message, prints the bot token, or writes
application/database state. Requires httpx (already listed in requirements.txt).
"""
from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def _base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Public service URL must be an absolute HTTPS URL.")
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not allowed in the public service URL.")
    return value


def assess_health(status_code: int, payload: Any) -> Result:
    if status_code != 200:
        return Result("Public health endpoint", "FAIL", f"HTTP status {status_code}; expected 200.")
    if not isinstance(payload, Mapping):
        return Result("Public health endpoint", "FAIL", "Response was not a JSON object.")
    status = str(payload.get("status", "")).lower()
    if status not in {"healthy", "ok", "ready"}:
        return Result("Public health endpoint", "WARN", "Endpoint responded, but its status is not explicitly healthy/ready.")
    return Result("Public health endpoint", "PASS", "HTTPS endpoint returned HTTP 200 and a healthy status.")


def assess_webhook(payload: Any, expected_url: str) -> list[Result]:
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        return [Result("Telegram webhook API", "FAIL", "Telegram getWebhookInfo did not return ok=true.")]
    info = payload.get("result")
    if not isinstance(info, Mapping):
        return [Result("Telegram webhook API", "FAIL", "Telegram response has no valid result object.")]
    actual_url = str(info.get("url", ""))
    if actual_url.rstrip("/") == expected_url.rstrip("/"):
        url_result = Result("Telegram webhook URL", "PASS", "Configured webhook matches the expected endpoint.")
    elif actual_url:
        url_result = Result("Telegram webhook URL", "FAIL", "A webhook is configured, but it does not match the expected endpoint.")
    else:
        url_result = Result("Telegram webhook URL", "FAIL", "No Telegram webhook URL is configured.")
    pending = info.get("pending_update_count", 0)
    if isinstance(pending, int) and pending > 0:
        queue_result = Result("Telegram pending updates", "WARN", f"Telegram reports {pending} pending update(s).")
    elif isinstance(pending, int) and pending == 0:
        queue_result = Result("Telegram pending updates", "PASS", "No pending updates are reported.")
    else:
        queue_result = Result("Telegram pending updates", "WARN", "Pending update count is unavailable or invalid.")
    last_error = info.get("last_error_message")
    if last_error:
        error_result = Result("Telegram last webhook error", "WARN", "Telegram reports a recent webhook error; inspect Bot API details privately.")
    else:
        error_result = Result("Telegram last webhook error", "PASS", "No last webhook error is reported.")
    return [Result("Telegram webhook API", "PASS", "Telegram getWebhookInfo succeeded."), url_result, queue_result, error_result]


async def run_checks(base_url: str, token: str, timeout: float = 10.0,
                     client: Optional[httpx.AsyncClient] = None) -> list[Result]:
    base_url = _base_url(base_url)
    if not token.strip():
        raise ValueError("Telegram bot token is required via TELEGRAM_BOT_TOKEN.")
    if timeout <= 0:
        raise ValueError("Timeout must be positive.")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    results: list[Result] = []
    try:
        try:
            response = await client.get(f"{base_url}/health")
            try:
                payload = response.json()
            except ValueError:
                payload = None
            results.append(assess_health(response.status_code, payload))
        except httpx.HTTPError:
            results.append(Result("Public health endpoint", "FAIL", "Request failed; check service availability and TLS/network configuration."))
        try:
            # Token is used only in the request URL and is never included in output.
            response = await client.get(f"https://api.telegram.org/bot{token.strip()}/getWebhookInfo")
            try:
                payload = response.json()
            except ValueError:
                payload = None
            results.extend(assess_webhook(payload, f"{base_url}/telegram-webhook"))
        except httpx.HTTPError:
            results.append(Result("Telegram webhook API", "FAIL", "Request failed; verify network access and bot token privately."))
    finally:
        if owns_client:
            await client.aclose()
    return results


def render(results: list[Result]) -> str:
    lines = ["ARIA live deployment smoke check (read-only)", "=" * 43]
    for item in results:
        lines.append(f"[{item.status}] {item.name}: {item.detail}")
    failures = sum(item.status == "FAIL" for item in results)
    warnings = sum(item.status == "WARN" for item in results)
    lines.append(f"\nSummary: {len(results) - failures - warnings} passed, {warnings} warnings, {failures} failures.")
    lines.append("This check does not send a Telegram message, change webhook settings, or verify the full answer pipeline.")
    return "\n".join(lines)


async def _async_main(args: argparse.Namespace) -> int:
    try:
        results = await run_checks(args.url or os.getenv("RENDER_EXTERNAL_URL", ""),
                                   os.getenv("TELEGRAM_BOT_TOKEN", ""), args.timeout)
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 2
    print(render(results))
    if any(result.status == "FAIL" for result in results):
        return 1
    if args.strict and any(result.status == "WARN" for result in results):
        return 2
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Public Render service HTTPS URL; defaults to RENDER_EXTERNAL_URL.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any warning is reported.")
    return asyncio.run(_async_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
