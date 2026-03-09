# Voyage — Decisions Log

## Fork from AdventureLog
- **Decision**: Fork AdventureLog and rebrand as Voyage
- **Rationale**: Build on proven foundation while adding itinerary UI, OSRM routing, LLM travel agent, lodging logic
- **Date**: Project inception

## Docker-Only Backend Development
- **Decision**: Backend development requires Docker; local Python pip install is not supported
- **Rationale**: Complex GDAL/PostGIS dependencies; pip install fails with network timeouts
- **Impact**: All backend commands run via `docker compose exec server`

## API Proxy Pattern
- **Decision**: Frontend proxies all API calls through SvelteKit server routes
- **Rationale**: Handles CSRF tokens and session cookies transparently; avoids CORS issues
- **Reference**: See [knowledge/overview.md](knowledge/overview.md#api-proxy-pattern)

## Package Manager: Bun (Frontend)
- **Decision**: Use Bun as frontend package manager (bun.lock present)
- **Note**: npm scripts still used for build/lint/check commands

## Tooling Preference: Bun + uv
- **Decision**: Prefer `bun` for frontend workflows and `uv` for Python workflows.
- **Rationale**: User preference for faster, consistent package/runtime tooling.
- **Operational rule**:
  - Frontend: use `bun install` and `bun run <script>` by default.
  - Python: use `uv` for local Python dependency/tooling commands when applicable.
  - Docker-managed backend runtime commands (e.g. `docker compose exec server python3 manage.py ...`) remain unchanged unless project tooling is explicitly migrated.
- **Date**: 2026-03-08

## Workflow Preference: Commit + Merge When Done
- **Decision**: Once a requested branch workstream is complete and validated, commit and merge promptly (do not leave completed branches unmerged).
- **Rationale**: User preference for immediate integration and reduced branch drift.
- **Operational rule**:
  - Ensure quality checks pass for the completed change set.
  - Commit feature branch changes.
  - Merge into target branch without delaying.
  - Clean up merged worktrees/branches after merge.
- **Date**: 2026-03-08

## WS1-F2 Review: Remove standalone /chat route
- **Verdict**: APPROVED (score 0)
- **Scope**: Deletion of `frontend/src/routes/chat/+page.svelte`, removal of `/chat` nav item and `mdiRobotOutline` import from Navbar.svelte.
- **Findings**: No broken imports, navigation links, or route references remain. All `/chat` string matches in codebase are `/api/chat/conversations/` backend API proxy calls (correct). Orphaned `navbar.chat` i18n key noted as minor cleanup suggestion.
- **Reference**: See [Plan: AI travel agent](plans/ai-travel-agent-collections-integration.md#task-ws1-f2)
- **Date**: 2026-03-08

## WS1 Tester Validation: collections-ai-agent worktree
- **Status**: PASS (Both Standard + Adversarial passes)
- **Build**: `bun run build` artifacts validated via `.svelte-kit/adapter-node` and `build/` output. No `/chat` route in compiled manifest. `AITravelChat` SSR-inlined into collections page at `currentView === 'recommendations'` with `embedded: true`.
- **Key findings**:
  - All 12 i18n keys used in `AITravelChat.svelte` confirmed present in `en.json`.
  - No `mdiRobotOutline`, `/chat` href, or chat nav references in any source `.svelte` files.
  - Navbar.svelte contains zero chat or robot icon references.
  - `CollectionRecommendationView` still renders after `AITravelChat` in recommendations view.
  - Build output is current: adapter-node manifest has 29 nodes (0-28) with no `/chat` page route.
- **Adversarial**: 3 hypotheses tested (broken i18n keys, orphaned chat imports, missing embedded prop); all negative.
- **MUTATION_ESCAPES**: 1/5 (minor: `embedded` prop boolean default not type-enforced; runtime safe).
- **Reference**: See [Plan: AI travel agent](plans/ai-travel-agent-collections-integration.md)
- **Date**: 2026-03-08

## Consolidated Review: AI Travel Agent + Collections + Provider Catalog
- **Verdict**: APPROVED (score 0)
- **Scope**: Full consolidated implementation in `collections-ai-agent` worktree — backend provider catalog endpoint (`GET /api/chat/providers/`), `CHAT_PROVIDER_CONFIG` with OpenCode Zen, dynamic provider selectors in `AITravelChat.svelte` and `settings/+page.svelte`, `ChatProviderCatalogEntry` type, chat embedding in Collections Recommendations, `/chat` route removal.
- **Acceptance verification**:
  - AI chat embedded in Collections Recommendations: `collections/[id]/+page.svelte:1264` renders `<AITravelChat embedded={true} />` inside `currentView === 'recommendations'`.
  - No `/chat` route: `frontend/src/routes/chat/` directory absent, no Navbar chat/robot references.
  - All LiteLLM providers listed: `get_provider_catalog()` iterates `litellm.provider_list` (128 providers) + appends custom `CHAT_PROVIDER_CONFIG` entries.
  - OpenCode Zen supported: `opencode_zen` in `CHAT_PROVIDER_CONFIG` with `api_base=https://opencode.ai/zen/v1`, `default_model=openai/gpt-4o-mini`.
- **Security**: `IsAuthenticated` on all chat endpoints, `get_queryset` scoped to `user=self.request.user`, no IDOR risk, API keys never exposed in catalog response, provider IDs validated before use.
- **Prior findings confirmed**: WS1-F2 removal review, WS1 tester validation, LiteLLM provider research — all still valid and matching implementation.
- **Reference**: See [Plan: AI travel agent](plans/ai-travel-agent-collections-integration.md)
- **Date**: 2026-03-08

## Consolidated Tester Validation: collections-ai-agent worktree (Full Consolidation)
- **Status**: PASS (Both Standard + Adversarial passes)
- **Pipeline inputs validated**: Frontend build (bun run format+lint+check+build → PASS, 0 errors, 6 expected warnings); Backend system check (manage.py check → PASS, 0 issues).
- **Key findings**:
  - All 12 i18n keys in `AITravelChat.svelte` confirmed present in `en.json`.
  - No `/chat` route file, no Navbar `/chat` href or `mdiRobotOutline` in any `.svelte` source.
  - Only `/chat` references are API proxy calls (`/api/chat/...`) — correct.
  - `ChatProviderCatalogEntry` type defined in `types.ts`; used correctly in both `AITravelChat.svelte` and `settings/+page.svelte`.
  - `opencode_zen` in `CHAT_PROVIDER_CONFIG` with `api_base`, appended by second loop in `get_provider_catalog()` since not in `litellm.provider_list`.
  - Provider validation in `send_message` view uses `is_chat_provider_available()` → 400 on invalid providers.
  - All agent tool functions scope DB queries to `user=user`.
  - `AITravelChat embedded={true}` correctly placed at `collections/[id]/+page.svelte:1264`.
- **Adversarial**: 5 hypotheses tested:
  1. `None`/empty provider_id → `_normalize_provider_id` returns `""` → `is_chat_provider_available` returns `False` → 400 (safe).
  2. Provider not in `CHAT_PROVIDER_CONFIG` → rejected at `send_message` level → 400 (correct).
  3. `opencode_zen` not in `litellm.provider_list` → catalog second loop covers it (correct).
  4. `tool_iterations` never incremented → `MAX_TOOL_ITERATIONS` guard is dead code; infinite tool loop theoretically possible — **pre-existing bug**, same pattern in `main` branch, not introduced by this change.
  5. `api_base` exposed in catalog response — pre-existing non-exploitable information leakage noted in prior security review.
- **MUTATION_ESCAPES**: 2/6 (tool_iterations dead guard; `embedded` boolean default not type-enforced — both pre-existing, runtime safe).
- **Lesson checks**: All prior WS1 + security review findings confirmed; no contradictions.
- **Reference**: See [Plan: AI travel agent](plans/ai-travel-agent-collections-integration.md)
- **Date**: 2026-03-08

## Consolidated Security Review: collections-ai-agent worktree
- **Verdict**: APPROVED (score 3)
- **Lens**: Correctness + Security
- **Scope**: Provider validation, API key handling, api_base/SSRF risks, auth/permission on provider catalog, /chat removal regressions.
- **Findings**:
  - WARNING: `api_base` field exposed in provider catalog response to frontend despite frontend never using it (`llm_client.py:112,141`). Non-exploitable (server-defined constants), but unnecessary information leakage. (confidence: MEDIUM)
  - No CRITICAL issues found.
- **Security verified**:
  - Provider IDs validated against `CHAT_PROVIDER_CONFIG` whitelist before any LLM call.
  - API keys Fernet-encrypted at rest, scoped to authenticated user, never returned in responses.
  - `api_base` is server-hardcoded only (no user input path) — no SSRF.
  - Provider catalog endpoint requires `IsAuthenticated`; returns same static catalog for all users.
  - Tool execution uses whitelist dispatch + allowed-kwargs filtering; all data queries scoped to `user=user`.
  - No IDOR: conversations filtered by user in queryset; tool operations filter/get by user.
- **Prior reviews confirmed**: WS1-F2 APPROVED and WS1 tester PASS findings remain consistent in consolidated branch.
- **Safe to proceed to testing**: Yes.
- **Reference**: See [Plan: AI travel agent](plans/ai-travel-agent-collections-integration.md)
- **Date**: 2026-03-08

## Critic Gate: OpenCode Zen Connection Error Fix
- **Verdict**: APPROVED
- **Scope**: Change default model from `openai/gpt-4o-mini` to `openai/gpt-5-nano`, improve error surfacing with sanitized messages, clean up `tool_choice`/`tools` kwargs — all in `backend/server/chat/llm_client.py`.
- **Key guardrails**: (1) Error surfacing must NOT forward raw `exc.message` — map LiteLLM exception types to safe user-facing categories. (2) `@mdi/js` build failure is a missing `bun install`, not a baseline issue — must run `bun install` before validation. (3) WSGI→ASGI migration and `sync_to_async` ORM fixes are explicitly out of scope.
- **Challenges accepted**: `gpt-5-nano` validity is research-based, not live-verified; mitigated by error surfacing fix making any remaining mismatch diagnosable.
- **Files evaluated**: `backend/server/chat/llm_client.py:59-64,225-234,274-276`, `frontend/src/lib/components/AITravelChat.svelte:4`, `frontend/package.json:44`
- **Reference**: See [Plan: OpenCode Zen connection error](plans/opencode-zen-connection-error.md#critic-gate)
- **Date**: 2026-03-08

## Security Review: OpenCode Zen Connection Error + Model Selection
- **Verdict**: APPROVED (score 3)
- **Lens**: Security
- **Scope**: Sanitized error handling, model override input validation, auth/permission integrity on send_message, localStorage usage for model preferences.
- **Files reviewed**: `backend/server/chat/views.py`, `backend/server/chat/llm_client.py`, `frontend/src/lib/components/AITravelChat.svelte`, `backend/server/chat/agent_tools.py`, `backend/server/integrations/models.py`, `frontend/src/lib/types.ts`
- **Findings**: No CRITICAL issues. 1 WARNING: pre-existing `api_base` exposure in provider catalog response (carried forward from prior review, decisions.md:103). Error surfacing uses class-based dispatch to hardcoded safe strings — critic guardrail confirmed satisfied. Model input used only as JSON field to `litellm.acompletion()` — no injection surface. Auth/IDOR protections unchanged. localStorage stores only `{provider_id: model_string}` — no secrets.
- **Prior findings**: All confirmed consistent (api_base exposure, provider validation, IDOR scoping, error sanitization guardrail).
- **Reference**: See [Plan: OpenCode Zen connection error](plans/opencode-zen-connection-error.md#reviewer-security-verdict)
- **Date**: 2026-03-08

## Tester Validation: OpenCode Zen Model Selection + Error Surfacing
- **Status**: PASS (Both Standard + Adversarial passes)
- **Pipeline inputs validated**: `manage.py check` (PASS, 0 issues), `bun run check` (PASS, 0 errors, 6 pre-existing warnings), `bun run build` (Vite compilation PASS; EACCES on `build/` dir is pre-existing Docker permission issue), backend 30 tests (6 pre-existing failures matching documented baseline).
- **Key targeted verifications**:
  - `opencode_zen` default model confirmed as `openai/gpt-5-nano` (changed from `gpt-4o-mini`).
  - `stream_chat_completion` accepts `model=None` with correct `None or default` fallback logic.
  - All empty/falsy model values (`""`, `"   "`, `None`, `False`, `0`) produce `None` in views.py — default fallback engaged.
  - All 6 LiteLLM exception classes (`NotFoundError`, `AuthenticationError`, `RateLimitError`, `BadRequestError`, `Timeout`, `APIConnectionError`) produce sanitized hardcoded payloads — no raw exception text, `api_base`, or sensitive data leaked.
  - `_is_model_override_compatible` correctly bypasses prefix check for `api_base` gateways (opencode_zen) and enforces prefix for standard providers.
  - `tools`/`tool_choice` conditionally excluded from LiteLLM kwargs when `tools` is falsy.
  - i18n keys `chat.model_label` and `chat.model_placeholder` confirmed in `en.json`.
- **Adversarial**: 9 hypotheses tested; all negative (no failures). Notable: `openai\n` normalizes to `openai` via `strip()` — correct and consistent with views.py.
- **MUTATION_ESCAPES**: 0/5 — all 5 mutation checks detected by test cases.
- **Pre-existing issues** (not introduced): `_merge_tool_call_delta` no upper bound on index (large index DoS); `tool_iterations` never incremented dead guard.
- **Reference**: See [Plan: OpenCode Zen connection error](plans/opencode-zen-connection-error.md#tester-verdict-standard--adversarial)
- **Date**: 2026-03-08

## Correctness Review: chat-loop-hardening
- **Verdict**: APPROVED (score 6)
- **Lens**: Correctness
- **Scope**: Required-argument tool-error short-circuit in `send_message()` streaming loop, historical replay filtering in `_build_llm_messages()`, tool description improvements in `agent_tools.py`, and `tool_iterations` increment fix.
- **Files reviewed**: `backend/server/chat/views/__init__.py`, `backend/server/chat/agent_tools.py`, `backend/server/chat/llm_client.py` (no hardening changes — confirmed stable)
- **Acceptance criteria verification**:
  - AC1 (no repeated invalid-arg loops): ✓ — `_is_required_param_tool_error()` detects patterns via hardcoded set + regex. `return` exits generator after error event + `[DONE]`.
  - AC2 (error payloads not replayed): ✓ — short-circuit skips persistence; `_build_llm_messages()` filters historical tool-error messages.
  - AC3 (stream terminates coherently): ✓ — all 4 exit paths yield `[DONE]`.
  - AC4 (successful tool flows preserved): ✓ — new check is pass-through for non-error results.
- **Findings**:
  - WARNING: [views/__init__.py:389-401] Multi-tool-call orphan state. When model returns N tool calls and call K (K>1) fails required-param validation, calls 1..K-1 are already persisted but the assistant message references all N tool_call IDs. Missing tool result causes LLM API errors on next conversation turn (caught by `_safe_error_payload`). (confidence: HIGH)
  - WARNING: [views/__init__.py:64-69] `_build_llm_messages` filters tool-role error messages but does not trim the corresponding assistant `tool_calls` array, creating the same orphan for historical messages. (confidence: HIGH)
- **Suggestions**: `get_weather` error `"dates must be a non-empty list"` (agent_tools.py:601) does not match the `is/are required` regex. Mitigated by `MAX_TOOL_ITERATIONS` guard.
- **Prior findings**: `tool_iterations` never-incremented bug (decisions.md:91,149) now fixed — line 349 increments correctly. Confirmed resolved.
- **Reference**: See [Plan: chat-provider-fixes](plans/chat-provider-fixes.md#follow-up-fixes)
- **Date**: 2026-03-09

## Correctness Review: OpenCode Zen Model Selection + Error Surfacing
- **Verdict**: APPROVED (score 0)
- **Lens**: Correctness
- **Scope**: Model selection in chat composer, per-provider browser persistence, optional model override to backend, error category mapping, and OpenCode Zen default model fix across 4 files.
- **Files reviewed**: `frontend/src/lib/components/AITravelChat.svelte`, `frontend/src/locales/en.json`, `backend/server/chat/views.py`, `backend/server/chat/llm_client.py`, `frontend/src/lib/types.ts`
- **Findings**: No CRITICAL or WARNING issues. Two optional SUGGESTIONS (debounce localStorage writes on model input; add clarifying comment on `getattr` fallback pattern in `_safe_error_payload`).
- **Verified paths**:
  - Model override end-to-end: frontend `trim() || undefined` → backend `strip() or None` → `stream_chat_completion(model=model)` → `completion_kwargs["model"] = model or default` — null/empty falls back correctly.
  - Per-provider persistence: `loadModelPref`/`saveModelPref` via `localStorage` with JSON parse error handling and SSR guards. Reactive blocks verified no infinite loop via `initializedModelProvider` sentinel.
  - Model-provider compatibility: `_is_model_override_compatible` skips validation for `api_base` gateways (OpenCode Zen), validates prefix for standard providers, allows bare model names.
  - Error surfacing: 6 LiteLLM exception types mapped to sanitized messages; no raw `exc.message` exposure; critic guardrail satisfied.
  - Tools/tool_choice: conditionally included only when `tools` is truthy; no `None` kwargs to LiteLLM.
  - i18n: `chat.model_label` and `chat.model_placeholder` confirmed in `en.json`.
  - Type safety: `ChatProviderCatalogEntry.default_model: string | null` handled with null-safe operators throughout.
- **Prior findings**: Critic gate guardrails (decisions.md:117-124) all confirmed followed. `api_base` catalog exposure (decisions.md:103) unchanged/pre-existing. `tool_iterations` never-incremented bug (decisions.md:91) pre-existing, not affected.
- **Reference**: See [Plan: OpenCode Zen connection error](plans/opencode-zen-connection-error.md#reviewer-correctness-verdict)
- **Date**: 2026-03-08

## Critic Gate: Travel Agent Context + Models Follow-up
- **Verdict**: APPROVED
- **Scope**: Three follow-up fixes — F1 (expand opencode_zen model dropdown), F2 (collection-level context injection instead of single-location), F3 (itinerary-centric quick-action prompts + `.places`→`.results` bug fix).
- **Key findings**: All source-level edit points verified current. F3a `.places`/`.results` key mismatch confirmed as critical rendering bug (place cards never display). F2 `values_list("name")` alone insufficient — need `city__name`/`country__name` for geocodable context. F1 model list should exclude reasoning models (`o1-preview`, `o1-mini`) pending tool-use compatibility verification.
- **Execution order**: F1 → F2 → F3 (F3 depends on F2's `deriveCollectionDestination` changes).
- **Files evaluated**: `backend/server/chat/views/__init__.py:144-168,417-418`, `backend/server/chat/llm_client.py:310-358`, `backend/server/chat/agent_tools.py:128,311-391`, `frontend/src/lib/components/AITravelChat.svelte:44,268,372-386,767-804`, `frontend/src/routes/collections/[id]/+page.svelte:259-280,1287-1294`, `backend/server/adventures/models.py:153-170,275-307`
- **Reference**: See [Plan: Travel agent context + models](plans/travel-agent-context-and-models.md#critic-gate)
- **Date**: 2026-03-09

## WS1 Configuration Infrastructure Backend Review
- **Verdict**: CHANGES-REQUESTED (score 6)
- **Lens**: Correctness + Security
- **Scope**: WS1 backend implementation — `settings.py` env vars, `llm_client.py` fallback chain + catalog enhancement, `UserAISettings` model/serializer/ViewSet/migration, provider catalog user passthrough in `chat/views.py`.
- **Findings**:
  - WARNING: Redundant instance-key fallback in `stream_chat_completion()` at `llm_client.py:328-331`. `get_llm_api_key()` (lines 262-266) already implements identical fallback logic. The duplicate creates divergence risk. (confidence: HIGH)
  - WARNING: `VOYAGE_AI_MODEL` env var defined at `settings.py:408` but never consumed by any code. Instance admins who set it will see no effect — model selection uses `CHAT_PROVIDER_CONFIG[provider]["default_model"]` or user override. False promise creates support burden. (confidence: HIGH)
- **Security verified**:
  - Instance API key (`VOYAGE_AI_API_KEY`) only returned when provider matches `VOYAGE_AI_PROVIDER` — no cross-provider key leakage.
  - `UserAISettings` endpoint requires `IsAuthenticated`; queryset scoped to `request.user`; no IDOR.
  - Catalog `instance_configured`/`user_configured` booleans expose only presence (not key values) — safe.
  - N+1 avoided: single `values_list()` prefetch for user API keys in `get_provider_catalog()`.
  - Migration correctly depends on `0007_userapikey_userrecommendationpreferenceprofile` + swappable `AUTH_USER_MODEL`.
  - ViewSet follows exact pattern of existing `UserRecommendationPreferenceProfileViewSet` (singleton upsert via `_upserted_instance`).
- **Suggestions**: (1) `ModelViewSet` exposes unneeded DELETE/PUT/PATCH — could restrict to Create+List mixins. (2) `preferred_model` max_length=100 may be tight for future model names.
- **Next**: Remove redundant fallback lines 328-331 in `llm_client.py`. Wire `VOYAGE_AI_MODEL` into model resolution or remove it from settings.
- **Prior findings**: `api_base` catalog exposure (decisions.md:103) still pre-existing. `_upserted_instance` thread-safety pattern consistent with existing code — pre-existing, not new.
- **Reference**: See [Plan: AI travel agent redesign](plans/ai-travel-agent-redesign.md#ws1-configuration-infrastructure)
- **Date**: 2026-03-08

## Correctness Review: suggestion-add-flow
- **Verdict**: APPROVED (score 3)
- **Lens**: Correctness
- **Scope**: Day suggestions provider/model resolution, suggestion normalization, add-item flow creating location + itinerary entry.
- **Files reviewed**: `backend/server/chat/views/day_suggestions.py`, `frontend/src/lib/components/collections/ItinerarySuggestionModal.svelte`, plus cross-referenced `llm_client.py`, `location_view.py`, `models.py`, `serializers.py`, `CollectionItineraryPlanner.svelte`.
- **Findings**:
  - WARNING: Hardcoded `"gpt-4o-mini"` fallback at `day_suggestions.py:251` — if provider config has no `default_model` and no model is resolved, this falls back to an OpenAI model string even for non-OpenAI providers. Contradicts "no hardcoded OpenAI" acceptance criterion at the deep fallback layer. (confidence: HIGH)
  - No CRITICAL issues.
- **Verified paths**:
  - Provider/model resolution follows correct precedence: request → UserAISettings → VOYAGE_AI_PROVIDER/MODEL → provider config default. `VOYAGE_AI_MODEL` is now consumed (resolves prior WARNING from decisions.md:186).
  - Add-item flow: `handleAddSuggestion` → `buildLocationPayload` → POST `/api/locations/` (name/description/location/rating/collections/is_public) → `dispatch('addItem', {type, itemId, updateDate})` → parent `addItineraryItemForObject`. Event shape matches parent handler exactly.
  - Normalization: `normalizeSuggestionItem` handles LLM response variants (title/place_name/venue, summary/details, address/neighborhood) defensively. Items without resolvable name are dropped. `normalizeRating` safely extracts numeric values. Not overly broad.
  - Auth: `IsAuthenticated` + collection owner/shared_with check. CSRF handled by API proxy. No IDOR.
- **Next**: Replace `or "gpt-4o-mini"` on line 251 with a raise or log if no model resolved, removing the last OpenAI-specific hardcoding.
- **Reference**: See [Plan: Chat provider fixes](plans/chat-provider-fixes.md#suggestion-add-flow)
- **Date**: 2026-03-09

## Correctness Review: default-ai-settings
- **Verdict**: APPROVED (score 0)
- **Lens**: Correctness + Security
- **Scope**: DB-backed default AI provider/model settings — Settings UI save/reload, Chat component initialization from saved defaults, backend send_message fallback, localStorage override prevention.
- **Files reviewed**: `frontend/src/routes/settings/+page.server.ts` (lines 112-121, 146), `frontend/src/routes/settings/+page.svelte` (lines 50-173, 237-239, 1676-1733), `frontend/src/lib/components/AITravelChat.svelte` (lines 82-134, 199-212), `backend/server/chat/views/__init__.py` (lines 183-216), `backend/server/integrations/views/ai_settings_view.py`, `backend/server/integrations/serializers.py` (lines 104-114), `backend/server/integrations/models.py` (lines 129-146), `frontend/src/lib/types.ts`, `frontend/src/locales/en.json`.
- **Acceptance criteria**:
  1. ✅ Settings UI save/reload: server-side loads `aiSettings` (page.server.ts:112-121), frontend initializes with normalization (page.svelte:50-51), saves via POST with re-validation (page.svelte:135-173), template renders provider/model selects (page.svelte:1676-1733).
  2. ✅ Chat initializes from saved defaults: `loadUserAISettings()` fetches from DB (AITravelChat:87-107), `applyInitialDefaults()` applies with validation (AITravelChat:109-134).
  3. ✅ localStorage doesn't override DB: `saveModelPref()` writes only (AITravelChat:199-212); old `loadModelPref()` reader removed.
  4. ✅ Backend fallback safe: requested → preferred (if available) → "openai" (views/__init__.py:195-201); model gated by `provider == preferred_provider` (views/__init__.py:204).
- **Verified paths**:
  - Provider normalization consistent (`.trim().toLowerCase()`) across settings, chat, backend. Model normalization (`.trim()` only) correct — model IDs are case-sensitive.
  - Upsert semantics correct: `perform_create` checks for existing, updates in place. Returns 200 OK; frontend checks `res.ok`. Matches `OneToOneField` constraint.
  - CSRF: transparent via API proxy. Auth: `IsAuthenticated` + user-scoped queryset. No IDOR.
  - Empty/null edge cases: `preferred_model: defaultAiModel || null` sends null for empty. Backend `or ""` normalization handles None. Robust.
  - Stale provider/model: validated against configured providers (page.svelte:119) and loaded models (page.svelte:125-127); falls back correctly.
  - Async ordering: sequential awaits correct (loadProviderCatalog → initializeDefaultAiSettings; Promise.all → applyInitialDefaults).
  - Race prevention: `initialDefaultsApplied` flag, `loadedModelsForProvider` guard.
  - Contract: serializer fields match frontend `UserAISettings` type. POST body matches serializer.
- **No CRITICAL or WARNING findings.**
- **Prior findings confirmed**: `preferred_model` max_length=100 and `ModelViewSet` excess methods (decisions.md:212) remain pre-existing, not introduced here.
- **Reference**: See [Plan: Chat provider fixes](plans/chat-provider-fixes.md#default-ai-settings)
- **Date**: 2026-03-09

## Re-Review: suggestion-add-flow (OpenAI fallback removal)
- **Verdict**: APPROVED (score 0)
- **Lens**: Correctness (scoped re-review)
- **Scope**: Verification that the WARNING from decisions.md:224 (hardcoded `or "gpt-4o-mini"` fallback in `_get_suggestions_from_llm`) is resolved, and no new issues introduced.
- **Original finding resolved**: ✅ — `day_suggestions.py:251` now reads `resolved_model = model or provider_config.get("default_model")` with no OpenAI fallback. Lines 252-253 raise `ValueError("No model configured for provider")` if `resolved_model` is falsy. Grep confirms zero `gpt-4o-mini` occurrences in `backend/server/chat/`.
- **No new issues introduced**:
  - `ValueError` at line 253 is safely caught by `except Exception` at line 87, returning generic 500 response.
  - `CHAT_PROVIDER_CONFIG.get(provider, {})` at line 250 handles `None` provider safely (returns `{}`).
  - Double-resolution of `provider_config` (once in `_resolve_provider_and_model:228`, again in `_get_suggestions_from_llm:250`) is redundant but harmless — defensive fallback consistent with streaming chat path.
  - Provider resolution chain at lines 200-241 intact: request → user settings → instance settings → OpenAI availability check. Model gated by `provider == preferred_provider` (line 237) prevents cross-provider model mismatches.
- **Reference**: See [Plan: Chat provider fixes](plans/chat-provider-fixes.md#suggestion-add-flow), prior finding at decisions.md:224
- **Date**: 2026-03-09

## Re-Review: chat-loop-hardening multi-tool-call orphan fix
- **Verdict**: APPROVED (score 0)
- **Lens**: Correctness (targeted re-review)
- **Scope**: Fix for multi-tool-call partial failure orphaned context — `_build_llm_messages()` trimming and `send_message()` successful-prefix persistence.
- **Original findings status**:
  - WARNING (decisions.md:164): Multi-tool-call orphan in streaming loop — **RESOLVED**. `send_message()` now accumulates `successful_tool_calls`/`successful_tool_messages` and persists only those on required-arg failure (lines 365-426). First-call failure correctly omits `tool_calls` from assistant message entirely (line 395 guard).
  - WARNING (decisions.md:165): `_build_llm_messages` assistant `tool_calls` not trimmed — **RESOLVED**. Lines 59-65 build `valid_tool_call_ids` from non-error tool messages; lines 85-91 filter assistant `tool_calls` to only matching IDs; empty result omits `tool_calls` key entirely.
- **New issues introduced**: None. Defensive null handling (`(tool_call or {}).get("id")`) correct. No duplicate persistence risk (failure path returns, success path continues). In-memory `current_messages` and persisted messages stay consistent.
- **Reference**: See [Plan: Chat provider fixes](plans/chat-provider-fixes.md#chat-loop-hardening)
- **Date**: 2026-03-09

## Re-Review: normalize_gateway_model + day-suggestions error handling
- **Verdict**: APPROVED (score 3)
- **Lens**: Correctness
- **Scope**: `normalize_gateway_model()` helper in `llm_client.py`, its integration in both `stream_chat_completion()` and `DaySuggestionsView._get_suggestions_from_llm()`, `_safe_error_payload` adoption in day suggestions, `temperature` kwarg removal, and exception logging addition.
- **Changes verified**:
  - `normalize_gateway_model` correctly prefixes bare `opencode_zen` model IDs with `openai/`, passes through all other models, and returns `None` for empty/None input.
  - `stream_chat_completion:420` calls `normalize_gateway_model` after model resolution but before `supports_function_calling` check — correct ordering.
  - `day_suggestions.py:266-271` normalizes resolved model and guards against `None` with `ValueError` — resolves prior WARNING about hardcoded `gpt-4o-mini` fallback (decisions.md:224).
  - `day_suggestions.py:93-106` uses `_safe_error_payload` with status-code mapping dict — LiteLLM exceptions get appropriate HTTP codes (400/401/429/503), `ValueError` falls through to generic 500.
  - `temperature` kwarg confirmed absent from `completion_kwargs` — resolves `UnsupportedParamsError` on `gpt-5-nano`.
  - `logger.exception` at line 94 ensures full tracebacks for debugging.
- **Findings**:
  - WARNING: `stream_chat_completion:420` has no `None` guard on `normalize_gateway_model` return, unlike `day_suggestions.py:270-271`. Currently unreachable (resolution chain always yields non-empty model from `CHAT_PROVIDER_CONFIG`), but defensive guard would make contract explicit. (confidence: LOW)
- **Prior findings**: hardcoded `gpt-4o-mini` WARNING (decisions.md:224) confirmed resolved. `_safe_error_payload` sanitization guardrail (decisions.md:120) confirmed satisfied.
- **Reference**: See [Plan: Chat provider fixes](plans/chat-provider-fixes.md#suggestion-add-flow)
- **Date**: 2026-03-09
