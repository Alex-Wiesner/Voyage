---
title: AGENTS
type: note
permalink: voyage/agents
---

# Voyage Development Instructions (OpenCode)

## Project
- **Name**: Voyage
- **Purpose**: Self-hosted travel companion web app (fork of AdventureLog)
- **Stack**: SvelteKit 2 (TypeScript) frontend · Django REST Framework (Python) backend · PostgreSQL + PostGIS · Memcached · Docker · Bun (frontend package manager)

## Pre-Release Policy
Voyage is **pre-release** — not yet in production use. During pre-release:
- Architecture-level changes are allowed, including replacing core libraries (e.g. LiteLLM).
- Prioritize correctness, simplicity, and maintainability over backward compatibility.
- Before launch, this policy must be revisited and tightened for production stability.

## Architecture Overview
- **API proxy pattern**: Frontend never calls Django directly. All API calls go through `frontend/src/routes/api/[...path]/+server.ts`, which proxies to `http://server:8000`, handles cookies, and injects CSRF behavior.
- **AI chat**: Embedded in Collections → Recommendations via `AITravelChat.svelte` component. No standalone `/chat` route. Provider list is dynamic from backend `GET /api/chat/providers/` (sourced from LiteLLM runtime + custom entries like `opencode_zen`). Chat conversations use SSE streaming via `/api/chat/conversations/`. Default AI provider/model saved via `UserAISettings` in DB (authoritative over browser localStorage). LiteLLM errors are mapped to sanitized user-safe messages via `_safe_error_payload()` (never exposes raw exception text). Invalid tool calls (missing required args) are detected and short-circuited with a user-visible error — not replayed into history. Chat agent tools (`get_trip_details`, `add_to_itinerary`) respect collection sharing — both owners and `shared_with` members can use them; `list_trips` remains owner-only.
- **Service ports**:
  - `web` → `:8015`
  - `server` → `:8016`
  - `db` → `:5432`
  - `cache` → internal only
- **Authentication**: Session-based via `django-allauth`; CSRF token from `/auth/csrf/`; mutating requests send `X-CSRFToken`; mobile middleware path supports `X-Session-Token`.

## Codebase Layout
- **Backend**: `backend/server/`
  - Apps: `adventures/`, `users/`, `worldtravel/`, `integrations/`, `achievements/`, `chat/`
  - Chat provider config: `backend/server/chat/llm_client.py` (`CHAT_PROVIDER_CONFIG`)
- **Frontend**: `frontend/src/`
  - Routes: `src/routes/`
  - Shared types: `src/lib/types.ts` (includes `ChatProviderCatalogEntry`)
  - Components: `src/lib/components/` (includes `AITravelChat.svelte`)
  - i18n: `src/locales/`

## Development Commands

### Frontend (prefer Bun)
- `cd frontend && bun run format`
- `cd frontend && bun run lint`
- `cd frontend && bun run check`
- `cd frontend && bun run build`
- `cd frontend && bun install`

### Backend (Docker required; prefer uv for local Python tooling)
- `docker compose exec server python3 manage.py test`
- `docker compose exec server python3 manage.py migrate`

### Docker
- `docker compose up -d`
- `docker compose down`

## Pre-Commit Checklist
Run in this order:
1. `cd frontend && bun run format`
2. `cd frontend && bun run lint`
3. `cd frontend && bun run check`
4. `cd frontend && bun run build`

## Known Issues (Expected)
- Frontend `bun run check`: **0 errors + 6 warnings** expected (pre-existing in `CollectionRecommendationView.svelte` + `RegionCard.svelte`)
- Backend tests: **6/39 fail** (pre-existing: 2 user email key errors + 4 geocoding API mocks; 32 chat tests all pass)
- Docker dev setup has frontend-backend communication issues (500 errors beyond homepage)

## Key Patterns
- i18n: use `$t('key')` for user-facing strings
- API calls: route through proxy at `/api/[...path]/+server.ts`
- Styling: use DaisyUI semantic colors/classes (`bg-primary`, `text-base-content`, etc.)
- Security: handle CSRF tokens via `/auth/csrf/` and `X-CSRFToken`
- Chat providers: dynamic catalog from `GET /api/chat/providers/`; configured in `CHAT_PROVIDER_CONFIG`
- Chat model override: dropdown selector fed by `GET /api/chat/providers/{provider}/models/`; persisted in `localStorage` key `voyage_chat_model_prefs`; backend accepts optional `model` param in `send_message`
- Chat context: collection chats inject collection UUID + multi-stop itinerary context; system prompt guides `get_trip_details`-first reasoning and confirms only before first `add_to_itinerary`; `search_places` has a deterministic context-retry fallback — when the LLM omits `location`, the backend retries using the trip destination or first itinerary stop before asking the user for clarification; a dining-intent heuristic infers `category="food"` from user messages when the LLM omits category for restaurant/dining requests
- `itinerary_stops` extraction: when `city`/`country` FK is null, city is extracted from the last non-numeric segment of a comma-separated address (e.g. `"Little Turnstile 6, London"` → `"London"`); ensures `trip_context_location` is always a geocodable city name, not a street address.
- After itinerary context retries: if all retries fail, result is converted to an execution failure rather than triggering a clarification prompt — the user is never asked for a location they already implied via collection context.
- Chat tool output: `role=tool` messages hidden from display; tool outputs render as concise summaries; persisted tool rows reconstructed on reload via `rebuildConversationMessages()`; tool results are deduplicated by `tool_call_id` at three layers — rebuild from persisted rows (discards server-side pre-populated `tool_results`), SSE ingestion (`appendToolResultDedup`), and render-time (`uniqueToolResultsByCallId`)
- Chat error surfacing: `_safe_error_payload()` maps LiteLLM exceptions to sanitized user-safe categories (never forwards raw `exc.message`); `execute_tool()` catch-all returns a generic sanitized message (never raw `str(exc)`)
- Invalid tool calls (missing required args) are detected and short-circuited with a user-visible error — not replayed into history
- Tool execution failures (`search_places`, `web_search`, catch-all errors) are classified separately from required-param validation errors; execution failures emit a bounded `tool_execution_error` SSE event and stop — they are never replayed into LLM context; `tool_iterations` increments only on successful tool calls; all-failure rounds are capped at `MAX_ALL_FAILURE_ROUNDS` (3); permanent failures (e.g. `web_search` import error with `retryable: false`) stop immediately
- Geocoding failures in `search_places` (`Could not geocode location: ...`) are eligible for the existing context-retry path (trip destination → first itinerary stop → user clarification)
- Geocoding: `background_geocode_and_assign()` runs in a thread after Location save; populates `region`, `city`, `country`, and also fills `Location.location` from reverse geocode `display_name` (truncated to field max_length) if blank or different

## Conventions
- Do **not** attempt to fix known test/configuration issues as part of feature work.
- Use `bun` for frontend commands, `uv` for local Python tooling where applicable.
- Commit and merge completed feature branches promptly once validation passes (avoid leaving finished work unmerged).

## .memory Files
- At the start of any task, read `.memory/manifest.yaml` to discover available files, then read `system.md` and relevant `knowledge/` files for project context.
- Read `.memory/decisions.md` for architectural decisions and review verdicts.
- Check relevant files in `.memory/plans/` and `.memory/research/` for prior work on related topics.
- These files capture architectural decisions, code review verdicts, security findings, and implementation plans from prior sessions.
- Do **not** duplicate information from `.memory/` into code comments — keep `.memory/` as the single source of truth for project history.

## Instruction File Sync
- `AGENTS.md` is the single source of truth for repository instructions.
- Do not maintain mirrored instruction files for other tools in this repo.
