import hashlib
from datetime import date as date_cls

from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from adventures.utils.weather import fetch_daily_temperature


class WeatherViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
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
                    {
                        "date": None,
                        "available": False,
                        "temperature_low_c": None,
                        "temperature_high_c": None,
                        "temperature_c": None,
                        "is_estimate": False,
                        "source": None,
                    }
                )
                continue

            date = entry.get("date")
            latitude = entry.get("latitude")
            longitude = entry.get("longitude")

            if not date or latitude is None or longitude is None:
                results.append(
                    {
                        "date": date,
                        "available": False,
                        "temperature_low_c": None,
                        "temperature_high_c": None,
                        "temperature_c": None,
                        "is_estimate": False,
                        "source": None,
                    }
                )
                continue

            parsed_date = self._parse_date(date)
            if parsed_date is None:
                results.append(
                    {
                        "date": date,
                        "available": False,
                        "temperature_low_c": None,
                        "temperature_high_c": None,
                        "temperature_c": None,
                        "is_estimate": False,
                        "source": None,
                    }
                )
                continue

            try:
                lat = float(latitude)
                lon = float(longitude)
            except (TypeError, ValueError):
                results.append(
                    {
                        "date": date,
                        "available": False,
                        "temperature_low_c": None,
                        "temperature_high_c": None,
                        "temperature_c": None,
                        "is_estimate": False,
                        "source": None,
                    }
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
        return fetch_daily_temperature(
            date=date, latitude=latitude, longitude=longitude
        )

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
