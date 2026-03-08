from django.db import models
from django.contrib.auth import get_user_model
import uuid
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

User = get_user_model()


class EncryptionConfigurationError(Exception):
    pass


def get_field_fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise EncryptionConfigurationError(
            "FIELD_ENCRYPTION_KEY is not configured. API key storage is unavailable."
        )

    key_bytes = key.encode() if isinstance(key, str) else key
    try:
        return Fernet(key_bytes)
    except (TypeError, ValueError) as exc:
        raise EncryptionConfigurationError(
            "FIELD_ENCRYPTION_KEY is invalid. Provide a valid Fernet key."
        ) from exc


class ImmichIntegration(models.Model):
    server_url = models.CharField(max_length=255)
    api_key = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    copy_locally = models.BooleanField(
        default=True,
        help_text="Copy image to local storage, instead of just linking to the remote URL.",
    )
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, primary_key=True
    )

    def __str__(self):
        return self.user.username + " - " + self.server_url


class StravaToken(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="strava_tokens"
    )
    access_token = models.CharField(max_length=255)
    refresh_token = models.CharField(max_length=255)
    expires_at = models.BigIntegerField()  # Unix timestamp
    athlete_id = models.BigIntegerField(null=True, blank=True)
    scope = models.CharField(max_length=255, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class WandererIntegration(models.Model):
    server_url = models.CharField(max_length=255)
    username = models.CharField(max_length=255)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="wanderer_integrations"
    )
    token = models.CharField(null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, primary_key=True
    )

    def __str__(self):
        return self.user.username + " - " + self.server_url

    class Meta:
        verbose_name = "Wanderer Integration"
        verbose_name_plural = "Wanderer Integrations"


class UserAPIKey(models.Model):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, primary_key=True
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys")
    provider = models.CharField(max_length=100)
    encrypted_api_key = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "provider")

    def set_api_key(self, value: str) -> None:
        if value is None:
            raise ValueError("API key cannot be None")
        fernet = get_field_fernet()
        self.encrypted_api_key = fernet.encrypt(value.encode()).decode()

    def get_api_key(self) -> str | None:
        if not self.encrypted_api_key:
            return None
        fernet = get_field_fernet()
        try:
            return fernet.decrypt(self.encrypted_api_key.encode()).decode()
        except (InvalidToken, ValueError):
            return None

    @property
    def masked_api_key(self) -> str:
        plain = self.get_api_key() or ""
        if len(plain) <= 6:
            return "*" * len(plain)
        return f"{plain[:3]}{'*' * (len(plain) - 6)}{plain[-3:]}"


class UserRecommendationPreferenceProfile(models.Model):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, primary_key=True
    )
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="recommendation_profile"
    )
    cuisines = models.TextField(blank=True, null=True)
    interests = models.JSONField(default=list, blank=True)
    trip_style = models.CharField(max_length=120, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
