from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase


User = get_user_model()


class WeatherEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="weather-user",
            email="weather@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=self.user)
        cache.clear()

    def test_daily_temperatures_rejects_too_many_days(self):
        payload = {
            "days": [
                {"date": "2026-01-01", "latitude": 10, "longitude": 10}
                for _ in range(61)
            ]
        }

        response = self.client.post(
            "/api/weather/daily-temperatures/", payload, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("maximum", response.json().get("error", "").lower())

    @patch("adventures.views.weather_view.requests.get")
    def test_daily_temperatures_future_date_returns_unavailable_without_external_call(
        self, mock_requests_get
    ):
        future_date = (timezone.now().date() + timedelta(days=10)).isoformat()

        response = self.client.post(
            "/api/weather/daily-temperatures/",
            {"days": [{"date": future_date, "latitude": 12.34, "longitude": 56.78}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"][0],
            {"date": future_date, "available": False, "temperature_c": None},
        )
        mock_requests_get.assert_not_called()

    @patch("adventures.views.weather_view.requests.get")
    def test_daily_temperatures_accepts_zero_lat_lon(self, mock_requests_get):
        today = timezone.now().date().isoformat()
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {
            "daily": {
                "temperature_2m_max": [20.0],
                "temperature_2m_min": [10.0],
            }
        }
        mock_requests_get.return_value = mocked_response

        response = self.client.post(
            "/api/weather/daily-temperatures/",
            {"days": [{"date": today, "latitude": 0, "longitude": 0}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["date"], today)
        self.assertTrue(response.json()["results"][0]["available"])
        self.assertEqual(response.json()["results"][0]["temperature_c"], 15.0)


class RecommendationPhotoProxyValidationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reco-user",
            email="reco@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=self.user)

    def test_google_photo_rejects_invalid_photo_name(self):
        response = self.client.get(
            "/api/recommendations/google-photo/?photo_name=invalid-photo-name"
        )
        self.assertEqual(response.status_code, 400)

    def test_google_photo_rejects_trailing_newline_photo_name(self):
        response = self.client.get(
            "/api/recommendations/google-photo/?photo_name=places/abc/photos/def%0A"
        )
        self.assertEqual(response.status_code, 400)


class MCPAuthTests(APITestCase):
    def test_mcp_unauthenticated_access_is_rejected(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.post("/api/mcp", {}, format="json")
        self.assertIn(response.status_code, [401, 403])
