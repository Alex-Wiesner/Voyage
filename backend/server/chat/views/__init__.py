import asyncio
import json
import logging
import re

from asgiref.sync import sync_to_async
from adventures.models import Collection
from django.http import StreamingHttpResponse
from integrations.models import UserAISettings
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
        ordered_messages = list(conversation.messages.all().order_by("created_at"))
        valid_tool_call_ids = {
            message.tool_call_id
            for message in ordered_messages
            if message.role == "tool"
            and message.tool_call_id
            and not self._is_required_param_tool_error_message_content(message.content)
            and not self._is_execution_failure_tool_error_message_content(
                message.content
            )
        }

        messages = [
            {
                "role": "system",
                "content": system_prompt or get_system_prompt(user),
            }
        ]
        for message in ordered_messages:
            if (
                message.role == "tool"
                and self._is_required_param_tool_error_message_content(message.content)
            ):
                continue
            if (
                message.role == "tool"
                and self._is_execution_failure_tool_error_message_content(
                    message.content
                )
            ):
                continue

            payload = {
                "role": message.role,
                "content": message.content,
            }
            if message.role == "assistant" and message.tool_calls:
                filtered_tool_calls = [
                    tool_call
                    for tool_call in message.tool_calls
                    if (tool_call or {}).get("id") in valid_tool_call_ids
                ]
                if filtered_tool_calls:
                    payload["tool_calls"] = filtered_tool_calls
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

    @staticmethod
    def _is_required_param_tool_error(result):
        if not isinstance(result, dict):
            return False

        error_text = result.get("error")
        if not isinstance(error_text, str):
            return False

        normalized_error = error_text.strip().lower()
        if normalized_error in {"location is required", "query is required"}:
            return True

        return bool(
            re.fullmatch(
                r"[a-z0-9_,\-\s]+ (is|are) required",
                normalized_error,
            )
        )

    @classmethod
    def _is_execution_failure_tool_error(cls, result):
        if not isinstance(result, dict):
            return False

        error_text = result.get("error")
        if not isinstance(error_text, str) or not error_text.strip():
            return False

        return not cls._is_required_param_tool_error(result)

    @staticmethod
    def _is_retryable_execution_failure(result):
        if not isinstance(result, dict):
            return False

        return result.get("retryable", True) is not False

    @classmethod
    def _is_required_param_tool_error_message_content(cls, content):
        if not isinstance(content, str):
            return False

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return False

        return cls._is_required_param_tool_error(parsed)

    @classmethod
    def _is_execution_failure_tool_error_message_content(cls, content):
        if not isinstance(content, str):
            return False

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return False

        return cls._is_execution_failure_tool_error(parsed)

    @staticmethod
    def _build_required_param_error_event(tool_name, result):
        tool_error = result.get("error") if isinstance(result, dict) else ""
        return {
            "error": (
                "The assistant attempted to call "
                f"'{tool_name}' without required arguments ({tool_error}). "
                "Please try your message again with more specific details."
            ),
            "error_category": "tool_validation_error",
        }

    @classmethod
    def _is_search_places_missing_location_required_error(cls, tool_name, result):
        if tool_name != "search_places" or not cls._is_required_param_tool_error(
            result
        ):
            return False

        error_text = (result or {}).get("error") if isinstance(result, dict) else ""
        if not isinstance(error_text, str):
            return False

        normalized_error = error_text.strip().lower()
        return "location" in normalized_error

    @staticmethod
    def _is_search_places_geocode_error(tool_name, result):
        if tool_name != "search_places" or not isinstance(result, dict):
            return False

        error_text = result.get("error")
        if not isinstance(error_text, str):
            return False

        return error_text.strip().lower().startswith("could not geocode location")

    @classmethod
    def _is_search_places_location_retry_candidate_error(cls, tool_name, result):
        return cls._is_search_places_missing_location_required_error(
            tool_name,
            result,
        ) or cls._is_search_places_geocode_error(tool_name, result)

    @staticmethod
    def _build_search_places_location_clarification_message():
        return (
            "Could you share the specific location you'd like me to search near "
            "(city, neighborhood, or address)? I can also focus on food, "
            "activities, or lodging."
        )

    @staticmethod
    def _build_tool_execution_error_event(tool_name, result):
        tool_error = (
            (result or {}).get("error")
            if isinstance(result, dict)
            else "Tool execution failed"
        )
        return {
            "error": (
                f"The assistant could not complete '{tool_name}' ({tool_error}). "
                "Please try again in a moment or adjust your request."
            ),
            "error_category": "tool_execution_error",
        }

    @staticmethod
    def _normalize_trip_context_destination(destination):
        destination_text = (destination or "").strip()
        if not destination_text:
            return ""

        if ";" not in destination_text:
            if re.fullmatch(r"\+\d+\s+more", destination_text, re.IGNORECASE):
                return ""
            return destination_text

        for segment in destination_text.split(";"):
            segment_text = segment.strip()
            if not segment_text:
                continue

            if re.fullmatch(r"\+\d+\s+more", segment_text, re.IGNORECASE):
                continue

            return segment_text

        return ""

    @classmethod
    def _trip_context_search_location(cls, destination, itinerary_stops):
        destination_text = cls._normalize_trip_context_destination(destination)
        if destination_text:
            return destination_text

        for stop in itinerary_stops or []:
            stop_text = (stop or "").strip()
            if stop_text:
                return stop_text

        return ""

    @staticmethod
    def _infer_search_places_category(user_content, prior_user_messages):
        message_parts = [(user_content or "").strip()]
        message_parts.extend(
            (content or "").strip() for content in prior_user_messages or []
        )
        normalized = " ".join(part for part in message_parts if part).lower()
        if not normalized:
            return None

        dining_intent_pattern = (
            r"\b(restaurant|restaurants|dining|dinner|lunch|breakfast|brunch|"
            r"cafe|cafes|food|eat|eating|cuisine|meal|meals|bistro|bar|bars)\b"
        )
        if re.search(dining_intent_pattern, normalized):
            return "food"

        return None

    # Verbs that indicate a command/request rather than a location reply.
    _COMMAND_VERBS = frozenset(
        [
            "find",
            "search",
            "show",
            "get",
            "look",
            "give",
            "tell",
            "help",
            "recommend",
            "suggest",
            "list",
            "fetch",
            "what",
            "where",
            "which",
            "who",
            "how",
            "can",
            "could",
            "would",
            "please",
        ]
    )

    @classmethod
    def _is_likely_location_reply(cls, user_content):
        if not isinstance(user_content, str):
            return False

        normalized = user_content.strip()
        if not normalized:
            return False

        if normalized.endswith("?"):
            return False

        if len(normalized) > 80:
            return False

        parts = normalized.split()
        if len(parts) > 6:
            return False

        # Exclude messages that start with a command/request verb — those are
        # original requests, not replies to a "where?" clarification prompt.
        first_word = parts[0].lower().rstrip(".,!;:")
        if first_word in cls._COMMAND_VERBS:
            return False

        return bool(re.search(r"[a-z0-9]", normalized, re.IGNORECASE))

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

        requested_provider = (request.data.get("provider") or "").strip().lower()
        requested_model = (request.data.get("model") or "").strip() or None
        ai_settings = UserAISettings.objects.filter(user=request.user).first()
        preferred_provider = (
            (ai_settings.preferred_provider or "").strip().lower()
            if ai_settings
            else ""
        )
        preferred_model = (
            (ai_settings.preferred_model or "").strip() if ai_settings else ""
        )

        provider = requested_provider
        if not provider and preferred_provider:
            if preferred_provider and is_chat_provider_available(preferred_provider):
                provider = preferred_provider

        if not provider:
            provider = "openai"

        model = requested_model
        if model is None and preferred_model and provider == preferred_provider:
            model = preferred_model

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
        itinerary_stops = []
        if collection_name:
            context_parts.append(f"Trip: {collection_name}")
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

        if collection:
            context_parts.append(
                "Collection UUID (use this exact collection_id for get_trip_details and add_to_itinerary): "
                f"{collection.id}"
            )
            seen_stops = set()
            for location in collection.locations.select_related(
                "city", "country"
            ).all():
                city_name = (getattr(location.city, "name", "") or "").strip()
                country_name = (getattr(location.country, "name", "") or "").strip()

                if city_name or country_name:
                    stop_label = (
                        f"{city_name}, {country_name}"
                        if city_name and country_name
                        else city_name or country_name
                    )
                    stop_key = f"geo:{city_name.lower()}|{country_name.lower()}"
                else:
                    fallback_name = (location.location or location.name or "").strip()
                    if not fallback_name:
                        continue
                    # When city/country FKs are not set, try to extract a geocodable
                    # city name from a comma-separated address string.
                    # e.g. "Little Turnstile 6, London" → "London"
                    # e.g. "Kingsway 58, London" → "London"
                    if "," in fallback_name:
                        parts = [p.strip() for p in fallback_name.split(",")]
                        # Last non-empty, non-purely-numeric segment is typically the city
                        city_hint = next(
                            (p for p in reversed(parts) if p and not p.isdigit()),
                            None,
                        )
                        stop_label = city_hint if city_hint else fallback_name
                    else:
                        stop_label = fallback_name
                    stop_key = f"name:{stop_label.lower()}"

                if stop_key in seen_stops:
                    continue

                seen_stops.add(stop_key)
                itinerary_stops.append(stop_label)

                if len(itinerary_stops) >= 8:
                    break

            if itinerary_stops:
                context_parts.append(f"Itinerary stops: {'; '.join(itinerary_stops)}")

        trip_context_location = self._trip_context_search_location(
            destination, itinerary_stops
        )
        if trip_context_location:
            context_parts.append(f"Destination: {trip_context_location}")
        prior_user_messages = list(
            conversation.messages.filter(role="user")
            .order_by("-created_at")
            .values_list("content", flat=True)[:3]
        )

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
        MAX_ALL_FAILURE_ROUNDS = 3

        async def event_stream():
            current_messages = list(llm_messages)
            encountered_error = False
            tool_iterations = 0
            all_failure_rounds = 0

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
                    yield "data: [DONE]\n\n"
                    break

                assistant_content = "".join(content_chunks)

                if tool_calls_accumulator:
                    successful_tool_calls = []
                    successful_tool_messages = []
                    successful_tool_chat_entries = []
                    first_execution_failure = None
                    encountered_permanent_failure = False

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

                        prepared_arguments = dict(arguments)
                        tool_call_for_history = tool_call

                        if function_name == "search_places":
                            if not (prepared_arguments.get("category") or "").strip():
                                inferred_category = self._infer_search_places_category(
                                    user_content,
                                    prior_user_messages,
                                )
                                if inferred_category:
                                    prepared_arguments["category"] = inferred_category

                            if prepared_arguments != arguments:
                                tool_call_for_history = {
                                    **tool_call,
                                    "function": {
                                        **function_payload,
                                        "name": function_name,
                                        "arguments": json.dumps(prepared_arguments),
                                    },
                                }

                        result = await sync_to_async(
                            execute_tool, thread_sensitive=True
                        )(
                            function_name,
                            request.user,
                            **prepared_arguments,
                        )

                        attempted_location_retry = False
                        if self._is_search_places_location_retry_candidate_error(
                            function_name,
                            result,
                        ):
                            retry_locations = []
                            if trip_context_location:
                                retry_locations.append(trip_context_location)
                            if self._is_likely_location_reply(user_content):
                                retry_locations.append(user_content)

                            seen_retry_locations = set()
                            for retry_location in retry_locations:
                                normalized_retry_location = (
                                    retry_location.strip().lower()
                                )
                                if (
                                    not normalized_retry_location
                                    or normalized_retry_location in seen_retry_locations
                                ):
                                    continue
                                seen_retry_locations.add(normalized_retry_location)
                                attempted_location_retry = True

                                retry_arguments = dict(prepared_arguments)
                                retry_arguments["location"] = retry_location
                                retry_result = await sync_to_async(
                                    execute_tool,
                                    thread_sensitive=True,
                                )(
                                    function_name,
                                    request.user,
                                    **retry_arguments,
                                )

                                if not self._is_required_param_tool_error(
                                    retry_result
                                ) and not self._is_execution_failure_tool_error(
                                    retry_result
                                ):
                                    result = retry_result
                                    tool_call_for_history = {
                                        **tool_call,
                                        "function": {
                                            **function_payload,
                                            "name": function_name,
                                            "arguments": json.dumps(retry_arguments),
                                        },
                                    }
                                    break

                            # If we attempted context retries but all failed, convert
                            # to an execution failure so we never ask the user for a
                            # location they already implied via itinerary context.
                            if (
                                attempted_location_retry
                                and self._is_required_param_tool_error(result)
                            ):
                                result = {
                                    "error": "Could not search places at the provided itinerary locations"
                                }

                        if self._is_required_param_tool_error(result):
                            assistant_message_kwargs = {
                                "conversation": conversation,
                                "role": "assistant",
                                "content": assistant_content,
                            }
                            if successful_tool_calls:
                                assistant_message_kwargs["tool_calls"] = (
                                    successful_tool_calls
                                )

                            await sync_to_async(
                                ChatMessage.objects.create, thread_sensitive=True
                            )(**assistant_message_kwargs)

                            for tool_message in successful_tool_messages:
                                await sync_to_async(
                                    ChatMessage.objects.create,
                                    thread_sensitive=True,
                                )(**tool_message)

                            if (
                                not attempted_location_retry
                                and self._is_search_places_missing_location_required_error(
                                    function_name,
                                    result,
                                )
                            ):
                                clarification_content = self._build_search_places_location_clarification_message()
                                await sync_to_async(
                                    ChatMessage.objects.create,
                                    thread_sensitive=True,
                                )(
                                    conversation=conversation,
                                    role="assistant",
                                    content=clarification_content,
                                )

                                await sync_to_async(
                                    conversation.save,
                                    thread_sensitive=True,
                                )(update_fields=["updated_at"])

                                yield (
                                    "data: "
                                    f"{json.dumps({'content': clarification_content})}"
                                    "\n\n"
                                )
                                yield "data: [DONE]\n\n"
                                return

                            await sync_to_async(
                                conversation.save,
                                thread_sensitive=True,
                            )(update_fields=["updated_at"])

                            logger.info(
                                "Stopping chat tool loop due to required-arg tool validation error: %s (%s)",
                                function_name,
                                result.get("error"),
                            )
                            error_event = self._build_required_param_error_event(
                                function_name,
                                result,
                            )
                            yield f"data: {json.dumps(error_event)}\n\n"
                            yield "data: [DONE]\n\n"
                            return

                        if self._is_execution_failure_tool_error(result):
                            if first_execution_failure is None:
                                first_execution_failure = (function_name, result)
                            if not self._is_retryable_execution_failure(result):
                                encountered_permanent_failure = True
                            continue

                        result_content = serialize_tool_result(result)

                        successful_tool_calls.append(tool_call_for_history)
                        tool_message_payload = {
                            "conversation": conversation,
                            "role": "tool",
                            "content": result_content,
                            "tool_call_id": tool_call_for_history.get("id"),
                            "name": function_name,
                        }
                        successful_tool_messages.append(tool_message_payload)
                        successful_tool_chat_entries.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_for_history.get("id"),
                                "name": function_name,
                                "content": result_content,
                            }
                        )

                        tool_event = {
                            "tool_result": {
                                "tool_call_id": tool_call_for_history.get("id"),
                                "name": function_name,
                                "result": result,
                            }
                        }
                        yield f"data: {json.dumps(tool_event)}\n\n"

                    if not successful_tool_calls and first_execution_failure:
                        if encountered_permanent_failure:
                            all_failure_rounds = MAX_ALL_FAILURE_ROUNDS
                        else:
                            all_failure_rounds += 1

                        if all_failure_rounds >= MAX_ALL_FAILURE_ROUNDS:
                            failed_tool_name, failed_tool_result = (
                                first_execution_failure
                            )
                            error_event = self._build_tool_execution_error_event(
                                failed_tool_name,
                                failed_tool_result,
                            )
                            await sync_to_async(
                                ChatMessage.objects.create,
                                thread_sensitive=True,
                            )(
                                conversation=conversation,
                                role="assistant",
                                content=error_event["error"],
                            )
                            await sync_to_async(
                                conversation.save,
                                thread_sensitive=True,
                            )(update_fields=["updated_at"])
                            yield f"data: {json.dumps(error_event)}\n\n"
                            yield "data: [DONE]\n\n"
                            return

                        continue

                    all_failure_rounds = 0
                    tool_iterations += 1

                    assistant_with_tools = {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": successful_tool_calls,
                    }
                    current_messages.append(assistant_with_tools)
                    current_messages.extend(successful_tool_chat_entries)

                    await sync_to_async(
                        ChatMessage.objects.create, thread_sensitive=True
                    )(
                        conversation=conversation,
                        role="assistant",
                        content=assistant_content,
                        tool_calls=successful_tool_calls,
                    )
                    for tool_message in successful_tool_messages:
                        await sync_to_async(
                            ChatMessage.objects.create,
                            thread_sensitive=True,
                        )(**tool_message)

                    await sync_to_async(conversation.save, thread_sensitive=True)(
                        update_fields=["updated_at"]
                    )

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

            if tool_iterations >= MAX_TOOL_ITERATIONS:
                logger.warning(
                    "Stopping chat tool loop after max iterations (%s)",
                    MAX_TOOL_ITERATIONS,
                )
                payload = {
                    "error": "The assistant stopped after too many tool calls. Please try again with a more specific request.",
                    "error_category": "tool_loop_limit",
                }
                yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"

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
        from chat.llm_client import CHAT_PROVIDER_CONFIG, get_llm_api_key

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

            if provider == "opencode_zen":
                import requests

                config = CHAT_PROVIDER_CONFIG.get("opencode_zen", {})
                api_base = config.get("api_base", "https://opencode.ai/zen/v1")
                response = requests.get(
                    f"{api_base}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )

                if response.ok:
                    data = response.json()
                    raw_models = (
                        data.get("data", data) if isinstance(data, dict) else data
                    )
                    model_ids = []
                    for model_entry in raw_models:
                        if not isinstance(model_entry, dict):
                            continue

                        model_id = model_entry.get("id") or model_entry.get("model_id")
                        if model_id:
                            model_ids.append(model_id)

                    return Response({"models": sorted(set(model_ids))})

                logger.warning(
                    "OpenCode Zen models fetch failed with status %s",
                    response.status_code,
                )
                return Response({"models": []})

            return Response({"models": []})
        except Exception as exc:
            logger.error("Failed to fetch models for %s: %s", provider, exc)
            return Response(
                {"error": f"Failed to fetch models: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


from .capabilities import CapabilitiesView
from .day_suggestions import DaySuggestionsView
