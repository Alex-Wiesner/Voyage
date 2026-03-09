import asyncio
import json
import logging

from asgiref.sync import sync_to_async
from adventures.models import Collection
from django.http import StreamingHttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..agent_tools import AGENT_TOOLS, execute_tool, serialize_tool_result
from ..llm_client import (
    get_provider_catalog,
    get_system_prompt,
    is_chat_provider_available,
    stream_chat_completion,
)
from ..models import ChatConversation, ChatMessage
from ..serializers import ChatConversationSerializer

logger = logging.getLogger(__name__)


class ChatViewSet(viewsets.ModelViewSet):
    serializer_class = ChatConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ChatConversation.objects.filter(user=self.request.user).prefetch_related(
            "messages"
        )

    def list(self, request, *args, **kwargs):
        conversations = self.get_queryset().only("id", "title", "updated_at")
        data = [
            {
                "id": str(conversation.id),
                "title": conversation.title,
                "updated_at": conversation.updated_at,
            }
            for conversation in conversations
        ]
        return Response(data)

    def create(self, request, *args, **kwargs):
        conversation = ChatConversation.objects.create(
            user=request.user,
            title=(request.data.get("title") or "").strip(),
        )
        serializer = self.get_serializer(conversation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _build_llm_messages(self, conversation, user, system_prompt=None):
        messages = [
            {
                "role": "system",
                "content": system_prompt or get_system_prompt(user),
            }
        ]
        for message in conversation.messages.all().order_by("created_at"):
            payload = {
                "role": message.role,
                "content": message.content,
            }
            if message.role == "assistant" and message.tool_calls:
                payload["tool_calls"] = message.tool_calls
            if message.role == "tool":
                payload["tool_call_id"] = message.tool_call_id
                payload["name"] = message.name
            messages.append(payload)
        return messages

    def _async_to_sync_generator(self, async_gen):
        loop = asyncio.new_event_loop()
        try:
            while True:
                try:
                    yield loop.run_until_complete(async_gen.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    @staticmethod
    def _merge_tool_call_delta(accumulator, tool_calls_delta):
        for idx, tool_call in enumerate(tool_calls_delta or []):
            idx = tool_call.get("index", idx)
            while len(accumulator) <= idx:
                accumulator.append(
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                )

            current = accumulator[idx]
            if tool_call.get("id"):
                current["id"] = tool_call.get("id")
            if tool_call.get("type"):
                current["type"] = tool_call.get("type")

            function_data = tool_call.get("function") or {}
            if function_data.get("name"):
                current["function"]["name"] = function_data.get("name")
            if function_data.get("arguments"):
                current["function"]["arguments"] += function_data.get("arguments")

    @action(detail=True, methods=["post"])
    def send_message(self, request, pk=None):
        # Auto-learn preferences from user's travel history
        from integrations.utils.auto_profile import update_auto_preference_profile

        try:
            update_auto_preference_profile(request.user)
        except Exception as exc:
            logger.warning("Auto-profile update failed: %s", exc)
            # Continue anyway - not critical

        conversation = self.get_object()
        user_content = (request.data.get("message") or "").strip()
        if not user_content:
            return Response(
                {"error": "message is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider = (request.data.get("provider") or "openai").strip().lower()
        model = (request.data.get("model") or "").strip() or None
        collection_id = request.data.get("collection_id")
        collection_name = request.data.get("collection_name")
        start_date = request.data.get("start_date")
        end_date = request.data.get("end_date")
        destination = request.data.get("destination")
        if not is_chat_provider_available(provider):
            return Response(
                {"error": f"Provider is not available for chat: {provider}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        context_parts = []
        if collection_name:
            context_parts.append(f"Trip: {collection_name}")
        if destination:
            context_parts.append(f"Destination: {destination}")
        if start_date and end_date:
            context_parts.append(f"Dates: {start_date} to {end_date}")

        collection = None
        if collection_id:
            try:
                requested_collection = Collection.objects.get(id=collection_id)
                if (
                    requested_collection.user == request.user
                    or requested_collection.shared_with.filter(
                        id=request.user.id
                    ).exists()
                ):
                    collection = requested_collection
            except Collection.DoesNotExist:
                pass

        system_prompt = get_system_prompt(request.user, collection)
        if context_parts:
            system_prompt += "\n\n## Trip Context\n" + "\n".join(context_parts)

        ChatMessage.objects.create(
            conversation=conversation,
            role="user",
            content=user_content,
        )
        conversation.save(update_fields=["updated_at"])

        if not conversation.title:
            conversation.title = user_content[:120]
            conversation.save(update_fields=["title", "updated_at"])

        llm_messages = self._build_llm_messages(
            conversation,
            request.user,
            system_prompt=system_prompt,
        )

        MAX_TOOL_ITERATIONS = 10

        async def event_stream():
            current_messages = list(llm_messages)
            encountered_error = False
            tool_iterations = 0

            while tool_iterations < MAX_TOOL_ITERATIONS:
                content_chunks = []
                tool_calls_accumulator = []

                async for chunk in stream_chat_completion(
                    request.user,
                    current_messages,
                    provider,
                    tools=AGENT_TOOLS,
                    model=model,
                ):
                    if not chunk.startswith("data: "):
                        yield chunk
                        continue

                    payload = chunk[len("data: ") :].strip()
                    if payload == "[DONE]":
                        continue

                    yield chunk

                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        encountered_error = True
                        break

                    if data.get("content"):
                        content_chunks.append(data["content"])

                    if data.get("tool_calls"):
                        self._merge_tool_call_delta(
                            tool_calls_accumulator,
                            data["tool_calls"],
                        )

                if encountered_error:
                    break

                assistant_content = "".join(content_chunks)

                if tool_calls_accumulator:
                    assistant_with_tools = {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": tool_calls_accumulator,
                    }
                    current_messages.append(assistant_with_tools)

                    await sync_to_async(
                        ChatMessage.objects.create, thread_sensitive=True
                    )(
                        conversation=conversation,
                        role="assistant",
                        content=assistant_content,
                        tool_calls=tool_calls_accumulator,
                    )
                    await sync_to_async(conversation.save, thread_sensitive=True)(
                        update_fields=["updated_at"]
                    )

                    for tool_call in tool_calls_accumulator:
                        function_payload = tool_call.get("function") or {}
                        function_name = function_payload.get("name") or ""
                        raw_arguments = function_payload.get("arguments") or "{}"

                        try:
                            arguments = json.loads(raw_arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                        if not isinstance(arguments, dict):
                            arguments = {}

                        result = await sync_to_async(
                            execute_tool, thread_sensitive=True
                        )(
                            function_name,
                            request.user,
                            **arguments,
                        )
                        result_content = serialize_tool_result(result)

                        current_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id"),
                                "name": function_name,
                                "content": result_content,
                            }
                        )

                        await sync_to_async(
                            ChatMessage.objects.create, thread_sensitive=True
                        )(
                            conversation=conversation,
                            role="tool",
                            content=result_content,
                            tool_call_id=tool_call.get("id"),
                            name=function_name,
                        )
                        await sync_to_async(conversation.save, thread_sensitive=True)(
                            update_fields=["updated_at"]
                        )

                        tool_event = {
                            "tool_result": {
                                "tool_call_id": tool_call.get("id"),
                                "name": function_name,
                                "result": result,
                            }
                        }
                        yield f"data: {json.dumps(tool_event)}\n\n"

                    continue

                await sync_to_async(ChatMessage.objects.create, thread_sensitive=True)(
                    conversation=conversation,
                    role="assistant",
                    content=assistant_content,
                )
                await sync_to_async(conversation.save, thread_sensitive=True)(
                    update_fields=["updated_at"]
                )
                yield "data: [DONE]\n\n"
                break

        response = StreamingHttpResponse(
            streaming_content=self._async_to_sync_generator(event_stream()),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class ChatProviderCatalogViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response(get_provider_catalog(user=request.user))

    @action(detail=True, methods=["get"])
    def models(self, request, pk=None):
        """Fetch available models from a provider's API."""
        from chat.llm_client import get_llm_api_key

        provider = (pk or "").lower()

        api_key = get_llm_api_key(request.user, provider)
        if not api_key:
            return Response(
                {"error": "No API key configured for this provider"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            if provider == "openai":
                import openai

                client = openai.OpenAI(api_key=api_key)
                models = client.models.list()
                chat_models = [
                    model.id
                    for model in models
                    if any(prefix in model.id for prefix in ["gpt-", "o1-", "chatgpt"])
                ]
                return Response({"models": sorted(set(chat_models), reverse=True)})

            if provider in ["anthropic", "claude"]:
                return Response(
                    {
                        "models": [
                            "claude-sonnet-4-20250514",
                            "claude-opus-4-20250514",
                            "claude-3-5-sonnet-20241022",
                            "claude-3-5-haiku-20241022",
                            "claude-3-haiku-20240307",
                        ]
                    }
                )

            if provider in ["gemini", "google"]:
                return Response(
                    {
                        "models": [
                            "gemini-2.0-flash",
                            "gemini-1.5-pro",
                            "gemini-1.5-flash",
                            "gemini-1.5-flash-8b",
                        ]
                    }
                )

            if provider in ["groq"]:
                return Response(
                    {
                        "models": [
                            "llama-3.3-70b-versatile",
                            "llama-3.1-70b-versatile",
                            "llama-3.1-8b-instant",
                            "mixtral-8x7b-32768",
                        ]
                    }
                )

            if provider in ["ollama"]:
                import requests

                try:
                    response = requests.get(
                        "http://localhost:11434/api/tags", timeout=5
                    )
                    if response.ok:
                        data = response.json()
                        models = [item["name"] for item in data.get("models", [])]
                        return Response({"models": models})
                except Exception:
                    pass
                return Response({"models": []})

            if provider in ["opencode_zen"]:
                return Response({"models": ["openai/gpt-5-nano"]})

            return Response({"models": []})
        except Exception as exc:
            logger.error("Failed to fetch models for %s: %s", provider, exc)
            return Response(
                {"error": f"Failed to fetch models: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


from .capabilities import CapabilitiesView
from .day_suggestions import DaySuggestionsView
