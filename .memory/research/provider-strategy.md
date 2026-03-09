# Research: Multi-Provider Strategy for Voyage AI Chat

**Date**: 2026-03-09
**Researcher**: researcher agent
**Status**: Complete

## Summary

Investigated how OpenCode, OpenClaw-like projects, and LiteLLM-based production systems handle multi-provider model discovery, auth, rate-limit resilience, and tool-calling compatibility. Assessed whether replacing LiteLLM is warranted for Voyage.

**Bottom line**: Keep LiteLLM, harden it. Replacing LiteLLM would be a multi-week migration with negligible user-facing benefit. LiteLLM already solves the hard problems (100+ provider SDKs, streaming, tool-call translation). Voyage's issues are in the **integration layer**, not in LiteLLM itself.

---

## 1. Pattern Analysis: How Projects Handle Multi-Provider

### 1a. Dynamic Model Discovery

| Project | Approach | Notes |
|---|---|---|
| **OpenCode** | Static registry from `models.dev` (JSON database), merged with user config, filtered by env/auth presence | No runtime API calls to providers for discovery; curated model metadata (capabilities, cost, limits) baked in |
| **Ragflow** | Hardcoded `SupportedLiteLLMProvider` enum + per-provider model lists | Similar to Voyage's current approach |
| **daily_stock_analysis** | `litellm.Router` model_list config + `fallback_models` list from config file | Runtime fallback, not runtime discovery |
| **Onyx** | `LLMProvider` DB model + admin UI for model configuration | DB-backed, admin-managed |
| **LiteLLM Proxy** | YAML config `model_list` with deployment-level params | Static config, hot-reloadable |
| **Voyage (current)** | `CHAT_PROVIDER_CONFIG` dict + hardcoded `models()` per provider + OpenAI API `client.models.list()` for OpenAI only | Mixed: one provider does live discovery, rest are hardcoded |

**Key insight**: No production project does universal runtime model discovery across all providers. OpenCode — the most sophisticated — uses a curated static database (`models.dev`) with provider/model metadata including capability flags (`toolcall`, `reasoning`, `streaming`). This is the right pattern for Voyage.

### 1b. Provider Auth Handling

| Project | Approach |
|---|---|
| **OpenCode** | Multi-source: env vars → `Auth.get()` (stored credentials) → config file → plugin loaders; per-provider custom auth (AWS chains, Google ADC, OAuth) |
| **LiteLLM Router** | `api_key` per deployment in model_list; env var fallback |
| **Cognee** | Rate limiter context manager wrapping LiteLLM calls |
| **Voyage (current)** | Per-user encrypted `UserAPIKey` DB model + instance-level `VOYAGE_AI_API_KEY` env fallback; key fetched per-request |

**Voyage's approach is sound.** Per-user DB-stored keys with instance fallback matches the self-hosted deployment model. No change needed.

### 1c. Rate-Limit Fallback / Retry

| Project | Approach |
|---|---|
| **LiteLLM Router** | Built-in: `num_retries`, `fallbacks` (cross-model), `allowed_fails` + `cooldown_time`, `RetryPolicy` (per-exception-type retry counts), `AllowedFailsPolicy` |
| **daily_stock_analysis** | `litellm.Router` with `fallback_models` list + multi-key support (rotate API keys on rate limit) |
| **Cognee** | `tenacity` retry decorator with `wait_exponential_jitter` + LiteLLM rate limiter |
| **Suna** | LiteLLM exception mapping → structured error processor |
| **Voyage (current)** | Zero retries. Single attempt. `_safe_error_payload()` maps exceptions to user messages but does not retry. |

**This is Voyage's biggest gap.** Every other production system has retry logic. LiteLLM has this built in — Voyage just isn't using it.

### 1d. Tool-Calling Compatibility

| Project | Approach |
|---|---|
| **OpenCode** | `capabilities.toolcall` boolean per model in `models.dev` database; models without tool support are filtered from agentic use |
| **LiteLLM** | `litellm.supports_function_calling(model=)` runtime check; `get_supported_openai_params(model=)` for param filtering |
| **PraisonAI** | `litellm.supports_function_calling()` guard before tool dispatch |
| **open-interpreter** | Same `litellm.supports_function_calling()` guard |
| **Voyage (current)** | No tool-call capability check. `AGENT_TOOLS` always passed. Reasoning models excluded from `opencode_zen` list by critic gate (manual). |

**Actionable gap.** `litellm.supports_function_calling(model=)` exists and should be used before passing `tools` kwarg.

---

## 2. Architecture Options Comparison

| Option | Description | Effort | Risk | Benefit |
|---|---|---|---|---|
| **A. Keep LiteLLM, harden** | Add Router for retry/fallback, add `supports_function_calling` guard, curate model lists with capability metadata | **Low** (1-2 sessions) | **Low** — incremental changes to existing working code | Retry resilience, tool-call safety, zero migration |
| **B. Hybrid: direct SDK for some** | Use `@ai-sdk/*` packages (like OpenCode) for primary providers, LiteLLM for others | **High** (1-2 weeks) | **High** — new TS→Python SDK mismatch, dual streaming paths, test surface explosion | Finer control per provider; no real benefit for Django backend |
| **C. Replace LiteLLM entirely** | Build custom provider abstraction or adopt Vercel AI SDK (TypeScript-only) | **Very High** (3-4 weeks) | **Very High** — rewrite streaming, tool-call translation, error mapping for each provider | Only makes sense if moving to full-stack TypeScript |
| **D. LiteLLM Proxy (sidecar)** | Run LiteLLM as a separate proxy service, call it via OpenAI-compatible API | **Medium** (2-3 days) | **Medium** — new Docker service, config management, latency overhead | Centralized config, built-in admin UI, but overkill for single-user self-hosted |

---

## 3. Recommendation

### Immediate (this session / next session): Option A — Harden LiteLLM

**Specific code-level adaptations:**

#### 3a. Add `litellm.Router` for retry + fallback (highest impact)

Replace bare `litellm.acompletion()` with `litellm.Router.acompletion()`:

```python
# llm_client.py — new module-level router
import litellm
from litellm.router import RetryPolicy

_router = None

def _get_router():
    global _router
    if _router is None:
        _router = litellm.Router(
            model_list=[],  # empty — we use router for retry/timeout only
            num_retries=2,
            timeout=60,
            retry_policy=RetryPolicy(
                AuthenticationErrorRetries=0,
                RateLimitErrorRetries=2,
                TimeoutErrorRetries=1,
                BadRequestErrorRetries=0,
            ),
        )
    return _router
```

**However**: LiteLLM Router requires models pre-registered in `model_list`. For Voyage's dynamic per-user-key model, the simpler approach is:

```python
# In stream_chat_completion, add retry params to acompletion:
response = await litellm.acompletion(
    **completion_kwargs,
    num_retries=2,
    request_timeout=60,
)
```

LiteLLM's `acompletion()` accepts `num_retries` directly — no Router needed.

**Files**: `backend/server/chat/llm_client.py` line 418 (add `num_retries=2, request_timeout=60`)

#### 3b. Add tool-call capability guard

```python
# In stream_chat_completion, before building completion_kwargs:
effective_model = model or provider_config["default_model"]
if tools and not litellm.supports_function_calling(model=effective_model):
    # Strip tools — model doesn't support them
    tools = None
    logger.warning("Model %s does not support function calling; tools stripped", effective_model)
```

**Files**: `backend/server/chat/llm_client.py` around line 397

#### 3c. Curate model lists with tool-call metadata in `models()` endpoint

Instead of returning bare string lists, return objects with capability info:

```python
# In ChatProviderCatalogViewSet.models():
if provider in ["opencode_zen"]:
    return Response({"models": [
        {"id": "openai/gpt-5-nano", "supports_tools": True},
        {"id": "openai/gpt-4o-mini", "supports_tools": True},
        {"id": "openai/gpt-4o", "supports_tools": True},
        {"id": "anthropic/claude-sonnet-4-20250514", "supports_tools": True},
        {"id": "anthropic/claude-3-5-haiku-20241022", "supports_tools": True},
    ]})
```

**Files**: `backend/server/chat/views/__init__.py` — `models()` action. Frontend `loadModelsForProvider()` would need minor update to handle objects.

#### 3d. Fix `day_suggestions.py` hardcoded model

Line 194 uses `model="gpt-4o-mini"` — doesn't respect provider config or user selection:

```python
# day_suggestions.py line 193-194
response = litellm.completion(
    model="gpt-4o-mini",  # BUG: ignores provider config
```

Should use provider_config default or user-selected model.

**Files**: `backend/server/chat/views/day_suggestions.py` line 194

### Long-term (future sessions)

1. **Adopt `models.dev`-style curated database**: OpenCode's approach of maintaining a JSON/YAML model registry with capabilities, costs, and limits is superior to hardcoded lists. Could be a YAML file in `backend/server/chat/models.yaml` loaded at startup.

2. **LiteLLM Proxy sidecar**: If Voyage gains multi-user production deployment, running LiteLLM as a proxy sidecar gives centralized rate limiting, key management, and an admin dashboard. Not warranted for current self-hosted single/few-user deployment.

3. **WSGI→ASGI migration**: Already documented as out-of-scope, but remains the long-term fix for event loop fragility (see [opencode-zen-connection-debug.md](opencode-zen-connection-debug.md#3-significant-wsgi--async-event-loop-per-request)).

---

## 4. Why NOT Replace LiteLLM

| Concern | Reality |
|---|---|
| "LiteLLM is too heavy" | It's a pip dependency (~40MB installed). No runtime sidecar. Same weight as Django itself. |
| "We could use provider SDKs directly" | Each provider has different streaming formats, tool-call schemas, and error types. LiteLLM normalizes all of this. Reimplementing costs weeks per provider. |
| "OpenCode doesn't use LiteLLM" | OpenCode is TypeScript + Vercel AI SDK. It has ~20 bundled `@ai-sdk/*` provider packages. The Python equivalent IS LiteLLM. |
| "LiteLLM has bugs" | All Voyage's issues are in our integration layer (no retries, no capability checks, hardcoded models), not in LiteLLM itself. |

---

## Cross-references

- See [Research: LiteLLM provider catalog](litellm-zen-provider-catalog.md)
- See [Research: OpenCode Zen connection debug](opencode-zen-connection-debug.md)
- See [Plan: Travel agent context + models](../plans/travel-agent-context-and-models.md)
- See [Decisions: Critic Gate](../decisions.md#critic-gate-travel-agent-context--models-follow-up)
