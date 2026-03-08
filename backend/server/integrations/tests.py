from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase


User = get_user_model()


class UserAPIKeyConfigurationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="api-key-user",
            email="apikey@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=self.user)

    @override_settings(FIELD_ENCRYPTION_KEY="")
    def test_api_key_endpoint_missing_encryption_key_is_graceful(self):
        response = self.client.get("/api/integrations/api-keys/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("FIELD_ENCRYPTION_KEY", response.json().get("detail", ""))

    @override_settings(FIELD_ENCRYPTION_KEY="invalid-key")
    def test_api_key_endpoint_invalid_encryption_key_is_graceful(self):
        response = self.client.get("/api/integrations/api-keys/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("invalid", response.json().get("detail", "").lower())

    @override_settings(FIELD_ENCRYPTION_KEY="")
    @patch("adventures.views.recommendations_view.requests.get")
    def test_google_photo_uses_graceful_fallback_when_user_key_unreadable(
        self, mock_requests_get
    ):
        from integrations.models import UserAPIKey

        # Legacy/bad row exists but cannot be decrypted due to missing key.
        UserAPIKey.objects.create(
            user=self.user,
            provider="google_maps",
            encrypted_api_key="not-a-valid-fernet-token",
        )

        response = self.client.get(
            "/api/recommendations/google-photo/?photo_name=places/abc/photos/def"
        )

        # Should fail gracefully as misconfigured key path, not crash (500).
        self.assertEqual(response.status_code, 400)
        self.assertIn("not configured", response.json().get("error", "").lower())
        mock_requests_get.assert_not_called()


class UserAPIKeyCreateBehaviorTests(APITestCase):
    @override_settings(
        FIELD_ENCRYPTION_KEY="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    )
    def setUp(self):
        self.user = User.objects.create_user(
            username="api-key-create-user",
            email="apikey-create@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=self.user)

    @override_settings(
        FIELD_ENCRYPTION_KEY="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    )
    def test_duplicate_provider_post_updates_existing_key(self):
        first_response = self.client.post(
            "/api/integrations/api-keys/",
            {"provider": "google_maps", "api_key": "first-secret"},
            format="json",
        )
        self.assertEqual(first_response.status_code, 201)

        second_response = self.client.post(
            "/api/integrations/api-keys/",
            {"provider": "google_maps", "api_key": "second-secret"},
            format="json",
        )

        self.assertEqual(second_response.status_code, 201)

        from integrations.models import UserAPIKey

        records = UserAPIKey.objects.filter(user=self.user, provider="google_maps")
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().get_api_key(), "second-secret")

    @override_settings(
        FIELD_ENCRYPTION_KEY="YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    )
    def test_provider_is_normalized_and_still_upserts(self):
        self.client.post(
            "/api/integrations/api-keys/",
            {"provider": "Google_Maps", "api_key": "first-secret"},
            format="json",
        )

        response = self.client.post(
            "/api/integrations/api-keys/",
            {"provider": "  google_maps  ", "api_key": "rotated-secret"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        from integrations.models import UserAPIKey

        records = UserAPIKey.objects.filter(user=self.user, provider="google_maps")
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().get_api_key(), "rotated-secret")
