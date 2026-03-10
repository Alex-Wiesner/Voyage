---
title: assistant-add-flow-fixes
type: note
permalink: voyage/plans/assistant-add-flow-fixes-1
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

## Regression Exploration: Restaurant Recommendations Across Test Itinerary (2026-03-10)

### Observed failure modes
1. **"too many tool calls"** — `tool_loop_limit` error after 10 iterations
2. **Repeated "search places could not be completed"** — LLM retries `search_places` each iteration, each producing a non-location-error that bypasses the clarification/retry gate
3. **Repeated "web search could not be completed"** — LLM retries `web_search` each iteration; non-fatal errors (rate-limit, ImportError, generic failure) are treated as successful tool calls and fed back to the LLM, which re-calls the tool

### Root cause analysis

#### RC1 — `web_search` non-fatal errors are NOT short-circuited (primary cause of web_search loop)
**File**: `backend/server/chat/views/__init__.py`, `event_stream()` loop (line 474+)
- `web_search` returns `{"error": "...", "results": []}` on ImportError, rate-limit, and generic failures.
- `_is_required_param_tool_error()` only matches "location is required" / "query is required" / `"X is required"` pattern. It does **not** match "Web search failed. Please try again." or "Search rate limit reached."
- So the error payload passes through `_is_required_param_tool_error` → `False`, and the tool result (including the error text) is added to `successful_tool_calls` and fed back into the LLM context as a successful tool message.
- The LLM sees a tool result with `error` text but no real data, and calls `web_search` again — repeating until `MAX_TOOL_ITERATIONS` (10) is hit.

#### RC2 — `search_places` geocoding/Overpass failures are NOT short-circuited (cause of search_places loop)
**File**: `backend/server/chat/agent_tools.py` `search_places()` (line 149, 199–205)
- `search_places` returns `{"error": "Could not geocode location: X"}` when Nominatim returns empty results, `{"error": "Places API request failed: ..."}` on network errors, or `{"error": "An unexpected error occurred..."}` on generic failures.
- **None of these match** `_is_required_param_tool_error()` (which only detects missing-param patterns). They are not `location is required`.
- The context-retry fallback (`_is_search_places_missing_location_required_error`, lines 522–565) only activates on `location is required`. Geocoding/network failures silently pass through as "successful" tool results.
- LLM receives `{"error": "Could not geocode location: Paris"}` in tool context, tries again → same failure → 10 times → loop limit.

#### RC3 — `MAX_TOOL_ITERATIONS = 10` counter increments even when ALL tool calls in an iteration are failures
**File**: `backend/server/chat/views/__init__.py`, line 475
- `tool_iterations += 1` happens **before** tool results are checked. A single iteration with 2 tool calls each producing non-fatal errors still costs 1 iteration count and adds 2 failed results to LLM context.
- For a restaurant request across a multi-stop itinerary, the LLM may call `search_places` for multiple stops per iteration, burning through 10 iterations rapidly.

#### RC4 — `successful_tool_calls` naming is misleading — it accumulates ALL non-required-param-error results
**File**: `backend/server/chat/views/__init__.py`, lines 476, 635
- The variable `successful_tool_calls` accumulates tool calls whose results are not `_is_required_param_tool_error`. This includes tool calls that returned geocoding failures, network errors, or `web_search` unavailability errors. These are appended to `current_messages` and persisted to DB, causing the LLM to see repeated failure payloads.

### Edit points and recommended fix approaches

#### EP1 — Add non-fatal tool error detection and short-circuit
**File**: `backend/server/chat/views/__init__.py`
**Symbol**: New static method `_is_nonfatal_tool_error(result)` + use in `event_stream()`
- Detect results that have `{"error": ..., "results": []}` (web_search style) or `{"error": "Could not geocode..."}` / `{"error": "Places API request failed..."}` (search_places failures).
- Recommended approach: check `result.get("error")` is non-empty AND the result is not a successful payload (no `results` data, no places data). If a tool returns an error result that is not a required-param error, log a warning, do NOT add to `successful_tool_calls`, and instead emit a summary to the LLM context as a tool message explaining the failure — then break the loop or emit a user-visible message after N consecutive non-fatal failures.

#### EP2 — Distinguish `web_search` persistent unavailability (ImportError) from retryable errors
**File**: `backend/server/chat/agent_tools.py`
**Symbol**: `web_search()` (lines 294–307)
- Currently ImportError (`duckduckgo-search` not installed) and rate-limit both return the same shape: `{"error": "...", "results": []}`.
- Recommended approach: add a sentinel field `"permanent": True` for ImportError, so the view layer can detect non-retryable failures and short-circuit immediately on the first iteration rather than retrying 10 times. Alternatively add a distinct error key like `"error_code": "unavailable"` vs `"error_code": "rate_limited"`.

#### EP3 — Add non-fatal tool error counting per-tool to break loops early
**File**: `backend/server/chat/views/__init__.py`
**Symbol**: `event_stream()` (line 424+)
- Track `consecutive_nonfatal_errors` per tool (or globally). After 2 consecutive failures of the same tool name, stop calling it for this turn and emit a user-facing message: "Search places could not be completed for this location."
- This prevents the 10-iteration burn for a single unreachable external API.

#### EP4 — Only increment `tool_iterations` when at least one tool call succeeds
**File**: `backend/server/chat/views/__init__.py`
**Symbol**: `event_stream()` line 475 (`tool_iterations += 1`)
- Move `tool_iterations += 1` to after the tool result loop, and only increment if `len(successful_tool_calls) > 0`. Failed-only iterations should not count toward the limit (or should count less). Alternatively, add a separate `failed_tool_iterations` counter with a lower limit (e.g. 3) specifically for all-failure iterations.

#### EP5 — `search_places` geocoding failure should surface earlier in retry logic
**File**: `backend/server/chat/views/__init__.py`
**Symbol**: `event_stream()` lines 522–565 (the `_is_search_places_missing_location_required_error` retry block)
- Current retry block only fires on `location is required`. Extend retry logic to also retry with fallback location when result contains `{"error": "Could not geocode location: ..."}` (Nominatim empty result) using the same `retry_locations` fallback list. This gives context-location a second chance when Nominatim fails on the first geocode.

### Files / symbols map

| File | Symbol | Role |
|------|--------|------|
| `backend/server/chat/views/__init__.py` | `MAX_TOOL_ITERATIONS = 10` (line 422) | Hard loop cap |
| `backend/server/chat/views/__init__.py` | `tool_iterations += 1` (line 475) | Iteration counter — always increments, even on all-failure iterations |
| `backend/server/chat/views/__init__.py` | `_is_required_param_tool_error()` (line 136) | Only detects missing-param errors; does NOT catch tool execution failures |
| `backend/server/chat/views/__init__.py` | `_is_search_places_missing_location_required_error()` (line 180) | Only triggers retry for `location is required`; geocoding/network failures bypass it |
| `backend/server/chat/views/__init__.py` | `successful_tool_calls` (line 476) | Misnamed — accumulates all non-required-param-error results including failures |
| `backend/server/chat/views/__init__.py` | `event_stream()` lines 480–660 | Full tool execution loop |
| `backend/server/chat/agent_tools.py` | `search_places()` (line 125) | Returns `{"error": "..."}` on geocode/network failure — not a required-param error |
| `backend/server/chat/agent_tools.py` | `web_search()` (line 257) | Returns `{"error": "...", "results": []}` on import/rate-limit/generic failure |
| `backend/server/chat/llm_client.py` | `stream_chat_completion()` (line 380) | No tool-level retry logic — passes through all tool results |
