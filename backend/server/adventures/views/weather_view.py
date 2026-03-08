import hashlib
import logging
from datetime import date as date_cls

import requests
from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


logger = logging.getLogger(__name__)


class WeatherViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
    OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    CACHE_TIMEOUT_SECONDS = 60 * 60 * 6
    MAX_DAYS_PER_REQUEST = 60

    @action(detail=False, methods=["post"], url_path="daily-temperatures")
    def daily_temperatures(self, request):
        days = request.data.get("days", [])
        if not isinstance(days, list):
            return Response(
                {"error": "'days' must be a list"}, status=status.HTTP_400_BAD_REQUEST
            )
        if len(days) > self.MAX_DAYS_PER_REQUEST:
            return Response(
                {
                    "error": f"A maximum of {self.MAX_DAYS_PER_REQUEST} days is allowed per request"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        for entry in days:
            if not isinstance(entry, dict):
                results.append(
                    {"date": None, "available": False, "temperature_c": None}
                )
                continue

            date = entry.get("date")
            latitude = entry.get("latitude")
            longitude = entry.get("longitude")

            if not date or latitude is None or longitude is None:
                results.append(
                    {"date": date, "available": False, "temperature_c": None}
                )
                continue

            parsed_date = self._parse_date(date)
            if parsed_date is None:
                results.append(
                    {"date": date, "available": False, "temperature_c": None}
                )
                continue

            if parsed_date > date_cls.today():
                results.append(
                    {"date": date, "available": False, "temperature_c": None}
                )
                continue

            try:
                lat = float(latitude)
                lon = float(longitude)
            except (TypeError, ValueError):
                results.append(
                    {"date": date, "available": False, "temperature_c": None}
                )
                continue

            cache_key = self._cache_key(date, lat, lon)
            cached = cache.get(cache_key)
            if cached is not None:
                results.append(cached)
                continue

            payload = self._fetch_daily_temperature(date, lat, lon)
            cache.set(cache_key, payload, timeout=self.CACHE_TIMEOUT_SECONDS)
            results.append(payload)

        return Response({"results": results}, status=status.HTTP_200_OK)

    def _fetch_daily_temperature(self, date: str, latitude: float, longitude: float):
        base_payload = {
            "date": date,
            "available": False,
            "temperature_c": None,
        }

        for url in (self.OPEN_METEO_ARCHIVE_URL, self.OPEN_METEO_FORECAST_URL):
            try:
                response = requests.get(
                    url,
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "start_date": date,
                        "end_date": date,
                        "daily": "temperature_2m_max,temperature_2m_min",
                        "timezone": "UTC",
                    },
                    timeout=8,
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException:
                continue
            except ValueError:
                continue

            daily = data.get("daily") or {}
            max_values = daily.get("temperature_2m_max") or []
            min_values = daily.get("temperature_2m_min") or []
            if not max_values or not min_values:
                continue

            try:
                avg = (float(max_values[0]) + float(min_values[0])) / 2
            except (TypeError, ValueError, IndexError):
                continue

            return {
                "date": date,
                "available": True,
                "temperature_c": round(avg, 1),
            }

        logger.info(
            "No weather data available for date=%s lat=%s lon=%s",
            date,
            latitude,
            longitude,
        )
        return base_payload

    def _cache_key(self, date: str, latitude: float, longitude: float) -> str:
        rounded_lat = round(latitude, 3)
        rounded_lon = round(longitude, 3)
        raw = f"{date}:{rounded_lat}:{rounded_lon}"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return f"weather_daily:{digest}"

    def _parse_date(self, value: str):
        try:
            return date_cls.fromisoformat(value)
        except ValueError:
            return None
