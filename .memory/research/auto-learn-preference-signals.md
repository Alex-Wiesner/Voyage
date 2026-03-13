---
title: auto-learn-preference-signals
type: note
permalink: voyage/research/auto-learn-preference-signals
---

# Research: Auto-Learn User Preference Signals

## Purpose
Map all existing user data that could be aggregated into an automatic preference profile, without requiring manual input.

## Signal Inventory

### 1. Location.category (FK → Category)
- **Model**: `adventures/models.py:Category` — per-user custom categories (name, display_name, icon)
- **Signal**: Top categories by count → dominant interest type (e.g. "hiking", "dining", "cultural")
- **Query**: `Location.objects.filter(user=user).values('category__name').annotate(cnt=Count('id')).order_by('-cnt')`
- **Strength**: HIGH — user-created categories are deliberate choices

### 2. Location.tags (ArrayField)
- **Model**: `adventures/models.py:Location.tags` — `ArrayField(CharField(max_length=100))`
- **Signal**: Most frequent tags across all user locations → interest keywords
- **Query**: `Location.objects.filter(user=user).values_list('tags', flat=True).distinct()` (used in `tags_view.py`)
- **Strength**: MEDIUM-HIGH — tags are free-text user input

### 3. Location.rating (FloatField)
- **Model**: `adventures/models.py:Location.rating`
- **Signal**: Average rating + high-rated locations → positive sentiment for place types; filtering for visited + high-rated → strong preferences
- **Query**: `Location.objects.filter(user=user).aggregate(avg_rating=Avg('rating'))` or breakdown by category
- **Strength**: HIGH for positive signals (≥4.0); weak if rarely filled in

### 4. Location.description / Visit.notes (TextField)
- **Model**: `adventures/models.py:Location.description`, `Visit.notes`
- **Signal**: Free-text content for NLP keyword extraction (budget, adventure, luxury, cuisine words)
- **Query**: `Location.objects.filter(user=user).values_list('description', flat=True)`
- **Strength**: LOW (requires NLP to extract structured signals; many fields blank)

### 5. Lodging.type (LODGING_TYPES enum)
- **Model**: `adventures/models.py:Lodging.type` — choices: hotel, hostel, resort, bnb, campground, cabin, apartment, house, villa, motel
- **Signal**: Most frequently used lodging type → travel style indicator (e.g. "hostel" → budget; "resort/villa" → luxury; "campground/cabin" → outdoor)
- **Query**: `Lodging.objects.filter(user=user).values('type').annotate(cnt=Count('id')).order_by('-cnt')`
- **Strength**: HIGH — directly maps to trip_style field

### 6. Lodging.rating (FloatField)
- **Signal**: Combined with lodging type, identifies preferred accommodation standards
- **Strength**: MEDIUM

### 7. Transportation.type (TRANSPORTATION_TYPES enum)
- **Model**: `adventures/models.py:Transportation.type` — choices: car, plane, train, bus, boat, bike, walking
- **Signal**: Primary transport mode → mobility preference (e.g. mostly walking/bike → slow travel; lots of planes → frequent flyer)
- **Query**: `Transportation.objects.filter(user=user).values('type').annotate(cnt=Count('id')).order_by('-cnt')`
- **Strength**: MEDIUM

### 8. Activity.sport_type (SPORT_TYPE_CHOICES)
- **Model**: `adventures/models.py:Activity.sport_type` — 60+ choices mapped to 10 SPORT_CATEGORIES in `utils/sports_types.py`
- **Signal**: Activity categories user is active in → physical/adventure interests
- **Categories**: running, walking_hiking, cycling, water_sports, winter_sports, fitness_gym, racket_sports, climbing_adventure, team_sports
- **Query**: Already aggregated in `stats_view.py:_get_activity_stats_by_category()` — uses `Activity.objects.filter(user=user).values('sport_type').annotate(count=Count('id'))`
- **Strength**: HIGH — objective behavioral data from Strava/Wanderer imports

### 9. VisitedRegion / VisitedCity (worldtravel)
- **Model**: `worldtravel/models.py` — `VisitedRegion(user, region)` and `VisitedCity(user, city)` with country/subregion
- **Signal**: Countries/regions visited → geographic preferences (beach vs. mountain vs. city; EU vs. Asia etc.)
- **Query**: `VisitedRegion.objects.filter(user=user).select_related('region__country')` → country distribution
- **Strength**: MEDIUM-HIGH — "where has this user historically traveled?" informs destination type

### 10. Collection metadata
- **Model**: `adventures/models.py:Collection` — name, description, start/end dates
- **Signal**: Collection names/descriptions may contain destination/theme hints; trip duration (end_date − start_date) → travel pace; trip frequency (count, spacing) → travel cadence
- **Query**: `Collection.objects.filter(user=user).values('name', 'description', 'start_date', 'end_date')`
- **Strength**: LOW-MEDIUM (descriptions often blank; names are free-text)

### 11. Location.price / Lodging.price (MoneyField)
- **Signal**: Average spend across locations/lodging → budget tier
- **Query**: `Location.objects.filter(user=user).aggregate(avg_price=Avg('price'))` (requires djmoney amount field)
- **Strength**: MEDIUM — but many records may have no price set

### 12. Location geographic clustering (lat/lon)
- **Signal**: Country/region distribution of visited locations → geographic affinity
- **Already tracked**: `Location.country`, `Location.region`, `Location.city` (FK, auto-geocoded)
- **Query**: `Location.objects.filter(user=user).values('country__name').annotate(cnt=Count('id')).order_by('-cnt')`
- **Strength**: HIGH

### 13. UserAchievement types
- **Model**: `achievements/models.py:UserAchievement` — types: `adventure_count`, `country_count`
- **Signal**: Milestone count → engagement level (casual vs. power user); high `country_count` → variety-seeker
- **Strength**: LOW-MEDIUM (only 2 types currently)

### 14. ChatMessage content (user role)
- **Model**: `chat/models.py:ChatMessage` — `role`, `content`
- **Signal**: User messages in travel conversations → intent signals ("I love hiking", "looking for cheap food", "family-friendly")
- **Query**: `ChatMessage.objects.filter(conversation__user=user, role='user').values_list('content', flat=True)`
- **Strength**: MEDIUM — requires NLP; could be rich but noisy

## Aggregation Patterns Already in Codebase

| Pattern | Location | Reusability |
|---|---|---|
| Activity stats by category | `stats_view.py:_get_activity_stats_by_category()` | Direct reuse |
| All-tags union | `tags_view.py:ActivityTypesView.types()` | Direct reuse |
| VisitedRegion/City counts | `stats_view.py:counts()` | Direct reuse |
| Multi-user preference merge | `llm_client.py:get_aggregated_preferences()` | Partial reuse |
| Category-filtered location count | `serializers.py:location_count` | Pattern reference |
| Location queryset scoping | `location_view.py:get_queryset()` | Standard pattern |

## Proposed Auto-Profile Fields from Signals

| Target Field | Primary Signals | Secondary Signals |
|---|---|---|
| `cuisines` | Location.tags (cuisine words), Location.category (dining) | Location.description NLP |
| `interests` | Activity.sport_type categories, Location.category top-N | Location.tags frequency, VisitedRegion types |
| `trip_style` | Lodging.type top (luxury/budget/outdoor), Transportation.type, Activity sport categories | Location.rating Avg, price signals |
| `notes` | (not auto-derived — keep manual only) | — |

## Where to Implement

**New function target**: `integrations/views/recommendation_profile_view.py` or a new `integrations/utils/auto_profile.py`

**Suggested function signature**:
```python
def build_auto_preference_profile(user) -> dict:
    """
    Returns {cuisines, interests, trip_style} inferred from user's travel history.
    Fields are non-destructive suggestions, not overrides of manual input.
    """
```

**New API endpoint target**: `POST /api/integrations/recommendation-preferences/auto-learn/`  
**ViewSet action**: `@action(detail=False, methods=['post'], url_path='auto-learn')` on `UserRecommendationPreferenceProfileViewSet`

## Integration Point
`get_system_prompt()` in `chat/llm_client.py` already consumes `UserRecommendationPreferenceProfile` — auto-learned values
flow directly into AI context with zero additional changes needed there.

See: [knowledge.md — User Recommendation Preference Profile](../knowledge.md#user-recommendation-preference-profile)
See: [plans/ai-travel-agent-redesign.md — WS2](../plans/ai-travel-agent-redesign.md#ws2-user-preference-learning)