import uuid

from django.conf import settings
from django.db import models


class ChatConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_conversations",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.title or 'Untitled'} ({self.user.username})"


class ChatMessage(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
        ("tool", "Tool"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, default="")
    tool_calls = models.JSONField(null=True, blank=True)
    tool_call_id = models.CharField(max_length=255, blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ChatSystemPrompt(models.Model):
    """Admin-editable system prompt for the travel assistant.

    Only one instance should exist (singleton pattern via Django admin).
    The prompt text replaces the hardcoded base prompt in get_system_prompt().
    Dynamic user/party preference injection is appended automatically.
    """

    prompt_text = models.TextField(
        help_text="Base system prompt for the travel assistant. "
        "User and party travel preferences are appended automatically."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Chat System Prompt"
        verbose_name_plural = "Chat System Prompt"

    def __str__(self):
        return f"System Prompt (updated {self.updated_at})"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Return the singleton instance or None if not configured."""
        try:
            return cls.objects.get(pk=1)
        except cls.DoesNotExist:
            return None
