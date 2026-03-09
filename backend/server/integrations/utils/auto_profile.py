"""
Auto-learn user preferences from their travel history.
"""

import logging

from django.db.models import Count

from adventures.models import Activity, Location, Lodging
from integrations.models import UserRecommendationPreferenceProfile
from worldtravel.models import VisitedCity, VisitedRegion

logger = logging.getLogger(__name__)


# Mapping of lodging types to travel styles
LODGING_STYLE_MAP = {
    "hostel": "budget",
    "campground": "outdoor",
    "cabin": "outdoor",
    "camping": "outdoor",
    "resort": "luxury",
    "villa": "luxury",
    "hotel": "comfort",
    "apartment": "independent",
    "bnb": "local",
    "boat": "adventure",
}

# Activity sport types to interest categories
ACTIVITY_INTEREST_MAP = {
    "hiking": "hiking & nature",
    "walking": "walking tours",
    "running": "fitness",
    "cycling": "cycling",
    "swimming": "water sports",
    "surfing": "water sports",
    "kayaking": "water sports",
    "skiing": "winter sports",
    "snowboarding": "winter sports",
    "climbing": "adventure sports",
}


def build_auto_preference_profile(user) -> dict:
    """
    Automatically build preference profile from user's existing data.

    Analyzes:
    - Activities (sport types) → interests
    - Location categories → interests
    - Lodging types → trip style
    - Visited regions/cities → geographic preferences

    Returns dict with: cuisines, interests, trip_style, notes
    """
    profile = {
        "cuisines": None,
        "interests": [],
        "trip_style": None,
        "notes": None,
    }

    try:
        activity_interests = (
            Activity.objects.filter(user=user)
            .values("sport_type")
            .annotate(count=Count("id"))
            .exclude(sport_type__isnull=True)
            .exclude(sport_type="")
            .order_by("-count")[:5]
        )

        for activity in activity_interests:
            sport = activity["sport_type"]
            if sport:
                interest = ACTIVITY_INTEREST_MAP.get(
                    sport.lower(), sport.replace("_", " ")
                )
                if interest not in profile["interests"]:
                    profile["interests"].append(interest)

        category_interests = (
            Location.objects.filter(user=user)
            .values("category__name")
            .annotate(count=Count("id"))
            .exclude(category__name__isnull=True)
            .exclude(category__name="")
            .order_by("-count")[:5]
        )

        for category in category_interests:
            category_name = category["category__name"]
            if category_name and category_name.lower() not in [
                i.lower() for i in profile["interests"]
            ]:
                profile["interests"].append(category_name)

        top_lodging = (
            Lodging.objects.filter(user=user)
            .values("type")
            .annotate(count=Count("id"))
            .exclude(type__isnull=True)
            .exclude(type="")
            .order_by("-count")
            .first()
        )

        if top_lodging and top_lodging["type"]:
            lodging_type = top_lodging["type"].lower()
            profile["trip_style"] = LODGING_STYLE_MAP.get(lodging_type, lodging_type)

        top_regions = list(
            VisitedRegion.objects.filter(user=user)
            .values("region__name")
            .annotate(count=Count("id"))
            .exclude(region__name__isnull=True)
            .order_by("-count")[:3]
        )

        if top_regions:
            region_names = [r["region__name"] for r in top_regions if r["region__name"]]
            if region_names:
                profile["notes"] = f"Frequently visits: {', '.join(region_names)}"

        if not profile["notes"]:
            top_cities = list(
                VisitedCity.objects.filter(user=user)
                .values("city__name")
                .annotate(count=Count("id"))
                .exclude(city__name__isnull=True)
                .order_by("-count")[:3]
            )
            if top_cities:
                city_names = [c["city__name"] for c in top_cities if c["city__name"]]
                if city_names:
                    profile["notes"] = f"Frequently visits: {', '.join(city_names)}"

        profile["interests"] = profile["interests"][:8]
    except Exception as exc:
        logger.error("Error building auto profile for user %s: %s", user.id, exc)

    return profile


def update_auto_preference_profile(user) -> UserRecommendationPreferenceProfile:
    """
    Build and save auto-learned profile to database.
    Called automatically when chat starts.
    """
    auto_data = build_auto_preference_profile(user)

    profile, created = UserRecommendationPreferenceProfile.objects.update_or_create(
        user=user,
        defaults={
            "cuisines": auto_data["cuisines"],
            "interests": auto_data["interests"],
            "trip_style": auto_data["trip_style"],
            "notes": auto_data["notes"],
        },
    )

    logger.info(
        "%s auto profile for user %s",
        "Created" if created else "Updated",
        user.id,
    )
    return profile
