import logging
from datetime import date as date_cls

import requests


logger = logging.getLogger(__name__)

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

HISTORICAL_YEARS_BACK = 5
HISTORICAL_WINDOW_DAYS = 7


def _base_payload(date: str) -> dict:
    return {
        "date": date,
        "available": False,
        "temperature_low_c": None,
        "temperature_high_c": None,
        "temperature_c": None,
        "is_estimate": False,
        "source": None,
    }


def _coerce_temperature(max_values, min_values):
    if not max_values or not min_values:
        return None

    try:
        low = float(min_values[0])
        high = float(max_values[0])
    except (TypeError, ValueError, IndexError):
        return None

    avg = (low + high) / 2
    return {
        "temperature_low_c": round(low, 1),
        "temperature_high_c": round(high, 1),
        "temperature_c": round(avg, 1),
    }


def _request_daily_range(
    url: str, latitude: float, longitude: float, start_date: str, end_date: str
):
    try:
        response = requests.get(
            url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start_date,
                "end_date": end_date,
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "UTC",
            },
            timeout=8,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None
    except ValueError:
        return None


def _fetch_direct_temperature(date: str, latitude: float, longitude: float):
    for source, url in (
        ("archive", OPEN_METEO_ARCHIVE_URL),
        ("forecast", OPEN_METEO_FORECAST_URL),
    ):
        data = _request_daily_range(url, latitude, longitude, date, date)
        if not data:
            continue

        daily = data.get("daily") or {}
        temperatures = _coerce_temperature(
            daily.get("temperature_2m_max") or [],
            daily.get("temperature_2m_min") or [],
        )
        if not temperatures:
            continue

        return {
            **temperatures,
            "available": True,
            "is_estimate": False,
            "source": source,
        }

    return None


def _fetch_historical_estimate(date: str, latitude: float, longitude: float):
    try:
        target_date = date_cls.fromisoformat(date)
    except ValueError:
        return None

    all_max: list[float] = []
    all_min: list[float] = []

    for years_back in range(1, HISTORICAL_YEARS_BACK + 1):
        year = target_date.year - years_back
        try:
            same_day = target_date.replace(year=year)
        except ValueError:
            # Leap-day fallback: use Feb 28 for non-leap years
            same_day = target_date.replace(year=year, day=28)

        start = same_day.fromordinal(same_day.toordinal() - HISTORICAL_WINDOW_DAYS)
        end = same_day.fromordinal(same_day.toordinal() + HISTORICAL_WINDOW_DAYS)
        data = _request_daily_range(
            OPEN_METEO_ARCHIVE_URL,
            latitude,
            longitude,
            start.isoformat(),
            end.isoformat(),
        )
        if not data:
            continue

        daily = data.get("daily") or {}
        max_values = daily.get("temperature_2m_max") or []
        min_values = daily.get("temperature_2m_min") or []
        pair_count = min(len(max_values), len(min_values))

        for index in range(pair_count):
            try:
                all_max.append(float(max_values[index]))
                all_min.append(float(min_values[index]))
            except (TypeError, ValueError):
                continue

    if not all_max or not all_min:
        return None

    avg_max = sum(all_max) / len(all_max)
    avg_min = sum(all_min) / len(all_min)
    avg = (avg_max + avg_min) / 2

    return {
        "available": True,
        "temperature_low_c": round(avg_min, 1),
        "temperature_high_c": round(avg_max, 1),
        "temperature_c": round(avg, 1),
        "is_estimate": True,
        "source": "historical_estimate",
    }


def fetch_daily_temperature(date: str, latitude: float, longitude: float):
    payload = _base_payload(date)

    direct = _fetch_direct_temperature(date, latitude, longitude)
    if direct:
        return {**payload, **direct}

    historical_estimate = _fetch_historical_estimate(date, latitude, longitude)
    if historical_estimate:
        return {**payload, **historical_estimate}

    logger.info(
        "No weather data available for date=%s lat=%s lon=%s",
        date,
        latitude,
        longitude,
    )
    return payload
