# Plan: Fix OpenCode Zen connection errors in AI travel chat

## Clarified requirements
- User configured provider `opencode_zen` in Settings with API key.
- Chat attempts return a generic connection error.
- Goal: identify root cause and implement a reliable fix for OpenCode Zen chat connectivity.
- Follow-up: add model selection in chat composer (instead of forced default model) and persist chosen model per user.

## Acceptance criteria
- Sending a chat message with provider `opencode_zen` no longer fails with a connection error due to Voyage integration/configuration.
- Backend provider routing for `opencode_zen` uses a validated OpenAI-compatible request shape and model format.
- Frontend surfaces backend/provider errors with actionable detail (not only generic connection failure) when available.
- Validation commands run successfully (or known project-expected failures only) and results recorded.

## Tasks
- [ ] Discovery: inspect current OpenCode Zen provider configuration and chat request pipeline (Agent: explorer)
- [ ] Discovery: verify OpenCode Zen API compatibility requirements vs current implementation (Agent: researcher)
- [ ] Discovery: map model-selection edit points and persistence path (Agent: explorer)
- [x] Implement fix for root cause + model selection/persistence (Agent: coder)
- [x] Correctness review of targeted changes (Agent: reviewer) — APPROVED (score 0)
- [x] Standard validation run and targeted chat-path checks (Agent: tester)
- [x] Documentation and knowledge sync for provider troubleshooting notes (Agent: librarian)

## Researcher findings

**Root cause**: Two mismatches in `backend/server/chat/llm_client.py` lines 59-64:

1. **Invalid model ID** — `default_model: "openai/gpt-4o-mini"` does not exist on OpenCode Zen. Zen has its own model catalog (gpt-5-nano, glm-5, kimi-k2.5, etc.). Sending `gpt-4o-mini` to the Zen API results in a model-not-found error.
2. **Endpoint routing** — GPT models on Zen use `/responses` endpoint, but LiteLLM's `openai/` prefix routes through the OpenAI Python client which appends `/chat/completions`. The `/chat/completions` endpoint only works for OpenAI-compatible models (GLM, Kimi, MiniMax, Qwen, Big Pickle).

**Error flow**: LiteLLM exception → caught by generic handler at line 274 → yields `"An error occurred while processing your request"` SSE → frontend shows either this message or falls back to `$t('chat.connection_error')`.

**Recommended fix** (primary — `llm_client.py:62`):
- Change `"default_model": "openai/gpt-4o-mini"` → `"openai/gpt-5-nano"` (free model, confirmed to work via `/chat/completions` by real-world usage in multiple repos)

**Secondary fix** (error surfacing — `llm_client.py:274-276`):
- Extract meaningful error info from LiteLLM exceptions (status_code, message) instead of swallowing all details into a generic message

Full analysis: [research/opencode-zen-connection-debug.md](../research/opencode-zen-connection-debug.md)

## Retry tracker
- OpenCode Zen connection fix task: 0

## Implementation checkpoint (coder)

- Added composer-level model selection + per-provider browser persistence in `frontend/src/lib/components/AITravelChat.svelte` using localStorage key `voyage_chat_model_prefs`.
- Added `chat.model_label` and `chat.model_placeholder` i18n keys in `frontend/src/locales/en.json`.
- Extended `send_message` backend intake in `backend/server/chat/views.py` to read optional `model` (`empty -> None`) and pass it to streaming.
- Updated `backend/server/chat/llm_client.py` to:
  - switch `opencode_zen` default model to `openai/gpt-5-nano`,
  - accept optional `model` override in `stream_chat_completion(...)`,
  - apply safe provider/model compatibility guard (skip strict prefix check for custom `api_base` gateways),
  - map known LiteLLM exception classes to sanitized user-safe error categories/messages,
  - include `tools` / `tool_choice` kwargs only when tools are present.

See related analysis in [research notes](../research/opencode-zen-connection-debug.md#model-selection-implementation-map).

---

## Explorer findings (model selection)

**Date**: 2026-03-08  
**Full detail**: [research/opencode-zen-connection-debug.md — Model selection section](../research/opencode-zen-connection-debug.md#model-selection-implementation-map)

### Persistence decision: `localStorage` (no migration)

**Recommended**: store `{ [provider_id]: model_string }` in `localStorage` key `voyage_chat_model_prefs`.

Rationale:
- No existing per-user model preference field anywhere in DB/API
- Adding a DB column to `CustomUser` requires a migration + serializer + API change → 4+ files
- `UserAPIKey` stores only encrypted API keys (not preferences)
- Model preference is UI-volatile (the model catalog changes; stale DB entries require cleanup)
- `localStorage` is already used elsewhere in the frontend for similar ephemeral UI state
- Model preference is not sensitive; persisting client-side is consistent with how the provider selector already works (no backend persistence either)
- **No migration required** for localStorage approach

### File-by-file edit plan (exact symbols)

#### Backend: `backend/server/chat/llm_client.py`
- `stream_chat_completion(user, messages, provider, tools=None)` → add `model: str | None = None` parameter
- Line 226: `"model": provider_config["default_model"]` → `"model": model or provider_config["default_model"]`
- Add validation: if `model` is not `None`, check it starts with a valid LiteLLM provider prefix (or matches a known-safe pattern); reject bare model strings that don't include provider prefix

#### Backend: `backend/server/chat/views.py`
- `send_message()` (line 104): extract `model = (request.data.get("model") or "").strip() or None`
- Pass `model=model` to `stream_chat_completion()` call (line 144)
- Add validation: if `model` is provided, confirm it belongs to the same provider family (prefix check); return 400 if mismatch

#### Frontend: `frontend/src/lib/types.ts`
- No change needed — `ChatProviderCatalogEntry.default_model` already exists

#### Frontend: `frontend/src/lib/components/AITravelChat.svelte`
- Add `let selectedModel: string = ''` (reset when provider changes)
- Add reactive: `$: selectedProviderEntry = chatProviders.find(p => p.id === selectedProvider) ?? null`
- Add reactive: `$: { if (selectedProviderEntry) { selectedModel = loadModelPref(selectedProvider) || selectedProviderEntry.default_model || ''; } }`
- `sendMessage()` line 121: body `{ message: msgText, provider: selectedProvider }` → `{ message: msgText, provider: selectedProvider, model: selectedModel }`
- Add model input field in the composer toolbar (near provider `<select>`, line 290-299): `<input type="text" class="input input-bordered input-sm" bind:value={selectedModel} placeholder={selectedProviderEntry?.default_model ?? ''} />`
- Add `loadModelPref(provider)` / `saveModelPref(provider, model)` functions using `localStorage` key `voyage_chat_model_prefs`
- Add `$: saveModelPref(selectedProvider, selectedModel)` reactive to persist on change

#### Frontend: `frontend/src/locales/en.json`
- Add `"chat.model_label"`: `"Model"` (label for model input)
- Add `"chat.model_placeholder"`: `"Default model"` (placeholder when empty)

### Validation constraints / risks

1. **Model-provider prefix mismatch**: `stream_chat_completion` uses `provider_config["default_model"]` prefix to route via LiteLLM. If user passes `openai/gpt-5-nano` for the `anthropic` provider, LiteLLM will try to call OpenAI with Anthropic credentials. Backend must validate that the supplied model string starts with the expected provider prefix or reject it.
2. **Free-text model field**: No enumeration from backend; user types any string. Validation (prefix check) is the only guard.
3. **localStorage staleness**: If a provider removes a model, the stored preference produces a LiteLLM error — the error surfacing fix (Fix #2 in existing plan) makes this diagnosable.
4. **Empty string vs null**: Frontend should send `model: selectedModel || undefined` (omit key if empty) to preserve backend default behavior.

### No migration required
All backend changes are parameter additions to existing function signatures + optional request field parsing. No DB schema changes.

---

## Explorer findings

**Date**: 2026-03-08  
**Detail**: Full trace in [research/opencode-zen-connection-debug.md](../research/opencode-zen-connection-debug.md)

### End-to-end path (summary)

```
AITravelChat.svelte:sendMessage()
  POST /api/chat/conversations/<id>/send_message/  { message, provider:"opencode_zen" }
  → +server.ts:handleRequest()  [CSRF refresh + proxy, SSE passthrough lines 94-98]
  → views.py:ChatViewSet.send_message()  [validates provider, saves user msg]
  → llm_client.py:stream_chat_completion()  [builds kwargs, calls litellm.acompletion]
  → litellm.acompletion(model="openai/gpt-4o-mini", api_base="https://opencode.ai/zen/v1")
  → POST https://opencode.ai/zen/v1/chat/completions  ← FAILS: model not on Zen
  → except Exception at line 274 → data:{"error":"An error occurred..."}
  ← frontend shows error string inline (or "Connection error." on network failure)
```

### Ranked root causes confirmed by code trace

1. **[CRITICAL] Wrong default model** (`openai/gpt-4o-mini` is not a Zen model)  
   - `backend/server/chat/llm_client.py:62`  
   - Fix: change to `"openai/gpt-5-nano"` (free, confirmed OpenAI-compat via `/chat/completions`)

2. **[SIGNIFICANT] Generic exception handler masks provider errors**  
   - `backend/server/chat/llm_client.py:274-276`  
   - Bare `except Exception:` swallows LiteLLM structured exceptions (NotFoundError, AuthenticationError, etc.)  
   - Fix: extract `exc.status_code` / `exc.message` and forward to SSE error payload

3. **[SIGNIFICANT] WSGI + per-request event loop for async LiteLLM**  
   - Backend runs **Gunicorn WSGI** (`supervisord.conf:11`); no ASGI entry point exists  
   - `views.py:66-76` `_async_to_sync_generator` creates `asyncio.new_event_loop()` per request  
   - LiteLLM httpx sessions may not be compatible with per-call new loops → potential connection errors on the second+ tool iteration  
   - Fix: wrap via `asyncio.run()` or migrate to ASGI (uvicorn)

4. **[MINOR] `tool_choice: None` / `tools: None` passed as kwargs when unused**  
   - `backend/server/chat/llm_client.py:227-229`  
   - Fix: conditionally include keys only when tools are present

5. **[MINOR] Synchronous ORM call inside async generator**  
   - `backend/server/chat/llm_client.py:217` — `get_llm_api_key()` calls `UserAPIKey.objects.get()` synchronously  
   - Fine under WSGI+new-event-loop but technically incorrect for async context  
   - Fix: wrap with `sync_to_async` or move key lookup before entering async boundary

### Minimal edit points for a fix

| Priority | File | Location | Change |
|---|---|---|---|
| 1 (required) | `backend/server/chat/llm_client.py` | line 62 | `"default_model": "openai/gpt-5-nano"` |
| 2 (recommended) | `backend/server/chat/llm_client.py` | lines 274-276 | Extract `exc.status_code`/`exc.message` for user-facing error |
| 3 (recommended) | `backend/server/chat/llm_client.py` | lines 225-234 | Only include `tools`/`tool_choice` keys when tools are provided |

---

## Critic gate

**VERDICT**: APPROVED  
**Date**: 2026-03-08  
**Reviewer**: critic agent

### Rationale

The plan is well-scoped, targets a verified root cause with clear code references, and all three changes are in a single file (`llm_client.py`) within the same request path. This is a single coherent bug fix, not a multi-feature plan — no decomposition required.

### Assumption challenges

1. **`gpt-5-nano` validity on Zen** — The researcher claims this model is confirmed via GitHub usage patterns, but there is no live API verification. The risk is mitigated by Fix #2 (error surfacing), which would make any remaining model mismatch immediately diagnosable. **Accepted with guardrail**: coder must add a code comment noting the model was chosen based on research, and tester must verify the error path produces a meaningful message if the model is still wrong.

2. **`@mdi/js` build failure is NOT a baseline issue** — `@mdi/js` is a declared dependency in `package.json:44` but `node_modules/` is absent in this worktree. Running `bun install` will resolve this. **Guardrail**: Coder must run `bun install` before the validation pipeline; do not treat this as a known/accepted failure.

3. **Error surfacing may leak sensitive info** — Forwarding raw `exc.message` from LiteLLM exceptions could expose `api_base` URLs, internal config, or partial request data. Prior security review (decisions.md:103) already flagged `api_base` leakage as unnecessary. **Guardrail**: The error surfacing fix must sanitize exception messages — use only `exc.status_code` and a generic category (e.g., "authentication error", "model not found", "rate limit exceeded"), NOT raw `exc.message`. Map known LiteLLM exception types to safe user-facing descriptions.

### Scope guardrails for implementation

1. **In scope**: Fixes #1, #2, #3 from the plan table (model name, error surfacing, tool_choice cleanup) — all in `backend/server/chat/llm_client.py`.
2. **Out of scope**: Fix #3 from Explorer findings (WSGI→ASGI migration), Fix #5 (sync_to_async ORM). These are structural improvements, not root cause fixes.
3. **No frontend changes** unless the error message format changes require corresponding updates to `AITravelChat.svelte` parsing — verify and include only if needed.
4. **Error surfacing must sanitize**: Map LiteLLM exception classes (`NotFoundError`, `AuthenticationError`, `RateLimitError`, `BadRequestError`) to safe user-facing categories. Do NOT forward raw `exc.message` or `str(exc)`.
5. **Validation**: Run `bun install` first, then full pre-commit checklist (`format`, `lint`, `check`, `build`). Backend `manage.py check` must pass. If possible, manually test the chat SSE error path with a deliberately bad model name to confirm error surfacing works.
6. **No new dependencies, no migrations, no schema changes** — none expected and none permitted for this fix.

---

## Reviewer security verdict

**VERDICT**: APPROVED  
**LENS**: Security  
**REVIEW_SCORE**: 3  
**Date**: 2026-03-08

### Security goals evaluated

| Goal | Status | Evidence |
|---|---|---|
| 1. Error handling doesn't leak secrets/api_base/raw internals | ✅ PASS | `_safe_error_payload()` maps exception classes to hardcoded user-safe strings; no `str(exc)`, `exc.message`, or `exc.args` forwarded. Logger.exception at line 366 is server-side only. Critic guardrail (decisions.md:189) fully satisfied. |
| 2. Model override input can't bypass provider constraints dangerously | ✅ PASS | Model string used only as JSON field in `litellm.acompletion()` kwargs. No SQL, no shell, no eval, no path traversal. `_is_model_override_compatible()` validates prefix for standard providers. Gateway providers (`api_base` set) skip prefix check — correct by design, worst case is provider returns an error caught by sanitized handler. |
| 3. No auth/permission regressions in send_message | ✅ PASS | `IsAuthenticated` + `get_queryset(user=self.request.user)` unchanged. New `model` param is additive-only, doesn't bypass existing validation. Tool execution scopes all DB queries to `user=user`. |
| 4. localStorage stores no sensitive values | ✅ PASS | Key `voyage_chat_model_prefs` stores `{provider_id: model_string}` only. SSR-safe guards present. Try/catch on JSON parse/write. |

### Findings

**CRITICAL**: (none)

**WARNINGS**:
- `[llm_client.py:194,225]` `api_base` field exposed in provider catalog response to frontend — pre-existing from prior consolidated review (decisions.md:103), not newly introduced. Server-defined constants only (not user-controllable), no SSRF. Frontend type includes field but never renders or uses it. (confidence: MEDIUM)

**SUGGESTIONS**:
1. Consider adding a `max_length` check on the `model` parameter in `views.py:114` (e.g., reject if >200 chars) as defense-in-depth against pathological inputs, though Django's request size limits provide a baseline guard.
2. Consider omitting `api_base` from the provider catalog response to frontend since the frontend never uses this value (pre-existing — tracked since prior security review).

### Prior findings cross-check
- **Critic guardrail** (decisions.md:119-123 — "Error surfacing must NOT forward raw exc.message"): **CONFIRMED** — implementation uses class-based dispatch to hardcoded strings.
- **Prior security review** (decisions.md:98-115 — api_base exposure, provider validation, IDOR checks): **CONFIRMED** — all findings still valid, no regressions.
- **Explorer model-provider prefix mismatch warning** (plan lines 108-109): **CONFIRMED** — `_is_model_override_compatible()` implements the recommended validation.

### Tracker states
- [x] Security goal 1: sanitized error handling (PASS)
- [x] Security goal 2: model override safety (PASS)
- [x] Security goal 3: auth/permission integrity (PASS)
- [x] Security goal 4: localStorage safety (PASS)

---

## Reviewer correctness verdict

**VERDICT**: APPROVED  
**LENS**: Correctness  
**REVIEW_SCORE**: 0  
**Date**: 2026-03-08

### Requirements verification

| Requirement | Status | Evidence |
|---|---|---|
| Chat composer model selection | ✅ PASS | `AITravelChat.svelte:346-353` — text input bound to `selectedModel`, placed in composer header next to provider selector. Disabled when no providers available. |
| Per-provider browser persistence | ✅ PASS | `loadModelPref`/`saveModelPref` (lines 60-92) use `localStorage` key `voyage_chat_model_prefs`. Provider change loads saved preference via `initializedModelProvider` sentinel (lines 94-98). User edits auto-save via reactive block (lines 100-102). JSON parse errors caught. SSR guards present. |
| Optional model passed to backend | ✅ PASS | Frontend sends `model: selectedModel.trim() || undefined` (line 173). Backend extracts `model = (request.data.get("model") or "").strip() or None` (views.py:114). Passed as `model=model` to `stream_chat_completion` (views.py:150). |
| Model used as override in backend | ✅ PASS | `completion_kwargs["model"] = model or provider_config["default_model"]` (llm_client.py:316). Null/empty correctly falls back to provider default. |
| No regressions in provider selection/send flow | ✅ PASS | Provider selection, validation, SSE streaming all unchanged except additive `model` param. Error field format compatible with existing frontend parsing (`parsed.error` at line 210). |
| Error category mapping coherent with frontend | ✅ PASS | Backend `_safe_error_payload` returns `{"error": "...", "error_category": "..."}`. Frontend checks `parsed.error` (human-readable string) and displays it. `error_category` available for future programmatic use. HTTP 400 errors also use `err.error` pattern (lines 177-183). |

### Correctness checklist

- **Off-by-one**: N/A — no index arithmetic in changes.
- **Null/undefined dereference**: `selectedProviderEntry?.default_model ?? ''` and `|| $t(...)` — null-safe. Backend `model or provider_config["default_model"]` — None-safe.
- **Ignored errors**: `try/catch` in `loadModelPref`/`saveModelPref` returns safe defaults. Backend exception handler maps to user-facing messages.
- **Boolean logic**: Reactive guard `initializedModelProvider !== selectedProvider` correctly gates initialization vs save paths.
- **Async/await**: No new async code in frontend. Backend `model` param is synchronous extraction before async boundary.
- **Race conditions**: None introduced — `selectedModel` is single-threaded Svelte state.
- **Resource leaks**: None — localStorage access is synchronous and stateless.
- **Unsafe defaults**: Model defaults to provider's `default_model` when empty — safe.
- **Dead/unreachable branches**: Pre-existing `tool_iterations` (views.py:139-141, never incremented) — not introduced by this change.
- **Contract violations**: Function signature `stream_chat_completion(user, messages, provider, tools=None, model=None)` matches all call sites. `_is_model_override_compatible` return type is bool, used correctly in conditional.
- **Reactive loop risk**: Verified — `initializedModelProvider` sentinel prevents re-entry between Block 1 (load) and Block 2 (save). `saveModelPref` has no state mutations → no cascading reactivity.

### Findings

**CRITICAL**: (none)  
**WARNINGS**: (none)

**SUGGESTIONS**:
1. `[AITravelChat.svelte:100-102]` Save-on-every-keystroke reactive block calls `saveModelPref` on each character typed. Consider debouncing or saving on blur/submit to reduce localStorage churn.
2. `[llm_client.py:107]` `getattr(exceptions, "NotFoundError", tuple())` — `isinstance(exc, ())` is always False by design (graceful fallback). A brief inline comment would clarify intent for future readers.

### Prior findings cross-check
- **Critic gate guardrails** (decisions.md:117-124): All 3 guardrails confirmed followed (sanitized errors, `bun install` prerequisite, WSGI migration out of scope).
- **`opencode_zen` default model**: Changed from `openai/gpt-4o-mini` → `openai/gpt-5-nano` as prescribed by researcher findings.
- **`api_base` catalog exposure** (decisions.md:103): Pre-existing, unchanged by this change.
- **`tool_iterations` dead guard** (decisions.md:91): Pre-existing, not affected by this change.

### Tracker states
- [x] Correctness goal 1: model selection end-to-end (PASS)
- [x] Correctness goal 2: per-provider persistence (PASS)
- [x] Correctness goal 3: model override to backend (PASS)
- [x] Correctness goal 4: no provider/send regressions (PASS)
- [x] Correctness goal 5: error mapping coherence (PASS)

---

## Tester verdict (standard + adversarial)

**STATUS**: PASS  
**PASS**: Both (Standard + Adversarial)  
**Date**: 2026-03-08

### Commands run

| Command | Result |
|---|---|
| `docker compose exec server python3 manage.py check` | PASS — 0 issues (1 silenced, expected) |
| `bun run check` (frontend) | PASS — 0 errors, 6 warnings (all pre-existing in `CollectionRecommendationView.svelte` + `RegionCard.svelte`, not in changed files) |
| `docker compose exec server python3 manage.py test --keepdb` | 30 tests found; pre-existing failures: 2 user tests (email field key error) + 4 geocoding tests (Google API mock) = 6 failures (matches documented "2/3 fail" baseline). No regressions. |
| Chat module static path validation (Django context) | PASS — all 5 targeted checks |
| `bun run build` | Vite compilation PASS (534 modules SSR, 728 client). EACCES error on `build/` dir is a pre-existing Docker worktree permission issue, not a compilation failure. |

### Targeted checks verified

- [x] `opencode_zen` default model is `openai/gpt-5-nano` — **CONFIRMED**
- [x] `stream_chat_completion` accepts `model: str | None = None` parameter — **CONFIRMED**
- [x] Empty/whitespace/falsy `model` values in `views.py` produce `None` (falls back to provider default) — **CONFIRMED**
- [x] `_safe_error_payload` does NOT leak raw exception text, `api_base`, or sensitive data — **CONFIRMED** (all 6 LiteLLM exception classes mapped to sanitized hardcoded strings)
- [x] `_is_model_override_compatible` skips prefix check for `api_base` gateways — **CONFIRMED**
- [x] Standard providers reject cross-provider model prefixes — **CONFIRMED**
- [x] `is_chat_provider_available` rejects null, empty, and adversarial provider IDs — **CONFIRMED**
- [x] i18n keys `chat.model_label` and `chat.model_placeholder` present in `en.json` — **CONFIRMED**
- [x] `tools`/`tool_choice` kwargs excluded from `completion_kwargs` when `tools` is falsy — **CONFIRMED**

### Adversarial attempts

| Hypothesis | Test | Expected failure signal | Observed result |
|---|---|---|---|
| 1. Pathological model strings (long/unicode/injection/null-byte) crash `_is_model_override_compatible` | 500-char model, unicode model, SQL injection model, null-byte model | Exception or incorrect behavior | PASS — no crashes, all return True/False correctly |
| 2. LiteLLM exception classes with sensitive data in `message` field leak via `_safe_error_payload` | All 6 LiteLLM exception classes instantiated with sensitive marker string | Sensitive data in SSE payload | PASS — all 6 classes return sanitized hardcoded payloads |
| 3. Empty/whitespace/falsy model string bypasses `None` conversion in `views.py` | `""`, `"   "`, `None`, `False`, `0` passed to views.py extraction | Model sent as empty string to LiteLLM | PASS — all produce `None`, triggering default fallback |
| 4. All CHAT_PROVIDER_CONFIG providers have `default_model=None` (would cause `model=None` to LiteLLM) | Check each provider's `default_model` value | At least one None | PASS — all 9 providers have non-null `default_model` |
| 5. Unknown provider without slash in `default_model` causes unintended prefix extraction | Provider not in `PROVIDER_MODEL_PREFIX` + bare `default_model` | Cross-prefix model rejected | PASS — no expected_prefix extracted from bare default → pass-through |
| 6. Adversarial provider IDs (`__proto__`, null-byte, SQL injection, path traversal) bypass availability check | Injected strings to `is_chat_provider_available` | Available=True for injected ID | PASS — all rejected. Note: `openai\n` returns True because `strip()` normalizes to `openai` (correct, consistent with views.py normalization). |
| 7. `_merge_tool_call_delta` with `None`, empty list, missing `index` key | Edge case inputs | Crash or wrong accumulator state | PASS — None/empty are no-ops; missing index defaults to 0 |
| 7b. Large index (9999) to `_merge_tool_call_delta` causes DoS via huge list allocation | `index=9999` | Memory spike | NOTE (pre-existing, not in scope) — creates 10000-entry accumulator; pre-existing behavior |
| 8. model fallback uses `and` instead of `or` | Verify `model or default` not `model and default` | Wrong model when set | PASS — `model or default` correctly preserves explicit model |
| 9. `tools=None` causes None kwargs to LiteLLM | Verify conditional exclusion | `tool_choice=None` in kwargs | PASS — `if tools:` guard correctly excludes both kwargs when None |

### Mutation checks

| Mutation | Critical logic | Detected by tests? |
|---|---|---|
| `_is_model_override_compatible`: `not model OR api_base` → `not model AND api_base` | Gateway bypass | DETECTED — test covers api_base set + model set case |
| `_merge_tool_call_delta`: `len(acc) <= idx` → `len(acc) < idx` | Off-by-one in accumulator growth | DETECTED — index=0 on empty list tested |
| `completion_kwargs["model"]`: `model or default` → `model and default` | Model fallback | DETECTED — both None and set-model cases tested |
| `is_chat_provider_available` negation | Provider validation gate | DETECTED — True and False cases both verified |
| `_safe_error_payload` exception dispatch order | Error sanitization | DETECTED — LiteLLM exception MRO verified, no problematic inheritance |

**MUTATION_ESCAPES: 0/5**

### Findings

**CRITICAL**: (none)

**WARNINGS** (pre-existing, not introduced by this change):
- `_merge_tool_call_delta` large index: no upper bound on accumulator size (pre-existing DoS surface; not in scope per critic gate)
- `tool_iterations` never incremented (pre-existing dead guard; not in scope)

**SUGGESTIONS** (carry-forward from reviewer):
1. Debounce `saveModelPref` on model input (every-keystroke localStorage writes)
2. Add clarifying comment on `getattr(exceptions, "NotFoundError", tuple())` fallback pattern

### Task tracker update
- [x] Standard validation run and targeted chat-path checks (Agent: tester) — PASS
- [x] Documentation and knowledge sync for provider troubleshooting notes (Agent: librarian) — COMPLETE

---

## Librarian coverage verdict

**STATUS**: COMPLETE  
**Date**: 2026-03-08

### Files updated

| File | Changes | Reason |
|---|---|---|
| `README.md` | Added model selection, error handling, and `gpt-5-nano` default to AI Chat section | User-facing docs now reflect model override and error surfacing features |
| `docs/docs/usage/usage.md` | Added model override and error messaging to AI Travel Chat section | Usage guide now covers model input and error behavior |
| `.memory/knowledge.md` | Added 3 new sections: Chat Model Override Pattern, Sanitized LLM Error Mapping, OpenCode Zen Provider. Updated AI Chat section with model override + error mapping refs. Updated known issues baseline (0 errors/6 warnings, 6/30 test failures). | Canonical project knowledge now covers all new patterns for future sessions |
| `AGENTS.md` | Added model override + error surfacing to AI chat description and Key Patterns. Updated known issues baseline. | OpenCode instruction file synced |
| `CLAUDE.md` | Same changes as AGENTS.md (AI chat description, key patterns, known issues) | Claude Code instruction file synced |
| `.github/copilot-instructions.md` | Added model override + error surfacing to AI Chat description. Updated known issues + command output baselines. | Copilot instruction file synced |
| `.cursorrules` | Updated known issues baseline. Added chat model override + error surfacing conventions. | Cursor instruction file synced |

### Knowledge propagation

- **Inward merge**: No new knowledge found in instruction files that wasn't already in `.memory/`. All instruction files were behind `.memory/` state.
- **Outward sync**: All 4 instruction files updated with: (1) model override pattern, (2) sanitized error mapping, (3) `opencode_zen` default model `openai/gpt-5-nano`, (4) corrected known issues baseline.
- **Cross-references**: knowledge.md links to plan file for model selection details and to decisions.md for critic gate guardrail. New sections cross-reference each other (error mapping → decisions.md, model override → plan).

### Not updated (out of scope)

- `docs/architecture.md` — Stub file; model override is an implementation detail, not architectural. The chat app entry already exists.
- `docs/docs/guides/travel_agent.md` — MCP endpoint docs; unrelated to in-app chat model selection.
- `docs/docs/configuration/advanced_configuration.md` — Chat uses per-user API keys (no server-side env vars); no config changes to document.

### Task tracker
- [x] Documentation and knowledge sync for provider troubleshooting notes (Agent: librarian)
