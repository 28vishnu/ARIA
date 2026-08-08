from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from actions.base import BaseAction, ActionResult


class TimeAction(BaseAction):
    """
    Provides the current local time for any IANA time zone.

    Examples:
        Asia/Kolkata
        Europe/London
        America/New_York
        Asia/Tokyo
        Australia/Sydney
    """

    name = "time_action"
    description = (
        "Get the current local time and date for any location "
        "using an IANA time zone."
    )
    permission_level = "safe"
    timeout_seconds = 5.0

    async def validate(self, params):
        if not isinstance(params, dict):
            return False

        timezone = params.get("timezone")

        # No timezone means UTC.
        if timezone is None:
            return True

        if not isinstance(timezone, str):
            return False

        timezone = timezone.strip()

        if not timezone:
            return True

        try:
            ZoneInfo(timezone)
            return True
        except ZoneInfoNotFoundError:
            return False

    async def execute(self, params):
        try:
            timezone_name = "UTC"

            if isinstance(params, dict):
                requested = params.get("timezone")

                if isinstance(requested, str) and requested.strip():
                    timezone_name = requested.strip()

            timezone = ZoneInfo(timezone_name)
            now = datetime.now(timezone)

            return ActionResult(
                success=True,
                action_name=self.name,
                data={
                    "timezone": timezone_name,
                    "datetime": now.isoformat(),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                    "utc_offset": now.strftime("%z"),
                },
            )

        except ZoneInfoNotFoundError:
            return ActionResult(
                success=False,
                action_name=self.name,
                error=f"Unknown time zone: {timezone_name}",
            )

        except Exception as e:
            return ActionResult(
                success=False,
                action_name=self.name,
                error=f"Unable to retrieve time: {e}",
            )