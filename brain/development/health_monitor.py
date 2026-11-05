from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class HealthCheckResult:
    healthy: bool
    url: str
    status_code: int | None
    response_time_ms: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "url": self.url,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class HealthReport:
    healthy: bool
    checks: tuple[
        HealthCheckResult,
        ...
    ] = field(
        default_factory=tuple
    )
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "attempts": self.attempts,
            "checks": [
                check.to_dict()
                for check in self.checks
            ],
        }


class HealthMonitor:
    """
    Performs post-deployment HTTP health checks.

    This is intentionally independent of Render or any other
    hosting provider.

    A deployment is considered healthy only when all supplied
    endpoints respond successfully.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive."
            )

        if max_response_bytes <= 0:
            raise ValueError(
                "max_response_bytes must be positive."
            )

        self.timeout_seconds = float(
            timeout_seconds
        )
        self.max_response_bytes = int(
            max_response_bytes
        )

    @staticmethod
    def _validate_url(
        url: str,
    ) -> str:

        if not isinstance(
            url,
            str,
        ):
            raise TypeError(
                "URL must be a string."
            )

        value = url.strip()

        parsed = urlparse(
            value
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            raise ValueError(
                "Only HTTP and HTTPS URLs are supported."
            )

        if not parsed.netloc:
            raise ValueError(
                "URL must contain a host."
            )

        return value

    async def check(
        self,
        url: str,
    ) -> HealthCheckResult:

        url = self._validate_url(
            url
        )

        started = time.monotonic()

        try:

            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:

                response = await client.get(
                    url
                )

                # Limit how much response data is retained.
                content = response.content[
                    : self.max_response_bytes
                ]

                del content

            elapsed = (
                time.monotonic()
                - started
            )

            return HealthCheckResult(
                healthy=(
                    200
                    <= response.status_code
                    < 400
                ),
                url=url,
                status_code=response.status_code,
                response_time_ms=(
                    elapsed * 1000
                ),
            )

        except Exception as exc:

            elapsed = (
                time.monotonic()
                - started
            )

            return HealthCheckResult(
                healthy=False,
                url=url,
                status_code=None,
                response_time_ms=(
                    elapsed * 1000
                ),
                error=str(exc),
            )

    async def check_all(
        self,
        urls: list[str] | tuple[str, ...],
    ) -> HealthReport:

        if not urls:
            raise ValueError(
                "At least one health URL is required."
            )

        checks = await asyncio.gather(
            *(
                self.check(url)
                for url in urls
            )
        )

        return HealthReport(
            healthy=all(
                check.healthy
                for check in checks
            ),
            checks=tuple(checks),
            attempts=1,
        )

    async def wait_until_healthy(
        self,
        urls: list[str] | tuple[str, ...],
        *,
        attempts: int = 5,
        delay_seconds: float = 5.0,
    ) -> HealthReport:

        attempts = max(
            1,
            int(attempts),
        )

        if delay_seconds < 0:
            raise ValueError(
                "delay_seconds cannot be negative."
            )

        latest = HealthReport(
            healthy=False,
            attempts=0,
        )

        for attempt in range(
            1,
            attempts + 1,
        ):

            latest = await self.check_all(
                urls
            )

            latest = HealthReport(
                healthy=latest.healthy,
                checks=latest.checks,
                attempts=attempt,
            )

            if latest.healthy:
                return latest

            if attempt < attempts:
                await asyncio.sleep(
                    delay_seconds
                )

        return latest