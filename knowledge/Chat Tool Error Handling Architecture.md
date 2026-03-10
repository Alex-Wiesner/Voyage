---
title: Chat Tool Error Handling Architecture
type: note
permalink: voyage/knowledge/chat-tool-error-handling-architecture
tags:
- chat
- tools
- error-handling
- architecture
- pattern
---

# Chat Tool Error Handling Architecture

## Overview

The chat agent tool loop classifies tool call outcomes into three distinct categories, each with different retry and surfacing behavior.

## Error Classification

### 1. Required-parameter validation errors
- [pattern] Detected by `_is_required_param_tool_error()` regex matching `"... is required"` patterns in tool result `error` field
- [convention] Short-circuited immediately with a user-visible error — never replayed into LLM history
- [pattern] `search_places` missing `location` has a special path: `_is_search_places_location_retry_candidate_error()` triggers deterministic context-retry (trip destination → first itinerary stop → user clarification) before surfacing

### 2. Execution failures (new in chat-tool-loop-fix)
- [pattern] Any `error`-bearing tool result dict that does NOT match the required-param pattern is classified as an execution failure by `_is_execution_failure_tool_error()`
- [convention] Execution failures are NEVER replayed into LLM context — they are excluded from `successful_tool_calls`, `successful_tool_messages`, and `successful_tool_chat_entries`
- [pattern] `tool_iterations` increments only after at least one successful tool call in a round
- [pattern] All-failure rounds (every tool in a round fails) increment `all_failure_rounds`, capped at `MAX_ALL_FAILURE_ROUNDS` (3)
- [pattern] Permanent failures (`retryable: false` in tool result, e.g. `web_search` ImportError) set `all_failure_rounds = MAX_ALL_FAILURE_ROUNDS` for immediate stop
- [convention] Execution failures emit a `tool_execution_error` SSE event with sanitized text via `_build_tool_execution_error_event()`

### 3. Geocoding failures in search_places
- [pattern] `Could not geocode location: ...` errors are detected by `_is_search_places_location_retry_candidate_error()` (same path as missing-location)
- [convention] Eligible for the existing context-retry fallback before being treated as a terminal failure

## Error Sanitization

- [convention] `_safe_error_payload()` maps LiteLLM exceptions to sanitized user-safe categories — never forwards raw `exc.message`
- [convention] `execute_tool()` catch-all returns `{"error": "Tool execution failed"}` (hardcoded) — never raw `str(exc)`
- [decision] The `_build_tool_execution_error_event()` wraps sanitized tool error text in a user-safe sentence for SSE emission and DB persistence

## Frontend Tool-Result Deduplication

- [pattern] Three-layer dedup by `tool_call_id`:
  1. `rebuildConversationMessages()` sets `tool_results: undefined` on all assistant messages, then re-derives exclusively from persisted `role=tool` sibling rows — discards any server-side pre-populated `tool_results`
  2. `appendToolResultDedup()` deduplicates during both rebuild walk and live SSE ingestion
  3. `uniqueToolResultsByCallId()` at render time provides a final safety net

## Key Files

- Backend classification/loop: `backend/server/chat/views/__init__.py`
- Tool execution + sanitization: `backend/server/chat/agent_tools.py`
- Frontend dedup: `frontend/src/lib/components/AITravelChat.svelte`
- Tests: `backend/server/chat/tests.py` (32 total chat tests)

## Relations
- related_to [[assistant-add-flow-fixes]]
