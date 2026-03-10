import json
from unittest import mock
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITransactionTestCase

from adventures.models import Collection, CollectionItineraryItem, Location
from chat.agent_tools import (
    add_to_itinerary,
    execute_tool,
    get_trip_details,
    web_search,
)
from chat.views import ChatViewSet


User = get_user_model()


class WebSearchToolFailureClassificationTests(TestCase):
    def test_web_search_import_error_sets_retryable_false(self):
        import builtins

        original_import = builtins.__import__

        def controlled_import(name, *args, **kwargs):
            if name == "duckduckgo_search":
                raise ImportError("missing dependency")
            return original_import(name, *args, **kwargs)

        user = User.objects.create_user(
            username="chat-web-search-user",
            email="chat-web-search-user@example.com",
            password="password123",
        )

        with mock.patch("builtins.__import__", side_effect=controlled_import):
            result = web_search(user, query="best restaurants")

        self.assertEqual(
            result.get("error"),
            "Web search is not available (duckduckgo-search not installed)",
        )
        self.assertEqual(result.get("retryable"), False)


class ExecuteToolErrorSanitizationTests(TestCase):
    def test_execute_tool_catch_all_returns_sanitized_error_message(self):
        def raising_tool(user):
            raise RuntimeError("sensitive backend detail")

        user = User.objects.create_user(
            username="chat-tool-sanitize-user",
            email="chat-tool-sanitize-user@example.com",
            password="password123",
        )

        with mock.patch.dict(
            "chat.agent_tools._REGISTERED_TOOLS", {"boom": raising_tool}
        ):
            result = execute_tool("boom", user)

        self.assertEqual(result, {"error": "Tool execution failed"})


class ChatAgentToolSharedTripAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="chat-owner",
            email="chat-owner@example.com",
            password="password123",
        )
        self.shared_user = User.objects.create_user(
            username="chat-shared",
            email="chat-shared@example.com",
            password="password123",
        )
        self.non_member = User.objects.create_user(
            username="chat-non-member",
            email="chat-non-member@example.com",
            password="password123",
        )
        self.collection = Collection.objects.create(
            user=self.owner,
            name="Shared Trip",
        )
        self.collection.shared_with.add(self.shared_user)

    def test_get_trip_details_allows_owner_access(self):
        result = get_trip_details(self.owner, collection_id=str(self.collection.id))

        self.assertIn("trip", result)
        self.assertEqual(result["trip"]["id"], str(self.collection.id))
        self.assertEqual(result["trip"]["name"], self.collection.name)

    def test_get_trip_details_allows_shared_user_access(self):
        result = get_trip_details(
            self.shared_user, collection_id=str(self.collection.id)
        )

        self.assertIn("trip", result)
        self.assertEqual(result["trip"]["id"], str(self.collection.id))

    def test_get_trip_details_owner_also_in_shared_with_avoids_duplicates(self):
        self.collection.shared_with.add(self.owner)

        result = get_trip_details(self.owner, collection_id=str(self.collection.id))

        self.assertIn("trip", result)
        self.assertEqual(result["trip"]["id"], str(self.collection.id))

    @patch("adventures.models.background_geocode_and_assign")
    def test_add_to_itinerary_allows_shared_user_access(self, _mock_background_geocode):
        result = add_to_itinerary(
            self.shared_user,
            collection_id=str(self.collection.id),
            name="Eiffel Tower",
            latitude=48.85837,
            longitude=2.294481,
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result["location"]["name"], "Eiffel Tower")
        self.assertTrue(
            CollectionItineraryItem.objects.filter(
                id=result["itinerary_item"]["id"],
                collection=self.collection,
            ).exists()
        )

    @patch("adventures.models.background_geocode_and_assign")
    def test_add_to_itinerary_owner_also_in_shared_with_avoids_duplicates(
        self,
        _mock_background_geocode,
    ):
        self.collection.shared_with.add(self.owner)

        result = add_to_itinerary(
            self.owner,
            collection_id=str(self.collection.id),
            name="Louvre Museum",
            latitude=48.860611,
            longitude=2.337644,
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result["location"]["name"], "Louvre Museum")

    @patch("adventures.models.background_geocode_and_assign")
    def test_non_member_access_remains_denied(self, _mock_background_geocode):
        trip_result = get_trip_details(
            self.non_member,
            collection_id=str(self.collection.id),
        )
        itinerary_result = add_to_itinerary(
            self.non_member,
            collection_id=str(self.collection.id),
            name="Should Fail",
            latitude=48.85837,
            longitude=2.294481,
        )

        self.assertEqual(
            trip_result,
            {
                "error": "collection_id is required and must reference a trip you can access"
            },
        )
        self.assertEqual(itinerary_result, {"error": "Trip not found"})


class ChatViewSetToolValidationBoundaryTests(TestCase):
    def test_trip_context_destination_summary_normalizes_to_first_segment(self):
        self.assertEqual(
            ChatViewSet._trip_context_search_location(
                "A; B; +1 more",
                ["Fallback City"],
            ),
            "A",
        )

    def test_dates_is_required_matches_required_param_short_circuit(self):
        self.assertTrue(
            ChatViewSet._is_required_param_tool_error({"error": "dates is required"})
        )

    def test_dates_non_empty_list_error_does_not_match_required_param_short_circuit(
        self,
    ):
        self.assertFalse(
            ChatViewSet._is_required_param_tool_error(
                {"error": "dates must be a non-empty list"}
            )
        )

    def test_collection_access_error_does_not_short_circuit_required_param_regex(self):
        error_text = (
            "collection_id is required and must reference a trip you can access"
        )

        self.assertFalse(
            ChatViewSet._is_required_param_tool_error({"error": error_text})
        )
        self.assertFalse(
            ChatViewSet._is_required_param_tool_error_message_content(
                json.dumps({"error": error_text})
            )
        )

    def test_search_places_missing_location_error_detected_for_clarification(self):
        self.assertTrue(
            ChatViewSet._is_search_places_missing_location_required_error(
                "search_places",
                {"error": "location is required"},
            )
        )

    def test_non_search_places_required_error_not_detected_for_clarification(self):
        self.assertFalse(
            ChatViewSet._is_search_places_missing_location_required_error(
                "web_search",
                {"error": "query is required"},
            )
        )

    def test_execution_failure_error_detected(self):
        self.assertTrue(
            ChatViewSet._is_execution_failure_tool_error(
                {"error": "Web search failed. Please try again."}
            )
        )

    def test_required_error_not_treated_as_execution_failure(self):
        self.assertFalse(
            ChatViewSet._is_execution_failure_tool_error(
                {"error": "location is required"}
            )
        )

    def test_search_places_geocode_error_detected_for_location_retry(self):
        self.assertTrue(
            ChatViewSet._is_search_places_location_retry_candidate_error(
                "search_places",
                {"error": "Could not geocode location: ???"},
            )
        )

    def test_retryable_execution_failure_defaults_true(self):
        self.assertTrue(
            ChatViewSet._is_retryable_execution_failure({"error": "Temporary outage"})
        )

    def test_retryable_execution_failure_honors_false_flag(self):
        self.assertFalse(
            ChatViewSet._is_retryable_execution_failure(
                {"error": "Not installed", "retryable": False}
            )
        )

    def test_likely_location_reply_heuristic_positive_case(self):
        self.assertTrue(ChatViewSet._is_likely_location_reply("london"))

    def test_likely_location_reply_heuristic_negative_question(self):
        self.assertFalse(ChatViewSet._is_likely_location_reply("where should I go?"))

    def test_likely_location_reply_heuristic_negative_long_sentence(self):
        self.assertFalse(
            ChatViewSet._is_likely_location_reply(
                "I am not sure what city yet, maybe something with beaches and nice museums"
            )
        )

    def test_infer_search_places_category_detects_restaurant_intent(self):
        self.assertEqual(
            ChatViewSet._infer_search_places_category(
                "Can you find restaurants for dinner?",
                [],
            ),
            "food",
        )

    def test_infer_search_places_category_detects_prior_message_dining_intent(self):
        self.assertEqual(
            ChatViewSet._infer_search_places_category(
                "What are the top picks?",
                ["We want good cafes nearby"],
            ),
            "food",
        )

    def test_infer_search_places_category_leaves_non_dining_intent_unchanged(self):
        self.assertIsNone(
            ChatViewSet._infer_search_places_category(
                "Find great museums and landmarks",
                ["We love cultural attractions"],
            )
        )


class ChatViewSetSearchPlacesClarificationTests(APITransactionTestCase):
    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_missing_search_place_location_streams_clarifying_content(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-clarify-user",
            email="chat-clarify-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Clarification Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def mock_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = mock_stream
        mock_execute_tool.return_value = {"error": "location is required"}

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {"message": "Find good places"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")

        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]

        done_count = sum(1 for payload in payload_lines if payload == "[DONE]")
        self.assertEqual(done_count, 1)

        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]
        self.assertTrue(any("content" in payload for payload in json_payloads))
        self.assertFalse(
            any(payload.get("error_category") for payload in json_payloads)
        )

        content_payload = next(
            payload for payload in json_payloads if "content" in payload
        )
        self.assertIn("specific location", content_payload["content"].lower())

        clarifying_message = (
            user.chat_conversations.get(id=conversation_id)
            .messages.filter(role="assistant")
            .order_by("created_at")
            .last()
        )
        self.assertIsNotNone(clarifying_message)
        self.assertIn("specific location", clarifying_message.content.lower())

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_missing_location_retry_uses_user_reply_and_avoids_clarification_loop(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-location-retry-user",
            email="chat-location-retry-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Location Retry Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def first_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def second_stream(*args, **kwargs):
            yield 'data: {"content": "Great, here are top spots in London."}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = [first_stream(), second_stream()]
        mock_execute_tool.side_effect = [
            {"error": "location is required"},
            {"results": [{"name": "British Museum"}]},
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {"message": "london"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]
        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]

        self.assertTrue(any("tool_result" in payload for payload in json_payloads))
        self.assertTrue(
            any(
                payload.get("content") == "Great, here are top spots in London."
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(
                "specific location" in payload.get("content", "").lower()
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(payload.get("error_category") for payload in json_payloads)
        )

        self.assertEqual(mock_execute_tool.call_count, 2)
        self.assertEqual(
            mock_execute_tool.call_args_list[1].kwargs.get("location"), "london"
        )

        assistant_messages = user.chat_conversations.get(
            id=conversation_id
        ).messages.filter(role="assistant")
        self.assertFalse(
            any(
                "specific location" in message.content.lower()
                for message in assistant_messages
            )
        )

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_collection_context_retry_uses_destination_and_food_category_for_restaurants(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-context-retry-user",
            email="chat-context-retry-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        collection = Collection.objects.create(user=user, name="Rome Food Trip")
        trip_stop = Location.objects.create(
            user=user,
            name="Trevi Fountain",
            location="Rome, Italy",
        )
        collection.locations.add(trip_stop)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Collection Context Retry Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def first_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def second_stream(*args, **kwargs):
            yield 'data: {"content": "Here are restaurant options in Rome."}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = [first_stream(), second_stream()]
        mock_execute_tool.side_effect = [
            {"error": "location is required"},
            {"results": [{"name": "Roscioli"}]},
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "Find great restaurants for dinner",
                "collection_id": str(collection.id),
                "collection_name": collection.name,
                "destination": "Rome, Italy",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]
        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]

        self.assertTrue(any("tool_result" in payload for payload in json_payloads))
        self.assertTrue(
            any(
                payload.get("content") == "Here are restaurant options in Rome."
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(
                "specific location" in payload.get("content", "").lower()
                for payload in json_payloads
            )
        )

        self.assertEqual(mock_execute_tool.call_count, 2)
        first_call_kwargs = mock_execute_tool.call_args_list[0].kwargs
        second_call_kwargs = mock_execute_tool.call_args_list[1].kwargs
        self.assertEqual(first_call_kwargs.get("category"), "food")
        self.assertEqual(second_call_kwargs.get("category"), "food")
        self.assertEqual(second_call_kwargs.get("location"), "Rome, Italy")

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_collection_context_retry_extracts_city_from_fallback_address(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-city-extract-user",
            email="chat-city-extract-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        collection = Collection.objects.create(user=user, name="London Food Trip")
        trip_stop = Location.objects.create(
            user=user,
            name="Turnstile",
            location="Little Turnstile 6, London",
        )
        collection.locations.add(trip_stop)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Fallback City Extraction Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def first_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def second_stream(*args, **kwargs):
            yield 'data: {"content": "Here are options in London."}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = [first_stream(), second_stream()]
        mock_execute_tool.side_effect = [
            {"error": "location is required"},
            {"results": [{"name": "Rules Restaurant"}]},
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "Find restaurants",
                "collection_id": str(collection.id),
                "collection_name": collection.name,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        # Consume the streaming response before checking mock call counts;
        # the event_stream generator only runs when streaming_content is iterated.
        list(response.streaming_content)
        self.assertEqual(mock_execute_tool.call_count, 2)
        second_call_kwargs = mock_execute_tool.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("location"), "London")

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_trip_context_retry_uses_normalized_summary_destination_for_search_places(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-summary-retry-user",
            email="chat-summary-retry-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Summary Destination Retry Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def first_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def second_stream(*args, **kwargs):
            yield 'data: {"content": "I found places in Paris."}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = [first_stream(), second_stream()]
        mock_execute_tool.side_effect = [
            {"error": "location is required"},
            {"results": [{"name": "Louvre Museum"}]},
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "Find top attractions",
                "destination": "Paris, France; Rome, Italy; +1 more",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]
        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]

        self.assertTrue(any("tool_result" in payload for payload in json_payloads))
        self.assertTrue(
            any(
                payload.get("content") == "I found places in Paris."
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(
                "specific location" in payload.get("content", "").lower()
                for payload in json_payloads
            )
        )

        self.assertEqual(mock_execute_tool.call_count, 2)
        second_call_kwargs = mock_execute_tool.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("location"), "Paris, France")

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_geocode_failure_retries_with_trip_context_location(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-geocode-retry-user",
            email="chat-geocode-retry-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Geocode Retry Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def first_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def second_stream(*args, **kwargs):
            yield 'data: {"content": "Here are options in Lisbon."}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = [first_stream(), second_stream()]
        mock_execute_tool.side_effect = [
            {"error": "Could not geocode location: invalid"},
            {"results": [{"name": "Time Out Market"}]},
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "Find restaurants",
                "destination": "Lisbon, Portugal",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]
        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]

        self.assertTrue(any("tool_result" in payload for payload in json_payloads))
        self.assertTrue(
            any(
                payload.get("content") == "Here are options in Lisbon."
                for payload in json_payloads
            )
        )
        self.assertEqual(mock_execute_tool.call_count, 2)
        second_call_kwargs = mock_execute_tool.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("location"), "Lisbon, Portugal")


class ChatViewSetToolExecutionFailureLoopTests(APITransactionTestCase):
    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_all_failure_rounds_stop_with_execution_error_before_tool_cap(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-loop-failure-user",
            email="chat-loop-failure-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Failure Loop Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def failing_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_w", "type": "function", "function": {"name": "web_search", "arguments": "{\\"query\\":\\"restaurants\\"}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = failing_stream
        mock_execute_tool.return_value = {
            "error": "Web search failed. Please try again.",
            "results": [],
        }

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {"message": "Find restaurants near me"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]
        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]

        self.assertTrue(
            any(
                payload.get("error_category") == "tool_execution_error"
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(
                payload.get("error_category") == "tool_loop_limit"
                for payload in json_payloads
            )
        )
        self.assertFalse(any("tool_result" in payload for payload in json_payloads))
        self.assertEqual(mock_stream_chat_completion.call_count, 3)
        self.assertEqual(mock_execute_tool.call_count, 3)

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_permanent_execution_failure_stops_immediately(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-permanent-failure-user",
            email="chat-permanent-failure-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Permanent Failure Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def failing_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_w", "type": "function", "function": {"name": "web_search", "arguments": "{\\"query\\":\\"restaurants\\"}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = failing_stream
        mock_execute_tool.return_value = {
            "error": "Web search is not available (duckduckgo-search not installed)",
            "results": [],
            "retryable": False,
        }

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {"message": "Find restaurants near me"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]
        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]

        self.assertTrue(
            any(
                payload.get("error_category") == "tool_execution_error"
                for payload in json_payloads
            )
        )
        self.assertEqual(mock_stream_chat_completion.call_count, 1)
        self.assertEqual(mock_execute_tool.call_count, 1)

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_context_retry_failure_does_not_emit_location_clarification(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="chat-retry-no-clarify-user",
            email="chat-retry-no-clarify-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Retry Failure No Clarify Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def failing_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_s", "type": "function", "function": {"name": "search_places", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = failing_stream
        mock_execute_tool.side_effect = [
            {"error": "location is required"},
            {"error": "location is required"},
            {"error": "location is required"},
            {"error": "location is required"},
            {"error": "location is required"},
            {"error": "location is required"},
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "Find restaurants",
                "destination": "Lisbon, Portugal",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        chunks = [
            chunk.decode("utf-8")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
            for chunk in response.streaming_content
        ]
        payload_lines = [
            chunk.strip()[len("data: ") :]
            for chunk in chunks
            if chunk.strip().startswith("data: ")
        ]
        json_payloads = [
            json.loads(payload) for payload in payload_lines if payload != "[DONE]"
        ]

        self.assertTrue(
            any(
                payload.get("error_category") == "tool_execution_error"
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(
                "specific location" in payload.get("content", "").lower()
                for payload in json_payloads
            )
        )
