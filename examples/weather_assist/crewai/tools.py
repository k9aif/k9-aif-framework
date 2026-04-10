from __future__ import annotations

from typing import Any, Dict

import requests
from crewai.tools import tool


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODE_MAP = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow fall",
    73: "moderate snow fall",
    75: "heavy snow fall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _safe_daily_value(daily: Dict[str, Any], key: str, idx: int) -> Any:
    values = daily.get(key)
    if not values or idx >= len(values):
        return None
    return values[idx]


@tool("get_weather_for_city")
def get_weather_for_city(city: str) -> str:
    """
    Get current weather and short forecast for a city using Open-Meteo.
    Returns a plain-English factual weather payload for downstream agents.
    """
    geo_resp = requests.get(
        GEOCODING_URL,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=20,
    )
    geo_resp.raise_for_status()
    geo_data = geo_resp.json()

    results = geo_data.get("results") or []
    if not results:
        return f"Could not find location for city: {city}"

    loc = results[0]
    latitude = loc["latitude"]
    longitude = loc["longitude"]
    timezone = loc.get("timezone", "auto")
    resolved_name = loc["name"]
    country = loc.get("country", "")

    forecast_params = [
        ("latitude", latitude),
        ("longitude", longitude),
        ("current", "temperature_2m"),
        ("current", "apparent_temperature"),
        ("current", "weather_code"),
        ("current", "wind_speed_10m"),
        ("daily", "weather_code"),
        ("daily", "temperature_2m_max"),
        ("daily", "temperature_2m_min"),
        ("daily", "precipitation_probability_max"),
        ("timezone", timezone),
        ("forecast_days", 3),
    ]

    fc_resp = requests.get(FORECAST_URL, params=forecast_params, timeout=20)
    fc_resp.raise_for_status()
    data = fc_resp.json()

    current = data.get("current", {})
    daily = data.get("daily", {})

    current_code = current.get("weather_code")
    today_code = _safe_daily_value(daily, "weather_code", 0)

    weather_text = WEATHER_CODE_MAP.get(current_code, "unknown")
    today_text = WEATHER_CODE_MAP.get(today_code, "unknown")

    return (
        f"Location: {resolved_name}, {country}\n"
        f"Timezone: {data.get('timezone', timezone)}\n"
        f"Current temperature: {current.get('temperature_2m')}°C\n"
        f"Feels like: {current.get('apparent_temperature')}°C\n"
        f"Current condition: {weather_text}\n"
        f"Wind speed: {current.get('wind_speed_10m')} km/h\n"
        f"Today's forecast condition: {today_text}\n"
        f"Today's high: {_safe_daily_value(daily, 'temperature_2m_max', 0)}°C\n"
        f"Today's low: {_safe_daily_value(daily, 'temperature_2m_min', 0)}°C\n"
        f"Max precipitation probability today: "
        f"{_safe_daily_value(daily, 'precipitation_probability_max', 0)}%\n"
    )