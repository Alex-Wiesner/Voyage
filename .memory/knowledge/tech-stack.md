# Tech Stack & Development

## Stack
- **Frontend**: SvelteKit 2, TypeScript, Bun (package manager), DaisyUI + Tailwind CSS, svelte-i18n, svelte-maplibre
- **Backend**: Django REST Framework, Python, django-allauth, djmoney, django-geojson, LiteLLM, duckduckgo-search
- **Database**: PostgreSQL + PostGIS
- **Cache**: Memcached
- **Infrastructure**: Docker, Docker Compose
- **Repo**: github.com/Alex-Wiesner/voyage
- **License**: GNU GPL v3.0

## Development Commands

### Frontend (prefer Bun)
- `cd frontend && bun run format` — fix formatting (6s)
- `cd frontend && bun run lint` — check formatting (6s)
- `cd frontend && bun run check` — Svelte type checking (12s; 0 errors, 6 warnings expected)
- `cd frontend && bun run build` — build (32s)
- `cd frontend && bun install` — install deps (45s)

### Backend (Docker required; uv for local Python tooling)
- `docker compose exec server python3 manage.py test` — run tests (7s; 6/30 pre-existing failures expected)
- `docker compose exec server python3 manage.py migrate` — run migrations

### Pre-Commit Checklist
1. `cd frontend && bun run format`
2. `cd frontend && bun run lint`
3. `cd frontend && bun run check`
4. `cd frontend && bun run build`

## Environment & Configuration

### .env Loading
- **Library**: `python-dotenv==1.2.2` (in `backend/server/requirements.txt`)
- **Entry point**: `backend/server/main/settings.py` calls `load_dotenv()` at module top
- **Docker**: `docker-compose.yml` sets `env_file: .env` on all services — single root `.env` file shared
- **Root `.env`**: `/home/alex/projects/voyage/.env` — canonical for Docker Compose setups

### Settings File
- **Single file**: `backend/server/main/settings.py` (no split/environment-specific settings files)

### Server-side Env Vars (from `settings.py`)
| Var | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | (required) | Django secret key |
| `GOOGLE_MAPS_API_KEY` | `""` | Google Maps integration |
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | `""` | Strava OAuth |
| `FIELD_ENCRYPTION_KEY` | `""` | Fernet key for `UserAPIKey` encryption |
| `OSRM_BASE_URL` | `"https://router.project-osrm.org"` | Routing service |
| `VOYAGE_AI_PROVIDER` | `"openai"` | Instance-level default AI provider |
| `VOYAGE_AI_MODEL` | `"gpt-4o-mini"` | Instance-level default AI model |
| `VOYAGE_AI_API_KEY` | `""` | Instance-level AI API key |

### Per-User LLM API Key Pattern
LLM provider keys stored per-user in DB (`UserAPIKey` model, `integrations/models.py`):
- `UserAPIKey` table: `(user, provider)` unique pair → `encrypted_api_key` (Fernet-encrypted text field)
- `FIELD_ENCRYPTION_KEY` env var required for encrypt/decrypt
- `llm_client.get_llm_api_key(user, provider)` → user key → instance key fallback (matching provider only) → `None`
- No global server-side LLM API keys — every user must configure their own per-provider key via Settings UI (or instance admin configures fallback)

## Known Issues
- Docker dev setup has frontend-backend communication issues (500 errors beyond homepage)
- Frontend check: 0 errors, 6 warnings expected (pre-existing in `CollectionRecommendationView.svelte` + `RegionCard.svelte`)
- Backend tests: 6/30 pre-existing failures (2 user email key errors + 4 geocoding API mocks)
- Local Python pip install fails (network timeouts) — use Docker
