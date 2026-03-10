import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITransactionTestCase

from adventures.models import Collection, CollectionItineraryItem, Location
from chat.agent_tools import add_to_itinerary, get_trip_details
from chat.views import ChatViewSet


User = get_user_model()


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
