# Coding Conventions & Patterns

## Frontend Patterns
- **i18n**: Use `$t('key')` from `svelte-i18n`; add keys to locale files
- **API calls**: Always use `credentials: 'include'` and `X-CSRFToken` header
- **Svelte reactivity**: Reassign to trigger: `items[i] = updated; items = items`
- **Styling**: DaisyUI semantic classes + Tailwind utilities; use `bg-primary`, `text-base-content` not raw colors
- **Maps**: `svelte-maplibre` with MapLibre GL; GeoJSON data

## Backend Patterns
- **Views**: DRF `ModelViewSet` subclasses; `get_queryset()` filters by `user=self.request.user`
- **Money**: `djmoney` MoneyField
- **Geo**: PostGIS via `django-geojson`
- **Chat providers**: Dynamic catalog from `GET /api/chat/providers/`; configured in `CHAT_PROVIDER_CONFIG`

## Workflow Conventions
- Do **not** attempt to fix known test/configuration issues as part of feature work
- Use `bun` for frontend commands, `uv` for local Python tooling where applicable
- Commit and merge completed feature branches promptly once validation passes (avoid leaving finished work unmerged)
- See [decisions.md](../decisions.md#workflow-preference-commit--merge-when-done) for rationale
