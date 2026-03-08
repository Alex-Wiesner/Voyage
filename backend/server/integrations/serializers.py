from .models import (
    EncryptionConfigurationError,
    ImmichIntegration,
    UserAPIKey,
    UserRecommendationPreferenceProfile,
)
from rest_framework import serializers


class ImmichIntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImmichIntegration
        fields = "__all__"
        read_only_fields = ["id", "user"]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation.pop("user", None)
        return representation


class UserAPIKeySerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=True, allow_blank=False)
    masked_api_key = serializers.CharField(read_only=True)

    class Meta:
        model = UserAPIKey
        fields = [
            "id",
            "provider",
            "api_key",
            "masked_api_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "masked_api_key", "created_at", "updated_at"]

    def validate_provider(self, value):
        return (value or "").strip().lower()

    def create(self, validated_data):
        api_key = validated_data.pop("api_key")
        user = self.context["request"].user
        instance = UserAPIKey(user=user, **validated_data)
        try:
            instance.set_api_key(api_key)
        except EncryptionConfigurationError as exc:
            raise serializers.ValidationError({"api_key": str(exc)}) from exc
        instance.save()
        return instance

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if api_key is not None:
            try:
                instance.set_api_key(api_key)
            except EncryptionConfigurationError as exc:
                raise serializers.ValidationError({"api_key": str(exc)}) from exc
        instance.save()
        return instance

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation.pop("api_key", None)
        return representation


class UserRecommendationPreferenceProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserRecommendationPreferenceProfile
        fields = [
            "id",
            "cuisines",
            "interests",
            "trip_style",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
