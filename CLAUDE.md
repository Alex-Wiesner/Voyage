# Voyage Development Instructions (Claude Code)

## Project
- **Name**: Voyage
- **Purpose**: Build and maintain a self-hosted travel companion web app (fork of AdventureLog).
- **Stack**: SvelteKit 2 (TypeScript) frontend · Django REST Framework (Python) backend · PostgreSQL + PostGIS · Memcached · Docker · Bun (frontend package manager)

## Pre-Release Policy
Voyage is **pre-release** — not yet in production use. During pre-release:
- Architecture-level changes are allowed, including replacing core libraries (e.g. LiteLLM).
- Prioritize correctness, simplicity, and maintainability over backward compatibility.
- Before launch, this policy must be revisited and tightened for production stability.

## Architecture Overview
- Use the API proxy pattern: never call Django directly from frontend components.
- Route all frontend API calls through `frontend/src/routes/api/[...path]/+server.ts`.
- Proxy target is `http://server:8000`; preserve session cookies and CSRF behavior.
- AI chat is embedded in Collections → Recommendations via `AITravelChat.svelte`. There is no standalone `/chat` route. Chat providers are loaded dynamically from `GET /api/chat/providers/` (backed by LiteLLM runtime providers + custom entries like `opencode_zen`). Chat conversations stream via SSE through `/api/chat/conversations/`. Default AI provider/model saved via `UserAISettings` in DB (authoritative over browser localStorage). LiteLLM errors are mapped to sanitized user-safe messages via `_safe_error_payload()` (never exposes raw exception text). Invalid tool calls (missing required args) are detected and short-circuited with a user-visible error — not replayed into history.
- Service ports:
  - `web` → `:8015`
  - `server` → `:8016`
  - `db` → `:5432`
  - `cache` → internal only
- Keep authentication session-based with `django-allauth`.
- Fetch CSRF token from `/auth/csrf/` and send `X-CSRFToken` on mutating requests.
- Preserve mobile middleware support for `X-Session-Token`.

## Codebase Layout
- Backend root: `backend/server/`
  - Apps: `adventures/`, `users/`, `worldtravel/`, `integrations/`, `achievements/`, `chat/`
  - Chat provider config: `backend/server/chat/llm_client.py` (`CHAT_PROVIDER_CONFIG`)
- Frontend root: `frontend/src/`
  - Routes: `src/routes/`
  - Shared types: `src/lib/types.ts` (includes `ChatProviderCatalogEntry`)
  - Components: `src/lib/components/` (includes `AITravelChat.svelte`)
  - Locales: `src/locales/`

## Development Workflow
- Develop Docker-first. Start services with Docker before backend-dependent work.
- Use these commands:

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
Run in this exact order:
1. `cd frontend && bun run format`
2. `cd frontend && bun run lint`
3. `cd frontend && bun run check`
4. `cd frontend && bun run build`

**ALWAYS run format before committing.**

## Known Issues (Expected)
- Frontend `bun run check`: **0 errors + 6 warnings** expected (pre-existing in `CollectionRecommendationView.svelte` + `RegionCard.svelte`)
- Backend tests: **6/30 fail** (pre-existing: 2 user email key errors + 4 geocoding API mocks)
- Docker dev setup has frontend-backend communication issues (500 errors beyond homepage)

## Key Patterns
- i18n: wrap user-facing strings with `$t('key')`
- API access: always use proxy route `/api/[...path]/+server.ts`
- Styling: prefer DaisyUI semantic classes (`bg-primary`, `text-base-content`)
- CSRF handling: use `/auth/csrf/` + `X-CSRFToken`
- Chat providers: dynamic catalog from `GET /api/chat/providers/`; configured in `CHAT_PROVIDER_CONFIG`
- Chat model override: dropdown selector fed by `GET /api/chat/providers/{provider}/models/`; persisted in `localStorage` key `voyage_chat_model_prefs`; backend accepts optional `model` param in `send_message`
- Chat context: collection chats inject multi-stop itinerary context; system prompt guides `get_trip_details`-first reasoning
- Chat error surfacing: `_safe_error_payload()` maps LiteLLM exceptions to sanitized user-safe categories (never forwards raw `exc.message`)
- Invalid tool calls (missing required args) are detected and short-circuited with a user-visible error — not replayed into history

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
- `AGENTS.md` (OpenCode), `CLAUDE.md` (Claude Code), `.cursorrules` (Cursor), and the Copilot CLI custom instructions must always be kept in sync.
- Whenever any of these files is updated (new convention, new decision, new workflow rule), apply the equivalent change to all the others.
