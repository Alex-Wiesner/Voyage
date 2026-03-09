# Chat & LLM Patterns

## Default AI Settings & Model Override

### DB-backed defaults (authoritative)
- **Model**: `UserAISettings` (OneToOneField, `integrations/models.py`) stores `preferred_provider` and `preferred_model` per user.
- **Endpoint**: `GET/POST /api/integrations/ai-settings/` — upsert pattern (OneToOneField + `perform_create` update-or-create).
- **Settings UI**: `settings/+page.svelte` loads/saves default provider and model. Provider dropdown filtered to configured providers; model dropdown from `GET /api/chat/providers/{provider}/models/`.
- **Chat initialization**: `AITravelChat.svelte` `loadUserAISettings()` fetches saved defaults on mount and applies them as authoritative initial provider/model. Direction is DB → localStorage (not reverse).
- **Backend fallback precedence** in `send_message()`:
  1. Explicit request payload (`provider`, `model`)
  2. `UserAISettings.preferred_provider` / `preferred_model` (only when provider matches)
  3. Instance defaults (`VOYAGE_AI_PROVIDER`, `VOYAGE_AI_MODEL`)
  4. `"openai"` hardcoded fallback
- **Cross-provider guard**: `preferred_model` only applied when resolved provider == `preferred_provider` (prevents e.g. `gpt-5-nano` leaking to Anthropic).

### Per-session model override (browser-only)
- **Frontend**: model dropdown next to provider selector, populated by `GET /api/chat/providers/{provider}/models/`.
- **Persistence**: `localStorage` key `voyage_chat_model_prefs` — written on selection, but never overrides DB defaults on initialization (DB wins).
- **Compatibility guard**: `_is_model_override_compatible()` validates model prefix for standard providers; skips check for `api_base` gateways (e.g. `opencode_zen`).
- **i18n keys**: `chat.model_label`, `chat.model_placeholder`, `default_ai_settings_title`, `default_ai_settings_desc`, `default_ai_save`, `default_ai_settings_saved`, `default_ai_settings_error`, `default_ai_provider_required`, `default_ai_no_providers`.

## Sanitized LLM Error Mapping
- `_safe_error_payload()` in `backend/server/chat/llm_client.py` maps LiteLLM exception classes to hardcoded user-safe strings with `error_category` field.
- Exception classes mapped: `NotFoundError` -> "model not found", `AuthenticationError` -> "authentication", `RateLimitError` -> "rate limit", `BadRequestError` -> "bad request", `Timeout` -> "timeout", `APIConnectionError` -> "connection".
- Raw `exc.message`, `str(exc)`, and `exc.args` are **never** forwarded to the client. Server-side `logger.exception()` logs full details.
- Uses `getattr(litellm.exceptions, "ClassName", tuple())` for resilient class lookup.
- Security guardrail from critic gate: [decisions.md](../../decisions.md#critic-gate-opencode-zen-connection-error-fix).

## Tool Call Error Handling (Chat Loop Hardening)
- **Required-arg detection**: `_is_required_param_tool_error()` matches tool results containing `"is required"` / `"are required"` patterns via regex. Detects errors like `"location is required"`, `"query is required"`, `"collection_id, name, latitude, and longitude are required"`.
- **Short-circuit on invalid tool calls**: When a tool call returns a required-param error, `send_message()` yields an SSE error event with `error_category: "tool_validation_error"` and immediately terminates the stream with `[DONE]`. No further LLM turns are attempted.
- **Persistence skip**: Invalid tool call results (and the tool_call entry itself) are NOT persisted to the database, preventing replay into future conversation turns.
- **Historical cleanup**: `_build_llm_messages()` filters persisted tool-role messages containing required-param errors AND trims the corresponding assistant `tool_calls` array to only IDs that have non-filtered tool messages. Empty `tool_calls` arrays are omitted entirely.
- **Multi-tool partial success**: When model returns N tool calls and call K fails, calls 1..K-1 (the successful prefix) are persisted normally. Only the failed call and subsequent calls are dropped.
- **Tool iteration guard**: `MAX_TOOL_ITERATIONS = 10` with correctly-incremented counter prevents unbounded loops from other error classes (e.g. `"dates must be a non-empty list"` from `get_weather` does NOT match the required-arg regex but is bounded by iteration limit).
- **Known gap**: `get_weather` error `"dates must be a non-empty list"` does not trigger the short-circuit — mitigated by `MAX_TOOL_ITERATIONS`.

## OpenCode Zen Provider
- Provider ID: `opencode_zen`
- `api_base`: `https://opencode.ai/zen/v1`
- Default model: `openai/gpt-5-nano` (changed from `openai/gpt-4o-mini` which was invalid on Zen)
- GPT models on Zen use `/chat/completions` endpoint (OpenAI-compatible)
- LiteLLM `openai/` prefix routes through OpenAI client to the custom `api_base`
- Model dropdown exposes 5 curated options (reasoning models excluded). See [decisions.md](../../decisions.md#critic-gate-travel-agent-context--models-follow-up).

## Multi-Stop Context Derivation
Chat context derives from the **full collection itinerary**, not just the first location.

### Frontend - `deriveCollectionDestination()`
- Located in `frontend/src/routes/collections/[id]/+page.svelte`.
- Extracts unique city/country pairs from `collection.locations`.
- Capped at 4 stops, semicolon-joined, with `+N more` overflow suffix.
- Passed to `AITravelChat` as `destination` prop.

### Backend - `send_message()` itinerary enrichment
- `backend/server/chat/views/__init__.py` `send_message()` reads `collection.locations` and injects `Itinerary stops:` into the system prompt `## Trip Context` section.
- Up to 8 unique stops; deduplication and blank-entry filtering applied.

### System prompt - trip-level reasoning
- `get_system_prompt()` includes guidance to treat collection chats as itinerary-wide and call `get_trip_details` before `search_places`.

## Itinerary-Centric Quick Prompts
- Quick-action buttons use `promptTripContext` (reactive: `collectionName || destination || ''`) instead of raw `destination`.
- Guard changed from `{#if destination}` to `{#if promptTripContext}`.
- Prompt wording uses `across my ${promptTripContext} itinerary?`.

## search_places Tool Output Key Convention
- Backend `agent_tools.py` `search_places()` returns `{"location": ..., "category": ..., "results": [...]}`.
- Frontend must use `.results` key (not `.places`).
- **Historical bug**: Prior code used `.places` causing place cards to never render. Fixed 2026-03-09.

## Agent Tools Architecture

### Registered Tools
| Tool name | Purpose | Required params |
|---|---|---|
| `search_places` | Nominatim geocode -> Overpass PoI search | `location` |
| `web_search` | DuckDuckGo web search for current travel info | `query` |
| `list_trips` | List user's collections | (none) |
| `get_trip_details` | Full collection detail with itinerary | `collection_id` |
| `add_to_itinerary` | Create Location + CollectionItineraryItem | `collection_id`, `name`, `lat`, `lon` |
| `get_weather` | Open-Meteo archive + forecast | `latitude`, `longitude`, `dates` |

### Registry pattern
- `@agent_tool(name, description, parameters)` decorator registers function references and generates OpenAI/LiteLLM-compatible tool schemas.
- `execute_tool(tool_name, user, **kwargs)` resolves from registry and filters kwargs via `inspect.signature(...)`.
- Extensibility: adding a new tool only requires defining a decorated function.

### Function signature convention
All tool functions: `def tool_name(user, **kwargs) -> dict`. Return `{"error": "..."}` on failure; never raise.

### Web Search Tool
- Uses `duckduckgo_search.DDGS().text(..., max_results=5)`.
- Error handling includes import fallback, rate-limit guard, and generic failure logging.
- Dependency: `duckduckgo-search>=4.0.0` in `backend/server/requirements.txt`.

## Backend Chat Endpoint Architecture

### URL Routing
- `backend/server/main/urls.py`: `path("api/chat/", include("chat.urls"))`
- `backend/server/chat/urls.py`: DRF `DefaultRouter` registers `conversations/` -> `ChatViewSet`, `providers/` -> `ChatProviderCatalogViewSet`
- Manual paths: `POST /api/chat/suggestions/day/` -> `DaySuggestionsView`, `GET /api/chat/capabilities/` -> `CapabilitiesView`

### ChatViewSet Pattern
- All actions: `permission_classes = [IsAuthenticated]`
- Streaming response uses `StreamingHttpResponse(content_type="text/event-stream")`
- SSE chunk format: `data: {json}\n\n`; terminal `data: [DONE]\n\n`
- Tool loop: up to `MAX_TOOL_ITERATIONS = 10` rounds

### Day Suggestions Endpoint
- `POST /api/chat/suggestions/day/` via `chat/views/day_suggestions.py`
- Non-streaming JSON response
- Inputs: `collection_id`, `date`, `category`, `filters`, `location_context`
- Provider/model resolution via `_resolve_provider_and_model()`: request payload → `UserAISettings` defaults → instance defaults (`VOYAGE_AI_PROVIDER`/`VOYAGE_AI_MODEL`) → provider config default. No hardcoded OpenAI fallback.
- Cross-provider model guard: `preferred_model` only applied when provider matches `preferred_provider`.
- LLM call via `litellm.completion` with regex JSON extraction fallback
- Suggestion normalization: frontend `normalizeSuggestionItem()` handles LLM response variants (title/place_name/venue, summary/details, address/neighborhood). Items without resolvable name are dropped.
- Add-to-itinerary: `buildLocationPayload()` constructs `LocationSerializer`-compatible payload (name/location/description/rating/collections/is_public) from normalized suggestion.

### Capabilities Endpoint
- `GET /api/chat/capabilities/` returns `{ "tools": [{ "name", "description" }, ...] }` from registry

## WS4-F4 Chat UI Rendering
- Travel-themed header (icon: airplane, title: `Travel Assistant` with optional collection name suffix)
- `ChatMessage` type supports `tool_results?: Array<{ name, result }>` for inline tool output
- SSE handling appends to current assistant message's `tool_results` array
- Renderer: `search_places` -> place cards, `web_search` -> linked cards, fallback -> JSON `<pre>`

## WS4-F3 Add-to-itinerary from Chat
- `search_places` card results can be added directly to itinerary when collection context exists
- Flow: date selector modal -> `POST /api/locations/` -> `POST /api/itineraries/` -> `itemAdded` event
- Coordinate guard (`hasPlaceCoordinates`) required
