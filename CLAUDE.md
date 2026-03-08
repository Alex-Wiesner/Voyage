# Voyage Development Instructions (Claude Code)

## Project
- **Name**: Voyage
- **Purpose**: Build and maintain a self-hosted travel companion web app (fork of AdventureLog).
- **Stack**: SvelteKit 2 (TypeScript) frontend · Django REST Framework (Python) backend · PostgreSQL + PostGIS · Memcached · Docker · Bun (frontend package manager)

## Architecture Overview
- Use the API proxy pattern: never call Django directly from frontend components.
- Route all frontend API calls through `frontend/src/routes/api/[...path]/+server.ts`.
- Proxy target is `http://server:8000`; preserve session cookies and CSRF behavior.
- AI chat is embedded in Collections → Recommendations via `AITravelChat.svelte`. There is no standalone `/chat` route. Chat providers are loaded dynamically from `GET /api/chat/providers/` (backed by LiteLLM runtime providers + custom entries like `opencode_zen`). Chat conversations stream via SSE through `/api/chat/conversations/`.
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
- Frontend `bun run check`: **3 type errors + 19 warnings** expected
- Backend tests: **2/3 fail** (expected)
- Docker dev setup has frontend-backend communication issues (500 errors beyond homepage)

## Key Patterns
- i18n: wrap user-facing strings with `$t('key')`
- API access: always use proxy route `/api/[...path]/+server.ts`
- Styling: prefer DaisyUI semantic classes (`bg-primary`, `text-base-content`)
- CSRF handling: use `/auth/csrf/` + `X-CSRFToken`
- Chat providers: dynamic catalog from `GET /api/chat/providers/`; configured in `CHAT_PROVIDER_CONFIG`

## Conventions
- Do **not** attempt to fix known test/configuration issues as part of feature work.
- Use `bun` for frontend commands, `uv` for local Python tooling where applicable.
- Commit and merge completed feature branches promptly once validation passes (avoid leaving finished work unmerged).
