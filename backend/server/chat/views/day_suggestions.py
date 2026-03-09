import logging
import json
import re

import litellm
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from adventures.models import Collection
from chat.agent_tools import search_places
from chat.llm_client import (
    CHAT_PROVIDER_CONFIG,
    _safe_error_payload,
    get_llm_api_key,
    get_system_prompt,
    is_chat_provider_available,
    normalize_gateway_model,
)
from integrations.models import UserAISettings


logger = logging.getLogger(__name__)


class DaySuggestionsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        collection_id = request.data.get("collection_id")
        date = request.data.get("date")
        category = request.data.get("category")
        filters = request.data.get("filters", {}) or {}
        location_context = request.data.get("location_context", "")

        if not all([collection_id, date, category]):
            return Response(
                {"error": "collection_id, date, and category are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_categories = ["restaurant", "activity", "event", "lodging"]
        if category not in valid_categories:
            return Response(
                {"error": f"category must be one of: {', '.join(valid_categories)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        collection = get_object_or_404(Collection, id=collection_id)
        if (
            collection.user != request.user
            and not collection.shared_with.filter(id=request.user.id).exists()
        ):
            return Response(
                {"error": "You don't have access to this collection"},
                status=status.HTTP_403_FORBIDDEN,
            )

        location = location_context or self._get_collection_location(collection)
        system_prompt = get_system_prompt(request.user, collection)
        provider, model = self._resolve_provider_and_model(request)

        if not is_chat_provider_available(provider):
            return Response(
                {
                    "error": "AI suggestions are not available. Please configure an API key."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            places_context = self._get_places_context(request.user, category, location)
            prompt = self._build_prompt(
                category=category,
                filters=filters,
                location=location,
                date=date,
                collection=collection,
                places_context=places_context,
            )

            suggestions = self._get_suggestions_from_llm(
                system_prompt=system_prompt,
                user_prompt=prompt,
                user=request.user,
                provider=provider,
                model=model,
            )
            return Response({"suggestions": suggestions}, status=status.HTTP_200_OK)
        except Exception as exc:
            logger.exception("Failed to generate day suggestions")
            payload = _safe_error_payload(exc)
            status_code = {
                "model_not_found": status.HTTP_400_BAD_REQUEST,
                "authentication_failed": status.HTTP_401_UNAUTHORIZED,
                "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
                "invalid_request": status.HTTP_400_BAD_REQUEST,
                "provider_unreachable": status.HTTP_503_SERVICE_UNAVAILABLE,
            }.get(payload.get("error_category"), status.HTTP_500_INTERNAL_SERVER_ERROR)
            return Response(
                payload,
                status=status_code,
            )

    def _get_collection_location(self, collection):
        for loc in collection.locations.select_related("city", "country").all():
            if loc.city:
                city_name = getattr(loc.city, "name", str(loc.city))
                country_name = getattr(loc.country, "name", "") if loc.country else ""
                return ", ".join([x for x in [city_name, country_name] if x])
            if loc.location:
                return loc.location
            if loc.name:
                return loc.name
        return "Unknown location"

    def _build_prompt(
        self,
        category,
        filters,
        location,
        date,
        collection,
        places_context="",
    ):
        category_prompts = {
            "restaurant": f"Find restaurant recommendations for {location}",
            "activity": f"Find activity recommendations for {location}",
            "event": f"Find event recommendations for {location} around {date}",
            "lodging": f"Find lodging recommendations for {location}",
        }

        prompt = category_prompts.get(
            category, f"Find {category} recommendations for {location}"
        )

        if filters:
            filter_parts = []
            if filters.get("cuisine_type"):
                filter_parts.append(f"cuisine type: {filters['cuisine_type']}")
            if filters.get("price_range"):
                filter_parts.append(f"price range: {filters['price_range']}")
            if filters.get("dietary"):
                filter_parts.append(f"dietary restrictions: {filters['dietary']}")
            if filters.get("activity_type"):
                filter_parts.append(f"type: {filters['activity_type']}")
            if filters.get("duration"):
                filter_parts.append(f"duration: {filters['duration']}")
            if filters.get("event_type"):
                filter_parts.append(f"event type: {filters['event_type']}")
            if filters.get("lodging_type"):
                filter_parts.append(f"lodging type: {filters['lodging_type']}")
            amenities = filters.get("amenities")
            if isinstance(amenities, list) and amenities:
                filter_parts.append(
                    f"amenities: {', '.join(str(x) for x in amenities)}"
                )

            if filter_parts:
                prompt += f" with these preferences: {', '.join(filter_parts)}"

        prompt += f". The trip date is {date}."

        if collection.start_date or collection.end_date:
            prompt += (
                " Collection trip window: "
                f"{collection.start_date or 'unknown'} to {collection.end_date or 'unknown'}."
            )

        if places_context:
            prompt += f" Nearby place context: {places_context}."

        prompt += (
            " Return 3-5 specific suggestions as a JSON array."
            " Each suggestion should have: name, description, why_fits, category, location, rating, price_level."
            " Return ONLY valid JSON, no markdown, no surrounding text."
        )
        return prompt

    def _get_places_context(self, user, category, location):
        tool_category_map = {
            "restaurant": "food",
            "activity": "tourism",
            "event": "tourism",
            "lodging": "lodging",
        }
        result = search_places(
            user,
            location=location,
            category=tool_category_map.get(category, "tourism"),
            radius=8,
        )
        if not isinstance(result, dict):
            return ""
        if result.get("error"):
            return ""

        raw_results = result.get("results")
        if not isinstance(raw_results, list):
            return ""

        entries = []
        for place in raw_results[:5]:
            if not isinstance(place, dict):
                continue
            name = place.get("name")
            address = place.get("address") or ""
            if name:
                entries.append(f"{name} ({address})" if address else name)
        return "; ".join(entries)

    def _resolve_provider_and_model(self, request):
        request_provider = (request.data.get("provider") or "").strip().lower() or None
        request_model = (request.data.get("model") or "").strip() or None

        user_settings = UserAISettings.objects.filter(user=request.user).first()  # type: ignore[attr-defined]
        preferred_provider = (
            (user_settings.preferred_provider or "").strip().lower()
            if user_settings and user_settings.preferred_provider
            else None
        )
        preferred_model = (
            (user_settings.preferred_model or "").strip()
            if user_settings and user_settings.preferred_model
            else None
        )

        settings_provider = (settings.VOYAGE_AI_PROVIDER or "").strip().lower() or None

        provider = request_provider or preferred_provider or settings_provider
        if not provider or not is_chat_provider_available(provider):
            provider = (
                settings_provider
                if is_chat_provider_available(settings_provider)
                else None
            )
        if not provider or not is_chat_provider_available(provider):
            provider = "openai" if is_chat_provider_available("openai") else provider

        provider_config = CHAT_PROVIDER_CONFIG.get(provider or "", {})
        default_model = (
            (settings.VOYAGE_AI_MODEL or "").strip()
            if provider == settings_provider and settings.VOYAGE_AI_MODEL
            else None
        ) or provider_config.get("default_model")

        model_from_user_defaults = (
            preferred_model
            if preferred_provider and provider == preferred_provider
            else None
        )
        model = request_model or model_from_user_defaults or default_model
        return provider, model

    def _get_suggestions_from_llm(
        self, system_prompt, user_prompt, user, provider, model
    ):
        api_key = get_llm_api_key(user, provider)
        if not api_key:
            raise ValueError("No API key available")

        provider_config = CHAT_PROVIDER_CONFIG.get(provider, {})
        resolved_model = normalize_gateway_model(
            provider,
            model or provider_config.get("default_model"),
        )
        if not resolved_model:
            raise ValueError("No model configured for provider")

        completion_kwargs = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "api_key": api_key,
            "max_tokens": 1000,
        }

        if provider_config.get("api_base"):
            completion_kwargs["api_base"] = provider_config["api_base"]

        response = litellm.completion(
            **completion_kwargs,
        )

        content = (response.choices[0].message.content or "").strip()
        try:
            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            parsed = (
                json.loads(json_match.group())
                if json_match
                else json.loads(content or "[]")
            )
            suggestions = parsed if isinstance(parsed, list) else [parsed]
            return suggestions[:5]
        except json.JSONDecodeError:
            return []
