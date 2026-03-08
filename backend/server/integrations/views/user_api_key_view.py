from rest_framework import viewsets
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated

from integrations.models import (
    EncryptionConfigurationError,
    UserAPIKey,
    get_field_fernet,
)
from integrations.serializers import UserAPIKeySerializer


class APIKeyConfigurationError(APIException):
    status_code = 503
    default_detail = (
        "API key storage is unavailable due to server encryption configuration."
    )
    default_code = "api_key_encryption_unavailable"


class UserAPIKeyViewSet(viewsets.ModelViewSet):
    serializer_class = UserAPIKeySerializer
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        try:
            get_field_fernet()
        except EncryptionConfigurationError as exc:
            raise APIKeyConfigurationError(detail=str(exc)) from exc
        return super().initial(request, *args, **kwargs)

    def get_queryset(self):
        return UserAPIKey.objects.filter(user=self.request.user).order_by("provider")
