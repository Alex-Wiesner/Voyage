from django.contrib import admin
from allauth.account.decorators import secure_admin_login
from django.utils.html import format_html

from .models import (
    ImmichIntegration,
    StravaToken,
    WandererIntegration,
    UserAPIKey,
    UserRecommendationPreferenceProfile,
)

admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)

admin.site.register(ImmichIntegration)
admin.site.register(StravaToken)
admin.site.register(WandererIntegration)


@admin.register(UserAPIKey)
class UserAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "masked_value", "updated_at")
    search_fields = ("user__username", "provider")
    readonly_fields = (
        "user",
        "provider",
        "masked_value",
        "created_at",
        "updated_at",
    )
    exclude = ("encrypted_api_key",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="API key")
    def masked_value(self, obj):
        return format_html("<code>{}</code>", obj.masked_api_key)


admin.site.register(UserRecommendationPreferenceProfile)
