# Collections & Sharing Domain

## Collection Sharing Architecture

### Data Model
- `Collection.shared_with` - `ManyToManyField(User, related_name='shared_with', blank=True)` - the primary access grant
- `CollectionInvite` - staging table for pending invites: `(collection FK, invited_user FK, unique_together)`; prevents self-invite and double-invite
- Both models in `backend/server/adventures/models.py`

### Access Flow (Invite -> Accept -> Membership)
1. Owner calls `POST /api/collections/{id}/share/{uuid}/` -> creates `CollectionInvite`
2. Invited user sees pending invites via `GET /api/collections/invites/`
3. Invited user calls `POST /api/collections/{id}/accept-invite/` -> adds to `shared_with`, deletes invite
4. Owner revokes: `POST /api/collections/{id}/revoke-invite/{uuid}/`
5. User declines: `POST /api/collections/{id}/decline-invite/`
6. Owner removes: `POST /api/collections/{id}/unshare/{uuid}/` - removes user's locations from collection
7. User self-removes: `POST /api/collections/{id}/leave/` - removes their locations

### Permission Classes
- `CollectionShared` - full access for owner and `shared_with` members; invite actions for invitees; anonymous read for `is_public`
- `IsOwnerOrSharedWithFullAccess` - child-object viewsets; traverses `obj.collections`/`obj.collection` to check `shared_with`
- `ContentImagePermission` - delegates to `IsOwnerOrSharedWithFullAccess` on `content_object`

### Key Design Constraints
- No role differentiation - all shared users have same write access
- On unshare/leave, departing user's locations are removed from collection (not deleted)
- `duplicate` action creates a private copy with no `shared_with` transfer

## Itinerary Architecture

### Primary Component
`CollectionItineraryPlanner.svelte` (~3818 lines) - monolith rendering the entire itinerary view and all modals.

### The "Add" Button
DaisyUI dropdown at bottom of each day card with "Link existing item" and "Create new" submenu (Location, Lodging, Transportation, Note, Checklist).

### Day Suggestions Modal (WS3)
- Component: `ItinerarySuggestionModal.svelte`
- Props: `collection`, `user`, `targetDate`, `displayDate`
- Events: `close`, `addItem { type: 'location', itemId, updateDate }`
- 3-step UX: category selection -> filters -> results from `POST /api/chat/suggestions/day/`

## User Recommendation Preference Profile
Backend-only feature: model, API, and system-prompt integration exist, but **no frontend UI** built yet.

### Auto-learned preference updates
- `backend/server/integrations/utils/auto_profile.py` derives profile from user history
- Fields: `interests` (from activities + locations), `trip_style` (from lodging), `notes` (frequently visited regions)
- `ChatViewSet.send_message()` invokes `update_auto_preference_profile(request.user)` at method start

### Model
`UserRecommendationPreferenceProfile` (OneToOne -> `CustomUser`): `cuisines`, `interests` (JSONField), `trip_style`, `notes`, timestamps.

### System Prompt Integration
- Single-user: labeled as auto-inferred with structured markdown section
- Shared collections: `get_aggregated_preferences(collection)` appends per-participant preferences
- Missing profiles skipped gracefully

### Frontend Gap
- No settings tab for manual preference editing
- TypeScript type available as `UserRecommendationPreferenceProfile` in `src/lib/types.ts`
- See [Plan: AI travel agent redesign](../../plans/ai-travel-agent-redesign.md#ws2-user-preference-learning)
