---
title: ai-travel-agent-collections-integration
type: note
permalink: voyage/plans/ai-travel-agent-collections-integration
---

# Plan: AI travel agent in Collections Recommendations

## Clarified requirements
- Move AI travel agent UX from standalone `/chat` tab/page into Collections → Recommendations.
- Remove the existing `/chat` route (not keep/redirect).
- Provider list should be dynamic and display all providers LiteLLM supports.
- Ensure OpenCode Zen is supported as a provider.

## Execution prerequisites
- In each worktree, run `cd frontend && npm install` before implementation to ensure node modules (including `@mdi/js`) are present and baseline build can run.

## Decomposition (approved by user)

### Workstream 1 — Collections recommendations chat integration (Frontend + route cleanup)
- **Worktree**: `.worktrees/collections-ai-agent`
- **Branch**: `feat/collections-ai-agent`
- **Risk**: Medium
- **Quality tier**: Tier 2
- **Task WS1-F1**: Embed AI chat experience inside Collections Recommendations UI.
  - **Acceptance criteria**:
    - Chat UI is available from Collections Recommendations section.
    - Existing recommendations functionality remains usable.
    - Chat interactions continue to work with existing backend chat APIs.
- **Task WS1-F2**: Remove standalone `/chat` route/page.
  - **Acceptance criteria**:
    - `/chat` page is removed from app routes/navigation.
    - No broken imports/navigation links remain.

### Workstream 2 — Provider catalog + Zen provider support (Backend + frontend settings/chat)
- **Worktree**: `.worktrees/litellm-provider-catalog`
- **Branch**: `feat/litellm-provider-catalog`
- **Risk**: Medium
- **Quality tier**: Tier 2 (promote to Tier 1 if auth/secret handling changes)
- **Task WS2-F1**: Implement dynamic provider listing based on LiteLLM-supported providers.
  - **Acceptance criteria**:
    - Backend exposes `GET /api/chat/providers/` using LiteLLM runtime provider list as source data.
    - Frontend provider selectors consume backend provider catalog rather than hardcoded arrays.
    - UI displays all LiteLLM provider IDs and metadata; non-chat-compatible providers are labeled unavailable.
    - Existing saved provider/API-key flows still function.
- **Task WS2-F2**: Add/confirm OpenCode Zen provider support end-to-end.
  - **Acceptance criteria**:
    - OpenCode Zen appears as provider id `opencode_zen`.
    - Backend model resolution and API-key lookup work for `opencode_zen`.
    - Zen calls use LiteLLM OpenAI-compatible routing with `api_base=https://opencode.ai/zen/v1`.
    - Chat requests using Zen provider are accepted without fallback/validation failures.

## Provider architecture decision
- Backend provider catalog endpoint `GET /api/chat/providers/` is the single source of truth for UI provider options.
- Endpoint response fields: `id`, `label`, `available_for_chat`, `needs_api_key`, `default_model`, `api_base`.
- All LiteLLM runtime providers are returned; entries without model mapping are `available_for_chat=false`.
- Chat send path only accepts providers where `available_for_chat=true`.

## Research findings (2026-03-08)
- LiteLLM provider enumeration is available at runtime (`litellm.provider_list`), currently 128 providers in this environment.
- OpenCode Zen is not a native LiteLLM provider alias; support should be implemented via OpenAI-compatible provider config and explicit `api_base`.
- Existing hardcoded provider duplication (backend + chat page + settings page) will be replaced by backend catalog consumption.
- Reference: [LiteLLM + Zen provider research](../research/litellm-zen-provider-catalog.md)

## Dependencies
- WS1 depends on existing chat API endpoint behavior and event streaming contract.
- WS2 depends on LiteLLM provider metadata/query capabilities and provider-catalog endpoint design.
- WS1-F1 depends on WS2 completion for dynamic provider selector integration.
- WS1-F2 depends on WS1-F1 completion.

## Human checkpoints
- No checkpoint required: Zen support path uses existing LiteLLM dependency via OpenAI-compatible API (no new SDK/service).

## Findings tracker
- WS1-F1 implemented in worktree `.worktrees/collections-ai-agent`:
  - Extracted chat route UI into reusable component `frontend/src/lib/components/AITravelChat.svelte`, preserving conversation list, message stream rendering, provider selector, conversation CRUD, and SSE send-message flow via `/api/chat/conversations/*`.
  - Updated `frontend/src/routes/chat/+page.svelte` to render the reusable component so existing `/chat` behavior remains intact for WS1-F1 scope (WS1-F2 route removal deferred).
  - Embedded `AITravelChat` into Collections Recommendations view in `frontend/src/routes/collections/[id]/+page.svelte` above `CollectionRecommendationView`, keeping existing recommendation search/map/create flows unchanged.
  - Reviewer warning resolved: removed redundant outer card wrapper around `AITravelChat` in Collections Recommendations embedding, eliminating nested card-in-card styling while preserving spacing and recommendations placement.
- WS1-F2 implemented in worktree `.worktrees/collections-ai-agent`:
  - Removed standalone chat route page by deleting `frontend/src/routes/chat/+page.svelte`.
  - Removed `/chat` navigation item from `frontend/src/lib/components/Navbar.svelte`, including the now-unused `mdiRobotOutline` icon import.
  - Verified embedded chat remains in Collections Recommendations via `AITravelChat` usage in `frontend/src/routes/collections/[id]/+page.svelte`; no remaining `/chat` route links/imports in `frontend/src`.
- WS2-F1 implemented in worktree `.worktrees/litellm-provider-catalog`:
  - Added backend provider catalog endpoint `GET /api/chat/providers/` from `litellm.provider_list` with response fields `id`, `label`, `available_for_chat`, `needs_api_key`, `default_model`, `api_base`.
  - Refactored chat provider model map into `CHAT_PROVIDER_CONFIG` in `backend/server/chat/llm_client.py` and reused it for both send-message routing and provider catalog metadata.
  - Updated chat/settings frontend provider consumers to fetch provider catalog dynamically and removed hardcoded provider arrays.
  - Chat UI now restricts provider selection/sending to `available_for_chat=true`; settings API key UI now lists full provider catalog (including unavailable-for-chat entries).
- WS2-F1 reviewer carry-forward fixes applied:
  - Fixed chat provider selection fallback timing in `frontend/src/routes/chat/+page.svelte` by computing `availableProviders` from local `catalog` response data instead of relying on reactive `chatProviders` immediately after assignment.
  - Applied low-risk settings improvement in `frontend/src/routes/settings/+page.svelte` by changing `await loadProviderCatalog()` to `void loadProviderCatalog()` in the second `onMount`, preventing provider fetch from delaying success toast logic.
- WS2-F2 implemented in worktree `.worktrees/litellm-provider-catalog`:
  - Added `opencode_zen` to `CHAT_PROVIDER_CONFIG` in `backend/server/chat/llm_client.py` with label `OpenCode Zen`, `needs_api_key=true`, `default_model=openai/gpt-4o-mini`, and `api_base=https://opencode.ai/zen/v1`.
  - Updated `get_provider_catalog()` to append configured chat providers not present in `litellm.provider_list`, ensuring OpenCode Zen appears in `GET /api/chat/providers/` even though it is an OpenAI-compatible alias rather than a native LiteLLM provider id.
  - Normalized provider IDs in `get_llm_api_key()` and `stream_chat_completion()` via `_normalize_provider_id()` to keep API-key lookup and LLM request routing consistent for `opencode_zen`.
- Consolidation completed in worktree `.worktrees/collections-ai-agent`:
  - Ported WS2 provider-catalog backend to `backend/server/chat` in the collections branch, including `GET /api/chat/providers/`, `CHAT_PROVIDER_CONFIG` metadata fields (`label`, `needs_api_key`, `default_model`, `api_base`), and chat-send validation to allow only `available_for_chat` providers.
  - Confirmed `opencode_zen` support in consolidated branch with `label=OpenCode Zen`, `default_model=openai/gpt-4o-mini`, `api_base=https://opencode.ai/zen/v1`, and API-key-required behavior.
  - Replaced hardcoded providers in `frontend/src/lib/components/AITravelChat.svelte` with dynamic `/api/chat/providers/` loading, preserving send guard to chat-available providers only.
  - Updated settings API-key provider dropdown in `frontend/src/routes/settings/+page.svelte` to load full provider catalog dynamically and added `ChatProviderCatalogEntry` type in `frontend/src/lib/types.ts`.
  - Preserved existing collections chat embedding and kept standalone `/chat` route removed (no route reintroduction in consolidation changes).

## Retry tracker
- WS1-F1: 0
- WS1-F2: 0
- WS2-F1: 0
- WS2-F2: 0

## Execution checklist
- [x] WS2-F1 Dynamic provider listing from LiteLLM (Tier 2)
- [x] WS2-F2 OpenCode Zen provider support (Tier 2)
- [x] WS1-F1 Embed AI chat into Collections Recommendations (Tier 2)
- [x] WS1-F2 Remove standalone `/chat` route (Tier 2)
- [x] Documentation coverage + knowledge sync (Librarian)