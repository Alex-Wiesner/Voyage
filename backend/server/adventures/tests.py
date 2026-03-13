import json
import tempfile
import base64
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from adventures.models import (
    Collection,
    CollectionItineraryItem,
    ContentImage,
    Lodging,
    Note,
    Transportation,
)
from adventures.utils.weather import fetch_daily_temperature


User = get_user_model()


class WeatherViewTests(APITestCase):
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

    @patch("adventures.views.weather_view.WeatherViewSet._fetch_daily_temperature")
    def test_daily_temperatures_future_date_reaches_fetch_path(
        self, mock_fetch_temperature
    ):
        future_date = (timezone.now().date() + timedelta(days=10)).isoformat()
        mock_fetch_temperature.return_value = {
            "date": future_date,
            "available": True,
            "temperature_low_c": 19.0,
            "temperature_high_c": 26.0,
            "temperature_c": 22.5,
            "is_estimate": False,
            "source": "forecast",
        }

        response = self.client.post(
            "/api/weather/daily-temperatures/",
            {"days": [{"date": future_date, "latitude": 12.34, "longitude": 56.78}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["date"], future_date)
        self.assertTrue(response.json()["results"][0]["available"])
        self.assertEqual(response.json()["results"][0]["temperature_low_c"], 19.0)
        self.assertEqual(response.json()["results"][0]["temperature_high_c"], 26.0)
        self.assertFalse(response.json()["results"][0]["is_estimate"])
        self.assertEqual(response.json()["results"][0]["source"], "forecast")
        self.assertEqual(response.json()["results"][0]["temperature_c"], 22.5)
        mock_fetch_temperature.assert_called_once_with(future_date, 12.34, 56.78)

    @patch("adventures.utils.weather.requests.get")
    def test_daily_temperatures_far_future_uses_historical_estimate(
        self, mock_requests_get
    ):
        future_date = (timezone.now().date() + timedelta(days=3650)).isoformat()

        archive_no_data = Mock()
        archive_no_data.raise_for_status.return_value = None
        archive_no_data.json.return_value = {"daily": {}}

        forecast_no_data = Mock()
        forecast_no_data.raise_for_status.return_value = None
        forecast_no_data.json.return_value = {"daily": {}}

        historical_data = Mock()
        historical_data.raise_for_status.return_value = None
        historical_data.json.return_value = {
            "daily": {
                "temperature_2m_max": [15.0, 18.0, 20.0],
                "temperature_2m_min": [7.0, 9.0, 11.0],
            }
        }

        call_sequence = [archive_no_data, forecast_no_data, historical_data]

        def mock_get(*args, **kwargs):
            if call_sequence:
                return call_sequence.pop(0)
            return historical_data

        mock_requests_get.side_effect = mock_get

        response = self.client.post(
            "/api/weather/daily-temperatures/",
            {"days": [{"date": future_date, "latitude": 12.34, "longitude": 56.78}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertTrue(result["available"])
        self.assertEqual(result["date"], future_date)
        self.assertEqual(result["temperature_low_c"], 9.0)
        self.assertEqual(result["temperature_high_c"], 17.7)
        self.assertEqual(result["temperature_c"], 13.3)
        self.assertTrue(result["is_estimate"])
        self.assertEqual(result["source"], "historical_estimate")
        self.assertGreaterEqual(mock_requests_get.call_count, 3)

    @patch("adventures.utils.weather.requests.get")
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
        self.assertEqual(response.json()["results"][0]["temperature_low_c"], 10.0)
        self.assertEqual(response.json()["results"][0]["temperature_high_c"], 20.0)
        self.assertFalse(response.json()["results"][0]["is_estimate"])
        self.assertEqual(response.json()["results"][0]["source"], "archive")
        self.assertEqual(response.json()["results"][0]["temperature_c"], 15.0)


class WeatherHelperTests(TestCase):
    @patch("adventures.utils.weather.requests.get")
    def test_fetch_daily_temperature_returns_unavailable_when_all_sources_fail(
        self, mock_requests_get
    ):
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {"daily": {}}
        mock_requests_get.return_value = mocked_response

        result = fetch_daily_temperature(
            date=(timezone.now().date() + timedelta(days=6000)).isoformat(),
            latitude=40.7128,
            longitude=-74.0060,
        )

        self.assertEqual(
            result,
            {
                "date": result["date"],
                "available": False,
                "temperature_low_c": None,
                "temperature_high_c": None,
                "temperature_c": None,
                "is_estimate": False,
                "source": None,
            },
        )


class MCPAuthTests(APITestCase):
    def test_mcp_unauthenticated_access_is_rejected(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.post("/api/mcp", {}, format="json")
        self.assertIn(response.status_code, [401, 403])


class LocationPayloadHardeningTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="location-hardening-user",
            email="location-hardening@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=self.user)

    def test_create_location_truncates_overlong_name_and_location(self):
        overlong_name = "N" * 250
        overlong_location = "L" * 250

        response = self.client.post(
            "/api/locations/",
            {
                "name": overlong_name,
                "location": overlong_location,
                "is_public": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["name"]), 200)
        self.assertEqual(len(response.data["location"]), 200)
        self.assertEqual(response.data["name"], overlong_name[:200])
        self.assertEqual(response.data["location"], overlong_location[:200])

    def test_create_location_accepts_high_precision_coordinates(self):
        response = self.client.post(
            "/api/locations/",
            {
                "name": "Precision test",
                "is_public": False,
                "latitude": 51.5007292,
                "longitude": -0.1246254,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["latitude"], "51.500729")
        self.assertEqual(response.data["longitude"], "-0.124625")


class CollectionViewSetTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="collection-owner",
            email="owner@example.com",
            password="password123",
        )
        self.shared_user = User.objects.create_user(
            username="collection-shared",
            email="shared@example.com",
            password="password123",
        )

    def _create_test_image_file(self, name="test.png"):
        # 1x1 PNG
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Y9x8AAAAASUVORK5CYII="
        )
        return SimpleUploadedFile(name, png_bytes, content_type="image/png")

    def _create_collection_with_non_location_images(self):
        collection = Collection.objects.create(
            user=self.owner,
            name="Image fallback collection",
        )

        lodging = Lodging.objects.create(
            user=self.owner,
            collection=collection,
            name="Fallback lodge",
        )
        transportation = Transportation.objects.create(
            user=self.owner,
            collection=collection,
            type="car",
            name="Fallback ride",
        )

        lodging_content_type = ContentType.objects.get_for_model(Lodging)
        transportation_content_type = ContentType.objects.get_for_model(Transportation)

        ContentImage.objects.create(
            user=self.owner,
            content_type=lodging_content_type,
            object_id=lodging.id,
            image=self._create_test_image_file("lodging.png"),
            is_primary=True,
        )
        ContentImage.objects.create(
            user=self.owner,
            content_type=transportation_content_type,
            object_id=transportation.id,
            image=self._create_test_image_file("transport.png"),
            is_primary=True,
        )

        return collection

    def test_list_includes_lodging_transportation_images_when_no_location_images(self):
        collection = self._create_collection_with_non_location_images()

        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/collections/")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data.get("results", [])), 0)

        collection_payload = next(
            item
            for item in response.data["results"]
            if item["id"] == str(collection.id)
        )
        self.assertIn("location_images", collection_payload)
        self.assertGreater(len(collection_payload["location_images"]), 0)
        self.assertTrue(
            any(
                image.get("is_primary")
                for image in collection_payload["location_images"]
            )
        )

    def test_shared_endpoint_includes_non_location_primary_images(self):
        collection = self._create_collection_with_non_location_images()
        collection.shared_with.add(self.shared_user)

        self.client.force_authenticate(user=self.shared_user)
        response = self.client.get("/api/collections/shared/")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

        collection_payload = next(
            item for item in response.data if item["id"] == str(collection.id)
        )
        self.assertEqual(str(collection.id), collection_payload["id"])
        self.assertIn("location_images", collection_payload)
        self.assertGreater(len(collection_payload["location_images"]), 0)
        first_image = collection_payload["location_images"][0]
        self.assertSetEqual(
            set(first_image.keys()),
            {"id", "image", "is_primary", "user", "immich_id"},
        )


class ExportCollectionsBackupCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="backup-user",
            email="backup@example.com",
            password="password123",
        )
        self.collaborator = User.objects.create_user(
            username="collab-user",
            email="collab@example.com",
            password="password123",
        )
        self.collection = Collection.objects.create(
            user=self.user,
            name="My Trip",
            description="Backup test collection",
        )
        self.collection.shared_with.add(self.collaborator)

        note = Note.objects.create(user=self.user, name="Test item")
        note_content_type = ContentType.objects.get_for_model(Note)
        CollectionItineraryItem.objects.create(
            collection=self.collection,
            content_type=note_content_type,
            object_id=note.id,
            date=timezone.now().date(),
            is_global=False,
            order=1,
        )

    def test_export_collections_backup_writes_expected_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "collections_snapshot.json"

            call_command("export_collections_backup", output=str(output_file))

            self.assertTrue(output_file.exists())
            payload = json.loads(output_file.read_text(encoding="utf-8"))

            self.assertEqual(payload["backup_type"], "collections_snapshot")
            self.assertIn("timestamp", payload)
            self.assertEqual(payload["counts"]["collections"], 1)
            self.assertEqual(payload["counts"]["collection_itinerary_items"], 1)
            self.assertEqual(len(payload["collections"]), 1)
            self.assertEqual(len(payload["collection_itinerary_items"]), 1)
            self.assertEqual(
                payload["collections"][0]["shared_with_ids"],
                [self.collaborator.id],
            )

    def test_export_collections_backup_raises_for_missing_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_directory = Path(temp_dir) / "missing"
            output_file = missing_directory / "collections_snapshot.json"

            with self.assertRaises(CommandError):
                call_command("export_collections_backup", output=str(output_file))
