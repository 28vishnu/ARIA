# actions/weather_action.py

import re
import logging
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

import httpx

from actions.base import BaseAction, ActionResult


logger = logging.getLogger("aria")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_FORECAST_URL = (
    "https://api.met.no/weatherapi/locationforecast/2.0/compact"
)

MET_USER_AGENT = (
    "ARIA-AI/1.0 "
    "(https://aria-ai-s5go.onrender.com)"
)


class WeatherAction(BaseAction):
    """
    Global live weather action using Open-Meteo.

    Supports:
    - Worldwide city/location lookup
    - Natural-language weather queries
    - Current temperature
    - Feels-like temperature
    - Humidity
    - Wind
    - Precipitation
    - Weather condition
    - Sunrise / sunset
    - Multi-day forecast
    - Automatic local timezone
    """

    name = "weather_action"

    description = (
        "Get live weather and forecast information for any worldwide "
        "city or location. Supports natural-language weather queries, "
        "temperature, feels-like temperature, humidity, rain, "
        "precipitation, wind, sunrise, sunset and forecasts. "
        "WEATHER DATA RULE: "
        "The weather draft is authoritative structured data. "
        "Never invent weather conditions, temperatures, humidity, "
        "rainfall, or trends for days that are not explicitly present "
        "in the draft. "
        "If multiple forecast days are present, preserve each day. "
        "Do not replace a daily forecast with a vague summary."
    )

    permission_level = "safe"
    timeout_seconds = 10.0

    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    WEATHER_CODES = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }

    async def validate(self, params: Dict[str, Any]) -> bool:
        if not isinstance(params, dict):
            return False

        location = (
            params.get("location")
            or params.get("city")
            or params.get("query")
        )

        if not isinstance(location, str):
            return False

        return bool(location.strip())

    async def execute(self, params: Dict[str, Any]) -> ActionResult:
        try:
            # =====================================================
            # 1. EXTRACT LOCATION
            # =====================================================

            location = (
                params.get("location")
                or params.get("city")
                or params.get("query")
            )

            if not isinstance(location, str) or not location.strip():
                return ActionResult(
                    success=False,
                    action_name=self.name,
                    error="Please provide a location.",
                )

            original_location = location

            location = self._clean_location(location)

            if not location:
                return ActionResult(
                    success=False,
                    action_name=self.name,
                    error="I couldn't determine the weather location.",
                )

            logger.info(
                "[WeatherAction] Location extracted: '%s' -> '%s'",
                original_location,
                location,
            )

            # =====================================================
            # 2. FORECAST DAYS
            # =====================================================

            forecast_days = params.get("forecast_days", 1)
            forecast_target = str(
                params.get("forecast_target", "today")
            ).lower().strip()

            if forecast_target not in ("today", "tomorrow"):
                forecast_target = "today"

            try:
                forecast_days = int(forecast_days)
            except (TypeError, ValueError):
                forecast_days = 1

            forecast_days = max(1, min(forecast_days, 7))

            # =====================================================
            # 3. HTTP CLIENT
            # =====================================================

            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ARIA-WeatherAction/1.0",
                },
            ) as client:

                # =================================================
                # 4. GLOBAL GEOCODING
                # =================================================

                geo_response = await client.get(
                    self.GEOCODING_URL,
                    params={
                        "name": location,
                        "count": 1,
                        "language": "en",
                        "format": "json",
                    },
                )

                # -------------------------------------------------
                # Handle geocoding rate limit separately
                # -------------------------------------------------

                if geo_response.status_code == 429:
                    retry_after = geo_response.headers.get(
                        "Retry-After"
                    )

                    logger.warning(
                        "[WeatherAction] Geocoding API rate-limited. "
                        "Retry-After=%s",
                        retry_after,
                    )

                    return ActionResult(
                        success=False,
                        action_name=self.name,
                        error=(
                            "The weather service is temporarily "
                            "rate-limited while locating the city. "
                            "Please try again shortly."
                        ),
                    )

                geo_response.raise_for_status()

                geo_data = geo_response.json()

                results = geo_data.get("results") or []

                if not results:
                    return ActionResult(
                        success=False,
                        action_name=self.name,
                        error=(
                            f"I couldn't find a location matching "
                            f"'{location}'."
                        ),
                    )

                place = results[0]

                latitude = place.get("latitude")
                longitude = place.get("longitude")

                if latitude is None or longitude is None:
                    return ActionResult(
                        success=False,
                        action_name=self.name,
                        error=(
                            f"I found '{location}', but couldn't "
                            "determine its coordinates."
                        ),
                    )

                city = (
                    place.get("name")
                    or location
                )

                country = place.get("country", "")
                country_code = place.get("country_code", "")
                timezone = place.get("timezone", "auto")

                # =================================================
                # 5. LIVE WEATHER
                # =================================================

                weather_response = await client.get(
                    self.FORECAST_URL,
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": (
                            "temperature_2m,"
                            "relative_humidity_2m,"
                            "apparent_temperature,"
                            "precipitation,"
                            "rain,"
                            "weather_code,"
                            "wind_speed_10m,"
                            "wind_direction_10m,"
                            "surface_pressure"
                        ),
                        "daily": (
                            "weather_code,"
                            "temperature_2m_max,"
                            "temperature_2m_min,"
                            "apparent_temperature_max,"
                            "apparent_temperature_min,"
                            "precipitation_sum,"
                            "rain_sum,"
                            "sunrise,"
                            "sunset"
                        ),
                        "forecast_days": forecast_days,
                        "timezone": "auto",
                        "temperature_unit": "celsius",
                        "wind_speed_unit": "kmh",
                        "precipitation_unit": "mm",
                    },
                )

                # -------------------------------------------------
                # IMPORTANT: HTTP 429
                # -------------------------------------------------

                if weather_response.status_code == 429:
                    retry_after = weather_response.headers.get(
                        "Retry-After"
                    )

                    logger.warning(
                        "[WeatherAction] Open-Meteo rate-limited. "
                        "Retry-After=%s location=%s",
                        retry_after,
                        location,
                    )

                    # -------------------------------------------------
                    # FALLBACK: MET NORWAY
                    # -------------------------------------------------

                    try:
                        met_data = await self._get_met_weather(
                            client,
                            latitude,
                            longitude,
                        )

                        # Normalize MET Norway response into the
                        # structure expected by the formatter below.
                        weather = self._normalize_met_weather(
                            met_data,
                            timezone,
                        )

                        logger.info(
                            "[WeatherAction] Using MET Norway fallback "
                            "for %s",
                            location_name
                            if "location_name" in locals()
                            else location,
                        )

                    except Exception:
                        logger.exception(
                            "[WeatherAction] MET Norway fallback failed."
                        )

                        return ActionResult(
                            success=False,
                            action_name=self.name,
                            error=(
                                "Weather providers are temporarily "
                                "unavailable. Please try again shortly."
                            ),
                        )

                else:
                    weather_response.raise_for_status()
                    weather = weather_response.json()

            # =====================================================
            # 6. FORMAT WEATHER DATA
            # =====================================================

            current = weather.get("current", {})
            daily = weather.get("daily", {})

            weather_code = current.get("weather_code")

            if weather_code is not None:
                condition = self.WEATHER_CODES.get(
                    weather_code,
                    "Unknown conditions",
                )
            else:
                condition = (
                    current.get("weather_symbol")
                    or "Unknown conditions"
                )

                condition = (
                    condition
                    .replace("_", " ")
                    .replace("day", "")
                    .replace("night", "")
                    .strip()
                    .title()
                )

            temperature = current.get("temperature_2m")
            feels_like = current.get("apparent_temperature")
            humidity = current.get("relative_humidity_2m")
            precipitation = current.get("precipitation")
            rain = current.get("rain")
            wind_speed = current.get("wind_speed_10m")
            wind_direction = current.get("wind_direction_10m")
            pressure = current.get("surface_pressure")
            current_time = current.get("time")

            # =====================================================
            # 7. HUMAN-READABLE LOCATION
            # =====================================================

            location_name = city

            if country:
                location_name = f"{city}, {country}"

            # =====================================================
            # 8. CURRENT WEATHER MESSAGE
            # =====================================================

            lines = [
                f"Weather in {location_name}",
                "",
                f"Condition: {condition}",
                f"Temperature: {temperature}°C",
                f"Feels like: {feels_like}°C",
                f"Humidity: {humidity}%",
                f"Precipitation: {precipitation} mm",
                f"Rain: {rain} mm",
                f"Wind: {wind_speed} km/h",
                f"Wind direction: {wind_direction}°",
                f"Pressure: {pressure} hPa",
                f"Local time: {current_time}",
                f"Timezone: {timezone}",
            ]

            # =====================================================
            # 9. FORECAST
            # =====================================================

            dates = daily.get("time", [])

            if dates:

                max_temps = daily.get(
                    "temperature_2m_max",
                    [],
                )

                min_temps = daily.get(
                    "temperature_2m_min",
                    [],
                )

                daily_codes = daily.get(
                    "weather_code",
                    [],
                )

                precipitation_sums = daily.get(
                    "precipitation_sum",
                    [],
                )

                sunrise = daily.get(
                    "sunrise",
                    [],
                )

                sunset = daily.get(
                    "sunset",
                    [],
                )

                # -------------------------------------------------
                # Select requested forecast indices based on days/target
                # -------------------------------------------------

                if forecast_days > 1:
                    selected_indices = range(
                        min(forecast_days, len(dates))
                    )

                elif forecast_target == "tomorrow":
                    selected_indices = [1] if len(dates) > 1 else [0]

                else:
                    selected_indices = [0]

                lines.append("")
                lines.append("Forecast:")

                for index in selected_indices:
                    date = dates[index]

                    code = (
                        daily_codes[index]
                        if index < len(daily_codes)
                        else None
                    )

                    description = self.WEATHER_CODES.get(
                        code,
                        "Unknown",
                    )

                    max_temp = (
                        max_temps[index]
                        if index < len(max_temps)
                        else None
                    )

                    min_temp = (
                        min_temps[index]
                        if index < len(min_temps)
                        else None
                    )

                    precipitation_total = (
                        precipitation_sums[index]
                        if index < len(precipitation_sums)
                        else None
                    )

                    lines.append(
                        f"{date}: {description}, "
                        f"{min_temp}°C–{max_temp}°C, "
                        f"precipitation {precipitation_total} mm"
                    )

                    if index < len(sunrise) and sunrise[index]:
                        lines.append(
                            f"Sunrise: {sunrise[index]}"
                        )

                    if index < len(sunset) and sunset[index]:
                        lines.append(
                            f"Sunset: {sunset[index]}"
                        )

            message = "\n".join(lines)

            # =====================================================
            # 10. SUCCESS
            # =====================================================

            logger.info(
                "[WeatherAction] Weather retrieved successfully "
                "for %s",
                location_name,
            )

            return ActionResult(
                success=True,
                action_name=self.name,
                data={
                    "message": message,
                    "location": location_name,
                    "city": city,
                    "country": country,
                    "country_code": country_code,
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": timezone,
                    "current": current,
                    "forecast": daily,
                    "forecast_target": forecast_target,
                },
            )

        # =========================================================
        # 11. TIMEOUT
        # =========================================================

        except httpx.TimeoutException:

            logger.warning(
                "[WeatherAction] Weather service timeout."
            )

            return ActionResult(
                success=False,
                action_name=self.name,
                error=(
                    "The weather service timed out. "
                    "Please try again shortly."
                ),
            )

        # =========================================================
        # 12. HTTP ERROR
        # =========================================================

        except httpx.HTTPStatusError as e:

            status_code = (
                e.response.status_code
                if e.response is not None
                else None
            )

            logger.exception(
                "[WeatherAction] HTTP status error: %s",
                status_code,
            )

            return ActionResult(
                success=False,
                action_name=self.name,
                error=(
                    "The weather service returned an error. "
                    "Please try again shortly."
                ),
            )

        except httpx.HTTPError as e:

            logger.exception(
                "[WeatherAction] HTTP error"
            )

            return ActionResult(
                success=False,
                action_name=self.name,
                error=(
                    "Unable to connect to the weather service. "
                    "Please try again shortly."
                ),
            )

        # =========================================================
        # 13. UNEXPECTED ERROR
        # =========================================================

        except Exception as e:

            logger.exception(
                "[WeatherAction] Unexpected error"
            )

            return ActionResult(
                success=False,
                action_name=self.name,
                error=(
                    "Unable to retrieve weather right now."
                ),
            )

    # =============================================================
    # NORMALIZE MET NORWAY RESPONSE
    # =============================================================

    @staticmethod
    def _normalize_met_weather(
        met_data: Dict[str, Any],
        timezone: str,
    ) -> Dict[str, Any]:
        """
        Convert MET Norway Locationforecast JSON into the
        Open-Meteo-like structure used by WeatherAction.

        MET Norway provides a time series, so this method builds:
            current
            daily

        from that time series.
        """

        timeseries = (
            met_data
            .get("properties", {})
            .get("timeseries", [])
        )

        if not timeseries:
            raise ValueError(
                "MET Norway returned no forecast timeseries."
            )

        # ---------------------------------------------------------
        # Helper functions
        # ---------------------------------------------------------

        def instant(data: Dict[str, Any], key: str):
            return (
                data
                .get("data", {})
                .get("instant", {})
                .get("details", {})
                .get(key)
            )

        def period_details(
            data: Dict[str, Any],
            period: str,
        ) -> Dict[str, Any]:
            return (
                data
                .get("data", {})
                .get(period, {})
                .get("details", {})
            )

        # ---------------------------------------------------------
        # CURRENT
        # ---------------------------------------------------------

        first = timeseries[0]

        first_details = (
            first
            .get("data", {})
            .get("instant", {})
            .get("details", {})
        )

        current_time = first.get("time")

        temperature = first_details.get(
            "air_temperature"
        )

        humidity = first_details.get(
            "relative_humidity"
        )

        wind_speed_ms = first_details.get(
            "wind_speed"
        )

        wind_direction = first_details.get(
            "wind_from_direction"
        )

        pressure = first_details.get(
            "air_pressure_at_sea_level"
        )

        # MET Norway wind speed is m/s.
        # ARIA internally uses km/h.
        wind_speed_kmh = None

        if wind_speed_ms is not None:
            wind_speed_kmh = round(
                float(wind_speed_ms) * 3.6,
                1,
            )

        # ---------------------------------------------------------
        # WEATHER SYMBOL
        # ---------------------------------------------------------

        first_period = (
            first
            .get("data", {})
            .get("next_1_hours", {})
        )

        symbol_code = (
            first_period
            .get("summary", {})
            .get("symbol_code")
        )

        if not symbol_code:
            first_period = (
                first
                .get("data", {})
                .get("next_6_hours", {})
            )

            symbol_code = (
                first_period
                .get("summary", {})
                .get("symbol_code")
            )

        # ---------------------------------------------------------
        # PRECIPITATION
        # ---------------------------------------------------------

        precipitation = (
            period_details(
                first,
                "next_1_hours",
            )
            .get("precipitation_amount")
        )

        if precipitation is None:
            precipitation = (
                period_details(
                    first,
                    "next_6_hours",
                )
                .get("precipitation_amount")
            )

        if precipitation is None:
            precipitation = 0.0

        # ---------------------------------------------------------
        # BUILD DAILY DATA
        #
        # MET provides hourly/6-hourly forecast points.
        # We aggregate those points by local calendar date.
        # ---------------------------------------------------------

        daily_map: Dict[str, Dict[str, Any]] = {}

        for item in timeseries:

            timestamp = item.get("time")

            if not timestamp:
                continue

            try:
                dt_utc = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )

                if timezone and timezone != "auto":
                    try:
                        dt_local = dt_utc.astimezone(
                            ZoneInfo(timezone)
                        )
                    except Exception:
                        dt_local = dt_utc
                else:
                    dt_local = dt_utc

            except Exception:
                continue

            date = dt_local.date().isoformat()

            if date not in daily_map:
                daily_map[date] = {
                    "temps": [],
                    "symbols": [],
                    "precipitation": [],
                }

            details = (
                item
                .get("data", {})
                .get("instant", {})
                .get("details", {})
            )

            temp = details.get(
                "air_temperature"
            )

            if temp is not None:
                daily_map[date]["temps"].append(
                    float(temp)
                )

            # Prefer 1-hour symbol.
            period = item.get(
                "data",
                {}
            ).get(
                "next_1_hours",
                {}
            )

            symbol = (
                period
                .get("summary", {})
                .get("symbol_code")
            )

            if not symbol:

                period = item.get(
                    "data",
                    {}
                ).get(
                    "next_6_hours",
                    {}
                )

                symbol = (
                    period
                    .get("summary", {})
                    .get("symbol_code")
                )

            if symbol:
                daily_map[date]["symbols"].append(
                    symbol
                )

            precipitation_value = (
                period
                .get("details", {})
                .get("precipitation_amount")
            )

            if precipitation_value is not None:
                daily_map[date]["precipitation"].append(
                    float(precipitation_value)
                )

        # ---------------------------------------------------------
        # Convert daily map into Open-Meteo-like arrays
        # ---------------------------------------------------------

        dates = sorted(daily_map.keys())

        daily_codes = []
        min_temps = []
        max_temps = []
        precipitation_sums = []

        for date in dates:

            info = daily_map[date]

            temps = info["temps"]

            # Temperature range
            if temps:
                min_temps.append(
                    round(min(temps), 1)
                )
                max_temps.append(
                    round(max(temps), 1)
                )
            else:
                min_temps.append(None)
                max_temps.append(None)

            # -----------------------------------------------------
            # Convert MET symbol_code into ARIA weather code
            # -----------------------------------------------------

            symbol = (
                info["symbols"][0]
                if info["symbols"]
                else None
            )

            daily_codes.append(
                WeatherAction._met_symbol_to_weather_code(
                    symbol
                )
            )

            precipitation_sums.append(
                round(
                    sum(info["precipitation"]),
                    1,
                )
            )

        # ---------------------------------------------------------
        # LOCAL CURRENT TIME
        # ---------------------------------------------------------

        local_time = current_time

        if current_time:

            try:

                dt_utc = datetime.fromisoformat(
                    current_time.replace(
                        "Z",
                        "+00:00",
                    )
                )

                if timezone and timezone != "auto":
                    try:
                        local_time = dt_utc.astimezone(
                            ZoneInfo(timezone)
                        ).isoformat()
                    except Exception:
                        local_time = dt_utc.isoformat()

            except Exception:
                pass

        # ---------------------------------------------------------
        # FINAL NORMALIZED STRUCTURE
        # ---------------------------------------------------------

        return {
            "current": {
                "temperature_2m": temperature,
                "apparent_temperature": temperature,
                "relative_humidity_2m": humidity,
                "precipitation": precipitation,
                "rain": precipitation,
                "weather_code": WeatherAction._met_symbol_to_weather_code(
                    symbol_code
                ),
                "weather_symbol": symbol_code,
                "wind_speed_10m": wind_speed_kmh,
                "wind_direction_10m": wind_direction,
                "surface_pressure": pressure,
                "time": local_time,
            },

            "daily": {
                "time": dates,
                "weather_code": daily_codes,
                "temperature_2m_max": max_temps,
                "temperature_2m_min": min_temps,
                "precipitation_sum": precipitation_sums,

                # MET fallback does not provide Open-Meteo-style
                # sunrise/sunset arrays here.
                "sunrise": [],
                "sunset": [],
            },
        }

    # =============================================================
    # MET SYMBOL TO WEATHER CODE HELPER
    # =============================================================

    @staticmethod
    def _met_symbol_to_weather_code(
        symbol: str | None,
    ) -> int | None:
        """
        Convert MET Norway symbol_code to the
        closest WMO/Open-Meteo weather code.
        """

        if not symbol:
            return None

        value = symbol.lower()

        # Thunder
        if "thunder" in value:
            return 95

        # Snow
        if "snow" in value:
            if "heavy" in value:
                return 75
            return 71

        # Sleet / freezing precipitation
        if "sleet" in value:
            return 65

        if "freezing" in value:
            return 66

        # Rain
        if "heavyrain" in value:
            return 65

        if "rainshowers" in value:
            return 80

        if "rain" in value:
            return 63

        # Drizzle
        if "drizzle" in value:
            return 51

        # Fog
        if "fog" in value:
            return 45

        # Overcast
        if "cloudy" in value:
            if "partly" in value:
                return 2

            return 3

        # Clear
        if "clearsky" in value:
            return 0

        # Fair / mostly clear
        if "fair" in value:
            return 1

        return None

    # =============================================================
    # MET NORWAY FALLBACK
    # =============================================================

    async def _get_met_weather(
        self,
        client: httpx.AsyncClient,
        latitude: float,
        longitude: float,
    ) -> Dict[str, Any]:
        """
        Fallback weather provider using MET Norway.

        Used when Open-Meteo is temporarily unavailable or rate-limited.
        """

        logger.info(
            "[WeatherAction] Trying MET Norway fallback for "
            "lat=%s lon=%s",
            latitude,
            longitude,
        )

        response = await client.get(
            MET_FORECAST_URL,
            params={
                "lat": latitude,
                "lon": longitude,
            },
            headers={
                "Accept": "application/json",
                "User-Agent": MET_USER_AGENT,
            },
        )

        if response.status_code == 429:
            logger.warning(
                "[WeatherAction] MET Norway also rate-limited."
            )

            raise httpx.HTTPStatusError(
                "MET Norway rate limited",
                request=response.request,
                response=response,
            )

        response.raise_for_status()

        data = response.json()

        logger.info(
            "[WeatherAction] MET Norway fallback succeeded."
        )

        return data

    # =============================================================
    # NATURAL-LANGUAGE LOCATION EXTRACTION
    # =============================================================

    @staticmethod
    def _clean_location(location: str) -> str:
        """
        Extract a clean geographical location from a natural-language
        weather request.

        Examples:
            "What's the weather in Vizag?" -> "Vizag"
            "weather in London" -> "London"
            "Temperature in New York" -> "New York"
            "What's the weather in Vizag, and tell me if it will rain"
                -> "Vizag"
            "Will it rain tomorrow in Tokyo?" -> "Tokyo"
        """

        if not isinstance(location, str):
            return ""

        text = location.strip()

        if not text:
            return ""

        # Normalize whitespace.
        text = re.sub(r"\s+", " ", text)

        # Remove common leading weather phrases.
        text = re.sub(
            r"^(?:"
            r"what(?:'|’)s\s+"
            r"|what\s+is\s+"
            r"|tell\s+me\s+"
            r"|can\s+you\s+tell\s+me\s+"
            r"|give\s+me\s+"
            r"|show\s+me\s+"
            r")?",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Remove common weather-intent prefixes.
        text = re.sub(
            r"^(?:"
            r"the\s+"
            r")?"
            r"(?:current\s+|today(?:'|’s)\s+|tomorrow(?:'|’s)\s+)?"
            r"(?:weather|temperature|forecast)"
            r"(?:\s+(?:in|at|for|of))?\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Handle phrases such as:
        # "will it rain in Vizag"
        # "will it rain tomorrow in Vizag"
        text = re.sub(
            r"^(?:"
            r"will\s+it\s+(?:rain|snow)"
            r"|is\s+it\s+(?:raining|snowing)"
            r")"
            r"(?:\s+(?:today|tomorrow))?"
            r"\s+(?:in|at)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Forecast-request boundary.
        text = re.split(
            r"\s+\bfor\s+(?:the\s+)?"
            r"(?:next\s+)?"
            r"(?:\d+\s+)?"
            r"(?:days?|weeks?|week|day)\b",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()

        # Defensive handling for malformed router output such as:
        # "Vizag for the and tell me which days have rain"
        text = re.sub(
            r"\s+\bfor\s+the\s+and\b.*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        # Existing location/follow-up boundary.
        text = re.split(
            r"\s*(?:,\s*(?:and|but)\b|\s+\b(?:and|but)\b|"
            r"\s+(?:and\s+)?(?:tell|show|give|let\s+me\s+know)\s+me\b|"
            r"\s+(?:whether|if)\b)",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        # Remove trailing question marks and punctuation.
        text = re.sub(r"[?!.]+$", "", text).strip()

        # Remove accidental leading/trailing punctuation.
        text = text.strip(" ,;:-")

        # Handle common trailing weather-query words.
        text = re.sub(
            r"\s+(?:today|tomorrow|tonight)$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        return text
