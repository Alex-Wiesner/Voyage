---
title: ai-travel-agent-redesign
type: note
permalink: voyage/plans/ai-travel-agent-redesign
---

# AI Travel Agent Redesign Plan

## Vision Summary

Redesign the AI travel agent with two context-aware entry points, user preference learning, flexible provider configuration, extensibility for future integrations, web search capability, and multi-user collection support.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        ENTRY POINTS                              │
├─────────────────────────────┬───────────────────────────────────┤
│  Day-Level Suggestions      │  Collection-Level Chat            │
│  (new modal)                │  (improved Recommendations tab)   │
│  - Category filters         │  - Context-aware                  │
│  - Sub-filters              │  - Add to itinerary actions       │
│  - Add to day action        │                                   │
└─────────────────────────────┴───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT CORE                                  │
├─────────────────────────────────────────────────────────────────┤
│  - LiteLLM backend (streaming SSE)                              │
│  - Tool calling (place search, web search, itinerary actions)   │
│  - Multi-user preference aggregation                            │
│  - Context injection (collection, dates, location)              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CONFIGURATION LAYERS                           │
├─────────────────────────────────────────────────────────────────┤
│  Instance (.env)    →  VOYAGE_AI_PROVIDER                       │
│                      →  VOYAGE_AI_MODEL                         │
│                      →  VOYAGE_AI_API_KEY                       │
│  User (DB)          →  UserAPIKey.per-provider keys             │
│                      →  UserAISettings.model preference         │
│  Fallback: User key → Instance key → Error                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Workstreams

### WS1: Configuration Infrastructure

**Goal**: Support both instance-level and user-level provider/model configuration with proper fallback.

#### WS1-F1: Instance-level configuration
- Add env vars to `settings.py`:
  - `VOYAGE_AI_PROVIDER` (default: `openai`)
  - `VOYAGE_AI_MODEL` (default: `gpt-4o-mini`)
  - `VOYAGE_AI_API_KEY` (optional global key)
- Update `llm_client.py` to read instance defaults
- Add fallback chain: user key → instance key → error

#### WS1-F2: User-level model preferences
- Add `UserAISettings` model (OneToOne → CustomUser):
  - `preferred_provider` (CharField)
  - `preferred_model` (CharField)
- Create API endpoint: `POST /api/ai/settings/`
- Add UI in Settings → AI section for model selection

#### WS1-F3: Provider catalog enhancement
- Extend provider catalog response to include:
  - `instance_configured`: bool (has instance key)
  - `user_configured`: bool (has user key)
- Update frontend to show configuration status per provider

**Files**: `settings.py`, `llm_client.py`, `integrations/models.py`, `integrations/views/`, `frontend/src/routes/settings/`

---

### WS2: User Preference Learning

**Goal**: Capture and use user preferences in AI recommendations.

#### WS2-F1: Preference UI
- Add "AI Preferences" tab to Settings page
- Form fields: cuisines, interests, trip_style, notes
- Use tag input for cuisines/interests (better UX than free text)
- Connect to existing `/api/integrations/recommendation-preferences/`

Implementation notes (2026-03-08):
- Implemented in `frontend/src/routes/settings/+page.svelte` as `travel_preferences` section in the existing settings sidebar, with `savePreferences(event)` posting to `/api/integrations/recommendation-preferences/`.
- `interests` conversion is string↔array at UI boundary: load via `(profile.interests || []).join(', ')`; save via `.split(',').map((s) => s.trim()).filter(Boolean)`.
- SSR preload added in `frontend/src/routes/settings/+page.server.ts` using parallel fetch with API keys; returns `props.recommendationProfile` as first list element or `null`.
- Frontend typing added in `frontend/src/lib/types.ts` (`UserRecommendationPreferenceProfile`) and i18n strings added under `settings` in `frontend/src/locales/en.json`.
- See backend capability reference in [Project Knowledge — User Recommendation Preference Profile](../knowledge.md#user-recommendation-preference-profile).

#### WS2-F2: Preference injection
- Enhance `get_system_prompt()` to format preferences better
- Add preference summary in system prompt (structured, not just appended)

#### WS2-F3: Multi-user aggregation
- New function: `get_aggregated_preferences(collection)` 
- Returns combined preferences from all `collection.shared_with` users + owner
- Format: "Party preferences: User A likes X, User B prefers Y..."
- Inject into system prompt for shared collections

**Files**: `frontend/src/routes/settings/`, `chat/llm_client.py`, `integrations/models.py`

---

### WS3: Day-Level Suggestions Modal

**Goal**: Add "Suggest" option to itinerary day "Add" dropdown with category filters.

#### WS3-F1: Suggestion modal component
- Create `ItinerarySuggestionModal.svelte`
- Two-step flow:
  1. **Category selection**: Restaurant, Activity, Event, Lodging
  2. **Filter refinement**: 
     - Restaurant: cuisine type, price range, dietary restrictions
     - Activity: type (outdoor, cultural, etc.), duration
     - Event: type, date/time preference
     - Lodging: type, amenities
- "Any/Surprise me" option for each filter

#### WS3-F2: Add button integration
- Add "Get AI suggestions" option to `CollectionItineraryPlanner.svelte` Add dropdown
- Opens suggestion modal with target date pre-set
- Modal receives: `collectionId`, `targetDate`, `collectionLocation` (for context)

#### WS3-F3: Suggestion results display
- Show 3-5 suggestions as cards with:
  - Name, description, why it fits preferences
  - "Add to this day" button
  - "Add to different day" option
- On add: **direct REST API call** to `/api/itineraries/` (not agent tool)
- User must approve each item individually - no bulk/auto-add
- Close modal and refresh itinerary on success

#### WS3-F4: Backend suggestion endpoint
- New endpoint: `POST /api/ai/suggestions/day/`
- Params: `collection_id`, `date`, `category`, `filters`, `location_context`
- Returns structured suggestions (not chat, direct JSON)
- Uses agent internally but returns parsed results

**Files**: `CollectionItineraryPlanner.svelte`, `ItinerarySuggestionModal.svelte` (new), `chat/views.py`, `chat/agent_tools.py`

---

### WS3.5: Insertion Flow Clarification

**Two insertion paths exist:**

| Path | Entry Point | Mechanism | Use Case |
|------|-------------|-----------|----------|
| **User-approved** | Suggestions modal | Direct REST API call to `/api/itineraries/` | Day-level suggestions, user reviews and clicks Add |
| **Agent-initiated** | Chat (Recommendations tab) | `add_to_itinerary` tool via SSE streaming | Conversational adds when user says "add that place" |

**Why two paths:**
- Modal: Faster, simpler UX - no round-trip through agent, user stays in control
- Chat: Natural conversation flow - agent can add as part of dialogue

**No changes needed to agent tools** - `add_to_itinerary` already exists in `agent_tools.py` and works for chat-initiated adds.

---

### WS4: Collection-Level Chat Improvements

**Goal**: Make Recommendations tab chat context-aware and action-capable.

#### WS4-F1: Context injection
- Pass collection context to `AITravelChat.svelte`:
  - `collectionId`, `collectionName`, `startDate`, `endDate`
  - `destination` (from collection locations or user input)
- Inject into system prompt: "You are helping plan a trip to X from Y to Z"

Implementation notes (2026-03-08):
- `frontend/src/lib/components/AITravelChat.svelte` now exposes optional context props (`collectionId`, `collectionName`, `startDate`, `endDate`, `destination`) and includes them in `POST /api/chat/conversations/{id}/send_message/` payload.
- `frontend/src/routes/collections/[id]/+page.svelte` now passes collection context into `AITravelChat`; destination is derived via `deriveCollectionDestination(...)` from `city/country/location/name` on the first usable location.
- `backend/server/chat/views/__init__.py::ChatViewSet.send_message()` now accepts the same optional fields, resolves `collection_id` (owner/shared access only), and appends a `## Trip Context` block to the system prompt before streaming.
- Related architecture note: [Project Knowledge — AI Chat](../knowledge.md#ai-chat-collections--recommendations).

#### WS4-F2: Quick action buttons
- Add preset prompts above chat input:
  - "Suggest restaurants for this trip"
  - "Find activities near [destination]"
  - "What should I pack for [dates]?"
- Pre-fill input on click

#### WS4-F3: Add-to-itinerary from chat
- When agent suggests a place, show "Add to itinerary" button
- User selects date → calls `add_to_itinerary` tool
- Visual feedback on success

Implementation notes (2026-03-08):
- Implemented in `frontend/src/lib/components/AITravelChat.svelte` as an MVP direct frontend flow (no agent round-trip):
  - Adds `Add to Itinerary` button to `search_places` result cards when `collectionId` exists.
  - Opens a date picker modal (`showDateSelector`, `selectedPlaceToAdd`, `selectedDate`) constrained by trip date range (`min={startDate}`, `max={endDate}`).
  - On confirm, creates a location via `POST /api/locations/` then creates itinerary entry via `POST /api/itineraries/`.
  - Dispatches `itemAdded { locationId, date }` and shows success toast (`added_successfully`).
  - Guards against missing/invalid coordinates by disabling add action unless lat/lon parse successfully.
- i18n keys added in `frontend/src/locales/en.json`: `add_to_itinerary`, `add_to_which_day`, `added_successfully`.

#### WS4-F4: Improved UI
- Remove generic "robot" branding, use travel-themed design
- Show collection name in header
- Better tool result display (cards instead of raw JSON)

Implementation notes (2026-03-08):
- `frontend/src/lib/components/AITravelChat.svelte` header now uses travel branding with `✈️` and renders `Travel Assistant · {collectionName}` when collection context is present; destination is shown as a subtitle when provided.
- Robot icon usage in chat UI was replaced with travel-themed emoji (`✈️`, `🌍`, `🗺️`) while keeping existing layout structure.
- SSE `tool_result` chunks are now attached to the in-flight assistant message via `tool_results` and rendered inline as structured cards for `search_places` and `web_search`, with JSON `<pre>` fallback for unknown tools.
- Legacy persisted `role: 'tool'` messages are still supported via JSON parsing fallback and use the same card rendering logic.
- i18n root keys added in `frontend/src/locales/en.json`: `travel_assistant`, `quick_actions`.

See [Project Knowledge — WS4-F4 Chat UI Rendering](../knowledge.md#ws4-f4-chat-ui-rendering).

**Files**: `AITravelChat.svelte`, `chat/views.py`, `chat/llm_client.py`

---

### WS5: Web Search Capability

**Goal**: Enable agent to search the web for current information.

#### WS5-F1: Web search tool
- Add `web_search` tool to `agent_tools.py`:
  - Uses DuckDuckGo (free, no API key) or Brave Search API (env var)
  - Returns top 5 results with titles, snippets, URLs
- Tool schema:
  ```python
  {
      "name": "web_search",
      "description": "Search the web for current information about destinations, events, prices, etc.",
      "parameters": {
          "query": "string - search query",
          "location_context": "string - optional location to bias results"
      }
  }
  ```

#### WS5-F2: Tool integration
- Register in `AGENT_TOOLS` list
- Add to `execute_tool()` dispatcher
- Handle rate limiting gracefully

**Files**: `chat/agent_tools.py`, `requirements.txt` (add `duckduckgo-search`)

---

### WS6: Extensibility Architecture

**Goal**: Design for easy addition of future integrations.

#### WS6-F1: Plugin tool registry
- Refactor `agent_tools.py` to use decorator-based registration:
  ```python
  @agent_tool(name="web_search", description="...")
  def web_search(query: str, location_context: str = None):
      ...
  ```
- Tools auto-register on import
- Easy to add new tools in separate files

#### WS6-F2: Integration hooks
- Create `chat/integrations/` directory for future:
  - `tripadvisor.py` - TripAdvisor API integration
  - `flights.py` - Flight search (Skyscanner, etc.)
  - `weather.py` - Enhanced weather data
- Each integration exports tools via decorator

#### WS6-F3: Capability discovery
- Endpoint: `GET /api/ai/capabilities/`
- Returns list of available tools/integrations
- Frontend can show "Powered by X, Y, Z" dynamically

**Files**: `chat/tools/` (new directory), `chat/agent_tools.py` (refactor)

---

## File Changes Summary

### New Files
- `frontend/src/lib/components/collections/ItinerarySuggestionModal.svelte`
- `backend/server/chat/tools/__init__.py`
- `backend/server/chat/tools/web_search.py`
- `backend/server/integrations/models.py` (add UserAISettings)
- `backend/server/integrations/views/ai_settings_view.py`

### Modified Files
- `backend/server/main/settings.py` - Add AI env vars
- `backend/server/chat/llm_client.py` - Config fallback, preference aggregation
- `backend/server/chat/views.py` - New suggestion endpoint, context injection
- `backend/server/chat/agent_tools.py` - Web search tool, refactor
- `frontend/src/lib/components/AITravelChat.svelte` - Context awareness, actions
- `frontend/src/lib/components/collections/CollectionItineraryPlanner.svelte` - Add button
- `frontend/src/routes/settings/+page.svelte` - AI preferences UI, model selection
- `frontend/src/routes/collections/[id]/+page.svelte` - Pass collection context

---

## Migration Path

1. **Phase 1 - Foundation** (WS1, WS2)
   - Configuration infrastructure
   - Preference UI
   - No user-facing changes to chat yet

2. **Phase 2 - Day Suggestions** (WS3)
   - New modal, new entry point
   - Backend suggestion endpoint
   - Can ship independently

3. **Phase 3 - Chat Improvements** (WS4, WS5)
   - Context-aware chat
   - Web search capability
   - Better UX

4. **Phase 4 - Extensibility** (WS6)
   - Plugin architecture
   - Future integration prep

---

## Decisions (Confirmed)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Web search provider | **DuckDuckGo** | Free, no API key, good enough for travel info |
| Suggestion API | **Dedicated REST endpoint** | Simpler, faster, returns JSON directly |
| Multi-user conflicts | **List all preferences** | Transparency - AI navigates differing preferences |

---

## Out of Scope

- WSGI→ASGI migration (keep current async-in-sync pattern)
- Role-based permissions (all shared users have same access)
- Real-time collaboration (WebSocket sync)
- Mobile-specific optimizations