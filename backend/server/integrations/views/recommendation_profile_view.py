from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from integrations.models import UserRecommendationPreferenceProfile
from integrations.serializers import UserRecommendationPreferenceProfileSerializer


class UserRecommendationPreferenceProfileViewSet(viewsets.ModelViewSet):
    serializer_class = UserRecommendationPreferenceProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserRecommendationPreferenceProfile.objects.filter(
            user=self.request.user
        )

    def list(self, request, *args, **kwargs):
        instance = self.get_queryset().first()
        if not instance:
            return Response([], status=status.HTTP_200_OK)
        serializer = self.get_serializer(instance)
        return Response([serializer.data], status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        existing = UserRecommendationPreferenceProfile.objects.filter(
            user=self.request.user
        ).first()
        if existing:
            for field, value in serializer.validated_data.items():
                setattr(existing, field, value)
            existing.save()
            self._upserted_instance = existing
            return

        self._upserted_instance = serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        output = self.get_serializer(self._upserted_instance)
        return Response(output.data, status=status.HTTP_200_OK)
