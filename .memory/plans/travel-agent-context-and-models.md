---
title: travel-agent-context-and-models
type: note
permalink: voyage/plans/travel-agent-context-and-models
---

# Plan: Travel Agent Context + Models Follow-up

## Scope
Address three follow-up issues in collection-level AI Travel Assistant:
1. Provider model dropdown only shows one option.
2. Chat context appears location-centric instead of full-trip/collection-centric.
3. Suggested prompts still assume a single location instead of itinerary-wide planning.

## Tasks
- [x] **F1 — Expand model options for OpenCode Zen provider**
  - **Acceptance criteria**:
    - Model dropdown offers multiple valid options for `opencode_zen` (not just one hardcoded value).
    - Options are sourced in a maintainable way (backend-side).
    - Selecting an option is sent through existing `model` override path.
  - **Agent**: explorer → coder → reviewer → tester
  - **Dependencies**: discovery of current `/api/chat/providers/{id}/models/` behavior.
  - **Workstream**: `main` (follow-up bugfix set)
  - **Implementation note (2026-03-09)**: Updated `ChatProviderCatalogViewSet.models()` in `backend/server/chat/views/__init__.py` to return a curated multi-model list for `opencode_zen` (OpenAI + Anthropic options), excluding `openai/o1-preview` and `openai/o1-mini` per critic guardrail.

- [x] **F2 — Correct chat context to reflect full trip/collection**
  - **Acceptance criteria**:
    - Assistant guidance/prompt context emphasizes full collection itinerary and date window.
    - Tool calls for planning are grounded in trip-level context (not only one location label).
    - No regression in existing collection-context fields.
  - **Agent**: explorer → coder → reviewer → tester
  - **Dependencies**: discovery of system prompt + tool context assembly.
  - **Workstream**: `main`
  - **Implementation note (2026-03-09)**: Updated frontend `deriveCollectionDestination()` to summarize unique itinerary stops (city/country-first with fallback names, compact cap), enriched backend `send_message()` trip context with collection-derived multi-stop itinerary data from `collection.locations`, and added explicit system prompt guidance to treat collection chats as trip-level and call `get_trip_details` before location search when additional context is needed.

- [x] **F3 — Make suggested prompts itinerary-centric**
  - **Acceptance criteria**:
    - Quick-action prompts no longer require/assume a single destination.
    - Prompts read naturally for multi-city/multi-country collections.
  - **Agent**: explorer → coder → reviewer → tester
  - **Dependencies**: discovery of prompt rendering logic in `AITravelChat.svelte`.
  - **Workstream**: `main`
  - **Implementation note (2026-03-09)**: Updated `AITravelChat.svelte` quick-action guard to use `collectionName || destination` context and itinerary-focused wording for Restaurants/Activities prompts; fixed `search_places` tool result parsing by changing `.places` reads to backend-aligned `.results` in both `hasPlaceResults()` and `getPlaceResults()`, restoring place-card rendering and Add-to-Itinerary actions.

## Notes
- User-provided trace in `agent-interaction.txt` indicates location-heavy responses and a `{"error":"location is required"}` tool failure during itinerary add flow.

---

## Discovery Findings

### F1 — Model dropdown shows only one option

**Root cause**: `backend/server/chat/views/__init__.py` lines 417–418, `ChatProviderCatalogViewSet.models()`:
```python
if provider in ["opencode_zen"]:
    return Response({"models": ["openai/gpt-5-nano"]})
```
The `opencode_zen` branch returns a single-element list. All other non-matched providers fall to `return Response({"models": []})` (line 420).

**Frontend loading path** (`AITravelChat.svelte` lines 115–142, `loadModelsForProvider()`):
- `GET /api/chat/providers/{provider}/models/` → sets `availableModels = data.models`.
- When the list has exactly one item, the dropdown shows only that item (correct DaisyUI `<select>`, lines 599–613).
- `availableModels.length === 0` → shows a single "Default" option (line 607), so both the zero-model and one-model paths surface as a one-option dropdown.

**Also**: The `models` endpoint (line 339–426) requires an API key and returns HTTP 403 if absent; the frontend silently sets `availableModels = []` on any non-OK response (line 136–138) — so users without a key see "Default" only, regardless of provider.

**Edit point**:
- `backend/server/chat/views/__init__.py` lines 417–418: expand `opencode_zen` model list to include Zen-compatible models (e.g., `openai/gpt-5-nano`, `openai/gpt-4o-mini`, `openai/gpt-4o`, `anthropic/claude-3-5-haiku-20241022`).
- Optionally: `AITravelChat.svelte` `loadModelsForProvider()` — handle non-OK response more gracefully (log distinct error instead of silent fallback to empty).

---

### F2 — Context appears location-centric, not trip-centric

**Root cause — `destination` prop is a single derived location string**:

`frontend/src/routes/collections/[id]/+page.svelte` lines 259–278, `deriveCollectionDestination()`:
```ts
const firstLocation = current.locations.find(...)
return `${cityName}, ${countryName}` // first location only
```
Only the **first** location in `collection.locations` is used. Multi-city trips surface a single city/country string.

**How it propagates** (`+page.svelte` lines 1287–1294):
```svelte
<AITravelChat
  destination={collectionDestination}   // ← single-location string
  ...
/>
```

**Backend trip context** (`backend/server/chat/views/__init__.py` lines 144–168, `send_message`):
```python
context_parts = []
if collection_name:  context_parts.append(f"Trip: {collection_name}")
if destination:      context_parts.append(f"Destination: {destination}")  # ← single string
if start_date and end_date: context_parts.append(f"Dates: ...")
system_prompt += "\n\n## Trip Context\n" + "\n".join(context_parts)
```
The `Destination:` line is a single string from the frontend — no multi-stop awareness. The `collection` object IS fetched from DB (lines 152–164) and passed to `get_system_prompt(user, collection)`, but `get_system_prompt` (`llm_client.py` lines 310–358) only uses `collection` to decide single-user vs. party preferences — it never reads collection locations, itinerary, or dates from the collection model itself.

**Edit points**:
1. `frontend/src/routes/collections/[id]/+page.svelte` `deriveCollectionDestination()` (lines 259–278): Change to derive a multi-location string (e.g., comma-joined list of unique city/country pairs, capped at 4–5) rather than first-only. Or rename to make clear it's itinerary-wide and return `undefined` when collection has many diverse destinations.
2. `backend/server/chat/views/__init__.py` `send_message()` (lines 144–168): Since `collection` is already fetched, enrich `context_parts` directly from `collection.locations` (unique cities/countries) rather than relying solely on the single-string `destination` param.
3. Optionally, `backend/server/chat/llm_client.py` `get_system_prompt()` (lines 310–358): When `collection` is not None, add a collection-derived section to the base prompt listing all itinerary destinations and dates from the collection object.

---

### F3 — Quick-action prompts assume a single destination

**Root cause — all destination-dependent prompts are gated on `destination` prop** (`AITravelChat.svelte` lines 766–804):
```svelte
{#if destination}
  <button>🍽️ Restaurants in {destination}</button>
  <button>🎯 Activities in {destination}</button>
{/if}
{#if startDate && endDate}
  <button>🎒 Packing tips for {startDate} to {endDate}</button>
{/if}
<button>📅 Itinerary help</button>   ← always shown, generic
```

The "Restaurants" and "Activities" buttons are hidden when no `destination` is derived (multi-city trip with no single dominant location), and their prompt strings hard-code `${destination}` — a single-city reference. They also don't reference the collection name or multi-stop nature.

**Edit points** (`AITravelChat.svelte` lines 766–804):
1. Replace `{#if destination}` guard for restaurant/activity buttons with a `{#if collectionName || destination}` guard.
2. Change prompt strings to use `collectionName` as primary context, falling back to `destination`:
   - `What are the best restaurants for my trip to ${collectionName || destination}?`
   - `What activities are there across my ${collectionName} itinerary?`
3. Add a "Budget" or "Transport" quick action that references the collection dates + itinerary scope (doesn't need `destination`).
4. The "📅 Itinerary help" button (line 797–804) sends `'Can you help me plan a day-by-day itinerary for this trip?'` — already collection-neutral; no change needed.
5. Packing tip prompt (lines 788–795) already uses `startDate`/`endDate` without `destination` — this one is already correct.

---

### Cross-cutting risk: `destination` prop semantics are overloaded

The `destination` prop in `AITravelChat.svelte` is used for:
- Header subtitle display (line 582: removed in current code — subtitle block gone)
- Quick-action prompt strings (lines 771, 779)
- `send_message` payload (line 268: `destination`)

Changing `deriveCollectionDestination()` to return a multi-location string affects all three uses. The header display is currently suppressed (no `{destination}` in the HTML header block after WS4-F4 changes), so that's safe. The `send_message` backend receives it as the `Destination:` context line, which is acceptable for a multi-city string.

### No regression surface from `loadModelsForProvider` reactive trigger

The `$: if (selectedProvider) { void loadModelsForProvider(); }` reactive statement (line 190–192) fires whenever `selectedProvider` changes. Expanding the `opencode_zen` model list won't affect other providers. The `loadModelPref`/`saveModelPref` localStorage path is independent of model list size.

### `add_to_itinerary` tool `location` required error (from Notes)

`search_places` tool (`agent_tools.py`) requires a `location` string param. When the LLM calls it with no location (because context only mentions a trip name, not a geocodable string), the tool returns `{"error": "location is required"}`. This is downstream of F2 — fixing the context so the LLM receives actual geocodable location strings will reduce these errors, but the tool itself should also be documented as requiring a geocodable string.

---

## Deep-Dive Findings (explorer pass 2 — 2026-03-09)

### F1: Exact line for single-model fix

`backend/server/chat/views/__init__.py` **lines 417–418**:
```python
if provider in ["opencode_zen"]:
    return Response({"models": ["openai/gpt-5-nano"]})
```
Single-entry hard-coded list. No Zen API call is made. Expand to all Zen-compatible models.

**Recommended minimal list** (OpenAI-compatible pass-through documented for Zen):
```python
return Response({"models": [
    "openai/gpt-5-nano",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "openai/o1-preview",
    "openai/o1-mini",
    "anthropic/claude-sonnet-4-20250514",
    "anthropic/claude-3-5-haiku-20241022",
]})
```

---

### F2: System prompt never injects collection locations into context

`backend/server/chat/views/__init__.py` lines **144–168** (`send_message`): `collection` is fetched from DB but only passed to `get_system_prompt()` for preference aggregation — its `.locations` queryset is never read to enrich context.

`backend/server/chat/llm_client.py` lines **310–358** (`get_system_prompt`): `collection` param only used for `shared_with` preference branch. Zero use of `collection.locations`, `.start_date`, `.end_date`, or `.itinerary_items`.

**Minimal fix — inject into context_parts in `send_message`**:
After line 164 (`collection = requested_collection`), add:
```python
if collection:
    loc_names = list(collection.locations.values_list("name", flat=True)[:8])
    if loc_names:
        context_parts.append(f"Locations in this trip: {', '.join(loc_names)}")
```
Also strengthen the base system prompt in `llm_client.py` to instruct the model to call `get_trip_details` when operating in collection context before calling `search_places`.

---

### F3a: Frontend `hasPlaceResults` / `getPlaceResults` use wrong key `.places` — cards never render

**Critical bug** — `AITravelChat.svelte`:
- **Line 377**: checks `(result.result as { places?: unknown[] }).places` — should be `results`
- **Line 386**: returns `(result.result as { places: any[] }).places` — should be `results`

Backend `search_places` (`agent_tools.py` line 188–192) returns:
```python
return {"location": location_name, "category": category, "results": results}
```
The key is `results`, not `places`. Because `hasPlaceResults` always returns `false`, the "Add to Itinerary" button on place cards is **never rendered** for any real tool output. The `<pre>` JSON fallback block shows instead.

**Minimal fix**: change both `.places` references → `.results` in `AITravelChat.svelte` lines 377 and 386.

---

### F3b: `{"error": "location is required"}` origin

`backend/server/chat/agent_tools.py` **line 128**:
```python
if not location_name:
    return {"error": "location is required"}
```
Triggered when LLM calls `search_places({})` with no `location` argument — which happens when the system prompt only contains a non-geocodable trip name (e.g., `Destination: Rome Trip 2025`) without actual city/place strings.

This error surfaces in the SSE stream → rendered as a tool result card with `{"error": "..."}` text.

**Fix**: Resolved by F2 (richer context); also improve guard message to be user-safe: `"Please provide a location or city name to search near."`.

---

### Summary of edit points

| Issue | File | Lines | Change |
|---|---|---|---|
| F1: expand opencode_zen models | `backend/server/chat/views/__init__.py` | 417–418 | Replace 1-item list with 7-item list |
| F2: inject collection locations | `backend/server/chat/views/__init__.py` | 144–168 | Add `loc_names` context_parts after line 164 |
| F2: reinforce system prompt | `backend/server/chat/llm_client.py` | 314–332 | Add guidance to use `get_trip_details` in collection context |
| F3a: fix `.places` → `.results` | `frontend/src/lib/components/AITravelChat.svelte` | 377, 386 | Two-char key rename |
| F3b: improve error guard | `backend/server/chat/agent_tools.py` | 128 | Better user-safe message (optional) |

---

## Critic Gate

- **Verdict**: APPROVED
- **Date**: 2026-03-09
- **Reviewer**: critic agent

### Assumption Challenges

1. **F2 `values_list("name")` may not produce geocodable strings** — `Location.name` can be opaque (e.g., "Eiffel Tower"). Mitigated: plan already proposes system prompt guidance to call `get_trip_details` first. Enhancement: use `city__name`/`country__name` in addition to `name` for the injected context.
2. **F3a `.places` vs `.results` key mismatch** — confirmed real bug. `agent_tools.py` returns `results` key; frontend checks `places`. Place cards never render. Two-char fix validated.

### Execution Guardrails

1. **Sequencing**: F1 (independent) → F2 (context enrichment) → F3 (prompts + `.places` fix). F3 depends on F2's `deriveCollectionDestination` changes.
2. **F1 model list**: Exclude `openai/o1-preview` and `openai/o1-mini` — reasoning models may not support tool-use in streaming chat. Verify compatibility before including.
3. **F2 context injection**: Use `select_related('city', 'country')` or `values_list('name', 'city__name', 'country__name')` — bare `name` alone is insufficient for geocoding context.
4. **F3a is atomic**: The `.places`→`.results` fix is a standalone bug, separate from prompt wording changes. Can bundle in F3's review cycle.
5. **Quality pipeline**: Each fix gets reviewer + tester pass. No batch validation.
6. **Functional verification required**: (a) model dropdown shows multiple options, (b) chat context includes multi-city info, (c) quick-action prompts render for multi-location collections, (d) search result place cards actually render (F3a).
7. **Decomposition**: Single workstream appropriate — tightly coupled bugfixes in same component/view pair, not independent services.

---

## F1 Review

- **Verdict**: APPROVED (score 0)
- **Lens**: Correctness
- **Date**: 2026-03-09
- **Reviewer**: reviewer agent

**Scope**: `backend/server/chat/views/__init__.py` lines 417–428 — `opencode_zen` model list expanded from 1 to 5 entries.

**Findings**: No CRITICAL or WARNING issues. Change is minimal and correctly scoped.

**Verified**:
- Critic guardrail followed: `o1-preview` and `o1-mini` excluded (reasoning models, no streaming tool-use).
- All 5 model IDs use valid LiteLLM `provider/model` format; `anthropic/*` IDs match exact entries in Anthropic branch.
- `_is_model_override_compatible()` bypasses prefix check for `api_base` gateways — all IDs pass validation.
- No regression in other provider branches (openai, anthropic, gemini, groq, ollama) — all untouched.
- Frontend `loadModelsForProvider()` handles multi-item arrays correctly; dropdown will show all 5 options.
- localStorage model persistence unaffected by list size change.

**Suggestion**: Add inline comment on why o1-preview/o1-mini are excluded to prevent future re-addition.

**Reference**: See [Critic Gate](#critic-gate), [decisions.md](../decisions.md#critic-gate-travel-agent-context--models-follow-up)

---

## F1 Test

- **Verdict**: PASS (Standard + Adversarial)
- **Date**: 2026-03-09
- **Tester**: tester agent

### Commands run

| # | Command | Exit code | Output |
|---|---|---|---|
| 1 | `docker compose exec server python3 -m py_compile /code/chat/views/__init__.py` | 0 | (no output — syntax OK) |
| 2 | Inline `python3 -c` assertion of `opencode_zen` branch | 0 | count: 5, all 5 model IDs confirmed present, PASS |
| 3 | Adversarial: branch isolation for 8 non-`opencode_zen` providers | 0 | All return `[]`, ADVERSARIAL PASS |
| 4 | Adversarial: critic guardrail + LiteLLM format check | 0 | `o1-preview` / `o1-mini` absent; all IDs in `provider/model` format, PASS |
| 5 | `docker compose exec server python3 -c "import chat.views; ..."` | 0 | Module import OK, `ChatProviderCatalogViewSet.models` action present |
| 6 | `docker compose exec server python3 manage.py test --verbosity=1 --keepdb` | 1 (pre-existing) | 30 tests: 24 pass, 1 fail, 5 errors — identical to known baseline (2 user email key + 4 geocoding mock). **Zero new failures.** |

### Key findings

- `opencode_zen` branch now returns exactly 5 models: `openai/gpt-5-nano`, `openai/gpt-4o-mini`, `openai/gpt-4o`, `anthropic/claude-sonnet-4-20250514`, `anthropic/claude-3-5-haiku-20241022`.
- Critic guardrail respected: `openai/o1-preview` and `openai/o1-mini` absent from list.
- All model IDs use valid `provider/model` format compatible with LiteLLM routing.
- No other provider branches affected.
- No regression in full Django test suite beyond pre-existing baseline.

### Adversarial attempts

- **Case insensitive match (`OPENCODE_ZEN`)**: does not match branch → returns `[]` (correct; exact case match required).
- **Partial match (`opencode_zen_extra`)**: does not match → returns `[]` (correct; no prefix leakage).
- **Empty string provider `""`**: returns `[]` (correct).
- **`openai/o1-preview` inclusion check**: absent from list (critic guardrail upheld).
- **`openai/o1-mini` inclusion check**: absent from list (critic guardrail upheld).

### MUTATION_ESCAPES: 0/4

All critical branch mutations checked: wrong provider name, case variation, extra-suffix variation, empty string — all correctly return `[]`. The 5-model list is hard-coded so count drift would be immediately caught by assertion.

### LESSON_CHECKS

- Pre-existing test failures (2 user + 4 geocoding) — **confirmed**, baseline unchanged.

---

## F2 Review

- **Verdict**: APPROVED (score 0)
- **Lens**: Correctness
- **Date**: 2026-03-09
- **Reviewer**: reviewer agent

**Scope**: F2 — Correct chat context to reflect full trip/collection. Three files changed:
- `frontend/src/routes/collections/[id]/+page.svelte` (lines 259–300): `deriveCollectionDestination()` rewritten from first-location-only to multi-stop itinerary summary.
- `backend/server/chat/views/__init__.py` (lines 166–199): `send_message()` enriched with collection-derived `Itinerary stops:` context from `collection.locations`.
- `backend/server/chat/llm_client.py` (lines 333–336): System prompt updated with trip-level reasoning guidance and `get_trip_details`-first instruction.

**Acceptance criteria verified**:
1. ✅ Frontend derives multi-stop destination string (unique city/country pairs, capped at 4, semicolon-joined, `+N more` overflow).
2. ✅ Backend enriches system prompt with `Itinerary stops:` from collection locations (up to 8, `select_related('city', 'country')` for efficiency).
3. ✅ System prompt instructs trip-level reasoning and `get_trip_details`-first behavior (tool confirmed to exist in `agent_tools.py`).
4. ✅ No regression: non-collection chats, single-location collections, and empty-location collections all handled correctly via guard conditions.

**Findings**: No CRITICAL or WARNING issues. Two minor suggestions (dead guard on line 274 of `+page.svelte`; undocumented cap constant in `views/__init__.py` line 195).

**Prior guidance**: Critic gate recommendation to use `select_related('city', 'country')` and city/country names — confirmed followed.

**Reference**: See [Critic Gate](#critic-gate), [F1 Review](#f1-review)

---

## F2 Test

- **Verdict**: PASS (Standard + Adversarial)
- **Date**: 2026-03-09
- **Tester**: tester agent

### Commands run

| # | Command | Exit code | Output summary |
|---|---|---|---|
| 1 | `bun run check` (frontend) | 0 | 0 errors, 6 warnings — all 6 are pre-existing in `CollectionRecommendationView.svelte` + `RegionCard.svelte`; no new issues from F2 changes |
| 2 | `docker compose exec server python3 -m py_compile /code/chat/views/__init__.py` | 0 | Syntax OK |
| 3 | `docker compose exec server python3 -m py_compile /code/chat/llm_client.py` | 0 | Syntax OK |
| 4 | Backend functional enrichment test (mock collection, 6 inputs → 5 unique stops) | 0 | `Itinerary stops: Rome, Italy; Florence, Italy; Venice, Italy; Switzerland; Eiffel Tower` — multi-stop line confirmed |
| 5 | Adversarial backend: 7 cases (cap-8, empty, all-blank, whitespace, unicode, dedup-12, None city) | 0 | All 7 PASS |
| 6 | Frontend JS adversarial: 7 cases (multi-stop, single, null, empty, overflow +N, fallback, all-blank) | 0 | All 7 PASS |
| 7 | System prompt phrase check | 0 | `itinerary-wide` + `get_trip_details` + `Treat context as itinerary-wide` all confirmed present |
| 8 | `docker compose exec server python3 manage.py test --verbosity=1 --keepdb` | 1 (pre-existing) | 30 tests: 24 pass, 1 fail, 5 errors — **identical to known baseline**; zero new failures |

### Acceptance criteria verdict

| Criterion | Result | Evidence |
|---|---|---|
| Multi-stop destination string derived in frontend | ✅ PASS | JS test: 3-city collection → `Rome, Italy; Florence, Italy; Venice, Italy`; 6-city → `A, X; B, X; C, X; D, X; +2 more` |
| Backend injects `Itinerary stops:` from `collection.locations` | ✅ PASS | Python test: 6 inputs → 5 unique stops joined with `; `, correctly prefixed `Itinerary stops:` |
| System prompt has trip-level + `get_trip_details`-first guidance | ✅ PASS | `get_system_prompt()` output contains `itinerary-wide`, `get_trip_details first`, `Treat context as itinerary-wide` |
| No regression in existing fields | ✅ PASS | Django test suite unchanged at baseline (24 pass, 6 pre-existing fail/error) |

### Adversarial attempts

| Hypothesis | Test | Expected failure signal | Observed |
|---|---|---|---|
| 12-city collection exceeds cap | Supply 12 unique cities | >8 stops returned | Capped at exactly 8 ✅ |
| Empty `locations` list | Pass `locations=[]` | Crash or non-empty result | Returns `undefined`/`[]` cleanly ✅ |
| All-blank location entries | All city/country/name empty or whitespace | Non-empty or crash | All skipped, returns `undefined`/`[]` ✅ |
| Whitespace-only city/country | `city.name='   '` with valid fallback | Whitespace treated as valid | Strip applied, fallback used ✅ |
| Unicode city names | `東京`, `Zürich`, `São Paulo` | Encoding corruption or skip | All 3 preserved correctly ✅ |
| 12 duplicate identical entries | Same city×12 | Multiple copies in output | Deduped to exactly 1 ✅ |
| `city.name = None` (DB null) | `None` city name, valid country | `AttributeError` or crash | Handled via `or ''` guard, country used ✅ |
| `null` collection passed to frontend func | `deriveCollectionDestination(null)` | Crash | Returns `undefined` cleanly ✅ |
| Overflow suffix formatting | 6 unique stops, maxStops=4 | Wrong suffix or missing | `+2 more` suffix correct ✅ |
| Fallback name path | No city/country, `location='Eiffel Tower'` | Missing or wrong label | `Eiffel Tower` used ✅ |

### MUTATION_ESCAPES: 0/6

Mutation checks applied:
1. `>= 8` cap mutated to `> 8` → A1 test (12-city produces 8, not 9) would catch.
2. `seen_stops` dedup check mutated to always-false → A6 test (12-dupes) would catch.
3. `or ''` null-guard on `city.name` removed → A7 test would catch `AttributeError`.
4. `if not fallback_name: continue` removed → A3 test (all-blank) would catch spurious entries.
5. `stops.slice(0, maxStops).join('; ')` separator mutated to `', '` → Multi-stop tests check for `'; '` as separator.
6. `return undefined` on empty guard mutated to `return ''` → A4 empty-locations test checks `=== undefined`.

All 6 mutations would be caught by existing test cases.

### LESSON_CHECKS

- Pre-existing test failures (2 user email key + 4 geocoding mock) — **confirmed**, baseline unchanged.
- F2 context enrichment using `select_related('city', 'country')` per critic guardrail — **confirmed** (line 169–171 of views/__init__.py).
- Fallback to `location`/`name` fields when geo data absent — **confirmed** working via A4/A5 tests.

**Reference**: See [F2 Review](#f2-review), [Critic Gate](#critic-gate)

---

## F3 Review

- **Verdict**: APPROVED (score 0)
- **Lens**: Correctness
- **Date**: 2026-03-09
- **Reviewer**: reviewer agent

**Scope**: Targeted re-review of two F3 findings in `frontend/src/lib/components/AITravelChat.svelte`:
1. `.places` → `.results` key mismatch in `hasPlaceResults()` / `getPlaceResults()`
2. Quick-action prompt guard and wording — location-centric → itinerary-centric

**Finding 1 — `.places` → `.results` (RESOLVED)**:
- `hasPlaceResults()` (line 378): checks `(result.result as { results?: unknown[] }).results` ✅
- `getPlaceResults()` (line 387): returns `(result.result as { results: any[] }).results` ✅
- Cross-verified against backend `agent_tools.py:188-191`: `return {"location": ..., "category": ..., "results": results}` — keys match.

**Finding 2 — Itinerary-centric prompts (RESOLVED)**:
- New reactive `promptTripContext` (line 72): `collectionName || destination || ''` — prefers collection name over single destination.
- Guard changed from `{#if destination}` → `{#if promptTripContext}` (line 768) — buttons now visible for named collections even without a single derived destination.
- Prompt strings use `across my ${promptTripContext} itinerary?` wording (lines 773, 783) — no longer implies single location.
- No impact on packing tips (still `startDate && endDate` gated) or itinerary help (always shown).

**No introduced issues**: `promptTripContext` always resolves to string; template interpolation safe; existing tool result rendering and `sendMessage()` logic unchanged beyond the key rename.

**SUGGESTIONS**: Minor indentation inconsistency between `{#if promptTripContext}` block (lines 768-789) and adjacent `{#if startDate}` block (lines 790-801) — cosmetic, `bun run format` should normalize.

**Reference**: See [Critic Gate](#critic-gate), [F2 Review](#f2-review), [decisions.md](../decisions.md#critic-gate-travel-agent-context--models-follow-up)

---

## F3 Test

- **Verdict**: PASS (Standard + Adversarial)
- **Date**: 2026-03-09
- **Tester**: tester agent

### Commands run

| # | Command | Exit code | Output summary |
|---|---|---|---|
| 1 | `bun run check` (frontend) | 0 | 0 errors, 6 warnings — all 6 pre-existing in `CollectionRecommendationView.svelte` + `RegionCard.svelte`; zero new issues from F3 changes |
| 2 | `bun run f3_test.mjs` (functional simulation) | 0 | 20 assertions: S1–S6 standard + A1–A6 adversarial + PTC1–PTC4 promptTripContext + prompt wording — ALL PASSED |

### Acceptance criteria verdict

| Criterion | Result | Evidence |
|---|---|---|
| `.places` → `.results` key fix in `hasPlaceResults()` | ✅ PASS | S1: `{results:[...]}` → true; S2: `{places:[...]}` → false (old key correctly rejected) |
| `.places` → `.results` key fix in `getPlaceResults()` | ✅ PASS | S1: returns 2-item array from `.results`; S2: returns `[]` on `.places` key |
| Old `.places` key no longer triggers card rendering | ✅ PASS | S2 regression guard: `hasPlaceResults({places:[...]})` → false |
| `promptTripContext` = `collectionName \|\| destination \|\| ''` | ✅ PASS | PTC1–PTC4: collectionName wins; falls back to destination; empty string when both absent |
| Quick-action guard is `{#if promptTripContext}` | ✅ PASS | Source inspection confirmed line 768 uses `promptTripContext` |
| Prompt wording is itinerary-centric | ✅ PASS | Both prompts contain `itinerary`; neither uses single-location "in X" wording |

### Adversarial attempts

| Hypothesis | Test design | Expected failure signal | Observed |
|---|---|---|---|
| `results` is a string, not array | `result: { results: 'not-array' }` | `Array.isArray` fails → false | false ✅ |
| `results` is null | `result: { results: null }` | `Array.isArray(null)` false | false ✅ |
| `result.result` is a number | `result: 42` | typeof guard rejects | false ✅ |
| `result.result` is a string | `result: 'str'` | typeof guard rejects | false ✅ |
| Both `.places` and `.results` present | both keys in result | Must use `.results` | `getPlaceResults` returns `.results` item ✅ |
| `results` is an object `{foo:'bar'}` | not an array | `Array.isArray` false | false ✅ |
| `promptTripContext` with empty collectionName string | `'' \|\| 'London' \|\| ''` | Should fall through to destination | 'London' ✅ |

### MUTATION_ESCAPES: 0/5

Mutation checks applied:
1. `result.result !== null` guard removed → S5 (null result) would crash `Array.isArray(null.results)` and be caught.
2. `Array.isArray(...)` replaced with truthy check → A1 (string results) test would catch.
3. `result.name === 'search_places'` removed → S4 (wrong tool name) would catch.
4. `.results` key swapped back to `.places` → S1 (standard payload) would return empty array, caught.
5. `collectionName || destination` order swapped → PTC1 test would return wrong value, caught.

All 5 mutations would be caught by existing assertions.

### LESSON_CHECKS

- `.places` vs `.results` key mismatch (F3a critical bug from discovery) — **confirmed fixed**: S1 passes with `.results`; S2 regression guard confirms `.places` no longer triggers card rendering.
- Pre-existing 6 svelte-check warnings — **confirmed**, no new warnings introduced.

---

## Completion Summary

- **Status**: ALL COMPLETE (F1 + F2 + F3)
- **Date**: 2026-03-09
- **All tasks**: Implemented, reviewed (APPROVED score 0), and tested (PASS standard + adversarial)
- **Zero regressions**: Frontend 0 errors / 6 pre-existing warnings; backend 24/30 pass (6 pre-existing failures)
- **Files changed**:
  - `backend/server/chat/views/__init__.py` — F1 (model list expansion) + F2 (itinerary stops context injection)
  - `backend/server/chat/llm_client.py` — F2 (system prompt trip-level guidance)
  - `frontend/src/routes/collections/[id]/+page.svelte` — F2 (multi-stop `deriveCollectionDestination`)
  - `frontend/src/lib/components/AITravelChat.svelte` — F3 (itinerary-centric prompts + `.results` key fix)
- **Knowledge recorded**: [knowledge.md](../knowledge.md#multi-stop-context-derivation-f2-follow-up) (multi-stop context, quick prompts, search_places key convention, opencode_zen model list)
- **Decisions recorded**: [decisions.md](../decisions.md#critic-gate-travel-agent-context--models-follow-up) (critic gate)
- **AGENTS.md updated**: Chat model override pattern (dropdown) + chat context pattern added

---

## Discovery: runtime failures (2026-03-09)

Explorer investigation of three user-trace errors against the complete scoped file set.

### Error 1 — "The model provider rate limit was reached"

**Exact origin**: `backend/server/chat/llm_client.py` **lines 128–132** (`_safe_error_payload`):
```python
if isinstance(exc, rate_limit_cls):
    return {
        "error": "The model provider rate limit was reached. Please wait and try again.",
        "error_category": "rate_limited",
    }
```
The user-trace text `"model provider rate limit was reached"` is a substring of this exact message. This is **not a bug** — it is the intended sanitized error surface for `litellm.exceptions.RateLimitError`. The error is raised by LiteLLM when the upstream provider (OpenAI, Anthropic, etc.) returns HTTP 429, and `_safe_error_payload()` converts it to this user-safe string. The SSE error payload is then propagated through `stream_chat_completion` (line 457) → `event_stream()` in `send_message` (line 256: `if data.get("error"): encountered_error = True; break`) → yielded to frontend → frontend SSE loop sets `assistantMsg.content = parsed.error` (line 307 of `AITravelChat.svelte`).

**Root cause of rate limiting itself**: Most likely `openai/gpt-5-nano` as the `opencode_zen` default model, or the user's provider hitting quota. No code fix required — this is provider-side throttling surfaced correctly. However, if the `opencode_zen` provider is being mistakenly routed to OpenAI's public endpoint instead of `https://opencode.ai/zen/v1`, it would exhaust a real OpenAI key rather than Zen. See Risk 1 below.

**No auth/session issue involved** — the error path reaches LiteLLM, meaning auth already succeeded up to the LLM call.

---

### Error 2 — `{"error":"location is required"}`

**Exact origin**: `backend/server/chat/agent_tools.py` **line 128**:
```python
if not location_name:
    return {"error": "location is required"}
```
Triggered when LLM calls `search_places({})` or `search_places({"category": "food"})` with no `location` argument. This happens when the system prompt's trip context does not give the model a geocodable string — the model knows a "trip name" but not a city/country, so it calls `search_places` without a location.

**Current state (post-F2)**: The F2 fix injects `"Itinerary stops: Rome, Italy; ..."` into the system prompt from `collection.locations` **only when `collection_id` is supplied and resolves to an authorized collection**. If `collection_id` is missing from the frontend payload OR if the collection has locations with no `city`/`country` FK and no `location`/`name` fallback, the context_parts will still have only the `destination` string.

**Residual trigger path** (still reachable after F2):
- `collection_id` not sent in `send_message` payload → collection never fetched → `context_parts` has only `Destination: <multi-stop string>` → LLM picks a trip-name string like "Italy 2025" as its location arg → `search_places(location="Italy 2025")` succeeds (geocoding finds "Italy") OR model sends `search_places({})` → error returned.
- OR: `collection_id` IS sent, all locations have no `city`/`country` AND `location` field is blank AND `name` is not geocodable (e.g., `"Hotel California"`) → `itinerary_stops` list is empty → no `Itinerary stops:` line injected.

**Second remaining trigger**: `get_trip_details` fails (Collection.DoesNotExist or exception) → returns `{"error": "An unexpected error occurred while fetching trip details"}` → model falls back to calling `search_places` without a location derived from context.

---

### Error 3 — `{"error":"An unexpected error occurred while fetching trip details"}`

**Exact origin**: `backend/server/chat/agent_tools.py` **lines 394–396** (`get_trip_details`):
```python
    except Exception:
        logger.exception("get_trip_details failed")
        return {"error": "An unexpected error occurred while fetching trip details"}
```

**Root cause — `get_trip_details` uses owner-only filter**: `agent_tools.py` **line 317**:
```python
collection = (
    Collection.objects.filter(user=user)
    ...
    .get(id=collection_id)
)
```
This uses `filter(user=user)` — **shared collections are excluded**. If the logged-in user is a shared member (not the owner) of the collection, `Collection.DoesNotExist` is raised, falls to the outer `except Exception`, and returns the generic error. However, `Collection.DoesNotExist` is caught specifically on **line 392** and returns `{"error": "Trip not found"}`, not the generic message. So the generic error can only come from a genuine Python exception inside the try block — most likely:

1. **`item.item` AttributeError** — `CollectionItineraryItem` uses a `GenericForeignKey`; if the referenced object has been deleted, `item.item` returns `None` and `getattr(None, "name", "")` would return `""` (safe, not an error) — so this is not the cause.
2. **`collection.itinerary_items` reverse relation** — if the `related_name="itinerary_items"` is not defined on `CollectionItineraryItem.collection` FK, the queryset call raises `AttributeError`. Checking `adventures/models.py` line 716: `related_name="itinerary_items"` is present — so this is not the cause.
3. **`collection.transportation_set` / `collection.lodging_set`** — if `Transportation` or `Lodging` doesn't have `related_name` defaulting to `transportation_set`/`lodging_set`, these would fail. This is the **most likely cause** — Django only auto-creates `_set` accessors with the model name in lowercase; `transportation_set` requires that the FK `related_name` is either set or left as default `transportation_set`. Need to verify model definition.
4. **`collection.start_date.isoformat()` on None** — guarded by `if collection.start_date` (line 347) — safe.

**Verified**: `Transportation.collection` (`models.py:332`) and `Lodging.collection` (`models.py:570`) are both ForeignKeys with **no `related_name`**, so Django auto-assigns `transportation_set` and `lodging_set` — the accessors used in `get_trip_details` lines 375/382 are correct. These do NOT cause the error.

**Actual culprit**: The `except Exception` at line 394 catches everything. Any unhandled exception inside the try block (e.g., a `prefetch_related("itinerary_items__content_type")` failure if a content_type row is missing, or a `date` field deserialization error on a malformed DB record) results in the generic error. Most commonly, the issue is the **shared-user access gap**: `Collection.objects.filter(user=user).get(id=...)` raises `Collection.DoesNotExist` for shared users, but that is caught by the specific handler at line 392 as `{"error": "Trip not found"}`, NOT the generic message. The generic message therefore indicates a true runtime Python exception somewhere inside the try body.

**Additionally**: the shared-collection access gap means `get_trip_details` returns `{"error": "Trip not found"}` (not the generic error) for shared users — this is a separate functional bug where shared users cannot use the AI tool on their shared trips.

---

### Authentication / CSRF in Chat Calls

**Verdict: Auth is working correctly for the SSE path. No auth failure in the reported errors.**

Evidence:
1. **Proxy path** (`frontend/src/routes/api/[...path]/+server.ts`):
   - `POST` to `send_message` goes through `handleRequest()` (line 16) with `requreTrailingSlash=true`.
   - On every proxied request: proxy deletes old `csrftoken` cookie, calls `fetchCSRFToken()` to get a fresh token from `GET /csrf/`, then sets `X-CSRFToken` header and reconstructs the `Cookie` header with `csrftoken=<new>; sessionid=<from-browser>` (lines 57–75).
   - SSE streaming: `content-type: text/event-stream` is detected (line 94) and the response body is streamed directly without buffering.
2. **Session**: `sessionid` cookie is extracted from browser cookies (line 66) and forwarded. `SESSION_COOKIE_SAMESITE=Lax` allows this.
3. **Rate-limit error is downstream of auth** — LiteLLM only fires if the Django view already authenticated the user and reached `stream_chat_completion`. A CSRF or session failure would return HTTP 403/401 before the SSE stream starts, and the frontend would hit the `if (!res.ok)` branch (line 273), not the SSE error path.

**One auth-adjacent gap**: `loadConversations()` (line 196) and `createConversation()` (line 203) do NOT include `credentials: 'include'` — but these go through the SvelteKit proxy which handles session injection server-side, so this is not a real failure point. The `send_message` fetch (line 258) also lacks explicit `credentials`, but again routes through the proxy.

**Potential auth issue — missing trailing slash for models endpoint**:
`loadModelsForProvider()` fetches `/api/chat/providers/${selectedProvider}/models/` (line 124) — this ends with `/` which is correct for the proxy's `requreTrailingSlash` logic. However, the proxy only adds a trailing slash for non-GET requests (it's applied to POST/PATCH/PUT/DELETE but not GET). Since `models/` is already in the URL, this is fine.

---

### Ranked Fixes by Impact

| Rank | Error | File | Line(s) | Fix |
|---|---|---|---|---|
| 1 (HIGH) | `get_trip_details` generic error | `backend/server/chat/agent_tools.py` | 316–325 | Add `\| Q(shared_with=user)` to collection filter so shared users can call the tool; also add specific catches for known exception types before the bare `except Exception` |
| 2 (HIGH) | `{"error":"location is required"}` residual | `backend/server/chat/views/__init__.py` | 152–164 | Ensure `collection_id` auth check also grants access for shared users (currently `shared_with.filter(id=request.user.id).exists()` IS present — ✅ already correct); verify `collection_id` is actually being sent from frontend on every `sendMessage` call |
| 2b (MEDIUM) | `search_places` called without location | `backend/server/chat/agent_tools.py` | 127–128 | Improve error message to be user-instructional: `"Please provide a city or location name to search near."` — already noted in prior plan; also add `location` as a `required` field in the JSON schema so LLM is more likely to provide it |
| 3 (MEDIUM) | `transportation_set`/`lodging_set` crash | `backend/server/chat/agent_tools.py` | 370–387 | Verify FK `related_name` values on Transportation/Lodging models; if wrong, correct the accessor names in `get_trip_details` |
| 4 (LOW) | Rate limiting | Provider config | N/A | No code fix — operational issue. Document that `opencode_zen` uses `https://opencode.ai/zen/v1` as `api_base` (already set in `CHAT_PROVIDER_CONFIG`) — ensure users aren't accidentally using a real OpenAI key with `opencode_zen` provider |

---

### Risks

1. **`get_trip_details` shared-user gap**: Shared users get `{"error": "Trip not found"}` — the LLM may then call `search_places` without the location context that `get_trip_details` would have provided, cascading into Error 2. Fix: add `| Q(shared_with=user)` to the collection filter at `agent_tools.py:317`.

2. **`transportation_set`/`lodging_set` reverse accessor names confirmed safe**: Django auto-generates `transportation_set` and `lodging_set` for the FKs (no `related_name` on `Transportation.collection` at `models.py:332` or `Lodging.collection` at `models.py:570`). These accessors work correctly. The generic error in `get_trip_details` must be from another exception path (e.g., malformed DB records, missing ContentType rows for deleted itinerary items, or the `prefetch_related` interaction on orphaned GFK references).

3. **`collection_id` not forwarded on all sends**: If `AITravelChat.svelte` is embedded without `collectionId` prop (e.g., standalone chat page), `collection_id` is `undefined` in the payload, the backend never fetches the collection, and no `Itinerary stops:` context is injected. The LLM then has no geocodable location data → calls `search_places` without `location`.

4. **`search_places` JSON schema marks `location` as required but `execute_tool` uses `filtered_kwargs`**: The tool schema (`agent_tools.py:103`) sets `"required": True` on `location`. However, `execute_tool` (line 619) passes only `filtered_kwargs` from the JSON-parsed `arguments` dict. If LLM sends `{}` (empty), `location=None` is the function default, not a schema-enforcement error. There is no server-side validation of required tool arguments — the required flag is only advisory to the LLM.

**See [decisions.md](../decisions.md) for critic gate context.**

---

## Research: Provider Strategy (2026-03-09)

**Full findings**: [research/provider-strategy.md](../research/provider-strategy.md)

### Verdict: Keep LiteLLM, Harden It

Replacing LiteLLM is not warranted. Every Voyage issue is in the integration layer (no retries, no capability checks, hardcoded models), not in LiteLLM itself. OpenCode's Python-equivalent IS LiteLLM — OpenCode uses Vercel AI SDK with ~20 bundled `@ai-sdk/*` provider packages, which is the TypeScript analogue.

### Architecture Options

| Option | Effort | Risk | Recommended? |
|---|---|---|---|
| **A. Keep LiteLLM, harden** (retry, tool-guard, metadata) | Low (1-2 sessions) | Low | ✅ YES |
| B. Hybrid: direct SDK for some providers | High (1-2 weeks) | High | No |
| C. Replace LiteLLM entirely | Very High (3-4 weeks) | Very High | No |
| D. LiteLLM Proxy sidecar | Medium (2-3 days) | Medium | Not yet — future multi-user |

### Immediate Code Fixes (4 items)

| # | Fix | File | Line(s) | Impact |
|---|---|---|---|---|
| 1 | Add `num_retries=2, request_timeout=60` to `litellm.acompletion()` | `llm_client.py` | 418 | Retry on rate-limit/timeout — biggest gap |
| 2 | Add `litellm.supports_function_calling(model=)` guard before passing tools | `llm_client.py` | ~397 | Prevents tool-call errors on incapable models |
| 3 | Return model objects with `supports_tools` metadata instead of bare strings | `views/__init__.py` | `models()` action | Frontend can warn/adapt per model capability |
| 4 | Replace hardcoded `model="gpt-4o-mini"` with provider config default | `day_suggestions.py` | 194 | Respects user's configured provider |

### Long-Term Recommendations

1. **Curated model registry** (YAML/JSON file like OpenCode's `models.dev`) with capabilities, costs, context limits — loaded at startup
2. **LiteLLM Proxy sidecar** — only if/when Voyage gains multi-user production deployment
3. **WSGI→ASGI migration** — long-term fix for event loop fragility (out of scope)

### Key Patterns Observed in Other Projects

- **No production project does universal runtime model discovery** — all use curated/admin-managed lists
- **Every production LiteLLM user has retry logic** — Voyage is the outlier with zero retries
- **Tool-call capability guards** are standard (`litellm.supports_function_calling()` used by PraisonAI, open-interpreter, mem0, ragbits, dspy)
- **Rate-limit resilience** ranges from simple `num_retries` to full `litellm.Router` with `RetryPolicy` and cross-model fallbacks