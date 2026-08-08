import re
import logging
from typing import Any, Dict

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
        "precipitation, wind, sunrise, sunset and forecasts."
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

                try:
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

                    if weather_response.status_code == 429:
                        logger.warning(
                            "[WeatherAction] Open-Meteo rate limited (429). Switching to fallback."
                        )
                        raise httpx.HTTPStatusError(
                            "Open-Meteo rate limited",
                            request=weather_response.request,
                            response=weather_response,
                        )

                    weather_response.raise_for_status()
                    weather = weather_response.json()

                except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError) as exc:
                    logger.warning(
                        "[WeatherAction] Open-Meteo failed (%s). Attempting MET Norway fallback.",
                        exc,
                    )
                    met_raw_data = await self._get_met_weather(client, latitude, longitude)
                    weather = self._normalize_met_weather(met_raw_data)

            # =====================================================
            # 6. FORMAT WEATHER DATA
            # =====================================================

            current = weather.get("current", {})
            daily = weather.get("daily", {})

            weather_code = current.get("weather_code")

            condition = self.WEATHER_CODES.get(
                weather_code,
                "Unknown conditions",
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
                lines.append("")
                lines.append("Forecast:")

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

                    precipitation_total = (
                        precipitation_sums[index]
                        if index < len(precipitation_sums)
                        else None
                    )

                    lines.append(
                        f"{date}: {description}, "
                        f"{min_temp}°C–{max_temp}°C, "
                        f"precipitation "
                        f"{precipitation_total} mm"
                    )

                    if index == 0:

                        if index < len(sunrise):
                            lines.append(
                                f"Sunrise: {sunrise[index]}"
                            )

                        if index < len(sunset):
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

    @staticmethod
    def _normalize_met_weather(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalizes MET Norway response structure to match Open-Meteo format.
        """
        properties = data.get("properties", {})
        timeseries = properties.get("timeseries", [])

        current_instant = {}
        current_details = {}
        if timeseries:
            first_entry = timeseries[0]
            current_instant = first_entry.get("data", {}).get("instant", {}).get("details", {})

        current_time = timeseries[0].get("time") if timeseries else None

        current_normalized = {
            "temperature_2m": current_instant.get("air_temperature"),
            "relative_humidity_2m": current_instant.get("relative_humidity_percent"),
            "apparent_temperature": current_instant.get("air_temperature"),
            "precipitation": 0.0,
            "rain": 0.0,
            "weather_code": 0,
            "wind_speed_10m": current_instant.get("wind_speed"),
            "wind_direction_10m": current_instant.get("wind_from_direction"),
            "surface_pressure": current_instant.get("air_pressure_at_sea_level"),
            "time": current_time,
        }

        daily_times = []
        daily_max_temps = []
        daily_min_temps = []
        daily_codes = []
        daily_precip = []

        seen_dates = set()
        for entry in timeseries:
            time_str = entry.get("time", "")
            date_part = time_str.split("T")[0] if "T" in time_str else time_str
            if date_part and date_part not in seen_dates:
                seen_dates.add(date_part)
                daily_times.append(date_part)
                details = entry.get("data", {}).get("instant", {}).get("details", {})
                temp = details.get("air_temperature", 0.0)
                daily_max_temps.append(temp)
                daily_min_temps.append(temp)
                daily_codes.append(0)
                daily_precip.append(0.0)

        daily_normalized = {
            "time": daily_times,
            "temperature_2m_max": daily_max_temps,
            "temperature_2m_min": daily_min_temps,
            "weather_code": daily_codes,
            "precipitation_sum": daily_precip,
            "sunrise": [],
            "sunset": [],
        }

        return {
            "current": current_normalized,
            "daily": daily_normalized,
        }

    # =============================================================
    # NATURAL-LANGUAGE LOCATION EXTRACTION
    # =============================================================

    @staticmethod
    def _clean_location(location: str) -> str:
        """
        Convert natural-language weather requests into a clean
        geocoding location.

        Examples:

            weather in Tokyo
                -> Tokyo

            What's the weather in New York?
                -> New York

            What is the weather in London?
                -> London

            Can you tell me the weather in Paris?
                -> Paris

            temperature in Mumbai
                -> Mumbai

            What's the temperature at Tokyo?
                -> Tokyo
        """

        value = location.strip()

        # ---------------------------------------------------------
        # Remove surrounding quotation marks
        # ---------------------------------------------------------

        value = value.strip(
            " \t\n\r\"'“”‘’"
        )

        # ---------------------------------------------------------
        # "What's the weather in X?"
        # "What is the weather in X?"
        # ---------------------------------------------------------

        patterns = [

            # What's the weather in London?
            r"^(?:what(?:'s| is)\s+)?"
            r"(?:the\s+)?weather\s+"
            r"(?:in|at|for)\s+(.+)$",

            # Can you tell me the weather in London?
            r"^(?:can\s+you\s+tell\s+me\s+)?"
            r"(?:the\s+)?weather\s+"
            r"(?:in|at|for)\s+(.+)$",

            # How is the weather in London?
            r"^how(?:'s| is)\s+"
            r"(?:the\s+)?weather\s+"
            r"(?:in|at|for)\s+(.+)$",

            # Give me the weather in London
            r"^(?:give\s+me|show\s+me|get\s+me)\s+"
            r"(?:the\s+)?weather\s+"
            r"(?:in|at|for)\s+(.+)$",

            # Weather in London
            r"^(?:the\s+)?weather\s+"
            r"(?:in|at|for)\s+(.+)$",

            # Temperature in London
            r"^(?:the\s+)?temperature\s+"
            r"(?:in|at|for)\s+(.+)$",

            # What's the temperature in London?
            r"^(?:what(?:'s| is)\s+)?"
            r"(?:the\s+)?temperature\s+"
            r"(?:in|at|for)\s+(.+)$",

            # Can you tell me the temperature in London?
            r"^(?:can\s+you\s+tell\s+me\s+)?"
            r"(?:the\s+)?temperature\s+"
            r"(?:in|at|for)\s+(.+)$",
        ]

        for pattern in patterns:

            match = re.match(
                pattern,
                value,
                flags=re.IGNORECASE,
            )

            if match:
                value = match.group(1).strip()
                break

        # ---------------------------------------------------------
        # Remove common trailing punctuation
        # ---------------------------------------------------------

        value = value.strip(
            " \t\n\r?!.,;:"
        )

        # ---------------------------------------------------------
        # Remove accidental surrounding quotes again
        # ---------------------------------------------------------

        value = value.strip(
            "\"'“”‘’"
        )

        return value.strip()
