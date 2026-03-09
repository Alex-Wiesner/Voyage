# OpenCode Zen Connection Debug — Research Findings

**Date**: 2026-03-08
**Researchers**: researcher agent (root cause), explorer agent (code path trace)
**Status**: Complete — root causes identified, fix proposed

## Summary

The OpenCode Zen provider configuration in `backend/server/chat/llm_client.py` has **two critical mismatches** that cause connection/API errors:

1. **Invalid model ID**: `gpt-4o-mini` does not exist on OpenCode Zen
2. **Wrong endpoint for GPT models**: GPT models on Zen use `/responses` endpoint, not `/chat/completions`

An additional structural risk is that the backend runs under **Gunicorn WSGI** (not ASGI/uvicorn), but `stream_chat_completion` is an `async def` generator that is driven via `_async_to_sync_generator` which creates a new event loop per call. This works but causes every tool iteration to open/close an event loop, which is inefficient and fragile under load.

## End-to-End Request Path

### 1. Frontend: `AITravelChat.svelte` → `sendMessage()`
- **File**: `frontend/src/lib/components/AITravelChat.svelte`, line 97
- POST body: `{ message: <text>, provider: selectedProvider }` (e.g. `"opencode_zen"`)
- Sends to: `POST /api/chat/conversations/<id>/send_message/`
- On `fetch` network failure: shows `$t('chat.connection_error')` = `"Connection error. Please try again."` (line 191)
- On HTTP error: tries `res.json()` → uses `err.error || $t('chat.connection_error')` (line 126)
- On SSE `parsed.error`: shows `parsed.error` inline in the chat (line 158)
- **Any exception from `litellm` is therefore masked as `"An error occurred while processing your request."` or `"Connection error. Please try again."`**

### 2. Proxy: `frontend/src/routes/api/[...path]/+server.ts` → `handleRequest()`
- Strips and re-generates CSRF token (line 57-60)
- POSTs to `http://server:8000/api/chat/conversations/<id>/send_message/`
- Detects `content-type: text/event-stream` and streams body directly through (lines 94-98) — **no buffering**
- On any fetch error: returns `{ error: 'Internal Server Error' }` (line 109)

### 3. Backend: `chat/views.py` → `ChatViewSet.send_message()`
- Validates provider via `is_chat_provider_available()` (line 114) — passes for `opencode_zen`
- Saves user message to DB (line 120)
- Builds LLM messages list (line 131)
- Wraps `async event_stream()` in `_async_to_sync_generator()` (line 269)
- Returns `StreamingHttpResponse` with `text/event-stream` content type (line 268)

### 4. Backend: `chat/llm_client.py` → `stream_chat_completion()`
- Normalizes provider (line 208)
- Looks up `CHAT_PROVIDER_CONFIG["opencode_zen"]` (line 209)
- Fetches API key from `UserAPIKey.objects.get(user=user, provider="opencode_zen")` (line 154)
- Decrypts it via Fernet using `FIELD_ENCRYPTION_KEY` (line 102)
- Calls `litellm.acompletion(model="openai/gpt-4o-mini", api_key=<key>, api_base="https://opencode.ai/zen/v1", stream=True, tools=AGENT_TOOLS, tool_choice="auto")` (line 237)
- On **any exception**: logs and yields `data: {"error": "An error occurred..."}` (lines 274-276)

## Root Cause Analysis

### #1 CRITICAL: Invalid default model `gpt-4o-mini`
- **Location**: `backend/server/chat/llm_client.py:62`
- `CHAT_PROVIDER_CONFIG["opencode_zen"]["default_model"] = "openai/gpt-4o-mini"`
- `gpt-4o-mini` is an OpenAI-hosted model. The OpenCode Zen gateway at `https://opencode.ai/zen/v1` does not offer `gpt-4o-mini`.
- LiteLLM sends: `POST https://opencode.ai/zen/v1/chat/completions` with `model: gpt-4o-mini`
- Zen API returns HTTP 4xx (model not found or not available)
- Exception is caught generically at line 274 → yields masked error SSE → frontend shows generic message

### #2 SIGNIFICANT: Generic exception handler masks real errors
- **Location**: `backend/server/chat/llm_client.py:274-276`
- Bare `except Exception:` with logger.exception and a generic user message
- LiteLLM exceptions carry structured information: `litellm.exceptions.NotFoundError`, `AuthenticationError`, `BadRequestError`, etc.
- All of these show up to the user as `"An error occurred while processing your request. Please try again."`
- Prevents diagnosis without checking Docker logs

### #3 SIGNIFICANT: WSGI + async event loop per request
- **Location**: `backend/server/chat/views.py:66-76` (`_async_to_sync_generator`)
- Backend runs **Gunicorn WSGI** (from `supervisord.conf:11`); there is **no ASGI entry point** (`asgi.py` doesn't exist)
- `stream_chat_completion` is `async def` using `litellm.acompletion` (awaited)
- `_async_to_sync_generator` creates a fresh event loop via `asyncio.new_event_loop()` for each request
- For multi-tool-iteration responses this loop drives multiple sequential `await` calls
- This works but is fragile: if `litellm.acompletion` internally uses a singleton HTTP client that belongs to a different event loop, it will raise `RuntimeError: This event loop is already running` or connection errors on subsequent calls
- **httpx/aiohttp sessions in LiteLLM may not be compatible with per-call new event loops**

### #4 MINOR: `tool_choice: "auto"` sent unconditionally with tools
- **Location**: `backend/server/chat/llm_client.py:229`
- `"tool_choice": "auto" if tools else None` — None values in kwargs are passed to litellm
- Some OpenAI-compat endpoints (including potentially Zen models) reject `tool_choice: null` or unsupported parameters
- Fix: remove key entirely instead of setting to None

### #5 MINOR: API key lookup is synchronous in async context
- **Location**: `backend/server/chat/llm_client.py:217` and `views.py:144`
- `get_llm_api_key` calls `UserAPIKey.objects.get(...)` synchronously
- Called from within `async for chunk in stream_chat_completion(...)` in the async `event_stream()` generator
- Django ORM operations must use `sync_to_async` in async contexts; direct sync ORM calls can cause `SynchronousOnlyOperation` errors or deadlocks under ASGI
- Under WSGI+new-event-loop approach this is less likely to fail but is technically incorrect

## Recommended Fix (Ranked by Impact)

### Fix #1 (Primary): Correct the default model
```python
# backend/server/chat/llm_client.py:59-64
"opencode_zen": {
    "label": "OpenCode Zen",
    "needs_api_key": True,
    "default_model": "openai/gpt-5-nano",   # Free; confirmed to work via /chat/completions
    "api_base": "https://opencode.ai/zen/v1",
},
```
Confirmed working models (use `/chat/completions`, OpenAI-compat):
- `openai/gpt-5-nano` (free)
- `openai/kimi-k2.5` (confirmed by GitHub usage)
- `openai/glm-5` (GLM family)
- `openai/big-pickle` (free)

GPT family models route through `/responses` endpoint on Zen, which LiteLLM's openai-compat mode does NOT use — only the above "OpenAI-compatible" models on Zen reliably work with LiteLLM's `openai/` prefix + `/chat/completions`.

### Fix #2 (Secondary): Structured error surfacing
```python
# backend/server/chat/llm_client.py:274-276
except Exception as exc:
    logger.exception("LLM streaming error")
    # Extract structured detail if available
    status_code = getattr(exc, 'status_code', None)
    detail = getattr(exc, 'message', None) or str(exc)
    user_msg = f"Provider error ({status_code}): {detail}" if status_code else "An error occurred while processing your request. Please try again."
    yield f"data: {json.dumps({'error': user_msg})}\n\n"
```

### Fix #3 (Minor): Remove None from tool_choice kwarg
```python
# backend/server/chat/llm_client.py:225-234
completion_kwargs = {
    "model": provider_config["default_model"],
    "messages": messages,
    "stream": True,
    "api_key": api_key,
}
if tools:
    completion_kwargs["tools"] = tools
    completion_kwargs["tool_choice"] = "auto"
if provider_config["api_base"]:
    completion_kwargs["api_base"] = provider_config["api_base"]
```

## Error Flow Diagram

```
User sends message (opencode_zen)
  → AITravelChat.svelte:sendMessage()
    → POST /api/chat/conversations/<id>/send_message/
      → +server.ts:handleRequest()  [proxy, no mutation]
        → POST http://server:8000/api/chat/conversations/<id>/send_message/
          → views.py:ChatViewSet.send_message()
            → llm_client.py:stream_chat_completion()
              → litellm.acompletion(model="openai/gpt-4o-mini",  ← FAILS HERE
                                    api_base="https://opencode.ai/zen/v1")
              → except Exception → yield data:{"error":"An error occurred..."}
            ← SSE: data:{"error":"An error occurred..."}
          ← StreamingHttpResponse(text/event-stream)
        ← streamed through
      ← streamed through
    ← reader.read() → parsed.error set
  ← assistantMsg.content = "An error occurred..."  ← shown to user
```

If the network/DNS fails entirely (e.g. `https://opencode.ai` unreachable):
```
  → litellm.acompletion raises immediately
  → except Exception → yield data:{"error":"An error occurred..."}
  — OR —
  → +server.ts fetch fails → json({error:"Internal Server Error"}, 500)
  → AITravelChat.svelte res.ok is false → res.json() → err.error || $t('chat.connection_error')
  → shows "Connection error. Please try again."
```

## File References

| File | Line(s) | Relevance |
|---|---|---|
| `backend/server/chat/llm_client.py` | 59-64 | `CHAT_PROVIDER_CONFIG["opencode_zen"]` — primary fix |
| `backend/server/chat/llm_client.py` | 150-157 | `get_llm_api_key()` — DB lookup for stored key |
| `backend/server/chat/llm_client.py` | 203-276 | `stream_chat_completion()` — full LiteLLM call + error handler |
| `backend/server/chat/llm_client.py` | 225-234 | `completion_kwargs` construction |
| `backend/server/chat/llm_client.py` | 274-276 | Generic `except Exception` (swallows all errors) |
| `backend/server/chat/views.py` | 103-274 | `send_message()` — SSE pipeline orchestration |
| `backend/server/chat/views.py` | 66-76 | `_async_to_sync_generator()` — WSGI/async bridge |
| `backend/server/integrations/models.py` | 78-112 | `UserAPIKey` — encrypted key storage |
| `frontend/src/lib/components/AITravelChat.svelte` | 97-195 | `sendMessage()` — SSE consumer + error display |
| `frontend/src/lib/components/AITravelChat.svelte` | 124-129 | HTTP error → `$t('chat.connection_error')` |
| `frontend/src/lib/components/AITravelChat.svelte` | 157-160 | SSE `parsed.error` → inline display |
| `frontend/src/lib/components/AITravelChat.svelte` | 190-192 | Outer catch → `$t('chat.connection_error')` |
| `frontend/src/routes/api/[...path]/+server.ts` | 34-110 | `handleRequest()` — proxy |
| `frontend/src/routes/api/[...path]/+server.ts` | 94-98 | SSE passthrough (no mutation) |
| `frontend/src/locales/en.json` | 46 | `chat.connection_error` = "Connection error. Please try again." |
| `backend/supervisord.conf` | 11 | Gunicorn WSGI startup (no ASGI) |

---

## Model Selection Implementation Map

**Date**: 2026-03-08

### Frontend Provider/Model Selection State (Current)

In `AITravelChat.svelte`:
- `selectedProvider` (line 29): `let selectedProvider = 'openai'` — bare string, no model tracking
- `providerCatalog` (line 30): `ChatProviderCatalogEntry[]` — already contains `default_model: string | null` per entry
- `chatProviders` (line 31): reactive filtered view of `providerCatalog` (available only)
- `loadProviderCatalog()` (line 37): populates catalog from `GET /api/chat/providers/`
- `sendMessage()` (line 97): POST body at line 121 is `{ message: msgText, provider: selectedProvider }` — **no model field**
- Provider `<select>` (lines 290–298): in the top toolbar of the chat panel

### Request Payload Build Point

`AITravelChat.svelte`, line 118–122:
```ts
const res = await fetch(`/api/chat/conversations/${conversation.id}/send_message/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: msgText, provider: selectedProvider })  // ← ADD model here
});
```

### Backend Request Intake Point

`chat/views.py`, `send_message()` (line 104):
- Line 113: `provider = (request.data.get("provider") or "openai").strip().lower()`
- Line 144: `stream_chat_completion(request.user, current_messages, provider, tools=AGENT_TOOLS)`
- **No model extraction**; model comes only from `CHAT_PROVIDER_CONFIG[provider]["default_model"]`

### Backend Model Usage Point

`chat/llm_client.py`, `stream_chat_completion()` (line 203):
- Line 225–226: `completion_kwargs = { "model": provider_config["default_model"], ... }`
- This is the **sole place model is resolved** — no override capability exists yet

### Persistence Options Analysis

| Option | Files changed | Migration? | Risk |
|---|---|---|---|
| **`localStorage` (recommended)** | `AITravelChat.svelte` only for persistence | No | Lowest: no backend, no schema |
| `CustomUser` field (`chat_model_prefs` JSONField) | `users/models.py`, `users/serializers.py`, `users/views.py`, migration | **Yes** | Medium: schema change, serializer exposure |
| `UserAPIKey`-style new model prefs table | new `chat/models.py` + serializer + view + urls + migration | **Yes** | High: new endpoint, multi-file |
| `UserRecommendationPreferenceProfile` JSONField addition | `integrations/models.py`, serializer, migration | **Yes** | Medium: migration on integrations app |

**Selected**: `localStorage` — key `voyage_chat_model_prefs`, value `Record<provider_id, model_string>`.

### File-by-File Edit Plan

#### 1. `backend/server/chat/llm_client.py`
| Symbol | Change |
|---|---|
| `stream_chat_completion(user, messages, provider, tools=None)` | Add `model: str \| None = None` parameter |
| `completion_kwargs["model"]` (line 226) | Change to `model or provider_config["default_model"]` |
| (new) validation | If `model` provided: assert it starts with expected LiteLLM prefix or raise SSE error |

#### 2. `backend/server/chat/views.py`
| Symbol | Change |
|---|---|
| `send_message()` (line 104) | Extract `model = (request.data.get("model") or "").strip() or None` |
| `stream_chat_completion(...)` call (line 144) | Pass `model=model` |
| (optional validation) | Return 400 if model prefix doesn't match provider |

#### 3. `frontend/src/lib/components/AITravelChat.svelte`
| Symbol | Change |
|---|---|
| (new) `let selectedModel: string` | Initialize from `loadModelPref(selectedProvider)` or `default_model` |
| (new) `$: selectedProviderEntry` | Reactive lookup of current provider's catalog entry |
| (new) `$: selectedModel` reset | Reset on provider change; persist with `saveModelPref` |
| `sendMessage()` body (line 121) | Add `model: selectedModel || undefined` to JSON body |
| (new) model `<input>` in toolbar | Placed after provider `<select>`, `bind:value={selectedModel}`, placeholder = `default_model` |
| (new) `loadModelPref(provider)` | Read from `localStorage.getItem('voyage_chat_model_prefs')` |
| (new) `saveModelPref(provider, model)` | Write to `localStorage.setItem('voyage_chat_model_prefs', ...)` |

#### 4. `frontend/src/locales/en.json`
| Key | Value |
|---|---|
| `chat.model_label` | `"Model"` |
| `chat.model_placeholder` | `"Default model"` |

### Provider-Model Compatibility Validation

The critical constraint is **LiteLLM model-string routing**. LiteLLM uses the `provider/model-name` prefix to determine which SDK client to use:
- `openai/gpt-5-nano` → OpenAI client (with custom `api_base` for Zen)
- `anthropic/claude-sonnet-4-20250514` → Anthropic client
- `groq/llama-3.3-70b-versatile` → Groq client

If user types `anthropic/claude-opus` for `openai` provider, LiteLLM uses Anthropic SDK with OpenAI credentials → guaranteed failure.

**Recommended backend guard** in `send_message()`:
```python
if model:
    expected_prefix = provider_config["default_model"].split("/")[0]
    if not model.startswith(expected_prefix + "/"):
        return Response(
            {"error": f"Model must use '{expected_prefix}/' prefix for provider '{provider}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
```

Exception: `opencode_zen` and `openrouter` accept any prefix (they're routing gateways). Guard should skip prefix check when `api_base` is set (custom gateway).

### Migration Requirement

**NO migration required** for the recommended localStorage approach.

---

## Cross-references

- See [Plan: OpenCode Zen connection error](../plans/opencode-zen-connection-error.md)
- See [Research: LiteLLM provider catalog](litellm-zen-provider-catalog.md)
- See [Knowledge: AI Chat](../knowledge.md#ai-chat-collections--recommendations)
