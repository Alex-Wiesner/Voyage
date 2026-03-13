---
title: chat-provider-fixes
type: note
permalink: voyage/plans/chat-provider-fixes
---

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

## Completion Note — `embedded-chat-ux-polish` (2026-03-09)

- Updated `frontend/src/lib/components/AITravelChat.svelte` embedded UX only: moved provider/model selectors into a compact header settings dropdown, reduced embedded sidebar width, and added sidebar toggle accessibility attributes (`aria-label`, `aria-expanded`, `aria-controls`).
- Replaced rigid embedded height (`h-[70vh]`) with a bounded strategy (`h-[65vh]` + min/max constraints) and softened embedded card treatment for better fit in recommendations layouts across desktop/mobile.
- Kept streaming status visible throughout generation (not only before first token) and tightened embedded quick-action/input alignment with compact chip sizing + scrollable chip row behavior.

## Completion Note — `chat-tool-output-cleanup` (2026-03-09)

- Updated `frontend/src/lib/components/AITravelChat.svelte` to suppress standalone rendering of persisted `role=tool` messages, so reloaded conversations no longer surface raw tool payload rows.
- Replaced inline raw-JSON fallback rendering with concise user-facing summaries for `get_trip_details`, `list_trips`, `add_to_itinerary`, and `get_weather`, while keeping existing rich cards for `search_places` and `web_search`.
- Added safe error summarization for inline tool results so tool error payloads no longer display raw JSON in the normal chat UI.

## Review Verdict — `chat-tool-output-cleanup` (2026-03-09)

### STATUS: CHANGES-REQUESTED (score 13)

**CRITICAL: Tool summaries and rich cards lost on conversation reload** (`AITravelChat.svelte:534,782`). `tool_results` is a frontend-only ephemeral field populated exclusively during SSE streaming (line 373). When a conversation is reloaded via `selectConversation()`, the backend serializer returns `role=tool` messages with raw payloads, but the new `visibleMessages` filter (line 534) hides them. No reconstruction step maps persisted `role=tool` messages back onto their preceding assistant message's `tool_results` array. Result: after page refresh or conversation switch, all tool activity indicators (summaries, search_places cards, web_search links) silently vanish. The user sees only the assistant's text with no tool context. (confidence: HIGH)

**WARNING: Acceptance criterion partially unmet — "reloaded conversations do not expose raw tool payloads"** is satisfied (filter works), but the related user expectation that tool activity "remains understandable" on reload is violated because no tool indicators appear at all on reloaded conversations.

**What was checked and confirmed safe:**
- `visibleMessages` filter correctly excludes `role=tool` messages from display (line 534). No raw JSON blobs shown during streaming or on reload.
- `getToolSummary()` logic is safe: uses Svelte text interpolation (not `{@html}`), so LLM-sourced names (trip names, location names) are auto-escaped. No XSS vector.
- Error tool results render a generic "could not be completed" message rather than raw error JSON. Correct and safe.
- Streaming state management is correct: `streamingContent` reset on each send (line 302), `isStreaming` cleared in `finally` (line 387). No stale state.
- `lastVisibleMessageId` correctly tracks the last visible (non-tool) message for the streaming indicator.
- `asRecord()` null guard is correct — rejects null, arrays, and non-objects.
- Fallback summary for unknown tool names (line 599-602) is generic and safe.

**NEXT (fix actions):**
In `selectConversation()`, after loading `data.messages`, reconstruct `tool_results` on each assistant message by scanning the immediately following `role=tool` messages (which share `tool_call_id` with the assistant's `tool_calls` entries). For each tool message, parse its `content` (JSON string from `serialize_tool_result`), extract the tool `name` from the message's `name` field, and push a `ToolResultEntry` onto the preceding assistant message's `tool_results`. This ensures summaries and rich cards appear on reload. The `visibleMessages` filter continues to hide the raw tool rows.

## Tester Validation — `chat-tool-output-cleanup` (2026-03-09)

### STATUS: PASS

**Evidence from lead (runtime):** Page reload of seeded conversation with persisted `get_trip_details` assistant tool call + `role=tool` result showed `🗺️ Loaded details for test (0 itinerary items).` — no raw JSON. Sidebar remained functional. Reviewer-APPROVED follow-up fix confirmed implemented and working.

**Standard pass findings:**

- `visibleMessages` filter (`messages.filter(msg => msg.role !== 'tool')`) correctly suppresses raw `role=tool` rows from display. Live DOM scan of 10 chat bubbles across two conversations found zero raw JSON blobs (`"itinerary":`, `"tool_call_id":` patterns absent).
- `rebuildConversationMessages()` scans messages in one pass: sets `activeAssistant` on each assistant-with-tool-calls message; attaches subsequent `role=tool` rows as `ToolResultEntry` objects matched via `tool_call_id`. `activeAssistant` overridden on each new assistant message, preventing cross-turn leakage.
- `parseStoredToolResult()` JSON-parses tool content; falls back to raw string on failure. Both paths produce a valid `ToolResultEntry` — no crash.
- `getToolSummary()` produces human-readable summaries for `get_trip_details`, `list_trips`, `add_to_itinerary`, `get_weather`; generic fallback for unknown tools. Error payloads render `"<name> could not be completed."` — no raw JSON.
- Backend `ChatMessageSerializer` confirmed to include `name`, `tool_call_id`, and `tool_calls` fields required for reconstruction.
- Multi-turn live conversation validated: `⚠️ get trip details could not be completed.` + `🧳 Found 1 trip.` + `🗺️ Loaded details for test (6 itinerary items).` — all clean summaries, no raw JSON.
- Text-only conversation (no tool calls) unaffected — loads correctly with zero tool artifacts.
- Frontend build: `bun run lint`, `bun run check`, `bun run build` all passed (per lead).

**Adversarial pass findings (7 hypotheses, all safe):**

1. **Hypothesis: `assistant.tool_calls` with null IDs causes cross-turn leakage.** When `toolCallIds=[]`, the guard `msg.tool_call_id && toolCallIds.length > 0 && !includes` short-circuits at `length=0` → tool IS attached (permissive loose match). But the next `assistant` message overrides `activeAssistant` before its own tool rows, so no cross-turn pollution occurs. **Acceptable; null IDs cannot arise from correctly persisted backend rows.**
2. **Hypothesis: orphaned `role=tool` after non-tool-call assistant attaches to wrong message.** `activeAssistant=null` when `tool_calls` absent/empty. Tool row skipped. **Not vulnerable.**
3. **Hypothesis: malformed JSON in tool content crashes reconstruction.** Try/catch fallback returns `result: rawString`. `asRecord(string)` → `null`; `getToolSummary` hits generic branch. **Safe; no crash, no raw JSON exposed.**
4. **Hypothesis: `name=null` on tool message causes downstream crash.** `msg.name || 'tool'` guard → `'tool'`. Generic fallback renders `"tool completed."` **Safe.**
5. **Hypothesis: multi-tool assistant reconstructs both in correct order.** Both `call_A` and `call_B` rows attach to same assistant; `activeAssistant` cleared after count reaches `toolCallIds.length`. **Verified: 2 results attached in correct order.**
6. **Hypothesis: empty `messages` array crashes.** Returns `[]` immediately. **Safe.**
7. **Hypothesis: `role=tool` before any assistant crashes or attaches to user message.** `activeAssistant=null` at start; tool row skipped. **Safe.**

**MUTATION_ESCAPES: 1/7** — The `toolCallIds.length > 0` guard in the clear condition means an assistant with all-null tool_call IDs never has `activeAssistant` cleared post-attachment. A second stray tool row would attach to the same assistant. Extremely low practical likelihood (backend always persists real IDs from LiteLLM); no production scenario produces this DB state.

**FLAKY: 0**

**COVERAGE: N/A** — No automated frontend test suite for `AITravelChat.svelte`. All validation via in-browser function evaluation (7 unit-level cases) + visual browser confirmation. Recommended follow-up: Playwright e2e test seeding a conversation with `role=tool` rows and verifying summary cards render on reload.

**Screenshot evidence:** Captured `tool-summary-reload-verification.png` — showed `Tool summary reload test` conversation with assistant text + `🗺️ Loaded details for test (0 itinerary items).` summary card, no raw JSON. Screenshot deleted post-verification (artifact not git-tracked).

## Tester Validation — `embedded-chat-ux-polish` (2026-03-09)

### STATUS: PASS

**Lead evidence accepted:**
- `bun run lint`, `bun run check` (0 errors, 6 pre-existing warnings), and `bun run build` all passed.
- Browser-validated: embedded chat opens with sidebar closed, compact header (`Show conversations` toggle + title + ⚙️ gear), recommendations area remains visible. Sidebar toggle opens conversation list correctly.
- Reviewer APPROVED after sidebar-default follow-up fix (`let sidebarOpen = !embedded;` at line 63 confirmed in code).

**Standard pass findings (code inspection):**

- AC1 (header de-crowded): ✅ Provider/model selectors moved into `<details class="dropdown dropdown-end">` at line 768. Header contains only: hamburger toggle (mobile) + ✈️ title + ⚙️ gear summary button.
- AC2 (layout stability): ✅ `h-[65vh]` + `min-h-[30rem]` + `max-h-[46rem]` on embedded mode (lines 683–685). `bg-base-100` + border treatment for embedded card (lines 674–677). Quick-action chips use `btn-xs` + `overflow-x-auto` + `pb-1` for embedded (lines 927–922).
- AC3 (streaming indicator): ✅ `isStreaming && msg.id === lastVisibleMessageId` condition (line 903) inside last assistant bubble. `lastVisibleMessageId` is a reactive derived value from `visibleMessages` (line 599) — stays current throughout stream.
- AC4 (sidebar default): ✅ `let sidebarOpen = !embedded;` (line 63). Sidebar CSS `{sidebarOpen ? '' : 'hidden'} lg:flex` (line 691) — starts hidden in embedded mode on mobile/tablet, always visible on lg+ (correct responsive pattern). Toggle button is `lg:hidden` (line 739).
- AC5 (existing features preserved): ✅ Tool result rendering, conversation management, date selector modal, quick actions, send button states unchanged.

**Adversarial pass findings:**

1. **Hypothesis: desktop (lg+) embedded layout still crushes content because sidebar is always visible via `lg:flex`.** Expected: content area unusable. Observed: `lg:flex` overrides `hidden` on lg+ — this is the intended responsive pattern. On lg+ screens there is enough horizontal space for sidebar (`w-60`) + chat content. `min-w-0` on chat panel prevents overflow. **Not a defect; designed behavior confirmed by reviewer.**

2. **Hypothesis: `<details>` settings dropdown doesn't close on outside click — user trapped.** Expected: frustration UX. Observed: DaisyUI `<details>` requires another click on summary to close. `settingsOpen = false` init confirmed (line 80). **Non-blocking UX inconvenience; pre-existing SUGGESTION from reviewer, not a blocking defect.**

3. **Hypothesis: `lastVisibleMessageId` becomes stale during streaming, causing indicator to appear on wrong message.** Expected: indicator shows on previous message. Observed: `lastVisibleMessageId` is reactive (`$:` at line 599) — updates synchronously when `visibleMessages` changes. No stale-closure risk. **Not vulnerable.**

4. **Hypothesis: `visibleMessages` filter excludes only `role=tool` — if all messages are tool messages, `lastVisibleMessageId` is `undefined` and streaming indicator never shows.** Expected: silent stream with no indicator. Observed: In practice, every send appends a `user` message and then an `assistant` streaming message — there will always be a non-tool message for the indicator to attach to. **Acceptable; degenerate case impossible in normal flow.**

5. **Hypothesis: `aria-label` hardcoded English strings at lines 743 and 771 violate i18n convention.** Expected: non-English users see English screen-reader labels. Observed: lines 743 (`'Hide conversations'`/`'Show conversations'`) and 771 (`"AI settings"`) are hardcoded. **Low-severity SUGGESTION from reviewer — non-blocking, accessibility-only impact.**

**MUTATION_ESCAPES: 0/4** — all critical logic paths for this UX-only feature are covered by the responsive CSS (no off-by-one possible) and the reactive `lastVisibleMessageId` derivation.

**FLAKY: 0**

**COVERAGE: N/A** — No automated test suite for frontend component; all validation via code inspection + lead browser evidence.

**Residual low-priority items (follow-up suggested, not blocking):**
- `aria-label` values at lines 743 and 771 should use `$t()` per i18n convention.
- `<details>` dropdown does not auto-close on outside click (SUGGESTION from reviewer).

## Completion Note — `chat-tool-grounding-and-confirmation` (2026-03-09)

- `send_message()` trip context now injects the active collection UUID with explicit instruction that it is the `collection_id` for `get_trip_details` and `add_to_itinerary`, reducing wrong-trip-id hallucinations.
- System prompt itinerary guidance now requires confirmation only before the first `add_to_itinerary` action; after explicit user approval phrases (e.g., "yes", "go ahead", "add them", "just add things there"), the assistant is instructed to stop re-confirming and call tools directly.
- Tool error wording was tightened to align with required-arg short-circuit behavior: `get_trip_details` inaccessible/missing trips now return a required-arg-style `collection_id` error string, and `get_weather` empty dates now return `"dates is required"`.
- Review verdict (2026-03-09): **APPROVED** (score 3). One WARNING: `get_trip_details` DoesNotExist error `"collection_id is required and must reference a trip you can access"` conflates missing-param and invalid-value semantics — may mislead LLM into thinking param was omitted rather than wrong. Does NOT create false-positive short-circuit (regex `fullmatch` correctly rejects the trailing clause). Closes prior known gap: `get_weather` "dates must be a non-empty list" now "dates is required" (matches regex). See [decisions.md](../decisions.md#correctness-review-chat-tool-grounding-and-confirmation).

## Tester Validation — `chat-tool-grounding-and-confirmation` (2026-03-09)

### STATUS: PASS

**Test run:** `docker compose exec server python3 manage.py test chat integrations --keepdb` — 5/5 PASS. Full Django baseline 24/30 (6 pre-existing failures unchanged; zero new regressions).

**Standard pass findings:**

- UUID context injection confirmed: `send_message()` lines 255–258 append `"Collection UUID (use this exact collection_id for get_trip_details and add_to_itinerary): {collection.id}"` into `context_parts`, embedded in `system_prompt` (lines 295–296). UUID appears in the `role=system` message on every conversation turn.
- Authorization gate confirmed: UUID injection block is inside `if collection:` (line 255); `collection` is only assigned when lookup succeeds AND user is owner or `shared_with` member (lines 244–251). Unauthorized collection_id → `collection = None` → block skipped.
- System prompt confirmation guidance verified (`llm_client.py:340–341`): confirms only before first `add_to_itinerary` action; after user approval phrases ("yes", "go ahead", "add them", "just add things there"), stops re-confirming.
- Regex validation — 11 test cases all pass:
  - `"collection_id is required"` → **True** (short-circuits)
  - `"collection_id is required and must reference a trip you can access"` → **False** (DoesNotExist; `fullmatch` rejects trailing clause — no false short-circuit)
  - `"dates is required"` → **True** (prior `chat-loop-hardening` gap now **RESOLVED**)
  - All legacy required-arg strings continue matching; non-matching strings correctly return False.
- `get_weather` empty dates: string changed from `"dates must be a non-empty list"` to `"dates is required"` — now matches regex and short-circuits. Prior known gap closed.

**Adversarial pass findings:**

1. **Unauthorized collection_id leaks UUID?** `if collection:` gate prevents injection when lookup fails/unauthorized. **NOT VULNERABLE.**
2. **DoesNotExist error creates false-positive short-circuit?** `fullmatch` returns `False` for trailing text. **NOT VULNERABLE.**
3. **UUID grounding lost between turns?** UUID is in `system_prompt` (role=system), rebuilt fresh on every `send_message`. **Grounding persists for entire conversation.**
4. **Null collection_id crashes injection block?** `if collection_id:` at line 242 gates the lookup; null → block skipped. **NOT VULNERABLE.**
5. **Shared member gets UUID in context but `get_trip_details` fails (filter excludes shared_with)?** Confirmed pre-existing bug: `get_trip_details` filters `user=user` only. Shared members get UUID context but tool returns DoesNotExist. Does not short-circuit (trailing text); falls to `MAX_TOOL_ITERATIONS`. **PRE-EXISTING, LOW severity, not introduced here.**
6. **`get_weather` short-circuit gap (prior MUTATION_ESCAPE) resolved?** Confirmed resolved — new `"dates is required"` string matches regex.

**MUTATION_ESCAPES: 0/5** — all mutation checks detected. DoesNotExist false-positive (reviewer WARNING) confirmed benign.

**FLAKY: 0**

**COVERAGE: N/A** — No automated test suite for `chat` app. All validation via in-container regex checks + lead's live-run evidence. Recommended follow-up: add Django TestCase for (a) UUID context injection with authorized vs unauthorized collection_id, (b) DoesNotExist path does not trigger short-circuit, (c) empty dates triggers short-circuit.

**Non-blocking known issues (accepted, pre-existing):** `get_trip_details` DoesNotExist wording semantically ambiguous (reviewer WARNING); `get_trip_details` excludes shared-collection members from `filter(user=user)` — both pre-existing, not introduced by this feature.

## Completion Note — `chat-a11y-and-dropdown-polish` (2026-03-09)

- Replaced embedded chat header hardcoded aria labels with i18n keys (`chat_a11y.show_conversations_aria`, `chat_a11y.hide_conversations_aria`, `chat_a11y.ai_settings_aria`) in `AITravelChat.svelte`.
- Added `chat_a11y` key group to all locale JSON files to keep key parity.
- Added settings dropdown close behavior on outside interaction (`pointerdown`/`mousedown`/`touchstart`) and `Escape`, with mount-time listener cleanup mirroring the existing dropdown pattern used elsewhere.

## Review Verdict — `chat-a11y-and-dropdown-polish` (2026-03-09)

### STATUS: APPROVED (score 3)

**Lens**: Correctness

**Checked and confirmed safe:**
- All hardcoded English `aria-label` strings replaced with `$t('chat_a11y.*')` calls (lines 778–781, 810). Zero raw strings remain.
- All 20 locale JSON files have key parity: `chat_a11y.{show_conversations_aria, hide_conversations_aria, ai_settings_aria}` present in each (English placeholders — correct for fallback, content translation is a separate concern).
- Outside-click listeners (`pointerdown`/`mousedown`/`touchstart`) correctly close dropdown via `settingsDropdownRef.contains(target)` check + `bind:open` two-way sync with native `<details>`.
- Escape handler closes dropdown on `keydown` Escape.
- `onMount` cleanup function removes all 4 listeners (3 outside-click + 1 keydown) using the same references. No leak.
- `<details bind:open={settingsOpen}>` bidirectional binding ensures no conflict between native summary toggle and programmatic close.
- No interaction regression with textarea `handleKeydown` (Enter-only) or date-selector modal.

**WARNING (1):** Escape handler (line 106) fires on every Escape keypress globally, even when `settingsOpen` is already `false`. No functional bug (idempotent assignment) but lacks a `settingsOpen` guard. (confidence: LOW)

**SUGGESTIONS (2):**
1. Non-English locale `chat_a11y` values are English placeholders — track for human translation.
2. `outsideEvents` includes both `pointerdown` and `mousedown` — handler fires twice per click on most browsers (second is no-op). Using only `pointerdown` + `touchstart` would be cleaner.

**Closes prior residual items** from `embedded-chat-ux-polish` tester validation: both the hardcoded aria-label i18n issue and the dropdown outside-click behavior are now resolved.

## Tester Validation — `chat-a11y-and-dropdown-polish` (2026-03-09)

### STATUS: PASS

**Lead evidence accepted:**
- `bun run format`, `bun run lint`, `bun run check` (0 errors, 6 pre-existing warnings), `bun run build` all passed.
- Reviewer APPROVED (score 3); two low-priority SUGGESTIONS (non-English locale placeholders + `pointerdown`/`mousedown` double-registration) confirmed non-blocking.

**Backend test suite:** `docker compose exec server python3 manage.py test chat --keepdb` — **9/9 PASS**. Zero regressions.

**Standard pass findings (code inspection + live browser):**

- AC1 (i18n aria-labels): ✅ All three hardcoded English strings replaced with `$t('chat_a11y.*')` calls (lines 778–781, 812). Live DOM confirmed: `allAriaLabels.filter(key.startsWith('chat_a11y'))` returned `[]` — no raw key strings leaked.
- AC2 (locale key parity): ✅ `chat_a11y` group present in all 20 locale JSON files confirmed. English values are real strings; non-English locales use English placeholders (accepted — translation is out of scope).
- AC3 (Escape closes dropdown): ✅ Live browser: `settingsDetails.open === true` before Escape, `false` after `keyboard.press('Escape')`.
- AC4 (outside click closes dropdown): ✅ Live browser: click on header h3 (outside `settingsDropdownRef.contains(target)`) → `settingsDetails.open === false`.
- AC5 (sidebar toggle aria updates): ✅ Before click: `aria-label="Show conversations"`, `aria-expanded="false"`. After click: `aria-label="Hide conversations"`, `[expanded]` state confirmed in accessibility snapshot. Sidebar conversation list rendered correctly.
- AC6 (listener cleanup): ✅ `onMount` return removes all 4 listeners using same references. No leak.
- AC7 (`bind:open` bidirectionality): ✅ `<details bind:open={settingsOpen}>` at line 807. `aria-expanded={settingsOpen}` on summary tracks in sync.

**Screenshot evidence:** Captured embedded chat header with Conversations sidebar open, hamburger (×) button and gear icon visible, "Travel Assistant · test" title, Recommendations tab active. Screenshot deleted post-verification (saved to MCP temp dir, not git-tracked).

**Adversarial pass findings:**

1. **Hypothesis: `pointerdown`+`mousedown` double-fire causes open→close→open flicker.** Synthesized both events on outside element after Svelte-bound open. Observed: `open_after_outside_events: false`, `double_fire_safe: true`. Second handler fires on already-false value — idempotent. **Not vulnerable.**

2. **Hypothesis: raw i18n key strings leak to DOM on locale fallback.** All `[aria-label]` values checked for `chat_a11y` prefix. Zero raw keys found. svelte-i18n falls back to English strings, not key names. **Not vulnerable.**

3. **Hypothesis: Escape key fires globally when dropdown already closed (reviewer WARNING).** Confirmed true — no `settingsOpen` guard. Assignment `settingsOpen = false` when already `false` is a no-op. **Accepted non-functional defect per reviewer.**

4. **Hypothesis: `aria-expanded` on `<summary>` desyncs when `<details>` closed by native browser toggle.** `bind:open={settingsOpen}` is bidirectional — native toggle updates `settingsOpen` → `aria-expanded`. **Not vulnerable.**

5. **Hypothesis: sidebar `aria-controls` target missing on desktop (button is `lg:hidden`).** `id="chat-conversations-sidebar"` is always rendered; `aria-controls` reference always valid. **Not vulnerable.**

**MUTATION_ESCAPES: 0/4** — All i18n, event handler, aria-sync, and listener-cleanup paths cover mutations. The reviewer WARNING about the missing `settingsOpen` guard is a superficial mutation (no functional impact).

**FLAKY: 0**

**COVERAGE: N/A** — No automated frontend test suite. All validation via in-browser DOM evaluation + keyboard/click interaction tests.

**Residual low-priority items (not blocking):**
- Non-English locale `chat_a11y` values are English placeholders — requires human translation (separate concern).
- `outsideEvents` includes both `pointerdown` and `mousedown` — double-fires but idempotent. Could simplify to `['pointerdown', 'touchstart']`.
- Escape handler lacks `settingsOpen` guard — idempotent no-op, no functional consequence.

## Completion Note — `shared-trip-tool-access` (2026-03-09)

- Updated `backend/server/chat/agent_tools.py` so `get_trip_details` and `add_to_itinerary` now authorize collections with the existing shared-access pattern `Q(user=user) | Q(shared_with=user)`.
- Preserved existing owner-only behavior for `list_trips` and kept prior error responses unchanged (`collection_id ... you can access` for trip-details misses, `Trip not found` for itinerary-add misses).
- Follow-up applied: added `.distinct()` to both shared-aware collection lookups to avoid `MultipleObjectsReturned` when an owner is also present in `shared_with`, and added regression tests in `backend/server/chat/tests.py` for that edge case.

## Completion Note — `chat-regression-tests` (2026-03-09)

- Added `backend/server/chat/tests.py` with focused backend regressions for shared-trip tool access: owner + shared-member success for `get_trip_details`, shared-member success for `add_to_itinerary`, and non-member denial behavior for both tools.
- Added required-parameter boundary tests against `ChatViewSet._is_required_param_tool_error` and `_is_required_param_tool_error_message_content`, confirming `dates is required` matches while `dates must be a non-empty list` and `collection_id is required and must reference a trip you can access` do not short-circuit.

## Review Verdict — `chat-regression-tests` (2026-03-09)

### STATUS: APPROVED (score 0)

**Lens**: Correctness

**Acceptance criteria verified**:
- Tests pass with current codebase: all tool function calls and static method invocations match current source signatures and return shapes. Mock targets (`adventures.models.background_geocode_and_assign`) are correct.
- Shared-trip access regression covered: 4 test methods exercise owner access, shared-member access (both get_trip_details and add_to_itinerary), and non-member denial for both tools — covering the `Q(user=user)|Q(shared_with=user)` fix at `agent_tools.py:326,464-466`.
- Required-param regex boundaries covered: 3 boundary tests confirm `"dates is required"` matches (closes prior gap), `"dates must be a non-empty list"` does not match, and `"collection_id is required and must reference a trip you can access"` does not false-positive short-circuit (both `_is_required_param_tool_error` and `_is_required_param_tool_error_message_content`).
- No new test infrastructure: only stdlib, Django TestCase, and existing project models/views imported. No new pip packages or external services.

**No defects found.** Tests are behavior-focused (call actual tool functions, assert documented return contracts) without overfitting to implementation details. Regex boundary tests use exact production error strings — appropriate since these are stable API-level contracts.

**SUGGESTIONS**: (1) `test_non_member_access_remains_denied` bundles two independent assertions; splitting would improve diagnostic granularity. (2) Multi-param positive match (`"collection_id, name, latitude, and longitude are required"`) not covered but was validated in prior tester sessions.

See [decisions.md](../decisions.md#correctness-review-chat-regression-tests).

## Tester Validation — `shared-trip-tool-access` (2026-03-09)

### STATUS: PASS

**Test run:** `docker compose exec server python3 manage.py test chat --keepdb --verbosity=2` — **9/9 PASS** (0 failures, 0 errors). Full baseline: 24/30 Django-wide pass; 6/30 pre-existing failures unchanged. Zero new regressions.

**Standard pass — code inspection + live test results:**

- `get_trip_details` (line 326): `Collection.objects.filter(Q(user=user) | Q(shared_with=user)).distinct().get(id=collection_id)` — correct shared-access pattern. `Collection.shared_with` is a `ManyToManyField(User)` (line 288 of `adventures/models.py`), so both predicates are valid FK/M2M joins. `.distinct()` prevents `MultipleObjectsReturned` when the requesting user appears in both `user=user` (owner) and `shared_with=user` (also added as member).
- `add_to_itinerary` (line 466): Identical filter pattern. `.distinct()` applied. The `Location.objects.create(user=user, ...)` at line 471 correctly assigns the location to the shared user's account (not the owner's) — consistent with how the REST API handles shared-user writes (`day_suggestions.py:55` also checks shared membership before allowing writes).
- `list_trips` (line 214): Remains owner-only (`filter(user=user)`) by design — consistent with the feature's accepted scope. This is not a regression.
- `send_message` collection-context gate (views/__init__.py:244-253): Uses same pattern (`owner == user OR shared_with.filter(id=user.id).exists()`). Consistent with tool-layer access.
- Non-member denial: `Collection.DoesNotExist` propagates correctly from `.get()` → caught at lines 402 and 526 → returns appropriate error strings.

**Test coverage of core acceptance criteria:**

| Criterion | Test method | Result |
|---|---|---|
| Owner can call `get_trip_details` | `test_get_trip_details_allows_owner_access` | PASS |
| Shared user can call `get_trip_details` | `test_get_trip_details_allows_shared_user_access` | PASS |
| Owner also-in-shared_with doesn't crash | `test_get_trip_details_owner_also_in_shared_with_avoids_duplicates` | PASS |
| Shared user can call `add_to_itinerary` | `test_add_to_itinerary_allows_shared_user_access` | PASS |
| Owner also-in-shared_with add doesn't crash | `test_add_to_itinerary_owner_also_in_shared_with_avoids_duplicates` | PASS |
| Non-member denied for both tools | `test_non_member_access_remains_denied` | PASS |
| DoesNotExist error not false-positive short-circuit | `test_collection_access_error_does_not_short_circuit_required_param_regex` | PASS |
| `dates is required` matches short-circuit | `test_dates_is_required_matches_required_param_short_circuit` | PASS |
| Old "dates must be non-empty list" does not match | `test_dates_non_empty_list_error_does_not_match_required_param_short_circuit` | PASS |

**Adversarial pass (4 hypotheses):**

1. **Hypothesis: invalid (non-UUID) `collection_id` causes unhandled exception, not a clean DoesNotExist.** Django UUIDField `.get(id="not-a-uuid")` raises `ValidationError` or `ValueError`, not `DoesNotExist` — the `except Exception` fallback at lines 406-408 catches it and returns `{"error": "An unexpected error occurred while fetching trip details"}`. No crash. **Not vulnerable** (exception absorbed, graceful error).
   - _For `add_to_itinerary`_: Same — caught by `except Exception` at lines 528-530. Returns `{"error": "An unexpected error occurred while adding to itinerary"}`. **Not vulnerable.**

2. **Hypothesis: shared user can overwrite collection membership by being added to `shared_with` of a collection they do not own.** `add_to_itinerary` creates a `Location` with `user=shared_user` and then calls `collection.locations.add(location)` — this adds the new location to the owner's collection. The location's user FK is `shared_user`, which is correct (shared users own their own contributed locations). **No privilege escalation.**

3. **Hypothesis: race condition — user removed from `shared_with` between filter and write inside `add_to_itinerary`.** Filter + `.get()` runs in a single DB query; the `Collection.DoesNotExist` path fires before any write occurs. No partial write possible. **Not vulnerable** (read-before-write order is safe in this non-transactional case).

4. **Hypothesis: `list_trips` leaks shared collections to non-owners by exposing collections where `shared_with=user`.** Confirmed: `list_trips` uses `filter(user=user)` only (line 214). Shared collections do not appear in `list_trips` output for shared users. **No information leak; intentionally owner-scoped.**

**MUTATION_ESCAPES: 1/5** — Invalid UUID input to `get_trip_details`/`add_to_itinerary` falls through to the generic `except Exception` handler rather than `DoesNotExist`, so test `test_non_member_access_remains_denied` would NOT detect a mutation that accidentally drops the `Q(shared_with=user)` clause for malformed UUIDs. However, valid UUID non-member inputs (the primary production scenario) are correctly caught. Risk is very low.

**FLAKY: 0**

**COVERAGE: N/A** — No coverage tooling configured. 6 of 9 tests directly exercise the changed lines (326, 466). The `.distinct()` edge case has its own dedicated test methods.

**LESSON_CHECKS:**
- Prior lesson (chat-tool-grounding-and-confirmation, adversarial item 5): shared member gets UUID in context but `get_trip_details` returns DoesNotExist — **CONTRADICTED / RESOLVED** by this feature. The fix (`Q(user=user) | Q(shared_with=user)`) means shared members now successfully retrieve trip details. The prior finding is no longer valid.
- Prior lesson (pre-existing, pre-release): shared-user write ownership for `add_to_itinerary` sets `user=shared_user` not `user=collection.user` — **confirmed** acceptable, consistent with REST API pattern.

**Known residual non-issue:** `test_non_member_access_remains_denied` bundles two independent assertions (noted by reviewer SUGGESTION); splitting would improve diagnostic granularity but does not affect correctness of the test outcome.

## Tester Validation — `chat-regression-tests` (2026-03-09)

### STATUS: PASS

**Test run:** `docker compose exec server python3 manage.py test chat --keepdb -v 2` — **9/9 PASS** (independently verified by tester; not just lead-reported). Full Django suite: 39 tests — 33 pass, 6 fail (all 6 pre-existing: 2 user email key errors + 4 geocoding mock failures). Zero new regressions.

**Standard pass findings:**

- All 6 `ChatAgentToolSharedTripAccessTests` exercise the `Q(user=user) | Q(shared_with=user)` fix with real DB operations: owner access, shared-member access for both `get_trip_details` and `add_to_itinerary`, `MultipleObjectsReturned` guard (owner also in `shared_with`), and non-member denial.
- All 3 `ChatViewSetToolValidationBoundaryTests` cover the exact boundary cases that are production contracts: `"dates is required"` short-circuits (gap closed by `chat-tool-grounding-and-confirmation`), `"dates must be a non-empty list"` does not short-circuit (regression guard), `"collection_id is required and must reference a trip you can access"` does not false-positive (DoesNotExist variant). Both `_is_required_param_tool_error` and `_is_required_param_tool_error_message_content` paths tested for the DoesNotExist string.
- Mock target `adventures.models.background_geocode_and_assign` is correct.
- Tests are behavior-focused; reviewer confirmed signature and return shape matches current source.

**Adversarial pass findings (5 hypotheses):**

1. **Hypothesis: regex accepts trailing text as false positive.** `re.fullmatch` with `r"[a-z0-9_,\-\s]+ (is|are) required"` rejects `"collection_id is required and must reference..."` because trailing text breaks fullmatch. **Confirmed safe; covered by test.**
2. **Hypothesis: `latitude=0.0` treated as falsy, bypassing `add_to_itinerary` guard.** Guard is `latitude is None` (line 460), not truthiness check. `0.0 is None` → False, guard passes. **Not vulnerable — code-inspection confirmed.**
3. **Hypothesis: non-existent UUID raises unhandled exception.** `Collection.DoesNotExist` caught at line 402; invalid UUID string caught by broad `except Exception` at line 406. Both return error dicts, no exception escapes. **Not vulnerable.**
4. **Hypothesis: `"collection_id is required"` positive case absent creates regression blind spot.** This was validated in the `chat-loop-hardening` pass (18 regex cases). New tests target the delta boundary cases only. **Acceptable scope.**
5. **Hypothesis: additional regex adversarial inputs (unicode injection, newline injection, whitespace-only) match unexpectedly.** Verified directly against production function in-container: all return `False`. **Not vulnerable.**

**MUTATION_ESCAPES: 0/5** — All five mutation checks detected by the executed suite. `fullmatch` boundary tested; `.distinct()` regression tested; shared-member positive path tested; non-member denial tested; both regex helper methods exercised.

**FLAKY: 0**

**COVERAGE: N/A** — Backend `chat` app now has 9 tests covering all critical paths for the `shared-trip-tool-access` and regression-test workstreams. No frontend test infrastructure exists (out of scope).

**LESSON_CHECKS:**
- Prior tester finding (chat-tool-grounding-and-confirmation adversarial item 5): shared-member `get_trip_details` returns DoesNotExist — **CONTRADICTED / RESOLVED** by `shared-trip-tool-access` fix. Confirmed by `test_get_trip_details_allows_shared_user_access` passing in this run.
- Prior tester finding (chat-loop-hardening): `get_weather` "dates must be a non-empty list" did not short-circuit — **RESOLVED** by `chat-tool-grounding-and-confirmation`. Confirmed by `test_dates_is_required_matches_required_param_short_circuit` passing.

**Reviewer optional suggestions** (not blocking, not addressed): (1) split `test_non_member_access_remains_denied` into two test methods; (2) add explicit multi-param positive regex case. Neither represents a coverage gap for the fixed behavior.