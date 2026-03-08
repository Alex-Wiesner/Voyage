import json
import logging

import litellm

from integrations.models import UserAPIKey

logger = logging.getLogger(__name__)

PROVIDER_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "anthropic/claude-sonnet-4-20250514",
    "gemini": "gemini/gemini-2.0-flash",
    "ollama": "ollama/llama3.1",
    "groq": "groq/llama-3.3-70b-versatile",
    "mistral": "mistral/mistral-large-latest",
    "github_models": "github/gpt-4o",
    "openrouter": "openrouter/auto",
}


def _safe_get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def get_llm_api_key(user, provider):
    """Get the user's API key for the given provider."""
    normalized_provider = (provider or "").strip().lower()
    try:
        key_obj = UserAPIKey.objects.get(user=user, provider=normalized_provider)
        return key_obj.get_api_key()
    except UserAPIKey.DoesNotExist:
        return None


def get_system_prompt(user, collection=None):
    """Build the system prompt with user context."""
    from integrations.models import UserRecommendationPreferenceProfile

    base_prompt = """You are a helpful travel planning assistant for the Voyage travel app. You help users discover places, plan trips, and organize their itineraries.

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
- Always confirm with the user before adding items
- Suggest logical ordering based on geography
- Consider travel time between locations

Be conversational, helpful, and enthusiastic about travel. Keep responses concise but informative."""

    try:
        profile = UserRecommendationPreferenceProfile.objects.get(user=user)
        prefs = []
        if profile.cuisines:
            prefs.append(f"Cuisine preferences: {profile.cuisines}")
        if profile.interests:
            prefs.append(f"Interests: {profile.interests}")
        if profile.trip_style:
            prefs.append(f"Travel style: {profile.trip_style}")
        if profile.notes:
            prefs.append(f"Additional notes: {profile.notes}")
        if prefs:
            base_prompt += "\n\nUser preferences:\n" + "\n".join(prefs)
    except UserRecommendationPreferenceProfile.DoesNotExist:
        pass

    return base_prompt


async def stream_chat_completion(user, messages, provider, tools=None):
    """Stream a chat completion using LiteLLM.

    Yields SSE-formatted strings.
    """
    normalized_provider = (provider or "").strip().lower()
    api_key = get_llm_api_key(user, normalized_provider)
    if not api_key:
        payload = {
            "error": f"No API key found for provider: {normalized_provider}. Please add one in Settings."
        }
        yield f"data: {json.dumps(payload)}\n\n"
        return

    model = PROVIDER_MODELS.get(normalized_provider, "gpt-4o")

    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto" if tools else None,
            stream=True,
            api_key=api_key,
        )

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
    except Exception:
        logger.exception("LLM streaming error")
        yield f"data: {json.dumps({'error': 'An error occurred while processing your request. Please try again.'})}\n\n"
