import json
import logging

import litellm
from asgiref.sync import sync_to_async
from django.conf import settings

from integrations.models import UserAPIKey

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are a helpful travel planning assistant for the Voyage travel app. You help users discover places, plan trips, and organize their itineraries.

Your capabilities:
- Search for interesting places (restaurants, tourist attractions, hotels) near any location
- View and manage the user's trip collections and itineraries
- Add new locations to trip itineraries
- Check weather/temperature data for travel dates

When suggesting places:
- Be specific with names, addresses, and why a place is worth visiting
- Consider the user's travel dates and weather conditions
- Group suggestions logically (by area, by type, by day)

When modifying itineraries:
- Confirm with the user before the first add_to_itinerary action in a conversation
- After the user clearly approves adding items (for example: "yes", "go ahead", "add them", "just add things there"), stop re-confirming and call add_to_itinerary directly for subsequent additions in that conversation
- Suggest logical ordering based on geography
- Consider travel time between locations

When chat context includes a trip collection:
- Treat context as itinerary-wide (potentially multiple stops), not a single destination
- Use get_trip_details first when you need complete collection context before searching for places
- Ground place searches in trip stops and dates from the provided trip context
- Only call search_places when you have a concrete, non-empty location string; if location is missing or unclear, ask a clarifying question to obtain it first

Be conversational, helpful, and enthusiastic about travel. Keep responses concise but informative."""

PROVIDER_MODEL_PREFIX = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "ollama": "ollama",
    "groq": "groq",
    "mistral": "mistral",
    "github_models": "github",
    "openrouter": "openrouter",
}

CHAT_PROVIDER_CONFIG = {
    "openai": {
        "label": "OpenAI",
        "needs_api_key": True,
        "default_model": "gpt-4o",
        "api_base": None,
    },
    "anthropic": {
        "label": "Anthropic",
        "needs_api_key": True,
        "default_model": "anthropic/claude-sonnet-4-20250514",
        "api_base": None,
    },
    "gemini": {
        "label": "Google Gemini",
        "needs_api_key": True,
        "default_model": "gemini/gemini-2.0-flash",
        "api_base": None,
    },
    "ollama": {
        "label": "Ollama",
        "needs_api_key": True,
        "default_model": "ollama/llama3.1",
        "api_base": None,
    },
    "groq": {
        "label": "Groq",
        "needs_api_key": True,
        "default_model": "groq/llama-3.3-70b-versatile",
        "api_base": None,
    },
    "mistral": {
        "label": "Mistral",
        "needs_api_key": True,
        "default_model": "mistral/mistral-large-latest",
        "api_base": None,
    },
    "github_models": {
        "label": "GitHub Models",
        "needs_api_key": True,
        "default_model": "github/gpt-4o",
        "api_base": None,
    },
    "openrouter": {
        "label": "OpenRouter",
        "needs_api_key": True,
        "default_model": "openrouter/auto",
        "api_base": None,
    },
    "opencode_zen": {
        "label": "OpenCode Zen",
        "needs_api_key": True,
        # Chosen from OpenCode Zen compatible OpenAI-routed models per
        # opencode_zen connection research (see .memory/research).
        "default_model": "openai/gpt-5-nano",
        "api_base": "https://opencode.ai/zen/v1",
    },
}


def _is_model_override_compatible(provider, provider_config, model):
    """Validate model/provider compatibility when strict checks are safe.

    For providers with a custom api_base gateway, skip strict prefix checks since
    gateway routing may legitimately accept cross-provider prefixes.
    """
    if not model or provider_config.get("api_base"):
        return True

    if "/" not in model:
        return True

    expected_prefix = PROVIDER_MODEL_PREFIX.get(provider)
    if not expected_prefix:
        default_model = provider_config.get("default_model") or ""
        if "/" in default_model:
            expected_prefix = default_model.split("/", 1)[0]

    if not expected_prefix:
        return True

    return model.startswith(f"{expected_prefix}/")


def _safe_error_payload(exc):
    exceptions = getattr(litellm, "exceptions", None)
    not_found_cls = getattr(exceptions, "NotFoundError", tuple())
    auth_cls = getattr(exceptions, "AuthenticationError", tuple())
    rate_limit_cls = getattr(exceptions, "RateLimitError", tuple())
    bad_request_cls = getattr(exceptions, "BadRequestError", tuple())
    timeout_cls = getattr(exceptions, "Timeout", tuple())
    api_connection_cls = getattr(exceptions, "APIConnectionError", tuple())

    if isinstance(exc, not_found_cls):
        return {
            "error": "The selected model is unavailable for this provider. Choose a different model and try again.",
            "error_category": "model_not_found",
        }

    if isinstance(exc, auth_cls):
        return {
            "error": "Authentication with the model provider failed. Verify your API key in Settings and try again.",
            "error_category": "authentication_failed",
        }

    if isinstance(exc, rate_limit_cls):
        return {
            "error": "The model provider rate limit was reached. Please wait and try again.",
            "error_category": "rate_limited",
        }

    if isinstance(exc, bad_request_cls):
        return {
            "error": "The model provider rejected this request. Check your selected model and try again.",
            "error_category": "invalid_request",
        }

    if isinstance(exc, timeout_cls) or isinstance(exc, api_connection_cls):
        return {
            "error": "Unable to reach the model provider right now. Please try again.",
            "error_category": "provider_unreachable",
        }

    return {
        "error": "An error occurred while processing your request. Please try again.",
        "error_category": "unknown_error",
    }


def _safe_get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_provider_id(provider_id):
    value = str(provider_id or "").strip()
    lowered = value.lower()
    if lowered.startswith("llmproviders."):
        return lowered.split(".", 1)[1]
    return lowered


def normalize_gateway_model(provider_id, model):
    normalized_provider = _normalize_provider_id(provider_id)
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return None

    if normalized_provider == "opencode_zen" and "/" not in normalized_model:
        return f"openai/{normalized_model}"

    return normalized_model


def _default_provider_label(provider_id):
    return provider_id.replace("_", " ").title()


def is_chat_provider_available(provider_id):
    normalized_provider = _normalize_provider_id(provider_id)
    return normalized_provider in CHAT_PROVIDER_CONFIG


def get_provider_catalog(user=None):
    seen = set()
    catalog = []
    user_key_providers = set()
    instance_provider = (
        _normalize_provider_id(settings.VOYAGE_AI_PROVIDER)
        if settings.VOYAGE_AI_PROVIDER
        else None
    )
    instance_has_key = bool(settings.VOYAGE_AI_API_KEY)
    if user:
        user_key_providers = set(
            UserAPIKey.objects.filter(user=user).values_list("provider", flat=True)
        )

    for provider_id in getattr(litellm, "provider_list", []):
        normalized_provider = _normalize_provider_id(provider_id)
        if not normalized_provider or normalized_provider in seen:
            continue

        seen.add(normalized_provider)
        provider_config = CHAT_PROVIDER_CONFIG.get(normalized_provider)
        if provider_config:
            catalog.append(
                {
                    "id": normalized_provider,
                    "label": provider_config["label"],
                    "available_for_chat": True,
                    "needs_api_key": provider_config["needs_api_key"],
                    "default_model": provider_config["default_model"],
                    "api_base": provider_config["api_base"],
                    "instance_configured": instance_has_key
                    and normalized_provider == instance_provider,
                    "user_configured": normalized_provider in user_key_providers,
                }
            )
            continue

        catalog.append(
            {
                "id": normalized_provider,
                "label": _default_provider_label(normalized_provider),
                "available_for_chat": False,
                "needs_api_key": None,
                "default_model": None,
                "api_base": None,
                "instance_configured": instance_has_key
                and normalized_provider == instance_provider,
                "user_configured": normalized_provider in user_key_providers,
            }
        )

    # Include app-supported OpenAI-compatible aliases that are not part of
    # LiteLLM's native provider list (for example OpenCode Zen).
    for provider_id, provider_config in CHAT_PROVIDER_CONFIG.items():
        normalized_provider = _normalize_provider_id(provider_id)
        if not normalized_provider or normalized_provider in seen:
            continue

        seen.add(normalized_provider)
        catalog.append(
            {
                "id": normalized_provider,
                "label": provider_config["label"],
                "available_for_chat": True,
                "needs_api_key": provider_config["needs_api_key"],
                "default_model": provider_config["default_model"],
                "api_base": provider_config["api_base"],
                "instance_configured": instance_has_key
                and normalized_provider == instance_provider,
                "user_configured": normalized_provider in user_key_providers,
            }
        )

    return catalog


def get_llm_api_key(user, provider):
    """Get the user's API key for the given provider."""
    normalized_provider = _normalize_provider_id(provider)
    try:
        key_obj = UserAPIKey.objects.get(user=user, provider=normalized_provider)
        return key_obj.get_api_key()
    except UserAPIKey.DoesNotExist:
        if normalized_provider == _normalize_provider_id(settings.VOYAGE_AI_PROVIDER):
            instance_api_key = (settings.VOYAGE_AI_API_KEY or "").strip()
            if instance_api_key:
                return instance_api_key
        return None


def _format_interests(interests):
    if isinstance(interests, list):
        return ", ".join(interests)
    return interests


def get_aggregated_preferences(collection):
    """Aggregate preferences from collection owner and shared users."""
    from integrations.models import UserRecommendationPreferenceProfile

    users = [collection.user] + list(collection.shared_with.all())
    preferences = []

    for member in users:
        try:
            profile = UserRecommendationPreferenceProfile.objects.get(user=member)
            user_prefs = []

            if profile.cuisines:
                user_prefs.append(f"cuisines: {profile.cuisines}")
            if profile.interests:
                user_prefs.append(f"interests: {_format_interests(profile.interests)}")
            if profile.trip_style:
                user_prefs.append(f"style: {profile.trip_style}")
            if profile.notes:
                user_prefs.append(f"notes: {profile.notes}")

            if user_prefs:
                preferences.append(f"- **{member.username}**: {', '.join(user_prefs)}")
        except UserRecommendationPreferenceProfile.DoesNotExist:
            continue

    if preferences:
        return (
            "\n\n## Party Preferences\n"
            + "\n".join(preferences)
            + "\n\nNote: Consider all travelers' preferences when making recommendations."
        )

    return ""


def get_system_prompt(user, collection=None):
    """Build the system prompt with user context."""
    from chat.models import ChatSystemPrompt
    from integrations.models import UserRecommendationPreferenceProfile

    custom = ChatSystemPrompt.load()
    base_prompt = (
        custom.prompt_text
        if custom and custom.prompt_text and custom.prompt_text.strip()
        else DEFAULT_SYSTEM_PROMPT
    )

    if collection and collection.shared_with.count() > 0:
        base_prompt += get_aggregated_preferences(collection)
    else:
        try:
            profile = UserRecommendationPreferenceProfile.objects.get(user=user)

            if profile.interests or profile.trip_style or profile.notes:
                base_prompt += "\n\n## Traveler Preferences\n"
                base_prompt += "*(Automatically inferred from travel history)*\n\n"

                if profile.interests:
                    interests_str = (
                        ", ".join(profile.interests)
                        if isinstance(profile.interests, list)
                        else str(profile.interests)
                    )
                    base_prompt += f"🎯 **Interests**: {interests_str}\n"
                if profile.trip_style:
                    base_prompt += f"✈️ **Travel Style**: {profile.trip_style}\n"
                if profile.notes:
                    base_prompt += f"📍 **Patterns**: {profile.notes}\n"
        except UserRecommendationPreferenceProfile.DoesNotExist:
            pass

    return base_prompt


async def stream_chat_completion(user, messages, provider, tools=None, model=None):
    """Stream a chat completion using LiteLLM.

    Yields SSE-formatted strings.
    """
    normalized_provider = _normalize_provider_id(provider)
    provider_config = CHAT_PROVIDER_CONFIG.get(normalized_provider)
    if not provider_config:
        payload = {
            "error": f"Provider is not available for chat: {normalized_provider}."
        }
        yield f"data: {json.dumps(payload)}\n\n"
        return

    api_key = await sync_to_async(get_llm_api_key)(user, normalized_provider)

    if provider_config["needs_api_key"] and not api_key:
        payload = {
            "error": f"No API key found for provider: {normalized_provider}. Please add one in Settings."
        }
        yield f"data: {json.dumps(payload)}\n\n"
        return

    if not _is_model_override_compatible(normalized_provider, provider_config, model):
        payload = {
            "error": "The selected model is incompatible with this provider. Choose a model for the selected provider and try again.",
            "error_category": "invalid_model_for_provider",
        }
        yield f"data: {json.dumps(payload)}\n\n"
        return

    resolved_model = (
        model
        or (
            settings.VOYAGE_AI_MODEL
            if normalized_provider
            == _normalize_provider_id(settings.VOYAGE_AI_PROVIDER)
            and settings.VOYAGE_AI_MODEL
            else None
        )
        or provider_config["default_model"]
    )
    resolved_model = normalize_gateway_model(normalized_provider, resolved_model)

    if tools and not litellm.supports_function_calling(model=resolved_model):
        logger.warning(
            "Model %s does not support function calling, disabling tools",
            resolved_model,
        )
        tools = None

    logger.info(
        "Chat request: provider=%s, model=%s, has_tools=%s",
        normalized_provider,
        resolved_model,
        bool(tools),
    )
    logger.debug(
        "API base: %s, messages count: %s",
        provider_config.get("api_base"),
        len(messages),
    )

    completion_kwargs = {
        "model": resolved_model,
        "messages": messages,
        "stream": True,
        "api_key": api_key,
        "num_retries": 2,
    }
    if tools:
        completion_kwargs["tools"] = tools
        completion_kwargs["tool_choice"] = "auto"
    if provider_config["api_base"]:
        completion_kwargs["api_base"] = provider_config["api_base"]

    try:
        response = await litellm.acompletion(**completion_kwargs)

        async for chunk in response:
            choices = _safe_get(chunk, "choices", []) or []
            if not choices:
                continue

            delta = _safe_get(choices[0], "delta")
            if not delta:
                continue

            chunk_data = {}
            content = _safe_get(delta, "content")
            if content:
                chunk_data["content"] = content

            tool_calls = _safe_get(delta, "tool_calls") or []
            if tool_calls:
                serialized = []
                for tool_call in tool_calls:
                    function = _safe_get(tool_call, "function")
                    serialized.append(
                        {
                            "id": _safe_get(tool_call, "id"),
                            "type": _safe_get(tool_call, "type"),
                            "function": {
                                "name": _safe_get(function, "name", "") or "",
                                "arguments": _safe_get(function, "arguments", "") or "",
                            },
                        }
                    )
                chunk_data["tool_calls"] = serialized

            if chunk_data:
                yield f"data: {json.dumps(chunk_data)}\n\n"

        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.error("LiteLLM error: %s: %s", type(exc).__name__, str(exc)[:200])
        logger.exception("LLM streaming error")
        payload = _safe_error_payload(exc)
        yield f"data: {json.dumps(payload)}\n\n"
