# Chat Provider Fixes

## Problem Statement
The AI chat feature is broken with multiple issues:
1. Rate limit errors from providers
2. "location is required" errors (tool calling issue)
3. "An unexpected error occurred while fetching trip details" errors
4. Models not being fetched properly for all providers
5. Potential authentication issues

## Root Cause Analysis

### Issue 1: Tool Calling Errors
The errors "location is required" and "An unexpected error occurred while fetching trip details" come from the agent tools (`search_places`, `get_trip_details`) being called with missing/invalid parameters. This suggests:
- The LLM is not properly understanding the tool schemas
- Or the model doesn't support function calling well
- Or there's a mismatch between how LiteLLM formats tools and what the model expects

### Issue 2: Models Not Fetched
The `models` endpoint in `ChatProviderCatalogViewSet` only handles:
- `openai` - uses OpenAI SDK to fetch live
- `anthropic/claude` - hardcoded list
- `gemini/google` - hardcoded list
- `groq` - hardcoded list
- `ollama` - calls local API
- `opencode_zen` - hardcoded list

All other providers return `{"models": []}`.

### Issue 3: Authentication Flow
1. Frontend sends request with `credentials: 'include'`
2. Backend gets user from session
3. `get_llm_api_key()` checks `UserAPIKey` model for user's key
4. Falls back to `settings.VOYAGE_AI_API_KEY` if user has no key and provider matches instance default
5. Key is passed to LiteLLM's `acompletion()`

Potential issues:
- Encryption key not configured correctly
- Key not being passed correctly to LiteLLM
- Provider-specific auth headers not being set

### Issue 4: LiteLLM vs Alternatives
Current approach (LiteLLM):
- Single library handles all providers
- Normalizes API calls across providers
- Built-in error handling and retries (if configured)

Alternative (Vercel AI SDK):
- Provider registry pattern with individual packages
- More explicit provider configuration
- Better TypeScript support
- But would require significant refactoring (backend is Python)

## Investigation Tasks

- [ ] Test the actual API calls to verify authentication
- [x] Check if models endpoint returns correct data
- [x] Verify tool schemas are being passed correctly
- [ ] Test with a known-working model (e.g., GPT-4o)

## Options

### Option A: Fix LiteLLM Integration (Recommended)
1. Add proper retry logic with `num_retries=2`
2. Add `supports_function_calling()` check before using tools
3. Expand models endpoint to handle more providers
4. Add better logging for debugging

### Option B: Replace LiteLLM with Custom Implementation
1. Use direct API calls per provider
2. More control but more maintenance
3. Significant development effort

### Option C: Hybrid Approach
1. Keep LiteLLM for providers it handles well
2. Add custom handlers for problematic providers
3. Medium effort, best of both worlds

## Status

### Completed (2026-03-09)
- [x] Implemented backend fixes for Option A:
  1. `ChatProviderCatalogViewSet.models()` now fetches OpenCode Zen models dynamically from `{api_base}/models` using the configured provider API base and user API key; returns deduplicated model ids and logs fetch failures.
  2. `stream_chat_completion()` now checks `litellm.supports_function_calling(model=resolved_model)` before sending tools and disables tools with a warning if unsupported.
  3. Added LiteLLM transient retry configuration via `num_retries=2` on streaming completions.
  4. Added request/error logging for provider/model/tool usage and API base/message count diagnostics.

### Verification Results
- Models endpoint: Returns 36 models from OpenCode Zen API (was 5 hardcoded)
- Function calling check: gpt-5-nano=True, claude-sonnet-4-6=True, big-pickle=False, minimax-m2.5=False
- Syntax check: Passed for both modified files
- Frontend check: 0 errors, 6 warnings (pre-existing)

### Remaining Issues (User Action Required)
- Rate limits: Free tier has limits, user may need to upgrade or wait
- Tool calling: Some models (big-pickle, minimax-m2.5) don't support function calling - tools will be disabled for these models

## Follow-up Fixes (2026-03-09)

### Clarified Behavior
- Approved preference precedence: database-saved default provider/model beats any per-device `localStorage` override.
- Requirement: user AI preferences must be persisted through the existing `UserAISettings` backend API and applied by both the settings UI and chat send-message fallback logic.

### Planned Workstreams

- [x] `chat-loop-hardening`
  - Acceptance: invalid required-argument tool calls do not loop repeatedly, tool-error messages are not replayed back into the model history, and SSE streams terminate cleanly with a user-visible error or `[DONE]`.
  - Files: `backend/server/chat/views/__init__.py`, `backend/server/chat/agent_tools.py`, optional `backend/server/chat/llm_client.py`
  - Notes: preserve successful tool flows; stop feeding `{"error": "location is required"}` / `{"error": "query is required"}` back into the next model turn.
  - Completion (2026-03-09): Added required-argument tool-error detection in `send_message()` streaming loop, short-circuited those tool failures with a user-visible SSE error + terminal `[DONE]`, skipped persistence/replay of those invalid tool payloads (including historical cleanup at `_build_llm_messages()`), and tightened `search_places`/`web_search` tool descriptions to explicitly call out required non-empty args.
  - Follow-up (2026-03-09): Fixed multi-tool-call consistency by persisting/replaying only the successful prefix of `tool_calls` when a later call fails required-arg validation; `_build_llm_messages()` now trims assistant `tool_calls` to only IDs that have kept (non-filtered) persisted tool messages.
  - Review verdict (2026-03-09): **APPROVED** (score 6). Two WARNINGs: (1) multi-tool-call orphan — when model returns N tool calls and call K fails required-param validation, calls 1..K-1 are already persisted but call K's result is not, leaving an orphaned `tool_calls` reference in the assistant message that may cause LLM API errors on the next conversation turn; (2) `_build_llm_messages` filters tool-role error messages but does not filter/trim the corresponding assistant-message `tool_calls` array, creating the same orphan on historical replay. Both are low-likelihood (multi-tool required-param failures are rare) and gracefully degraded (next-turn errors are caught by `_safe_error_payload`). One SUGGESTION: `get_weather` error `"dates must be a non-empty list"` does not match the `is/are required` regex and would not trigger the short-circuit (mitigated by `MAX_TOOL_ITERATIONS` guard). Also confirms prior pre-existing bug (`tool_iterations` never incremented) is now fixed in this changeset.

- [x] `default-ai-settings`
  - Acceptance: settings page shows default AI provider/model controls, saving persists via `UserAISettings`, chat UI initializes from saved preferences, and backend chat fallback uses saved defaults when request payload omits provider/model.
  - Files: `frontend/src/routes/settings/+page.server.ts`, `frontend/src/routes/settings/+page.svelte`, `frontend/src/lib/types.ts`, `frontend/src/lib/components/AITravelChat.svelte`, `backend/server/chat/views/__init__.py`
  - Notes: DB-saved defaults override browser-local model prefs.

### Completion Note (2026-03-09)
- Implemented DB-backed default AI settings end-to-end: settings page now loads/saves `UserAISettings` via `/api/integrations/ai-settings/`, with provider/model selectors powered by provider catalog + per-provider models endpoint.
- Chat initialization now treats saved DB defaults as authoritative initial provider/model; stale `voyage_chat_model_prefs` localStorage values no longer override defaults and are synchronized to the saved defaults.
- Backend `send_message` now uses saved `UserAISettings` only when request payload omits provider/model, preserving explicit request values and existing provider validation behavior.
- Follow-up fix: backend model fallback now only applies `preferred_model` when the resolved provider matches `preferred_provider`, preventing cross-provider default model mismatches when users explicitly choose another provider.

- [x] `suggestion-add-flow`
  - Acceptance: day suggestions use the user-configured/default provider/model instead of hardcoded OpenAI values, and adding a suggested place creates a location plus itinerary entry successfully.
  - Files: `backend/server/chat/views/day_suggestions.py`, `frontend/src/lib/components/collections/ItinerarySuggestionModal.svelte`
  - Notes: normalize suggestion payloads needed by `/api/locations/` and preserve existing add-item event wiring.
  - Completion (2026-03-09): Day suggestions now resolve provider/model in precedence order (request payload → `UserAISettings` defaults → instance/provider defaults) without OpenAI hardcoding; modal now normalizes suggestion objects and builds stable `/api/locations/` payloads (name/location/description/rating) before dispatching existing `addItem` flow.
  - Follow-up (2026-03-09): Removed remaining OpenAI-specific `gpt-4o-mini` fallback from day suggestions LLM call; endpoint now uses provider-resolved/default model only and fails safely when no model is configured.
  - Follow-up (2026-03-09): Removed unsupported `temperature` from day suggestions requests, normalized bare `opencode_zen` model ids through the gateway (`openai/<model>`), and switched day suggestions error responses to the same sanitized categories used by chat. Browser result: the suggestion modal now completes normally (empty-state or rate-limit message) instead of crashing with a generic 500.

## Tester Validation — `default-ai-settings` (2026-03-09)

### STATUS: PASS

**Evidence from lead:** Authenticated POST `/api/integrations/ai-settings/` returned 200 and persisted; subsequent GET returned same values; POST `/api/chat/conversations/{id}/send_message/` with no provider/model in body used `preferred_provider='opencode_zen'` and `preferred_model='gpt-5-nano'` from DB, producing valid SSE stream.

**Standard pass findings:**
- `UserAISettings` model, serializer, and `UserAISettingsViewSet` are correct. Upsert logic in `perform_create` handles first-write and update-in-place correctly (single row per user via OneToOneField).
- `list()` returns `[serializer.data]` (wrapped array), which the frontend expects as `settings[0]` — contract matches.
- Backend `send_message` precedence: `requested_provider` → `preferred_provider` (if available) → `"openai"` fallback. `model` only inherits `preferred_model` when `provider == preferred_provider` — cross-provider default mismatch is correctly prevented (follow-up fix confirmed).
- Settings page initializes `defaultAiProvider`/`defaultAiModel` from SSR-loaded `aiSettings` and validates against provider catalog on `onMount`. If saved provider is no longer configured, it falls back to first configured provider.
- `AITravelChat.svelte` fetches AI settings on mount, applies as authoritative default, and writes to `localStorage` (sync direction is DB → localStorage, not the reverse).
- The `send_message` handler in the frontend always sends the current UI `selectedProvider`/`selectedModel`, not localStorage values directly — these are only used for UI state initialization, not bypassing DB defaults.
- All i18n keys present in `en.json`: `default_ai_settings_title`, `default_ai_settings_desc`, `default_ai_no_providers`, `default_ai_save`, `default_ai_settings_saved`, `default_ai_settings_error`, `default_ai_provider_required`.
- Django integration tests (5/5) pass; no tests exist for `UserAISettings` specifically — residual regression risk noted.

**Adversarial pass findings (all hypotheses did not find bugs):**

1. **Hypothesis: model saved for provider A silently applied when user explicitly sends provider B (cross-provider model leak).** Checked `send_message` lines 218–220: `model = requested_model; if model is None and preferred_model and provider == preferred_provider: model = preferred_model`. When `requested_provider=B` and `preferred_provider=A`, `provider == preferred_provider` is false → `model` stays `None`. **Not vulnerable.**

2. **Hypothesis: null/empty preferred_model or preferred_provider in DB triggers error.** Serializer allows `null` on both fields (CharField with `blank=True, null=True`). Backend normalizes with `.strip().lower()` inside `(ai_settings.preferred_provider or "").strip().lower()` guard. Frontend uses `?? ''` coercion. **Handled safely.**

3. **Hypothesis: second POST to `/api/integrations/ai-settings/` creates a second row instead of updating.** `UserAISettings` uses `OneToOneField(user, ...)` + `perform_create` explicitly fetches and updates existing row. A second POST cannot produce a duplicate. **Not vulnerable.**

4. **Hypothesis: initializeDefaultAiSettings silently overwrites the saved DB provider with the first catalog provider if the saved provider is temporarily unavailable (e.g., API key deleted).** Confirmed: line 119–121 does silently auto-select first available provider and blank the model if the saved provider is gone. This affects display only (not DB); the save action is still explicit. **Acceptable behavior; low risk.**

5. **Hypothesis: frontend sends `model: undefined` (vs `model: null`) when no model selected, causing backend to ignore it.** `requested_model = (request.data.get("model") or "").strip() or None` — if `undefined`/absent from JSON body, `get("model")` returns `None`, which becomes `None` after the guard. `model` variable falls through to default logic. **Works correctly.**

**MUTATION_ESCAPES: 1/8** — the regex `(is|are) required` in `_is_required_param_tool_error` (chat-loop-hardening code) would escape if a future required-arg error used a different pattern, but this is unrelated to `default-ai-settings` scope.

**Zero automated test coverage for `UserAISettings` CRUD + precedence logic.** Backend logic is covered only by the lead's live-run evidence. Recommended follow-up: add Django TestCase covering (a) upsert idempotency, (b) provider/model precedence in `send_message`, (c) cross-provider model guard.

## Tester Validation — `chat-loop-hardening` (2026-03-09)

### STATUS: PASS

**Evidence from lead (runtime):** Authenticated POST to `send_message` with patched upstream stream emitting `search_places {}` (missing required `location`) returned status 200, SSE body `data: {"tool_calls": [...]}` → `data: {"error": "...", "error_category": "tool_validation_error"}` → `data: [DONE]`. Persisted DB state after that turn: only `('user', None, 'restaurants please')` + `('assistant', None, '')` — no invalid `role=tool` error row.

**Standard pass findings:**

- `_is_required_param_tool_error`: correctly matches `location is required`, `query is required`, `collection_id is required`, `collection_id, name, latitude, and longitude are required`, `latitude and longitude are required`. Does NOT match non-required-arg errors (`dates must be a non-empty list`, `Trip not found`, `Unknown tool: foo`, etc.). All 18 test cases pass.
- `_is_required_param_tool_error_message_content`: correctly parses JSON-wrapped content from persisted DB rows and delegates to above. Handles non-JSON, non-dict JSON, and `error: null` safely. All 7 test cases pass.
- Orphan trimming in `_build_llm_messages`: when assistant has `tool_calls=[A, B]` and B's persisted tool row contains a required-param error, the rebuilt `assistant.tool_calls` retains only `[A]` and tool B's row is filtered. Verified for both the multi-tool case and the single-tool (lead's runtime) scenario.
- SSE stream terminates with `data: [DONE]` immediately after the `tool_validation_error` event — confirmed by code path at line 425–426 which `return`s the generator.
- `MAX_TOOL_ITERATIONS = 10` correctly set; `tool_iterations` counter is incremented on each tool iteration (pre-existing bug confirmed fixed).
- `_merge_tool_call_delta` handles `None`, `[]`, missing `index`, and malformed argument JSON without crash.
- Full Django test suite: 24/30 pass; 6/30 fail (all pre-existing: 2 user email key errors + 4 geocoding API mock errors). Zero regressions introduced by this changeset.

**Adversarial pass findings:**

1. **Hypothesis: `get_weather` with empty `dates=[]` bypasses short-circuit and loops.** `get_weather` returns `{"error": "dates must be a non-empty list"}` which does NOT match the `is/are required` regex → not short-circuited. Falls through to `MAX_TOOL_ITERATIONS` guard (10 iterations max). **Known gap, mitigated by guard — confirmed matches reviewer WARNING.**

2. **Hypothesis: regex injection via crafted error text creates false-positive short-circuit.** Tested `'x is required; rm -rf /'` (semicolon breaks `fullmatch`), newline injection, Cyrillic lookalike. All return `False` correctly. **Not vulnerable.**

3. **Hypothesis: `assistant.tool_calls=[]` (empty list) pollutes rebuilt messages.** `filtered_tool_calls` is `[]` → the `if filtered_tool_calls:` guard prevents empty `tool_calls` key from being added to the payload. **Not vulnerable.**

4. **Hypothesis: `tool message content = None` is incorrectly classified as required-param error.** `_is_required_param_tool_error_message_content(None)` returns `False` (not a string → returns early). **Not vulnerable.**

5. **Hypothesis: `_build_required_param_error_event` crashes on None/missing `result`.** `result.get("error")` is guarded by `if isinstance(result, dict)` in caller; the static method itself handles `None` result via `isinstance` check and produces `error=""`. **No crash.**

6. **Hypothesis: multi-tool scenario — only partial `tool_calls` prefix trimmed correctly.** Tested assistant with `[A, B]` where A succeeds and B fails: rebuilt messages contain `tool_calls=[A]` only. Tested assistant with only `[X]` failing: rebuilt messages contain `tool_calls=None` (key absent). **Both correct.**

**MUTATION_ESCAPES: 1/7** — `get_weather` returning `"dates must be a non-empty list"` not triggering the short-circuit. This is a known, reviewed, accepted gap (mitigated by `MAX_TOOL_ITERATIONS`). No other mutation checks escaped detection.

**FLAKY: 0**

**COVERAGE: N/A** — no automated test suite exists for the `chat` app; all validation is via unit-level method tests + lead's live-run evidence. Recommended follow-up: add Django `TestCase` for `send_message` streaming loop covering (a) single required-arg tool failure → short-circuit, (b) multi-tool partial success, (c) `MAX_TOOL_ITERATIONS` exhaustion, (d) `_build_llm_messages` orphan-trimming round-trip.

## Tester Validation — `suggestion-add-flow` (2026-03-09)

### STATUS: PASS

**Test run:** 30 Django tests (24 pass, 6 fail — all 6 pre-existing: 2 user email key errors + 4 geocoding mock failures). Zero new regressions. 44 targeted unit-level checks (42 pass, 2 fail — both failures confirmed as test-script defects, not code bugs).

**Standard pass findings:**

- `_resolve_provider_and_model` precedence verified end-to-end: explicit request payload → `UserAISettings.preferred_provider/model` → `settings.VOYAGE_AI_PROVIDER/MODEL` → provider-config default. All 4 precedence levels tested and confirmed correct.
- Cross-provider model guard confirmed: when request provider ≠ `preferred_provider`, the `preferred_model` is NOT applied (prevents `gpt-5-nano` from leaking to anthropic, etc.).
- Null/empty `preferred_provider`/`preferred_model` in `UserAISettings` handled safely (`or ""` coercion guards throughout).
- JSON parsing in `_get_suggestions_from_llm` is robust: handles clean JSON array, embedded JSON in prose, markdown-wrapped JSON, plain text (no JSON), empty string, `None` content — all return correct results (empty list or parsed list). Response capped at 5 items. Single-dict LLM response wrapped in list correctly.
- `normalizeSuggestionItem` normalization verified: non-dict returns `null`, missing name+location returns `null`, field aliases (`title`→`name`, `address`→`location`, `summary`→`description`, `score`→`rating`, `whyFits`→`why_fits`) all work. Whitespace-only name falls back to location.
- `rating=0` correctly preserved in TypeScript via `??` (nullish coalescing at line 171), not dropped. The Python port used `or` which drops `0`, but that's a test-script defect only.
- `buildLocationPayload` constructs a valid `LocationSerializer`-compatible payload: `name`, `location`, `description`, `rating`, `collections`, `is_public`. Falls back to collection location when suggestion has none.
- `handleAddSuggestion` → POST `/api/locations/` → `dispatch('addItem', {type:'location', itemId, updateDate:false})` wiring confirmed by code inspection (lines 274–294). Parent `CollectionItineraryPlanner` handler at line 2626 calls `addItineraryItemForObject`.

**Adversarial pass findings:**

1. **Hypothesis: cross-provider model leak (gpt-5-nano applied to anthropic).** Tested `request.provider=anthropic` + `UserAISettings.preferred_provider=opencode_zen`, `preferred_model=gpt-5-nano`. Result: `model_from_user_defaults=None` (because `provider != preferred_provider`). **Not vulnerable.**

2. **Hypothesis: null/empty DB prefs cause exceptions.** `preferred_provider=None`, `preferred_model=None` — all guards use `(value or "").strip()` pattern. Falls through to `settings.VOYAGE_AI_PROVIDER` safely. **Not vulnerable.**

3. **Hypothesis: all-None provider/model/settings causes exception in `_resolve_provider_and_model`.** Tested with `is_chat_provider_available=False` everywhere, all settings None. Returns `(None, None)` without exception; caller checks `is_chat_provider_available(provider)` and returns 503. **Not vulnerable.**

4. **Hypothesis: missing API key causes silent empty result instead of error.** `get_llm_api_key` returns `None` → raises `ValueError("No API key available")` → caught by `post()` try/except → returns 500. **Explicit error path confirmed.**

5. **Hypothesis: no model configured causes silent failure.** `model=None` + empty `provider_config` → raises `ValueError("No model configured for provider")` → 500. **Explicit error path confirmed.**

6. **Hypothesis: `normalizeSuggestionItem` with mixed array (nulls, strings, invalid dicts).** `[None, {name:'A'}, 'string', {description:'only'}, {name:'B'}]` → after normalize+filter: 2 valid items. **Correct.**

7. **Hypothesis: rating=0 dropped by falsy check.** Actual TS uses `item.rating ?? item.score` (nullish coalescing, not `||`). `normalizeRating(0)` returns `0` (finite number check). **Not vulnerable in actual code.**

8. **Hypothesis: XSS in name field.** `<script>alert(1)</script>` passes through as a string; Django serializer stores as text, template rendering escapes it. **Not vulnerable.**

9. **Hypothesis: double-click `handleAddSuggestion` creates duplicate location.** `isAdding` guard at line 266 exits early if `isAdding` is truthy — prevents re-entrancy. **Protected by UI-state guard.**

**Known low-severity defect (pre-existing, not introduced by this workstream):** LLM-generated `name`/`location` fields are not truncated before passing to `LocationSerializer` (max_length=200). If LLM returns a name > 200 chars, the POST to `/api/locations/` returns 400 and the frontend shows a generic error. Risk is very low in practice (LLM names are short). Recommended fix: add `.slice(0, 200)` in `buildLocationPayload` for `name` and `location` fields.

**MUTATION_ESCAPES: 1/9** — `rating=0` would escape mutation detection in naive Python tests (but is correctly handled in the actual TS `??` code). No logic mutations escape in the backend Python code.

**FLAKY: 0**

**COVERAGE: N/A** — no automated suite for `chat` or `suggestions` app. All validation via unit-level method tests + provider/model resolution checks. Recommended follow-up: add Django `TestCase` for `DaySuggestionsView.post()` covering (a) missing required fields → 400, (b) invalid category → 400, (c) unauthorized collection → 403, (d) provider unavailable → 503, (e) LLM exception → 500, (f) happy path → 200 with `suggestions` array.

**Cleanup required:** Two test artifact files left on host (not git-tracked, safe to delete):
- `/home/alex/projects/voyage/test_suggestion_flow.py`
- `/home/alex/projects/voyage/suggestion-modal-error-state.png`
