from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase


User = get_user_model()


class MCPTokenEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mcp-token-user",
            email="mcp-token@example.com",
            password="password123",
        )

    def test_requires_authentication(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get("/auth/mcp-token/")
        self.assertIn(response.status_code, [401, 403])

    def test_returns_token_for_authenticated_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/auth/mcp-token/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())
        self.assertTrue(Token.objects.filter(user=self.user).exists())

    def test_reuses_existing_token(self):
        existing_token = Token.objects.create(user=self.user)

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/auth/mcp-token/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("token"), existing_token.key)
        self.assertEqual(Token.objects.filter(user=self.user).count(), 1)
