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
            "temperature_c": 22.5,
        }

        response = self.client.post(
            "/api/weather/daily-temperatures/",
            {"days": [{"date": future_date, "latitude": 12.34, "longitude": 56.78}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["date"], future_date)
        self.assertTrue(response.json()["results"][0]["available"])
        self.assertEqual(response.json()["results"][0]["temperature_c"], 22.5)
        mock_fetch_temperature.assert_called_once_with(future_date, 12.34, 56.78)

    @patch("adventures.views.weather_view.requests.get")
    def test_daily_temperatures_far_future_returns_unavailable_when_upstream_has_no_data(
        self, mock_requests_get
    ):
        future_date = (timezone.now().date() + timedelta(days=3650)).isoformat()
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.json.return_value = {"daily": {}}
        mock_requests_get.return_value = mocked_response

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
        self.assertEqual(mock_requests_get.call_count, 2)

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


class MCPAuthTests(APITestCase):
    def test_mcp_unauthenticated_access_is_rejected(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.post("/api/mcp", {}, format="json")
        self.assertIn(response.status_code, [401, 403])


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
