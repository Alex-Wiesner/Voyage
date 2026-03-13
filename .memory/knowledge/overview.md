---
title: overview
type: note
permalink: voyage/knowledge/overview
---

# Architecture Overview

## API Proxy Pattern
Frontend never calls Django directly. All API calls go through `src/routes/api/[...path]/+server.ts` → Django at `http://server:8000`. Frontend uses relative URLs like `/api/locations/`.

## AI Chat (Collections → Recommendations)
- AI travel chat is embedded in **Collections → Recommendations** via `AITravelChat.svelte` (no standalone `/chat` route).
- Provider selector loads dynamically from `GET /api/chat/providers/` (backed by `litellm.provider_list` + `CHAT_PROVIDER_CONFIG` in `backend/server/chat/llm_client.py`).
- Supported configured providers: OpenAI, Anthropic, Gemini, Ollama, Groq, Mistral, GitHub Models, OpenRouter, OpenCode Zen (`opencode_zen`, `api_base=https://opencode.ai/zen/v1`, default model `openai/gpt-5-nano`).
- Chat conversations stream via SSE through `/api/chat/conversations/`.
- `ChatViewSet.send_message()` accepts optional context fields (`collection_id`, `collection_name`, `start_date`, `end_date`, `destination`) and appends a `## Trip Context` section to the system prompt when provided. When a `collection_id` is present, also injects `Itinerary stops:` from `collection.locations` (up to 8 unique stops) and the collection UUID with explicit `get_trip_details`/`add_to_itinerary` grounding. See [patterns/chat-and-llm.md](patterns/chat-and-llm.md#trip-context-uuid-grounding) and [patterns/chat-and-llm.md](patterns/chat-and-llm.md#multi-stop-context-derivation).
- Chat composer supports per-provider model override (persisted in browser `localStorage` key `voyage_chat_model_prefs`). DB-saved default provider/model (`UserAISettings`) is authoritative on initialization; localStorage is write-only sync target. Backend `send_message` accepts optional `model` param; falls back to DB defaults → instance defaults → `"openai"`.
- Chat agent tools (`get_trip_details`, `add_to_itinerary`) authorize using `Q(user=user) | Q(shared_with=user)` — both owners and shared members can use them. `list_trips` remains owner-only. See [patterns/chat-and-llm.md](patterns/chat-and-llm.md#shared-trip-tool-access).
- Invalid required-argument tool calls are detected and short-circuited: stream terminates with `tool_validation_error` SSE event + `[DONE]` and invalid tool results are not replayed into conversation history. See [patterns/chat-and-llm.md](patterns/chat-and-llm.md#tool-call-error-handling-chat-loop-hardening).
- LiteLLM errors mapped to sanitized user-safe messages via `_safe_error_payload()` (never exposes raw exception text). See [patterns/chat-and-llm.md](patterns/chat-and-llm.md#sanitized-llm-error-mapping).
- Tool outputs display as concise summaries (not raw JSON) via `getToolSummary()`. Persisted `role=tool` messages are hidden from display; on conversation reload, `rebuildConversationMessages()` reconstructs `tool_results` on assistant messages. See [patterns/chat-and-llm.md](patterns/chat-and-llm.md#tool-output-rendering).
- Embedded chat uses compact header (provider/model selectors in settings dropdown with outside-click/Escape close), bounded height, sidebar-closed-by-default, visible streaming indicator, and i18n aria-labels. See [patterns/chat-and-llm.md](patterns/chat-and-llm.md#embedded-chat-ux).
- Frontend type: `ChatProviderCatalogEntry` in `src/lib/types.ts`.
- Reference: [Plan: AI travel agent](../plans/ai-travel-agent-collections-integration.md), [Plan: AI travel agent redesign — WS4](../plans/ai-travel-agent-redesign.md#ws4-collection-level-chat-improvements)

## Services (Docker Compose)
| Service | Container | Port |
|---------|-----------|------|
| Frontend | `web` | :8015 |
| Backend | `server` | :8016 |
| Database | `db` | :5432 |
| Cache | `cache` | internal |

## Authentication
Session-based via `django-allauth`. CSRF tokens from `/auth/csrf/`, passed as `X-CSRFToken` header. Mobile clients use `X-Session-Token` header.

## Key File Locations
- Frontend source: `frontend/src/`
- Backend source: `backend/server/`
- Django apps: `adventures/`, `users/`, `worldtravel/`, `integrations/`, `achievements/`, `chat/`
- Chat LLM config: `backend/server/chat/llm_client.py` (`CHAT_PROVIDER_CONFIG`)
- AI Chat component: `frontend/src/lib/components/AITravelChat.svelte`
- Types: `frontend/src/lib/types.ts`
- API proxy: `frontend/src/routes/api/[...path]/+server.ts`
- i18n: `frontend/src/locales/`
- Docker config: `docker-compose.yml`, `docker-compose.dev.yml`
- CI/CD: `.github/workflows/`
- Public docs: `documentation/` (VitePress)