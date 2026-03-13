---
title: litellm-zen-provider-catalog
type: note
permalink: voyage/research/litellm-zen-provider-catalog
---

# Research: LiteLLM provider catalog and OpenCode Zen support

Date: 2026-03-08
Related plan: [AI travel agent in Collections Recommendations](../plans/ai-travel-agent-collections-integration.md)

## LiteLLM provider enumeration
- Runtime provider list is available via `litellm.provider_list` and currently returns 128 provider IDs in this environment.
- The enum source `LlmProviders` can be used for canonical provider identifiers.

## OpenCode Zen compatibility
- OpenCode Zen is **not** a native LiteLLM provider alias.
- Zen can be supported via LiteLLM's OpenAI-compatible routing using:
  - provider id in app: `opencode_zen`
  - model namespace: `openai/<zen-model>`
  - `api_base`: `https://opencode.ai/zen/v1`
- No new SDK dependency required.

## Recommended backend contract
- Add backend source-of-truth endpoint: `GET /api/chat/providers/`.
- Response fields:
  - `id`
  - `label`
  - `available_for_chat`
  - `needs_api_key`
  - `default_model`
  - `api_base`
- Return all LiteLLM runtime providers; mark non-mapped providers `available_for_chat=false` for display-only compliance.

## Data/storage compatibility notes
- Existing `UserAPIKey(provider)` model supports adding `opencode_zen` without migration.
- Consistent provider ID usage across serializer validation, key lookup, and chat request payload is required.

## Risks
- Zen model names may evolve; keep default model configurable in backend mapping.
- Full provider list is large; UI should communicate unavailable-for-chat providers clearly.