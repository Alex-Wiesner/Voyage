from django.contrib import admin

from .models import ChatConversation, ChatMessage


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
