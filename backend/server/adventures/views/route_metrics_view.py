import hashlib
import logging
import math
from urllib.parse import urlparse, urlunparse

import requests
from django.conf import settings
from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


logger = logging.getLogger(__name__)


class RouteMetricsViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    MAX_PAIRS = 50
    CACHE_TIMEOUT_SECONDS = 60 * 60 * 24
    WALKING_SPEED_KMH = 5
    DRIVING_SPEED_KMH = 60
    WALKING_THRESHOLD_MINUTES = 20
    OSRM_HEADERS = {"User-Agent": "Voyage Server"}
    OSRM_DEFAULT_BASE_URL = "https://router.project-osrm.org"

    @action(detail=False, methods=["post"])
    def query(self, request):
        pairs = request.data.get("pairs")

        if not isinstance(pairs, list):
            return Response(
                {"error": "'pairs' must be a list"}, status=status.HTTP_400_BAD_REQUEST
            )

        if len(pairs) > self.MAX_PAIRS:
            return Response(
                {
                    "error": f"A maximum of {self.MAX_PAIRS} pairs is allowed per request"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        for index, pair in enumerate(pairs):
            try:
                from_lat, from_lon, to_lat, to_lon = self._parse_pair(pair)
            except ValueError as error:
                logger.warning(
                    "Skipping invalid route-metrics pair at index %s: %s", index, error
                )
                results.append(
                    self._invalid_metrics_result(
                        error_code="invalid_pair", message="Invalid route pair payload"
                    )
                )
                continue

            cache_key = self._build_cache_key(from_lat, from_lon, to_lat, to_lon)
            cached_result = self._safe_cache_get(cache_key)
            if cached_result:
                results.append(cached_result)
                continue

            try:
                result = self._calculate_osrm_metrics(
                    from_lat, from_lon, to_lat, to_lon
                )
            except Exception as error:
                logger.warning(
                    "OSRM metrics unavailable for pair index %s; using haversine fallback (%s)",
                    index,
                    error.__class__.__name__,
                )
                try:
                    result = self._calculate_haversine_fallback(
                        from_lat, from_lon, to_lat, to_lon
                    )
                except Exception as fallback_error:
                    logger.warning(
                        "Haversine fallback failed for pair index %s; returning invalid placeholder (%s)",
                        index,
                        fallback_error.__class__.__name__,
                    )
                    result = self._invalid_metrics_result(
                        error_code="compute_failed",
                        message="Route metrics unavailable",
                    )

            self._safe_cache_set(cache_key, result)
            results.append(result)

        return Response({"results": results})

    def _parse_pair(self, pair):
        if not isinstance(pair, dict):
            raise ValueError("Each pair must be an object")

        from_data = pair.get("from")
        to_data = pair.get("to")
        if not isinstance(from_data, dict) or not isinstance(to_data, dict):
            raise ValueError("Each pair must include 'from' and 'to' objects")

        from_lat = self._parse_coordinate(from_data.get("latitude"), "from.latitude")
        from_lon = self._parse_coordinate(from_data.get("longitude"), "from.longitude")
        to_lat = self._parse_coordinate(to_data.get("latitude"), "to.latitude")
        to_lon = self._parse_coordinate(to_data.get("longitude"), "to.longitude")

        if not (-90 <= from_lat <= 90) or not (-90 <= to_lat <= 90):
            raise ValueError("Latitude must be between -90 and 90")

        if not (-180 <= from_lon <= 180) or not (-180 <= to_lon <= 180):
            raise ValueError("Longitude must be between -180 and 180")

        return from_lat, from_lon, to_lat, to_lon

    def _parse_coordinate(self, value, field_name):
        try:
            coordinate = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be a number")

        if not math.isfinite(coordinate):
            raise ValueError(f"{field_name} must be finite")

        return coordinate

    def _calculate_osrm_metrics(self, from_lat, from_lon, to_lat, to_lon):
        foot_distance_km, foot_duration_minutes = self._query_osrm_route(
            profile="foot",
            from_lat=from_lat,
            from_lon=from_lon,
            to_lat=to_lat,
            to_lon=to_lon,
        )

        if foot_duration_minutes <= self.WALKING_THRESHOLD_MINUTES:
            return self._build_metrics_result(
                distance_km=foot_distance_km,
                duration_minutes=foot_duration_minutes,
                mode="walking",
                source="osrm",
            )

        car_distance_km, car_duration_minutes = self._query_osrm_route(
            profile="car",
            from_lat=from_lat,
            from_lon=from_lon,
            to_lat=to_lat,
            to_lon=to_lon,
        )
        return self._build_metrics_result(
            distance_km=car_distance_km,
            duration_minutes=car_duration_minutes,
            mode="driving",
            source="osrm",
        )

    def _query_osrm_route(self, profile, from_lat, from_lon, to_lat, to_lon):
        base_url = self._get_validated_osrm_base_url()
        route_coords = f"{from_lon},{from_lat};{to_lon},{to_lat}"
        base_parts = urlparse(base_url)
        base_path = base_parts.path.rstrip("/")
        route_path = f"{base_path}/route/v1/{profile}/{route_coords}"
        url = urlunparse(
            (
                base_parts.scheme,
                base_parts.netloc,
                route_path,
                "",
                "",
                "",
            )
        )

        response = requests.get(
            url,
            params={"overview": "false"},
            headers=self.OSRM_HEADERS,
            timeout=(2, 5),
        )
        response.raise_for_status()

        data = response.json()
        routes = data.get("routes") or []
        if not routes:
            raise ValueError("OSRM route response missing routes")

        route = routes[0]
        distance_meters = route.get("distance")
        duration_seconds = route.get("duration")

        if not isinstance(distance_meters, (int, float)) or not math.isfinite(
            distance_meters
        ):
            raise ValueError("OSRM route distance is invalid")
        if not isinstance(duration_seconds, (int, float)) or not math.isfinite(
            duration_seconds
        ):
            raise ValueError("OSRM route duration is invalid")

        distance_km = max(distance_meters / 1000, 0)
        duration_minutes = max(duration_seconds / 60, 0)
        return distance_km, duration_minutes

    def _calculate_haversine_fallback(self, from_lat, from_lon, to_lat, to_lon):
        distance_km = self._haversine_distance_km(from_lat, from_lon, to_lat, to_lon)
        walking_minutes = (distance_km / self.WALKING_SPEED_KMH) * 60
        driving_minutes = (distance_km / self.DRIVING_SPEED_KMH) * 60
        use_driving = walking_minutes > self.WALKING_THRESHOLD_MINUTES

        return self._build_metrics_result(
            distance_km=distance_km,
            duration_minutes=driving_minutes if use_driving else walking_minutes,
            mode="driving" if use_driving else "walking",
            source="haversine",
        )

    def _haversine_distance_km(self, from_lat, from_lon, to_lat, to_lon):
        earth_radius_km = 6371

        lat_delta = math.radians(to_lat - from_lat)
        lon_delta = math.radians(to_lon - from_lon)
        from_lat_radians = math.radians(from_lat)
        to_lat_radians = math.radians(to_lat)

        a = (
            math.sin(lat_delta / 2) ** 2
            + math.cos(from_lat_radians)
            * math.cos(to_lat_radians)
            * math.sin(lon_delta / 2) ** 2
        )
        a = min(max(a, 0.0), 1.0)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return max(earth_radius_km * c, 0)

    def _get_validated_osrm_base_url(self):
        configured_base_url = (
            getattr(settings, "OSRM_BASE_URL", self.OSRM_DEFAULT_BASE_URL)
            or self.OSRM_DEFAULT_BASE_URL
        )
        parsed = urlparse(configured_base_url)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            logger.warning(
                "Invalid OSRM_BASE_URL configured; falling back to haversine metrics"
            )
            raise ValueError("invalid_osrm_base_url")

        normalized_path = parsed.path.rstrip("/")
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                normalized_path,
                "",
                "",
                "",
            )
        )

    def _invalid_metrics_result(self, error_code, message):
        return {
            "distance_km": None,
            "duration_minutes": None,
            "distance_label": None,
            "duration_label": None,
            "mode": None,
            "source": "invalid",
            "error": error_code,
            "message": message,
        }

    def _build_metrics_result(self, distance_km, duration_minutes, mode, source):
        safe_distance = max(distance_km, 0)
        safe_duration = max(duration_minutes, 0)
        rounded_distance = round(safe_distance, 2)
        rounded_duration = int(round(safe_duration))

        return {
            "distance_km": rounded_distance,
            "duration_minutes": rounded_duration,
            "distance_label": self._format_distance_label(safe_distance),
            "duration_label": self._format_duration_label(safe_duration),
            "mode": mode,
            "source": source,
        }

    def _format_distance_label(self, distance_km):
        if distance_km < 10:
            return f"{distance_km:.1f} km"
        return f"{int(round(distance_km))} km"

    def _format_duration_label(self, minutes):
        safe_minutes = max(0, int(round(minutes)))
        hours = safe_minutes // 60
        remaining_minutes = safe_minutes % 60

        if hours == 0:
            return f"{remaining_minutes}m"
        if remaining_minutes == 0:
            return f"{hours}h"
        return f"{hours}h {remaining_minutes}m"

    def _build_cache_key(self, from_lat, from_lon, to_lat, to_lon):
        raw = (
            f"{from_lat:.6f},{from_lon:.6f}:{to_lat:.6f},{to_lon:.6f}"
            f":walk={self.WALKING_THRESHOLD_MINUTES}"
        )
        hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"route_metrics:{hashed}"

    def _safe_cache_get(self, key):
        try:
            return cache.get(key)
        except Exception as error:
            logger.warning("Route metrics cache get failed: %s", error)
            return None

    def _safe_cache_set(self, key, value):
        try:
            cache.set(key, value, self.CACHE_TIMEOUT_SECONDS)
        except Exception as error:
            logger.warning("Route metrics cache set failed: %s", error)
