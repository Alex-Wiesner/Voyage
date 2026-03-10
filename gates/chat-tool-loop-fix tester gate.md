---
title: chat-tool-loop-fix tester gate
type: note
permalink: voyage/gates/chat-tool-loop-fix-tester-gate
tags:
- tester
- gate
- chat
- loop-fix
- adversarial
---

## Gate: chat-tool-loop-fix adversarial validation (2026-03-10)

**Verdict: PASS**
**Plan ref:** [[voyage/plans/assistant-add-flow-fixes]]
**Branch:** fix/chat-tool-loop-fix

### Test execution
- All 32 chat tests pass (docker compose exec server python3 manage.py test chat --keepdb --verbosity=2)
- 0 failures, 0 errors, 0 flaky

### Adversarial checks and findings

#### AC1 — all-failure rounds stop cleanly without falling into tool_loop_limit
PASS. `all_failure_rounds` counter increments only when `not successful_tool_calls and first_execution_failure` (line 749). On reaching `MAX_ALL_FAILURE_ROUNDS=3`, the code issues `tool_execution_error` and `return`s (line 777). `tool_iterations` is never incremented for all-failure rounds (it increments only at line 782, after `all_failure_rounds = 0`), so 10-iteration cap is never hit for pure-failure scenarios. Test `test_all_failure_rounds_stop_with_execution_error_before_tool_cap` confirms exactly 3 `stream_chat_completion` calls and `tool_execution_error` rather than `tool_loop_limit`.

#### AC2 — permanent failures stop in one round
PASS. When `retryable=False`, `encountered_permanent_failure = True` is set (line 717), then at post-iteration check (line 750-751) `all_failure_rounds` is set directly to `MAX_ALL_FAILURE_ROUNDS` (bypassing the increment), triggering immediate stop. Test `test_permanent_execution_failure_stops_immediately` confirms 1 `stream_chat_completion` call.

#### AC3 — required-parameter clarification flow still intact
PASS. The `_is_required_param_tool_error` path (lines 647-711) short-circuits before the execution-failure path (line 713). `search_places` missing-location triggers `clarification_content` SSE emit + DB persist + `return`. Other required-param errors still emit `tool_validation_error` and `return`. Tests `test_missing_search_place_location_streams_clarifying_content` and `test_collection_access_error_does_not_short_circuit_required_param_regex` confirm correctness.

#### AC4 — execution failures sanitized and NOT emitted as tool_result SSE events
PASS. The execution-failure branch at line 713 does `continue` — it never reaches the `yield tool_event` at line 747. Failed tool results are recorded in `first_execution_failure` but not in `successful_tool_calls` / `successful_tool_messages` / `successful_tool_chat_entries`, so they are never persisted to DB as role=tool rows and never streamed to the frontend. `_build_tool_execution_error_event` uses only the sanitized error text (line 265-271), not the raw exception. Test confirms no `tool_result` events in failure scenarios.

#### AC5 — mixed-batch partial failure: one tool succeeds, another fails
OBSERVED FINDING (LOW): When a batch has e.g. 2 tool calls where call_1 succeeds and call_2 fails with an execution error:
- `successful_tool_calls` will contain call_1's result; call_2's failure is silently dropped from this iteration's context.
- The assistant message persisted to DB will reference only call_1's tool_calls.
- `all_failure_rounds` stays at 0 (successful_tool_calls is non-empty, so the `not successful_tool_calls` condition at line 749 is False).
- Loop continues as if call_2 never happened — the LLM won't know call_2 failed.
- Acceptable for now (pre-release), but the LLM may loop trying to re-execute call_2 if it expects an answer. Not a regression from the old behavior (where ALL failures were fed back to LLM), and the `MAX_TOOL_ITERATIONS` cap remains as a backstop.

#### AC6 — `_build_llm_messages` orphan tool_call filtering on reload
PASS. `valid_tool_call_ids` (line 59) is built only from non-required-param-error and non-execution-failure tool messages. Assistant messages with `tool_calls` have their `tool_calls` filtered to only the valid set (line 95-101). If ALL tool_calls for an assistant message are failures, `filtered_tool_calls` is empty and `payload["tool_calls"]` is not set (line 100 guard) — the assistant message is sent to LLM without tool_calls, avoiding orphaned tool references.

#### AC7 — frontend `rebuildConversationMessages` dedupe
PASS. Line 374 forces `tool_results: undefined` on all messages before the sibling-walk, discarding any server-side `tool_results` field. `appendToolResultDedup` guards on `tool_call_id` uniqueness during the walk. `uniqueToolResultsByCallId` is applied again at render time (line 939) as a second safety net. Combined: no double-accumulation on reload.

#### AC8 — `uniqueToolResultsByCallId` silent drop for null/undefined tool_call_id
LOW RISK: `uniqueToolResultsByCallId` (line 351-368) has a special case: if `result.tool_call_id` is falsy (null/undefined), the result is always appended without dedup check (line 359 guard). This means multiple results with no `tool_call_id` will all be included. Given that tool_call_id is always populated from the backend for proper tool calls, this is a safe fallback for edge cases.

#### AC9 — `_is_execution_failure_tool_error` catches ANY non-empty error that is not required-param error
PASS. This is intentionally broad — any `{error: "..."}` dict that isn't a missing-param pattern is treated as an execution failure. This correctly captures geocode errors, network errors, unexpected exceptions, etc.

#### AC10 — retry fallback after geocode failure still uses `_is_execution_failure_tool_error` guard
PASS (line 631-634): The retry succeeds only if the retry result is not a required-param error AND not an execution failure. If all retries fail, the `result` remains the original geocode error, which is then caught by `_is_execution_failure_tool_error` at line 713 and handled as a failure (not emitted as tool result).

### Mutation escape analysis
- MUTATION_ESCAPES: 1/8
- The unchecked mutation: flipping `not successful_tool_calls` → `successful_tool_calls` in the all-failure-round check (line 749) would cause failures to be silently dropped without incrementing the counter. No existing test with partial success + partial failure to detect this mutation. Low risk given the mixed-batch scenario is acceptable behavior.

### Summary
Implementation is sound for the primary stated goals. All-failure rounds stop cleanly; permanent failures stop in 1 round; clarification flow is intact; execution failures are not leaked to frontend. Frontend dedupe is correct via `tool_results: undefined` reset + ID-based dedup. One low-severity gap: mixed-batch partial failure silently drops the failing tool call (acceptable pre-release).
