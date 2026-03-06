# Voyage Agent Project Notes

This file captures project-local commands and conventions for working in the Voyage repository.

## Frontend (SvelteKit)

- Working directory: `frontend/`
- Package manager: `pnpm`
- Install dependencies: `pnpm install`
- Dev server: `pnpm dev` (Vite dev server; frontend is configured to work with the Django backend in development)
- Build: `pnpm build`
- Preview production build: `pnpm preview`
- Type check: `pnpm check` (`svelte-check`)
- Lint: `pnpm lint` (currently runs `prettier --check .`; no ESLint config file is present right now)
- Format: `pnpm format` (runs `prettier --write .`)
- Type check (watch mode): `pnpm check:watch`

## Backend (Django + DRF)

- Working directory: `backend/server/`
- Python environment: use project-root `.venv/` if available, otherwise standard Django/Python environment setup
- Install dependencies: `pip install -r requirements.txt`
- Run development server: `python manage.py runserver`
- Apply migrations: `python manage.py migrate`
- Create admin user: `python manage.py createsuperuser`
- Run tests: `python manage.py test`
- Django app locations:
  - `backend/server/adventures/`
  - `backend/server/achievements/`
  - `backend/server/integrations/`
  - `backend/server/main/`
  - `backend/server/users/`
  - `backend/server/worldtravel/`
- Linting: `ruff check .`
- Formatting: `ruff format .`

## Docker Compose Workflows

- Development stack: `docker compose -f docker-compose.dev.yml up`
- Production-like stack: `docker compose up`
- Traefik stack: `docker compose -f docker-compose-traefik.yaml up`
- Rebuild images after changes: add `--build` to the selected command

## Testing Notes

- Frontend tests: no `test` script is currently defined in `frontend/package.json`
- Backend tests: run `python manage.py test` from `backend/server/`

## Code Style and Quality

- Python style tooling: Ruff (`ruff check .` and `ruff format .`)
- Ruff config location: no `pyproject.toml` or `ruff.toml` was found in this repository, so Ruff defaults (or editor/tooling settings) apply unless added later
- TypeScript/Svelte style tooling: Prettier is configured in `frontend/.prettierrc`; ESLint config files are not currently present
- Commit style: Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`)

## Project Structure Quick Reference

- Frontend source: `frontend/src/`
- Backend apps: `backend/server/<app>/`
- Documentation site: `documentation/` (VitePress)
- Container images:
  - `ghcr.io/alex-wiesner/voyage-frontend`
  - `ghcr.io/alex-wiesner/voyage-backend`
