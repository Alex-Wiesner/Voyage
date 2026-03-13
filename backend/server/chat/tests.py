import json
from datetime import date
from unittest import mock
from unittest.mock import MagicMock, patch

import requests as _requests

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITransactionTestCase

from adventures.models import Collection, CollectionItineraryItem, Location, Visit
from chat.agent_tools import (
    add_to_itinerary,
    execute_tool,
    add_lodging,
    add_transportation,
    get_trip_details,
    move_itinerary_item,
    remove_itinerary_item,
    remove_lodging,
    remove_transportation,
    search_places,
    update_location_details,
    update_lodging,
    update_transportation,
    web_search,
)
from chat.views import ChatViewSet
from chat.views.day_suggestions import DaySuggestionsView


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
    def test_add_to_itinerary_reuses_same_day_location_without_duplicate_rows(
        self,
        _mock_background_geocode,
    ):
        first = add_to_itinerary(
            self.owner,
            collection_id=str(self.collection.id),
            name="Eiffel Tower",
            latitude=48.85837,
            longitude=2.294481,
            date="2026-06-01",
        )
        second = add_to_itinerary(
            self.owner,
            collection_id=str(self.collection.id),
            name="Eiffel Tower",
            latitude=48.858370001,
            longitude=2.294480999,
            date="2026-06-01",
        )

        self.assertTrue(first.get("success"))
        self.assertTrue(second.get("success"))
        self.assertEqual(
            second.get("note"),
            "Location is already in the itinerary for this date",
        )
        self.assertEqual(first["location"]["id"], second["location"]["id"])
        self.assertEqual(first["itinerary_item"]["id"], second["itinerary_item"]["id"])
        self.assertEqual(Location.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(
            CollectionItineraryItem.objects.filter(collection=self.collection).count(),
            1,
        )

    @patch("adventures.models.background_geocode_and_assign")
    def test_add_to_itinerary_allows_reusing_same_location_on_different_dates(
        self,
        _mock_background_geocode,
    ):
        first = add_to_itinerary(
            self.owner,
            collection_id=str(self.collection.id),
            name="Eiffel Tower",
            latitude=48.85837,
            longitude=2.294481,
            date="2026-06-01",
        )
        second = add_to_itinerary(
            self.owner,
            collection_id=str(self.collection.id),
            name="Eiffel Tower",
            latitude=48.858370001,
            longitude=2.294480999,
            date="2026-06-02",
        )

        self.assertTrue(first.get("success"))
        self.assertTrue(second.get("success"))
        self.assertNotIn("note", second)
        self.assertEqual(first["location"]["id"], second["location"]["id"])
        self.assertNotEqual(
            first["itinerary_item"]["id"], second["itinerary_item"]["id"]
        )
        self.assertEqual(Location.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(
            CollectionItineraryItem.objects.filter(collection=self.collection).count(),
            2,
        )

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


class ChatAgentToolItineraryManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="chat-itinerary-owner",
            email="chat-itinerary-owner@example.com",
            password="password123",
        )
        self.shared_user = User.objects.create_user(
            username="chat-itinerary-shared",
            email="chat-itinerary-shared@example.com",
            password="password123",
        )
        self.non_member = User.objects.create_user(
            username="chat-itinerary-non-member",
            email="chat-itinerary-non-member@example.com",
            password="password123",
        )

        self.collection = Collection.objects.create(
            user=self.owner,
            name="Assistant Managed Trip",
        )
        self.collection.shared_with.add(self.shared_user)

        self.location = Location.objects.create(
            user=self.owner,
            name="Existing Stop",
            latitude=48.8566,
            longitude=2.3522,
        )
        self.collection.locations.add(self.location)

        self.location_content_type = ContentType.objects.get_for_model(Location)
        self.day1_item = CollectionItineraryItem.objects.create(
            collection=self.collection,
            content_type=self.location_content_type,
            object_id=self.location.id,
            date="2026-06-01",
            order=0,
            is_global=False,
        )

    def test_move_itinerary_item_allows_shared_user(self):
        result = move_itinerary_item(
            self.shared_user,
            collection_id=str(self.collection.id),
            itinerary_item_id=str(self.day1_item.id),
            date="2026-06-02",
            order=0,
        )

        self.assertTrue(result.get("success"))
        self.day1_item.refresh_from_db()
        self.assertEqual(self.day1_item.date.isoformat(), "2026-06-02")
        self.assertEqual(self.day1_item.order, 0)

    def test_remove_itinerary_item_removes_matching_visit_for_locations(self):
        Visit.objects.create(
            location=self.location,
            start_date="2026-06-01T10:00:00Z",
            end_date="2026-06-01T12:00:00Z",
        )

        result = remove_itinerary_item(
            self.owner,
            collection_id=str(self.collection.id),
            itinerary_item_id=str(self.day1_item.id),
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("deleted_visit_count"), 1)
        self.assertFalse(
            CollectionItineraryItem.objects.filter(id=self.day1_item.id).exists()
        )
        self.assertEqual(Visit.objects.filter(location=self.location).count(), 0)

    def test_update_location_details_scoped_to_collection(self):
        outsider_location = Location.objects.create(
            user=self.owner,
            name="Outside",
            latitude=1.0,
            longitude=1.0,
        )

        denied = update_location_details(
            self.shared_user,
            collection_id=str(self.collection.id),
            location_id=str(outsider_location.id),
            name="Should fail",
        )
        self.assertEqual(denied, {"error": "Location not found in this trip"})

        allowed = update_location_details(
            self.shared_user,
            collection_id=str(self.collection.id),
            location_id=str(self.location.id),
            name="Updated Stop",
            latitude=40.7128,
            longitude=-74.0060,
        )
        self.assertTrue(allowed.get("success"))
        self.location.refresh_from_db()
        self.assertEqual(self.location.name, "Updated Stop")
        self.assertAlmostEqual(float(self.location.latitude), 40.7128, places=4)
        self.assertAlmostEqual(float(self.location.longitude), -74.0060, places=4)

    def test_lodging_management_tools_allow_shared_user(self):
        created = add_lodging(
            self.shared_user,
            collection_id=str(self.collection.id),
            name="River Hotel",
            type="hotel",
            location="Paris",
            check_in="2026-06-02T15:00:00Z",
            check_out="2026-06-04T11:00:00Z",
            latitude=48.85,
            longitude=2.35,
            itinerary_date="2026-06-02",
        )

        self.assertTrue(created.get("success"))
        lodging_id = created["lodging"]["id"]
        self.assertIsNotNone(created.get("itinerary_item"))

        updated = update_lodging(
            self.shared_user,
            collection_id=str(self.collection.id),
            lodging_id=lodging_id,
            name="River Hotel Updated",
            location="Paris Center",
        )
        self.assertTrue(updated.get("success"))
        self.assertEqual(updated["lodging"]["name"], "River Hotel Updated")

        removed = remove_lodging(
            self.shared_user,
            collection_id=str(self.collection.id),
            lodging_id=lodging_id,
        )
        self.assertTrue(removed.get("success"))
        self.assertGreaterEqual(removed.get("removed_itinerary_items", 0), 1)

    def test_transportation_management_tools_allow_shared_user(self):
        created = add_transportation(
            self.shared_user,
            collection_id=str(self.collection.id),
            name="Train to Lyon",
            type="train",
            date="2026-06-03T09:00:00Z",
            end_date="2026-06-03T11:00:00Z",
            from_location="Paris",
            to_location="Lyon",
            origin_latitude=48.8566,
            origin_longitude=2.3522,
            destination_latitude=45.7640,
            destination_longitude=4.8357,
            itinerary_date="2026-06-03",
        )

        self.assertTrue(created.get("success"))
        transportation_id = created["transportation"]["id"]

        updated = update_transportation(
            self.shared_user,
            collection_id=str(self.collection.id),
            transportation_id=transportation_id,
            to_location="Lyon Part-Dieu",
        )
        self.assertTrue(updated.get("success"))
        self.assertEqual(updated["transportation"]["to_location"], "Lyon Part-Dieu")

        removed = remove_transportation(
            self.shared_user,
            collection_id=str(self.collection.id),
            transportation_id=transportation_id,
        )
        self.assertTrue(removed.get("success"))
        self.assertGreaterEqual(removed.get("removed_itinerary_items", 0), 1)

    def test_management_tools_deny_non_member(self):
        move_result = move_itinerary_item(
            self.non_member,
            collection_id=str(self.collection.id),
            itinerary_item_id=str(self.day1_item.id),
            date="2026-06-02",
        )
        remove_result = remove_itinerary_item(
            self.non_member,
            collection_id=str(self.collection.id),
            itinerary_item_id=str(self.day1_item.id),
        )
        update_result = update_location_details(
            self.non_member,
            collection_id=str(self.collection.id),
            location_id=str(self.location.id),
            name="No access",
        )

        self.assertEqual(move_result, {"error": "Trip not found"})
        self.assertEqual(remove_result, {"error": "Trip not found"})
        self.assertEqual(update_result, {"error": "Trip not found"})


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


class SearchPlaces429NonRetryableTests(TestCase):
    """search_places must return retryable=False on HTTP 429."""

    def test_429_response_marks_result_non_retryable(self):
        mock_response = MagicMock()
        mock_response.status_code = 429
        http_error = _requests.HTTPError(response=mock_response)

        with patch("chat.agent_tools.requests.get", side_effect=http_error):
            result = search_places(
                user=None,
                location="Paris, France",
            )

        self.assertIn("error", result)
        self.assertFalse(
            result.get("retryable", True),
            "429 error must set retryable=False to prevent retry spiral",
        )

    def test_non_429_http_error_is_retryable_by_default(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = _requests.HTTPError(response=mock_response)

        with patch("chat.agent_tools.requests.get", side_effect=http_error):
            result = search_places(
                user=None,
                location="Paris, France",
            )

        self.assertIn("error", result)
        self.assertTrue(
            result.get("retryable", True),
            "Non-429 HTTP errors should remain retryable (default=True)",
        )

    def test_generic_request_exception_is_retryable_by_default(self):
        conn_error = _requests.ConnectionError("timeout")

        with patch("chat.agent_tools.requests.get", side_effect=conn_error):
            result = search_places(
                user=None,
                location="Paris, France",
            )

        self.assertIn("error", result)
        self.assertTrue(
            result.get("retryable", True),
            "Generic RequestException should remain retryable",
        )


class GetWeatherCoordFallbackTests(APITransactionTestCase):
    """get_weather lat/lng required param should be retried with collection location coords."""

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_get_weather_retries_with_collection_coordinates(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="weather-coord-user",
            email="weather-coord-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        collection = Collection.objects.create(
            user_id=user.id,
            name="Paris Trip",
        )
        paris_location = Location.objects.create(
            user_id=user.id,
            name="Paris",
            latitude=48.8566,
            longitude=2.3522,
        )
        collection.locations.add(paris_location)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Weather Coord Fallback Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def weather_stream(*args, **kwargs):
            # LLM calls get_weather without coordinates
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_w1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def success_stream(*args, **kwargs):
            yield 'data: {"content": "The weather in Paris is sunny."}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = [weather_stream(), success_stream()]
        mock_execute_tool.side_effect = [
            # First call: no lat/lon
            {"error": "latitude and longitude are required"},
            # Retry call: with injected coords from collection — succeeds
            {"temperature": 22, "condition": "sunny", "location": "Paris"},
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "What's the weather like?",
                "collection_id": str(collection.id),
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
        json_payloads = [json.loads(p) for p in payload_lines if p != "[DONE]"]

        # Verify the retry happened with coordinates (execute_tool called twice)
        self.assertEqual(
            mock_execute_tool.call_count,
            2,
            "Expected exactly 2 execute_tool calls: initial + coord retry",
        )
        # Verify no tool_execution_error surfaced to the user
        self.assertFalse(
            any(
                payload.get("error_category") == "tool_execution_error"
                for payload in json_payloads
            ),
            "Should not emit tool_execution_error when coord retry succeeds",
        )

        # Verify coordinates were passed in the retry call
        retry_kwargs = mock_execute_tool.call_args_list[1][1]
        self.assertAlmostEqual(retry_kwargs.get("latitude"), 48.8566, places=3)
        self.assertAlmostEqual(retry_kwargs.get("longitude"), 2.3522, places=3)

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_get_weather_missing_coords_no_collection_emits_error(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="weather-no-collection-user",
            email="weather-no-collection-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Weather No Collection Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def weather_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_w2", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = weather_stream
        mock_execute_tool.return_value = {
            "error": "latitude and longitude are required"
        }

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {"message": "What's the weather like?"},
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
        json_payloads = [json.loads(p) for p in payload_lines if p != "[DONE]"]

        # No collection means no coord fallback — should emit tool_validation_error
        self.assertTrue(
            any(
                payload.get("error_category") == "tool_validation_error"
                for payload in json_payloads
            ),
            "Should emit tool_validation_error when no collection coords available",
        )

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_get_weather_missing_coords_and_dates_retries_with_collection_dates(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="weather-coord-dates-user",
            email="weather-coord-dates-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        collection = Collection.objects.create(
            user_id=user.id,
            name="Vienna Trip",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
        )
        vienna_location = Location.objects.create(
            user_id=user.id,
            name="Vienna",
            latitude=48.2082,
            longitude=16.3738,
        )
        collection.locations.add(vienna_location)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Weather Coord+Dates Fallback Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def weather_stream(*args, **kwargs):
            yield 'data: {"tool_calls": [{"index": 0, "id": "call_w3", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def success_stream(*args, **kwargs):
            yield 'data: {"content": "Vienna forecast loaded."}\n\n'
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = [weather_stream(), success_stream()]
        mock_execute_tool.side_effect = [
            {"error": "latitude and longitude are required"},
            {
                "location": "Vienna",
                "forecast": [
                    {"date": "2026-06-10", "temperature": 24, "condition": "sunny"}
                ],
            },
        ]

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "What's the weather for my trip?",
                "collection_id": str(collection.id),
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
        json_payloads = [json.loads(p) for p in payload_lines if p != "[DONE]"]

        self.assertEqual(mock_execute_tool.call_count, 2)
        retry_kwargs = mock_execute_tool.call_args_list[1][1]
        self.assertAlmostEqual(retry_kwargs.get("latitude"), 48.2082, places=3)
        self.assertAlmostEqual(retry_kwargs.get("longitude"), 16.3738, places=3)
        self.assertEqual(
            retry_kwargs.get("dates"),
            ["2026-06-10", "2026-06-11", "2026-06-12"],
        )
        self.assertFalse(
            any(
                payload.get("error_category") == "tool_execution_error"
                for payload in json_payloads
            )
        )

    @patch("chat.views.execute_tool")
    @patch("chat.views.stream_chat_completion")
    @patch("integrations.utils.auto_profile.update_auto_preference_profile")
    def test_get_weather_missing_dates_only_remains_validation_error(
        self,
        _mock_auto_profile,
        mock_stream_chat_completion,
        mock_execute_tool,
    ):
        user = User.objects.create_user(
            username="weather-missing-dates-user",
            email="weather-missing-dates-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        collection = Collection.objects.create(
            user_id=user.id,
            name="Berlin Trip",
        )
        berlin_location = Location.objects.create(
            user_id=user.id,
            name="Berlin",
            latitude=52.52,
            longitude=13.405,
        )
        collection.locations.add(berlin_location)

        conversation_response = self.client.post(
            "/api/chat/conversations/",
            {"title": "Weather Missing Dates Validation Test"},
            format="json",
        )
        self.assertEqual(conversation_response.status_code, 201)
        conversation_id = conversation_response.json()["id"]

        async def weather_stream(*args, **kwargs):
            yield (
                'data: {"tool_calls": [{"index": 0, "id": "call_w4", "type": '
                '"function", "function": {"name": "get_weather", "arguments": '
                '"{\\"latitude\\":52.52,\\"longitude\\":13.405}"}}]}\n\n'
            )
            yield "data: [DONE]\n\n"

        mock_stream_chat_completion.side_effect = weather_stream
        mock_execute_tool.return_value = {"error": "dates is required"}

        response = self.client.post(
            f"/api/chat/conversations/{conversation_id}/send_message/",
            {
                "message": "What's the weather there?",
                "collection_id": str(collection.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload_lines = [
            (
                chunk.decode("utf-8")
                if isinstance(chunk, (bytes, bytearray))
                else str(chunk)
            ).strip()[len("data: ") :]
            for chunk in response.streaming_content
            if (
                (
                    chunk.decode("utf-8")
                    if isinstance(chunk, (bytes, bytearray))
                    else str(chunk)
                )
                .strip()
                .startswith("data: ")
            )
        ]
        json_payloads = [json.loads(p) for p in payload_lines if p != "[DONE]"]

        self.assertEqual(mock_execute_tool.call_count, 1)
        self.assertTrue(
            any(
                payload.get("error_category") == "tool_validation_error"
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(
                payload.get("error_category") == "tool_execution_error"
                for payload in json_payloads
            )
        )
        self.assertFalse(
            any(
                "Could not fetch weather for the collection locations"
                in payload.get("error", "")
                for payload in json_payloads
            )
        )


class DaySuggestionsCoordinateEnrichmentTests(TestCase):
    def setUp(self):
        self.view = DaySuggestionsView()

    def test_enriches_suggestion_with_coordinates_from_place_context(self):
        suggestions = [
            {
                "name": "Roscioli",
                "location": "Via dei Giubbonari, Rome",
                "description": "Classic Roman spot",
            }
        ]
        place_candidates = [
            {
                "name": "Roscioli",
                "address": "Via dei Giubbonari, Rome",
                "latitude": 41.8933,
                "longitude": 12.4722,
            }
        ]

        enriched = self.view._enrich_suggestions_with_coordinates(
            suggestions,
            place_candidates,
        )

        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0]["latitude"], 41.8933)
        self.assertEqual(enriched[0]["longitude"], 12.4722)

    def test_preserves_existing_suggestion_coordinates(self):
        suggestions = [
            {
                "name": "Known Place",
                "location": "Somewhere",
                "latitude": 10.5,
                "longitude": 20.5,
            }
        ]
        place_candidates = [
            {
                "name": "Known Place",
                "address": "Somewhere",
                "latitude": 1.0,
                "longitude": 2.0,
            }
        ]

        enriched = self.view._enrich_suggestions_with_coordinates(
            suggestions,
            place_candidates,
        )

        self.assertEqual(enriched[0]["latitude"], 10.5)
        self.assertEqual(enriched[0]["longitude"], 20.5)

    def test_enriches_coordinates_with_token_based_name_matching(self):
        suggestions = [
            {
                "name": "Borough food market",
                "location": "South Bank",
                "description": "Popular food destination",
            }
        ]
        place_candidates = [
            {
                "name": "Borough Market",
                "address": "8 Southwark St, London SE1 1TL",
                "latitude": 51.5055,
                "longitude": -0.0904,
            }
        ]

        enriched = self.view._enrich_suggestions_with_coordinates(
            suggestions,
            place_candidates,
        )

        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0]["latitude"], 51.5055)
        self.assertEqual(enriched[0]["longitude"], -0.0904)

    def test_falls_back_to_coordinate_match_when_best_text_match_has_no_coordinates(
        self,
    ):
        suggestions = [
            {
                "name": "Sunset Bar",
                "location": "Pier 7",
                "description": "Cocktail spot",
            }
        ]
        place_candidates = [
            {
                "name": "Sunset Bar",
                "address": "Pier 7",
                "latitude": None,
                "longitude": None,
            },
            {
                "name": "Harbor Walk",
                "address": "Pier 7, Lisbon",
                "latitude": 38.7072,
                "longitude": -9.1366,
            },
        ]

        enriched = self.view._enrich_suggestions_with_coordinates(
            suggestions,
            place_candidates,
        )

        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0]["latitude"], 38.7072)
        self.assertEqual(enriched[0]["longitude"], -9.1366)

    def test_does_not_inject_null_coordinates_when_no_coordinate_match_exists(self):
        suggestions = [
            {
                "name": "Skyline View",
                "location": "Hilltop",
            }
        ]
        place_candidates = [
            {
                "name": "Skyline View",
                "address": "Hilltop",
                "latitude": None,
                "longitude": None,
            }
        ]

        enriched = self.view._enrich_suggestions_with_coordinates(
            suggestions,
            place_candidates,
        )

        self.assertEqual(len(enriched), 1)
        self.assertNotIn("latitude", enriched[0])
        self.assertNotIn("longitude", enriched[0])
