import re
import logging
from typing import Any, Dict

import httpx

from actions.base import BaseAction, ActionResult


logger = logging.getLogger("aria")


class WeatherAction(BaseAction):
    """
    Global live weather action using Open-Meteo.

    Supports:
    - Worldwide city/location lookup
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
        "city or location. Supports temperature, feels-like temperature, "
        "humidity, rain, precipitation, wind, sunrise, sunset and forecasts."
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

            location = self._clean_location(location)

            forecast_days = params.get("forecast_days", 1)

            try:
                forecast_days = int(forecast_days)
            except (TypeError, ValueError):
                forecast_days = 1

            forecast_days = max(1, min(forecast_days, 7))

            async with httpx.AsyncClient(
                timeout=self.timeout_seconds
            ) as client:

                # -------------------------------------------------
                # 1. GLOBAL GEOCODING
                # -------------------------------------------------

                geo_response = await client.get(
                    self.GEOCODING_URL,
                    params={
                        "name": location,
                        "count": 1,
                        "language": "en",
                        "format": "json",
                    },
                )

                geo_response.raise_for_status()

                geo_data = geo_response.json()

                results = geo_data.get("results") or []

                if not results:
                    return ActionResult(
                        success=False,
                        action_name=self.name,
                        error=f"I couldn't find a location matching '{location}'.",
                    )

                place = results[0]

                latitude = place["latitude"]
                longitude = place["longitude"]

                city = (
                    place.get("name")
                    or location
                )

                country = place.get("country", "")
                country_code = place.get("country_code", "")
                timezone = place.get("timezone", "auto")

                # -------------------------------------------------
                # 2. LIVE WEATHER
                # -------------------------------------------------

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

                weather_response.raise_for_status()

                weather = weather_response.json()

            # -----------------------------------------------------
            # 3. FORMAT RESULT
            # -----------------------------------------------------

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

            # -----------------------------------------------------
            # 4. BUILD HUMAN-READABLE MESSAGE
            # -----------------------------------------------------

            location_name = city

            if country:
                location_name = f"{city}, {country}"

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

            # -----------------------------------------------------
            # 5. FORECAST
            # -----------------------------------------------------

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
                        f"precipitation {precipitation_total} mm"
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

        except httpx.TimeoutException:
            return ActionResult(
                success=False,
                action_name=self.name,
                error="The weather service timed out. Please try again shortly.",
            )

        except httpx.HTTPError as e:
            logger.exception("[WeatherAction] HTTP error")
            return ActionResult(
                success=False,
                action_name=self.name,
                error=f"Weather service error: {e}",
            )

        except Exception as e:
            logger.exception("[WeatherAction] Unexpected error")
            return ActionResult(
                success=False,
                action_name=self.name,
                error=f"Unable to retrieve weather: {e}",
            )

    @staticmethod
    def _clean_location(location: str) -> str:
        """
        Remove common natural-language prefixes.

        Examples:
            'weather in Tokyo' -> 'Tokyo'
            'weather at London' -> 'London'
            'temperature in Paris' -> 'Paris'
        """

        value = location.strip()

        value = re.sub(
            r"^(?:the\s+)?weather\s+(?:in|at|for)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"^(?:the\s+)?temperature\s+(?:in|at|for)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        )

        return value.strip(" ?.,")