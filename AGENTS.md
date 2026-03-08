# Voyage Development Instructions (OpenCode)

## Project
- **Name**: Voyage
- **Purpose**: Self-hosted travel companion web app (fork of AdventureLog)
- **Stack**: SvelteKit 2 (TypeScript) frontend · Django REST Framework (Python) backend · PostgreSQL + PostGIS · Memcached · Docker · Bun (frontend package manager)

## Architecture Overview
- **API proxy pattern**: Frontend never calls Django directly. All API calls go through `frontend/src/routes/api/[...path]/+server.ts`, which proxies to `http://server:8000`, handles cookies, and injects CSRF behavior.
- **AI chat**: Embedded in Collections → Recommendations via `AITravelChat.svelte` component. No standalone `/chat` route. Provider list is dynamic from backend `GET /api/chat/providers/` (sourced from LiteLLM runtime + custom entries like `opencode_zen`). Chat conversations use SSE streaming via `/api/chat/conversations/`. Chat composer supports per-provider model override (persisted in browser `localStorage`). LiteLLM errors are mapped to sanitized user-safe messages via `_safe_error_payload()` (never exposes raw exception text).
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
- Backend tests: **6/30 fail** (pre-existing: 2 user email key errors + 4 geocoding API mocks)
- Docker dev setup has frontend-backend communication issues (500 errors beyond homepage)

## Key Patterns
- i18n: use `$t('key')` for user-facing strings
- API calls: route through proxy at `/api/[...path]/+server.ts`
- Styling: use DaisyUI semantic colors/classes (`bg-primary`, `text-base-content`, etc.)
- Security: handle CSRF tokens via `/auth/csrf/` and `X-CSRFToken`
- Chat providers: dynamic catalog from `GET /api/chat/providers/`; configured in `CHAT_PROVIDER_CONFIG`
- Chat model override: composer text input for per-provider model selection; persisted in `localStorage` key `voyage_chat_model_prefs`; backend accepts optional `model` param in `send_message`
- Chat error surfacing: `_safe_error_payload()` maps LiteLLM exceptions to sanitized user-safe categories (never forwards raw `exc.message`)

## Conventions
- Do **not** attempt to fix known test/configuration issues as part of feature work.
- Use `bun` for frontend commands, `uv` for local Python tooling where applicable.
- Commit and merge completed feature branches promptly once validation passes (avoid leaving finished work unmerged).

## .memory Files
- At the start of any task, read `.memory/knowledge.md` and `.memory/decisions.md` for project context.
- Check relevant files in `.memory/plans/` and `.memory/research/` for prior work on related topics.
- These files capture architectural decisions, code review verdicts, security findings, and implementation plans from prior sessions.
- Do **not** duplicate information from `.memory/` into code comments — keep `.memory/` as the single source of truth for project history.

## Instruction File Sync
- `AGENTS.md` (OpenCode), `CLAUDE.md` (Claude Code), `.cursorrules` (Cursor), and the Copilot CLI custom instructions must always be kept in sync.
- Whenever any of these files is updated (new convention, new decision, new workflow rule), apply the equivalent change to all the others.
