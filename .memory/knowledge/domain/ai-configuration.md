---
title: ai-configuration
type: note
permalink: voyage/knowledge/domain/ai-configuration
---

# AI Configuration Domain

## WS1 Configuration Infrastructure

### WS1-F1: Instance-level env vars and key fallback
- `settings.py`: `VOYAGE_AI_PROVIDER`, `VOYAGE_AI_MODEL`, `VOYAGE_AI_API_KEY`
- `get_llm_api_key(user, provider)` falls back to instance key only when provider matches `VOYAGE_AI_PROVIDER`
- Fallback chain: user key -> matching-provider instance key -> error
- See [tech-stack.md](../tech-stack.md#server-side-env-vars-from-settingspy), [decisions.md](../../decisions.md#ws1-configuration-infrastructure-backend-review)

### WS1-F2: UserAISettings model
- `integrations/models.py`: `UserAISettings` (OneToOneField to user) with `preferred_provider` and `preferred_model`
- Endpoint: `/api/integrations/ai-settings/` (upsert pattern)
- Migration: `0008_useraisettings.py`

### WS1-F3: Provider catalog enhancement
- `get_provider_catalog(user=None)` adds `instance_configured` and `user_configured` booleans
- User API keys prefetched once per request (no N+1)
- `ChatProviderCatalogEntry` TypeScript type updated with both fields

### Frontend Provider Selection (Fixed)
- No longer hardcodes `selectedProvider = 'openai'`; auto-selects first usable provider
- Filtered to configured+usable entries only (`available_for_chat && (user_configured || instance_configured)`)
- Warning alert + Settings link when no providers configured
- Model selection uses dropdown from `GET /api/chat/providers/{provider}/models/`

## Known Frontend Gaps

### Root Cause of User-Facing LLM Errors
Three compounding issues (all resolved):
1. ~~Hardcoded `'openai'` default~~ (fixed: auto-selects first usable)
2. ~~No provider status feedback~~ (fixed: catalog fields consumed)
3. ~~`UserAISettings.preferred_provider` never loaded~~ (fixed: Settings UI saves/loads DB defaults; chat initializes from saved prefs)
4. `FIELD_ENCRYPTION_KEY` not set disables key storage (env-dependent)
5. ~~TypeScript type missing fields~~ (fixed)

## Key Edit Reference Points
| Feature | File | Location |
|---|---|---|
| AI env vars | `backend/server/main/settings.py` | after `FIELD_ENCRYPTION_KEY` |
| Fallback key | `backend/server/chat/llm_client.py` | `get_llm_api_key()` |
| UserAISettings model | `backend/server/integrations/models.py` | after UserAPIKey |
| Catalog user flags | `backend/server/chat/llm_client.py` | `get_provider_catalog()` |
| Provider view | `backend/server/chat/views/__init__.py` | `ChatProviderCatalogViewSet` |