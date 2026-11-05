# actions/weather_action.py

import re
import logging
from datetime import datetime, timedelta
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
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
    AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

    SOURCE_FORECAST = "Open-Meteo forecast API"
    SOURCE_ARCHIVE = "Open-Meteo historical weather API (reanalysis)"
    SOURCE_AIR_QUALITY = "Open-Meteo air-quality API"

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
            # 2b. REQUEST MODE (current / forecast / historical /
            #     air quality). Historical dates are validated before
            #     any network request is made.
            # =====================================================

            mode = self._resolve_mode(params)

            start_date, end_date, history_error = (
                self._resolve_history_range(params)
            )

            if history_error:
                return ActionResult(
                    success=False,
                    action_name=self.name,
                    error=history_error,
                )

            if mode == "historical":
                # Historical reanalysis uses an explicit date range.
                forecast_days = 1

            # =====================================================
            # 3. HTTP CLIENT
            # =====================================================

            air_quality: Dict[str, Any] = {}

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
                # 5. LIVE WEATHER / HISTORICAL WEATHER
                # =================================================

                if mode == "historical":
                    weather_response = await client.get(
                        self.ARCHIVE_URL,
                        params={
                            "latitude": latitude,
                            "longitude": longitude,
                            "start_date": start_date,
                            "end_date": end_date,
                            "daily": (
                                "weather_code,"
                                "temperature_2m_max,"
                                "temperature_2m_min,"
                                "temperature_2m_mean,"
                                "precipitation_sum,"
                                "rain_sum,"
                                "wind_speed_10m_max,"
                                "sunrise,"
                                "sunset"
                            ),
                            "timezone": "auto",
                            "temperature_unit": "celsius",
                            "wind_speed_unit": "kmh",
                            "precipitation_unit": "mm",
                        },
                    )

                    if weather_response.status_code == 429:
                        logger.warning(
                            "[WeatherAction] Historical API rate-limited."
                        )
                        return ActionResult(
                            success=False,
                            action_name=self.name,
                            error=(
                                "The historical weather service is "
                                "temporarily rate-limited. Please try "
                                "again shortly."
                            ),
                        )

                    weather_response.raise_for_status()
                    weather = weather_response.json()

                else:
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

                # =================================================
                # 5b. AIR QUALITY (optional mode)
                # =================================================

                if mode == "air_quality":
                    aq_response = await client.get(
                        self.AIR_QUALITY_URL,
                        params={
                            "latitude": latitude,
                            "longitude": longitude,
                            "current": (
                                "european_aqi,"
                                "us_aqi,"
                                "pm10,"
                                "pm2_5,"
                                "carbon_monoxide,"
                                "nitrogen_dioxide,"
                                "sulphur_dioxide,"
                                "ozone,"
                                "uv_index"
                            ),
                            "timezone": "auto",
                        },
                    )

                    if aq_response.status_code == 429:
                        logger.warning(
                            "[WeatherAction] Air-quality API rate-limited."
                        )
                        return ActionResult(
                            success=False,
                            action_name=self.name,
                            error=(
                                "The air-quality service is temporarily "
                                "rate-limited. Please try again shortly."
                            ),
                        )

                    aq_response.raise_for_status()
                    air_quality = aq_response.json()

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

            location_name = city

            if country:
                location_name = f"{city}, {country}"

            # =====================================================
            # 7b. PREPARE DISPLAY LABELS
            # =====================================================

            title_prefix = "Weather in"
            if mode == "historical":
                title_prefix = "Historical weather in"
            elif mode == "air_quality":
                title_prefix = "Air quality in"

            lines: list[str] = []

            daily_values = daily if isinstance(daily, dict) else {}
            dates = daily_values.get("time", []) or []
            max_temps = daily_values.get("temperature_2m_max", []) or []
            min_temps = daily_values.get("temperature_2m_min", []) or []
            daily_codes = daily_values.get("weather_code", []) or []
            precipitation_sums = daily_values.get("precipitation_sum", []) or []
            sunrise = daily_values.get("sunrise", []) or []
            sunset = daily_values.get("sunset", []) or []

            if mode == "historical":
                lines = [
                    f"{title_prefix} {location_name}",
                    "",
                    f"Source: {self.SOURCE_ARCHIVE}",
                    f"Observed period: {start_date} to {end_date} (UTC/localized as provided by Open-Meteo)",
                    f"Timezone: {timezone}",
                ]

                if dates:
                    lines.append("")
                    lines.append("Daily observed values:")
                    for index, date in enumerate(dates):
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
                        mean_temp = (
                            daily.get("temperature_2m_mean", [])[index]
                            if index < len(daily.get("temperature_2m_mean", []))
                            else None
                        )
                        precipitation_total = (
                            precipitation_sums[index]
                            if index < len(precipitation_sums)
                            else None
                        )
                        wind_max = (
                            daily.get("wind_speed_10m_max", [])[index]
                            if index < len(daily.get("wind_speed_10m_max", []))
                            else None
                        )
                        line_parts = [
                            f"{date}: {description}",
                            f"{min_temp}°C–{max_temp}°C",
                        ]
                        if mean_temp is not None:
                            line_parts.append(f"mean {mean_temp}°C")
                        if precipitation_total is not None:
                            line_parts.append(
                                f"precipitation {precipitation_total} mm"
                            )
                        if wind_max is not None:
                            line_parts.append(
                                f"max wind {wind_max} km/h"
                            )
                        lines.append(", ".join(line_parts))

            elif mode == "air_quality":
                lines = [
                    f"{title_prefix} {location_name}",
                    "",
                    f"Source: {self.SOURCE_AIR_QUALITY}",
                    f"Timezone: {timezone}",
                ]
                aq_current = air_quality.get("current", {}) if isinstance(air_quality, dict) else {}
                def _aq(name: str):
                    val = aq_current.get(name)
                    return val if val is not None else "unknown"

                lines.append("")
                lines.append("Current air quality (observed):")
                lines.append(f"European AQI: {_aq('european_aqi')}")
                lines.append(f"US AQI: {_aq('us_aqi')}")
                lines.append(f"PM2.5: {_aq('pm2_5')} µg/m³")
                lines.append(f"PM10: {_aq('pm10')} µg/m³")
                lines.append(f"Ozone (O₃): {_aq('ozone')} µg/m³")
                lines.append(f"Nitrogen dioxide (NO₂): {_aq('nitrogen_dioxide')} µg/m³")
                lines.append(f"Sulphur dioxide (SO₂): {_aq('sulphur_dioxide')} µg/m³")
                lines.append(f"Carbon monoxide (CO): {_aq('carbon_monoxide')} µg/m³")
                lines.append(f"UV index: {_aq('uv_index')}")

            else:
                # =====================================================
                # 8. CURRENT WEATHER MESSAGE (forecast/current)
                # =====================================================

                lines = [
                    f"Weather in {location_name}",
                    "",
                    f"Source: {self.SOURCE_FORECAST}",
                    f"Condition (current): {condition} (observed/current)",
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

                if dates:

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
                    lines.append("Forecast (model forecast):")

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
                            f"{date}: {description} (forecast), "
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
                    "mode": mode,
                    "data_type": (
                        "observed_reanalysis"
                        if mode == "historical"
                        else "observed_current"
                        if mode == "air_quality"
                        else "current_observation_plus_forecast"
                    ),
                    "observed_vs_forecast": (
                        "observed"
                        if mode in {"historical", "air_quality"}
                        else "current observations followed by model forecast"
                    ),
                    "sources": [
                        self.SOURCE_ARCHIVE
                        if mode == "historical"
                        else self.SOURCE_AIR_QUALITY
                        if mode == "air_quality"
                        else self.SOURCE_FORECAST
                    ],
                    "source": (
                        self.SOURCE_ARCHIVE
                        if mode == "historical"
                        else self.SOURCE_AIR_QUALITY
                        if mode == "air_quality"
                        else self.SOURCE_FORECAST
                    ),
                    "start_date": start_date,
                    "end_date": end_date,
                    "current": current,
                    "forecast": daily,
                    "forecast_target": forecast_target,
                    "air_quality": air_quality,
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
    # REQUEST MODE / HISTORICAL RANGE
    # =============================================================

    @staticmethod
    def _resolve_mode(params: Dict[str, Any]) -> str:
        """Resolve the requested data mode without guessing silently."""

        raw = str(
            params.get("mode")
            or params.get("data_mode")
            or params.get("weather_mode")
            or ""
        ).strip().lower()

        aliases = {
            "current": "current",
            "now": "current",
            "today": "current",
            "forecast": "forecast",
            "tomorrow": "forecast",
            "historical": "historical",
            "history": "historical",
            "historical_weather": "historical",
            "past": "historical",
            "archive": "historical",
            "air_quality": "air_quality",
            "air-quality": "air_quality",
            "aqi": "air_quality",
        }
        if raw in aliases:
            return aliases[raw]

        # Only infer from the request text when no explicit mode was supplied.
        text = " ".join(
            str(
                params.get(key) or ""
            )
            for key in ("query", "location", "request")
        ).lower()

        if any(
            marker in text
            for marker in (
                "air quality",
                "aqi",
                "pollution",
                "pm2.5",
                "pm10",
            )
        ):
            return "air_quality"

        if any(
            marker in text
            for marker in (
                "historical weather",
                "weather history",
                "weather last year",
                "what was the weather",
                "past weather",
                "archive weather",
            )
        ):
            return "historical"

        if any(
            marker in text
            for marker in (
                "forecast",
                "tomorrow",
                "next week",
                "next few days",
                "this week",
            )
        ):
            return "forecast"

        return "current"

    @staticmethod
    def _resolve_history_range(params: Dict[str, Any]):
        """Return ``(start_date, end_date, error)`` for historical mode."""

        raw_start = (
            params.get("start_date")
            or params.get("date_from")
        )
        raw_end = (
            params.get("end_date")
            or params.get("date_to")
            or raw_start
        )

        # Convenience: "past N days" relative to today.
        if not raw_start and params.get("history_days") is not None:
            try:
                days = max(1, min(int(params.get("history_days")), 92))
            except (TypeError, ValueError):
                days = 7
            end = datetime.utcnow().date()
            start = end - timedelta(days=days - 1)
            return start.isoformat(), end.isoformat(), None

        # Default historical window: last 7 complete days.
        if not raw_start:
            end = datetime.utcnow().date() - timedelta(days=1)
            start = end - timedelta(days=6)
            return start.isoformat(), end.isoformat(), None

        def parse(value):
            try:
                return datetime.fromisoformat(
                    str(value).strip()[:10]
                ).date()
            except (TypeError, ValueError):
                return None

        start = parse(raw_start)
        end = parse(raw_end or raw_start)

        if start is None or end is None:
            return (
                None,
                None,
                (
                    "Historical weather requires valid ISO dates "
                    "(YYYY-MM-DD)."
                ),
            )

        if end < start:
            return (
                None,
                None,
                (
                    "The historical weather end date must not be "
                    "before the start date."
                ),
            )

        if (end - start).days > 92:
            return (
                None,
                None,
                (
                    "Historical weather is limited to a 92-day range "
                    "per request."
                ),
            )

        if end > datetime.utcnow().date():
            return (
                None,
                None,
                "Historical weather dates cannot be in the future.",
            )

        return start.isoformat(), end.isoformat(), None

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
