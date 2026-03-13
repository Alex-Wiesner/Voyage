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
            place_candidates = self._fetch_place_candidates(
                request.user,
                category,
                location,
            )
            places_context = self._build_places_context(place_candidates)
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
            suggestions = self._enrich_suggestions_with_coordinates(
                suggestions,
                place_candidates,
            )
            return Response({"suggestions": suggestions}, status=status.HTTP_200_OK)
        except Exception as exc:
            logger.exception("Failed to generate day suggestions")
            payload = _safe_error_payload(exc)
            error_category = (
                payload.get("error_category") if isinstance(payload, dict) else None
            )
            status_code_map = {
                "model_not_found": status.HTTP_400_BAD_REQUEST,
                "authentication_failed": status.HTTP_401_UNAUTHORIZED,
                "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
                "invalid_request": status.HTTP_400_BAD_REQUEST,
                "provider_unreachable": status.HTTP_503_SERVICE_UNAVAILABLE,
            }
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            if isinstance(error_category, str):
                status_code = status_code_map.get(
                    error_category,
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
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
            " Include latitude and longitude when known from nearby-place context."
            " Return ONLY valid JSON, no markdown, no surrounding text."
        )
        return prompt

    def _fetch_place_candidates(self, user, category, location):
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
            return []
        if result.get("error"):
            return []

        raw_results = result.get("results")
        if not isinstance(raw_results, list):
            return []

        return [entry for entry in raw_results if isinstance(entry, dict)]

    def _build_places_context(self, place_candidates):
        if not isinstance(place_candidates, list):
            return ""

        entries = []
        for place in place_candidates[:5]:
            name = place.get("name")
            address = place.get("address") or ""
            latitude = place.get("latitude")
            longitude = place.get("longitude")
            if not name:
                continue

            details = [name]
            if address:
                details.append(address)
            if latitude is not None and longitude is not None:
                details.append(f"lat={latitude}")
                details.append(f"lon={longitude}")
            entries.append(" | ".join(details))
        return "; ".join(entries)

    def _tokenize_text(self, value):
        normalized = self._normalize_text(value)
        if not normalized:
            return set()
        return set(re.findall(r"[a-z0-9]+", normalized))

    def _normalize_text(self, value):
        if not isinstance(value, str):
            return ""
        return value.strip().lower()

    def _extract_suggestion_identity(self, suggestion):
        if not isinstance(suggestion, dict):
            return "", ""

        name = self._normalize_text(
            suggestion.get("name")
            or suggestion.get("title")
            or suggestion.get("place_name")
            or suggestion.get("venue")
        )
        location_text = self._normalize_text(
            suggestion.get("location")
            or suggestion.get("address")
            or suggestion.get("neighborhood")
        )
        return name, location_text

    def _best_place_match(self, suggestion, place_candidates):
        suggestion_name, suggestion_location = self._extract_suggestion_identity(
            suggestion
        )
        if not suggestion_name and not suggestion_location:
            return None

        suggestion_name_tokens = self._tokenize_text(suggestion_name)
        suggestion_location_tokens = self._tokenize_text(suggestion_location)

        def has_coordinates(candidate):
            return (
                candidate.get("latitude") is not None
                and candidate.get("longitude") is not None
            )

        best_candidate = None
        best_score = -1
        best_coordinate_candidate = None
        best_coordinate_score = -1
        for candidate in place_candidates:
            candidate_name = self._normalize_text(candidate.get("name"))
            candidate_address = self._normalize_text(candidate.get("address"))
            candidate_name_tokens = self._tokenize_text(candidate_name)
            candidate_address_tokens = self._tokenize_text(candidate_address)
            score = 0

            if suggestion_name and candidate_name:
                if suggestion_name == candidate_name:
                    score += 4
                elif (
                    suggestion_name in candidate_name
                    or candidate_name in suggestion_name
                ):
                    score += 2

                shared_name_tokens = suggestion_name_tokens & candidate_name_tokens
                if len(shared_name_tokens) >= 2:
                    score += 3
                elif len(shared_name_tokens) == 1:
                    score += 1

            if suggestion_location and candidate_address:
                if suggestion_location == candidate_address:
                    score += 2
                elif (
                    suggestion_location in candidate_address
                    or candidate_address in suggestion_location
                ):
                    score += 1

                shared_location_tokens = (
                    suggestion_location_tokens & candidate_address_tokens
                )
                if len(shared_location_tokens) >= 2:
                    score += 2
                elif len(shared_location_tokens) == 1:
                    score += 1

            if score > best_score:
                best_score = score
                best_candidate = candidate
            elif (
                score == best_score
                and best_candidate is not None
                and not has_coordinates(best_candidate)
                and has_coordinates(candidate)
            ):
                best_candidate = candidate

            if has_coordinates(candidate) and score > best_coordinate_score:
                best_coordinate_score = score
                best_coordinate_candidate = candidate

        if best_score <= 0:
            return None

        if has_coordinates(best_candidate):
            return best_candidate

        # Bounded fallback: if the strongest text match has no coordinates,
        # accept the best coordinate-bearing candidate only with a
        # reasonably strong lexical overlap score.
        if best_coordinate_score >= 2:
            return best_coordinate_candidate

        return best_candidate

    def _enrich_suggestions_with_coordinates(self, suggestions, place_candidates):
        if not isinstance(suggestions, list) or not isinstance(place_candidates, list):
            return suggestions

        enriched = []
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue

            if (
                suggestion.get("latitude") is not None
                and suggestion.get("longitude") is not None
            ):
                enriched.append(suggestion)
                continue

            matched_place = self._best_place_match(suggestion, place_candidates)
            if not matched_place:
                enriched.append(suggestion)
                continue

            if (
                matched_place.get("latitude") is None
                or matched_place.get("longitude") is None
            ):
                enriched.append(suggestion)
                continue

            merged = dict(suggestion)
            merged["latitude"] = matched_place.get("latitude")
            merged["longitude"] = matched_place.get("longitude")
            merged["location"] = merged.get("location") or matched_place.get("address")
            enriched.append(merged)

        return enriched

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

        provider_config = CHAT_PROVIDER_CONFIG.get(provider or "", {})
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
