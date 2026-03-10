---
title: assistant-add-flow-fixes
type: note
permalink: voyage/plans/assistant-add-flow-fixes
---

## Feature A hotfix implementation note
- Added a targeted chat hotfix in `ChatViewSet` so required-arg validation for `search_places` with missing `location` now emits a natural assistant clarification as SSE `content` (and persists it as an assistant message) instead of streaming a `tool_validation_error` payload.
- Kept existing generic required-param short-circuit behavior unchanged for all other tools/errors.
- Added tests covering the specific detection helper and end-to-end streaming behavior for the missing-location clarify path.

## Follow-up fix: itinerary-aware search fallback
- Feature: Use collection itinerary context to satisfy missing `search_places.location` when available, and preserve dining intent when category is omitted.
- Acceptance:
  - Restaurant requests across a collection itinerary should not ask for location when itinerary context can provide one.
  - `search_places` should not silently return tourism attractions for restaurant requests when category is omitted.
  - Existing behavior for non-dining searches remains intact.
- Planned worktree: `.worktrees/chat-search-intent-fix`
- Planned branch: `fix/chat-search-intent-fix`

## Implementation note: chat search intent + context retry
- Implemented deterministic `search_places` retry fallback in `ChatViewSet`: when tool call misses required `location`, retry first with trip context (`destination`, then first itinerary stop label), then retain existing user-location-reply retry behavior.
- Added deterministic dining-intent heuristic in `ChatViewSet` to inject `category="food"` when `search_places.category` is omitted and current/recent user messages indicate restaurant/dining intent.
- Updated `search_places` tool schema text to explicitly describe `food` (restaurants/dining), `tourism` (attractions), and `lodging` (hotels/stays).
- Added targeted tests for category inference and a collection-context integration flow proving restaurant requests can complete via destination-backed retry without location clarification prompt.

## Regression: Duplicate Tool Summaries / Repeated Items — Frontend Analysis (2026-03-10)

### Context
Exploring why restaurant recommendations across a test itinerary produce duplicated itinerary-item summaries and repeated warning toasts in the frontend chat renderer.

### Root Cause 1 — `rebuildConversationMessages` double-accumulates `tool_results` on reload

**File:** `frontend/src/lib/components/AITravelChat.svelte`, `rebuildConversationMessages()` (lines 333–375)

**Mechanism:** When `selectConversation()` reloads a conversation from the API, `rebuildConversationMessages()` walks the raw message list and pushes each `role=tool` message into its parent assistant message's `tool_results` array. The backend serializer may return a pre-populated `tool_results` field on the assistant message object. Because the `rebuilt` map at line 336 preserves any server-side `tool_results` via spread (`msg.tool_results ? [...msg.tool_results] : undefined`), and then the walk loop **appends again** from the raw `role=tool` sibling messages, any tool result present on both the server-side `assistant.tool_results` field *and* as a sibling `role=tool` message will be pushed **twice**.

**Second trigger path:** A multi-stop itinerary causes the backend tool loop to fire `search_places` once per stop via the context-retry fallback. Each call emits a separate `tool_result` SSE event. The frontend appends each into `assistantMsg.tool_results` during streaming (line 472). On conversation reload, `rebuildConversationMessages` re-appends them again from the persisted `role=tool` DB rows → **2× the place-result cards**.

**Fix approach:** Change line 336 so the initial `rebuilt` map always sets `tool_results: undefined`. This discards any server-side `tool_results` field on assistant messages and lets the sibling-walk be the sole source of truth:
```ts
// line 334–337 — change to:
const rebuilt = rawMessages.map((msg) => ({
  ...msg,
  tool_results: undefined   // always re-derive from role=tool siblings below
}));
```

### Root Cause 2 — Multi-iteration tool loop creates multiple assistant messages; `rebuildConversationMessages` may pair results to wrong parent

**File:** `AITravelChat.svelte`, `rebuildConversationMessages()` lines 342–344 and backend `event_stream` lines 662–688

**Mechanism:** For a multi-restaurant flow the backend iterates: `search_places` (iteration 1) → saves assistant+tool messages → then `add_to_itinerary × N` (iterations 2–N). Each iteration saves a separate assistant message with distinct `tool_calls`. On reload, the loop in `rebuildConversationMessages` sets `activeAssistant` to each assistant message with `tool_calls`, then nulls it when `tool_results.length >= toolCallIds.length` (lines 366–371). If the DB `created_at` timestamps for assistant and tool messages are identical (same DB transaction), the `order_by("created_at")` in `_build_llm_messages` is non-deterministic, and the sibling walk may misalign tool results to wrong parent assistant messages → wrong or duplicated summary cards.

**Fix approach (backend):** After saving the assistant message at line 670 with `await sync_to_async(ChatMessage.objects.create)`, save each tool message **in a separate awaited call** (already the case at lines 678–682) and add a `time.sleep(0)` / tick between saves to guarantee distinct `created_at`. Alternatively, add an explicit `order` integer field to `ChatMessage` and sort by it instead of `created_at`.

### Root Cause 3 — Repeated "success" toast from duplicate place-result cards

**File:** `AITravelChat.svelte`, `addPlaceToItinerary()` lines 569–632

**Mechanism:** `addToast('success', $t('added_successfully'))` fires unconditionally at line 626 on every user-triggered add. When Root Cause 1 causes duplicate place-result cards to be rendered, the user sees two "Add to itinerary" buttons for the same place and clicking either fires a toast. Fixing Root Cause 1 (dedup in `rebuildConversationMessages`) eliminates the duplicate cards and therefore this repeat toast.

**No action required here unless RC1 fix is insufficient.** As a defense-in-depth measure, consider tracking which place names have been added within the session and disabling the button.

### Concrete Edit Points

| File | Function/Section | Change |
|---|---|---|
| `AITravelChat.svelte` L334–336 | `rebuilt` map init in `rebuildConversationMessages` | Change `tool_results: msg.tool_results ? [...msg.tool_results] : undefined` → `tool_results: undefined` (always re-derive from sibling walk) |
| `AITravelChat.svelte` L467–474 | SSE `parsed.tool_result` handler in `sendMessage` | Add dedup guard: skip push if `tool_call_id` already in `assistantMsg.tool_results` |
| `AITravelChat.svelte` L894–944 | `{#each msg.tool_results as result}` template | Add JS-side dedup by `tool_call_id` or a `{#key}` block before rendering |
| `backend/server/chat/views/__init__.py` L670–682 | assistant + tool message save in `event_stream` | Verify saved order is deterministic; add explicit sequence/order field if `created_at` collisions are possible |

### Recommended Fix Sequence
1. **Priority 1:** `AITravelChat.svelte` line 336 — change to `tool_results: undefined`. Single-line fix, eliminates Root Cause 1 and RC3 transitively.
2. **Priority 2:** `AITravelChat.svelte` SSE handler (line 472) — add `tool_call_id` dedup guard for defense against backend emitting duplicate events.
3. **Priority 3:** Template dedup (lines 894–944) as render-layer safety net.
4. **Verify:** Reload a multi-restaurant conversation; each `add_to_itinerary` summary and each place card must appear exactly once.

### Related Notes
- [[assistant-add-flow-fixes]] — backend search intent + retry logic that triggers multi-iteration tool loops

## Follow-on fix: restaurant recommendation tool loop
- [ ] Workstream `fix/chat-tool-loop-fix` in `.worktrees/chat-tool-loop-fix`: stop chat tool loops from replaying execution failures into the LLM context; only count successful tool iterations, cap repeated all-failure rounds, and hard-stop permanent `web_search` failures.
  - Acceptance: restaurant recommendation requests do not end with "too many tool calls" when tool executions fail; `search_places`/`web_search` failures surface once and stop retry spirals.
- [ ] Keep frontend tool-result rendering deduplicated in `AITravelChat.svelte` during both SSE streaming and conversation rebuild.
  - Acceptance: itinerary/tool summaries do not render duplicate cards or duplicate downstream add-to-itinerary affordances after reload.
- [ ] Validate the fix in worktree `fix/chat-tool-loop-fix` with targeted backend chat tests plus frontend `bun run check`/`bun run build`, then perform a functional restaurant-request verification.
  - Acceptance: validation demonstrates the assistant either returns restaurant guidance or surfaces a single actionable failure instead of looping.

## Implementation outcome: chat tool loop + duplicate summary fix
- Added execution-failure classification in `backend/server/chat/views/__init__.py` that separates required-parameter validation errors from execution failures, and excludes execution-failure tool rows from LLM replay/history filtering.
- Updated tool loop control so `tool_iterations` increments only after at least one successful tool call; added bounded `MAX_ALL_FAILURE_ROUNDS = 3` for all-failure rounds, with immediate stop for permanent failures (`retryable: false`).
- Extended `search_places` location retry candidate detection to include geocoding failures (`Could not geocode location: ...`) so destination/itinerary/user-location fallback can retry before terminating.
- Marked `web_search` dependency import failure as permanent in `backend/server/chat/agent_tools.py` (`retryable: false`) so it is not retried like transient outages.
- Fixed frontend duplication in `frontend/src/lib/components/AITravelChat.svelte` by rebuilding tool results only from persisted `role=tool` rows, deduping on `tool_call_id` during rebuild and live SSE ingestion, and rendering deduped tool results.
- Added focused backend tests in `backend/server/chat/tests.py` for execution-failure classification, geocode retry fallback, bounded all-failure loop behavior, permanent failure immediate stop, and `web_search` import-failure retryability flag.
- Related prior analysis note: [[assistant-add-flow-fixes]]

## Security Review Verdict: chat-tool-loop-fix (2026-03-10)

- **Verdict:** CHANGES-REQUESTED
- **Review Score:** 6 (2 WARNINGs × 3)
- **Lens:** Security
- **WARNING 1:** `_build_tool_execution_error_event` (views/__init__.py:260-272) forwards raw tool error text to the client SSE stream. The error string from `execute_tool` (agent_tools.py:643) uses `str(exc)`, which can contain internal details for uncaught exceptions. This is also persisted as assistant message content.
- **WARNING 2:** Persisted error text in assistant messages (L769) creates a durable exposure vector — raw error details survive in DB and are re-served on reload.
- **No CRITICALs.** Auth/permission checks, injection safety, and CSRF handling remain intact.
- **Fix required:** Sanitize error text in `_build_tool_execution_error_event` or at source in `execute_tool` catch-all. Targeted re-review sufficient after fix.
- **Confirmed:** `_safe_error_payload()` convention not violated by existing code, but new path bypasses it.
- Related: [[assistant-add-flow-fixes]]

## Review verdict: chat-tool-loop-fix (2026-03-10)

**VERDICT: APPROVED**
**LENS: correctness**
**REVIEW_SCORE: 0**

### What was checked

1. **Execution failure classification** (`_is_execution_failure_tool_error`, `_is_retryable_execution_failure`): Verified the classification is correctly the complement of `_is_required_param_tool_error` — any `error`-bearing dict that doesn't match the required-param pattern is an execution failure. The `retryable` flag defaults to `True` unless explicitly `False`. No false-positive/false-negative classification risk found.

2. **Execution failure exclusion from LLM context**: Execution failure tool results are never added to `successful_tool_calls`/`successful_tool_messages`/`successful_tool_chat_entries` (skipped via `continue` at line 718). They are never persisted to DB and never appended to `current_messages`. The `_build_llm_messages` filter at lines 65-67 and 84-88 is a belt-and-suspenders defense for pre-existing DB data.

3. **All-failure-round bounding**: `all_failure_rounds` increments by 1 on each all-failure round and is hard-set to MAX on permanent failures. The outer `while` loop guard (`tool_iterations < MAX_TOOL_ITERATIONS`) remains satisfied during all-failure rounds (since `tool_iterations` isn't incremented), but `all_failure_rounds >= MAX_ALL_FAILURE_ROUNDS` (3) exits within bounded iterations. No infinite loop possible.

4. **Permanent failure fast-path**: `encountered_permanent_failure = True` → `all_failure_rounds = MAX_ALL_FAILURE_ROUNDS` → immediate stop. Confirmed `web_search` ImportError returns `retryable: False`.

5. **Geocode failure retry**: `_is_search_places_location_retry_candidate_error` now matches both "location is required" and "Could not geocode location: ..." patterns. Retry uses trip context destination or user content. Retry success check (lines 631-635) now requires the retry to be free of BOTH required-param AND execution-failure errors — correct tightening vs main branch.

6. **Frontend tool-result dedup**: Three layers of defense confirmed:
   - `rebuildConversationMessages` now sets `tool_results: undefined` (line 374), eliminating RC1 (double-accumulation from server-side pre-populated `tool_results`).
   - `appendToolResultDedup` deduplicates by `tool_call_id` during both rebuild (line 402) and SSE streaming (line 514).
   - `uniqueToolResultsByCallId` at render time (line 939) provides a final safety net.
   - Edge case: tool results without `tool_call_id` bypass dedup — acceptable since real tool calls always have IDs.

7. **Test coverage**: Tests cover execution failure classification, geocode retry, bounded all-failure loop (verifying 3 LLM calls + 3 tool calls), permanent failure immediate stop (verifying 1 LLM call + 1 tool call), and `web_search` ImportError retryability flag. Mock setup is correct — `side_effect = failing_stream` (callable) creates fresh async generators per call.

### No findings

- No off-by-one in loop bounds.
- No async/await misuse — `sync_to_async` wraps synchronous `execute_tool` correctly.
- No resource leaks — generators terminate cleanly via `return` or `break`.
- No race conditions — the event stream is single-threaded.
- No contract violations — SSE event format is preserved for both success and error paths.
- No mutation/shared-state risks — `first_execution_failure` and `encountered_permanent_failure` are scoped per tool-call batch.

## Security fix outcome: execute_tool error sanitization
- Updated `backend/server/chat/agent_tools.py` so `execute_tool()` catch-all no longer returns raw `str(exc)`.
- New catch-all payload is now the safe generic message: `{"error": "Tool execution failed"}`.
- Added focused regression test in `backend/server/chat/tests.py` (`ExecuteToolErrorSanitizationTests`) to verify exception text is not exposed via `execute_tool()`.

## Security Re-Review Verdict: execute_tool sanitization fix (2026-03-10)

- **Verdict:** APPROVED
- **Review Score:** 0
- **Lens:** Security (targeted re-review)
- **Resolution:** Both prior WARNINGs (SSE raw error leak, DB persistence of raw errors) are RESOLVED.
- **Evidence:**
  - `execute_tool()` catch-all at `agent_tools.py:643` now returns `{"error": "Tool execution failed"}` (hardcoded string, no `str(exc)`).
  - `_build_tool_execution_error_event()` at `views/__init__.py:260-272` wraps the sanitized error in a user-safe sentence.
  - SSE emission at `views/__init__.py:775` and DB persistence at `views/__init__.py:769` both receive only the wrapped safe text.
  - Regression test `ExecuteToolErrorSanitizationTests` at `tests.py:49-65` validates sanitization by injecting `RuntimeError("sensitive backend detail")` and asserting the generic output.
- **No new issues introduced.** Single-line source-level fix with no new code paths or trust boundaries.
- Related: [[assistant-add-flow-fixes]]

## Outcome: restaurant recommendation tool loop fix (2026-03-10)
- [x] Workstream `fix/chat-tool-loop-fix` in `.worktrees/chat-tool-loop-fix`: chat tool execution failures no longer replay into LLM context as successful tool results; successful-tool iteration budget is separate from all-failure rounds; permanent failures stop immediately.
- [x] Frontend `AITravelChat.svelte` dedupes tool results on rebuild, SSE ingestion, and render.
- [x] Validation passed: backend targeted chat suites passed after syncing worktree files into `voyage-server-1:/code/chat/...`; frontend `bun run check` and `bun run build` passed with only pre-existing warnings.
- [x] Review passed after sanitizing `execute_tool()` catch-all errors to `"Tool execution failed"`.

Open risk accepted for pre-release:
- Mixed batches with both successful and failed tool calls can still drop the failed tool silently and rely on `MAX_TOOL_ITERATIONS` as the backstop; adversarial tester marked this low severity and acceptable for pre-release.

## Implementation outcome: backend context-location extraction + clarification suppression
- Updated `backend/server/chat/views/__init__.py` itinerary-stop fallback parsing so address-only stops derive a city hint from the last non-numeric comma-separated segment (e.g. `Little Turnstile 6, London` → `London`) before computing `trip_context_location`.
- Updated `search_places` context-retry block to track `attempted_location_retry`; when retries were attempted but still return required-param errors, result is converted to execution failure (`Could not search places at the provided itinerary locations`) to avoid location clarification prompts.
- Clarification branch now only triggers for missing-location required-param errors when no context retry was attempted.
- Added tests in `backend/server/chat/tests.py` for city extraction from fallback address and for retry-with-context failure path asserting no clarification SSE is emitted and execution-failure behavior is returned.

## Targeted Re-Review Verdict: city extraction + clarification suppression (2026-03-10)

- **Verdict:** APPROVED
- **Review Score:** 0
- **Lens:** Correctness (targeted re-review of Fix 1 + Fix 2 only)
- **Scope:** `views/__init__.py` lines 444-462 (city extraction from fallback address) and lines 611-671 + 694-700 (retry failure → execution failure mutation + clarification guard). Plus two new tests in `tests.py`.

### Fix 1: City extraction — edge cases verified
- Comma address: extracts last non-empty non-numeric segment (correct)
- No comma: falls back to raw `fallback_name` (correct)
- All-numeric segments: falls back to full `fallback_name` (safe, will fail geocoding gracefully)
- Empty parts after split: filtered by truthiness check (correct)
- Dedup via `stop_key`: uses extracted city, correctly collapses same-city addresses

### Fix 2: Retry failure mutation — flow verified
- `attempted_location_retry` is per-tool-call scoped (no cross-call bleed)
- Mutated result `"Could not search places at the provided itinerary locations"` correctly fails `_is_required_param_tool_error` (no match on exact strings or regex)
- Mutated result correctly passes `_is_execution_failure_tool_error` (dict with non-empty error, not required-param)
- Routes to execution-failure handler, not clarification branch
- Clarification guard at lines 694-700 is defense-in-depth (unreachable in mutation scenario, but protects against future refactoring)

### Test coverage verified
- `test_collection_context_retry_extracts_city_from_fallback_address`: correctly tests city extraction from `"Little Turnstile 6, London"` → `"London"` retry
- `test_context_retry_failure_does_not_emit_location_clarification`: correctly tests mutation routing to `tool_execution_error` SSE event, no clarification
- Both tests exercise the intended code paths with correct mock setups

### No findings — APPROVED with zero issues
- Related: [[assistant-add-flow-fixes]]
