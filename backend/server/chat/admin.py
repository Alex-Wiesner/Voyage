from django.contrib import admin
from django.db import models
from django.forms import Textarea

from .models import ChatConversation, ChatMessage, ChatSystemPrompt


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "updated_at", "created_at")
    search_fields = ("title", "user__username")
    list_filter = ("created_at", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "name", "created_at")
    search_fields = ("conversation__id", "content", "name")
    list_filter = ("role", "created_at")


@admin.register(ChatSystemPrompt)
class ChatSystemPromptAdmin(admin.ModelAdmin):
    readonly_fields = ("updated_at",)
    formfield_overrides = {
        models.TextField: {"widget": Textarea(attrs={"rows": 20, "cols": 120})},
    }

    def has_add_permission(self, request):
        return not ChatSystemPrompt.objects.exists()
