---
title: architecture
type: note
permalink: voyage/docs/architecture
---

# Voyage Architecture

> **Status**: Stub — to be expanded as architecture evolves.

## Overview

Voyage is a self-hosted travel companion built with SvelteKit (frontend) and Django REST Framework (backend), deployed via Docker.

## Key Architectural Patterns

### API Proxy
The frontend never calls Django directly. All API calls go through `src/routes/api/[...path]/+server.ts`, which proxies to the Django server, injecting CSRF tokens and managing session cookies.

### Services (Docker Compose)
- `web` → SvelteKit frontend (`:8015`)
- `server` → Django via Gunicorn + Nginx (`:8016`)
- `db` → PostgreSQL + PostGIS (`:5432`)
- `cache` → Memcached (internal)

### Authentication
Session-based via `django-allauth`. CSRF tokens from `/auth/csrf/`, passed as `X-CSRFToken` header.

## Backend Apps
- `adventures` — core domain (locations, collections, itineraries, notes, transportation, MCP)
- `users` — user management
- `worldtravel` — countries, regions, cities, visited tracking
- `integrations` — external service integrations
- `achievements` — gamification
- `chat` — LLM chat/agent (AI travel chat in Collections → Recommendations; dynamic provider catalog via LiteLLM; `GET /api/chat/providers/`)

## Frontend Structure
- `src/routes/` — SvelteKit file-based routing
- `src/lib/types.ts` — TypeScript interfaces
- `src/lib/components/` — Svelte components by domain
- `src/locales/` — i18n JSON files

## TODO
- [ ] Data flow diagrams
- [ ] Database schema overview
- [ ] Deployment architecture
- [ ] MCP endpoint architecture