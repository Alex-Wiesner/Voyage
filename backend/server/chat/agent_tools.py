import json
import inspect
import logging
from datetime import date as date_cls, datetime

import requests
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from adventures.models import (
    Collection,
    CollectionItineraryItem,
    Lodging,
    Location,
    Transportation,
    Visit,
)
from adventures.utils.itinerary import reorder_itinerary_items
from adventures.utils.weather import fetch_daily_temperature

logger = logging.getLogger(__name__)

_REGISTERED_TOOLS = {}
_TOOL_SCHEMAS = []


def agent_tool(name: str, description: str, parameters: dict):
    """Decorator to register a function as an agent tool."""

    def decorator(func):
        _REGISTERED_TOOLS[name] = func

        required = [k for k, v in parameters.items() if v.get("required", False)]
        props = {
            k: {kk: vv for kk, vv in v.items() if kk != "required"}
            for k, v in parameters.items()
        }

        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }
        _TOOL_SCHEMAS.append(schema)

        return func

    return decorator


def get_tool_schemas() -> list:
    """Return all registered tool schemas for LLM."""
    return _TOOL_SCHEMAS.copy()


def get_registered_tools() -> dict:
    """Return all registered tool functions."""
    return _REGISTERED_TOOLS.copy()


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_HEADERS = {"User-Agent": "Voyage/1.0"}
LOCATION_COORD_TOLERANCE = 0.00001


def _get_accessible_collection(user, collection_id: str):
    return (
        Collection.objects.filter(Q(user=user) | Q(shared_with=user))
        .distinct()
        .get(id=collection_id)
    )


def _normalize_date_input(value):
    if value is None:
        return None
    if isinstance(value, date_cls):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    try:
        return date_cls.fromisoformat(raw[:10])
    except ValueError:
        return None


def _normalize_datetime_input(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    parsed = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None

    if parsed is None:
        parsed_date = _normalize_date_input(raw)
        if parsed_date is None:
            return None
        parsed = datetime.combine(parsed_date, datetime.min.time())

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

    return parsed


def _parse_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_exception_message(exc, fallback_message):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        for value in detail.values():
            if isinstance(value, (list, tuple)) and value:
                return str(value[0])
            if value:
                return str(value)
    elif isinstance(detail, (list, tuple)) and detail:
        return str(detail[0])
    elif detail:
        return str(detail)

    message = str(exc).strip()
    return message or fallback_message


def _serialize_lodging(lodging: Lodging):
    return {
        "id": str(lodging.id),
        "name": lodging.name,
        "type": lodging.type,
        "check_in": lodging.check_in.isoformat() if lodging.check_in else None,
        "check_out": lodging.check_out.isoformat() if lodging.check_out else None,
        "location": lodging.location or "",
        "latitude": float(lodging.latitude) if lodging.latitude is not None else None,
        "longitude": float(lodging.longitude)
        if lodging.longitude is not None
        else None,
    }


def _serialize_transportation(transportation: Transportation):
    return {
        "id": str(transportation.id),
        "name": transportation.name,
        "type": transportation.type,
        "date": transportation.date.isoformat() if transportation.date else None,
        "end_date": transportation.end_date.isoformat()
        if transportation.end_date
        else None,
        "from_location": transportation.from_location or "",
        "to_location": transportation.to_location or "",
        "origin_latitude": float(transportation.origin_latitude)
        if transportation.origin_latitude is not None
        else None,
        "origin_longitude": float(transportation.origin_longitude)
        if transportation.origin_longitude is not None
        else None,
        "destination_latitude": float(transportation.destination_latitude)
        if transportation.destination_latitude is not None
        else None,
        "destination_longitude": float(transportation.destination_longitude)
        if transportation.destination_longitude is not None
        else None,
    }


def _build_overpass_query(latitude, longitude, radius_meters, category):
    if category == "food":
        node_filter = '["amenity"~"restaurant|cafe|bar|fast_food"]'
    elif category == "lodging":
        node_filter = '["tourism"~"hotel|hostel|guest_house|motel|apartment"]'
    else:
        node_filter = '["tourism"~"attraction|museum|viewpoint|gallery|theme_park"]'

    return f"""
[out:json][timeout:25];
(
  node{node_filter}(around:{int(radius_meters)},{latitude},{longitude});
  way{node_filter}(around:{int(radius_meters)},{latitude},{longitude});
  relation{node_filter}(around:{int(radius_meters)},{latitude},{longitude});
);
out center 20;
"""


def _parse_address(tags):
    if not tags:
        return ""
    if tags.get("addr:full"):
        return tags["addr:full"]
    street = tags.get("addr:street", "")
    house = tags.get("addr:housenumber", "")
    city = (
        tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village") or ""
    )
    parts = [f"{street} {house}".strip(), city]
    return ", ".join([p for p in parts if p])


@agent_tool(
    name="search_places",
    description=(
        "Search for places of interest near a location. "
        "Required: provide a non-empty 'location' string (city, neighborhood, or address). "
        "Use category='food' for restaurants/dining, category='tourism' for attractions, "
        "and category='lodging' for hotels/stays."
    ),
    parameters={
        "location": {
            "type": "string",
            "description": "Location name or address to search near",
            "required": True,
        },
        "category": {
            "type": "string",
            "enum": ["tourism", "food", "lodging"],
            "description": "Place type: food (restaurants/dining), tourism (attractions), lodging (hotels/stays)",
        },
        "radius": {
            "type": "number",
            "description": "Search radius in km (default 10)",
        },
    },
)
def search_places(
    user,
    location: str | None = None,
    category: str = "tourism",
    radius: float = 10,
):
    try:
        location_name = location
        if not location_name:
            return {"error": "location is required"}

        category = category or "tourism"
        radius_km = float(radius or 10)
        radius_meters = max(500, min(int(radius_km * 1000), 50000))

        geocode_resp = requests.get(
            NOMINATIM_URL,
            params={"q": location_name, "format": "json", "limit": 1},
            headers=REQUEST_HEADERS,
            timeout=10,
        )
        geocode_resp.raise_for_status()
        geocode_data = geocode_resp.json()
        if not geocode_data:
            return {"error": f"Could not geocode location: {location_name}"}

        base_lat = float(geocode_data[0]["lat"])
        base_lon = float(geocode_data[0]["lon"])
        query = _build_overpass_query(base_lat, base_lon, radius_meters, category)

        overpass_resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=REQUEST_HEADERS,
            timeout=20,
        )
        overpass_resp.raise_for_status()
        overpass_data = overpass_resp.json()

        results = []
        for item in (overpass_data.get("elements") or [])[:20]:
            tags = item.get("tags") or {}
            name = tags.get("name")
            if not name:
                continue

            latitude = item.get("lat")
            longitude = item.get("lon")
            if latitude is None or longitude is None:
                center = item.get("center") or {}
                latitude = center.get("lat")
                longitude = center.get("lon")

            if latitude is None or longitude is None:
                continue

            results.append(
                {
                    "name": name,
                    "address": _parse_address(tags),
                    "latitude": latitude,
                    "longitude": longitude,
                    "category": category,
                }
            )

            if len(results) >= 5:
                break

        return {
            "location": location_name,
            "category": category,
            "results": results,
        }
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            return {"error": f"Places API request failed: {exc}", "retryable": False}
        return {"error": f"Places API request failed: {exc}"}
    except requests.RequestException as exc:
        return {"error": f"Places API request failed: {exc}"}
    except (TypeError, ValueError) as exc:
        return {"error": f"Invalid search parameters: {exc}"}
    except Exception:
        logger.exception("search_places failed")
        return {"error": "An unexpected error occurred during place search"}


@agent_tool(
    name="list_trips",
    description="List the user's trip collections with dates and descriptions",
    parameters={},
)
def list_trips(user):
    try:
        collections = Collection.objects.filter(user=user).prefetch_related("locations")
        trips = []
        for collection in collections:
            trips.append(
                {
                    "id": str(collection.id),
                    "name": collection.name,
                    "start_date": collection.start_date.isoformat()
                    if collection.start_date
                    else None,
                    "end_date": collection.end_date.isoformat()
                    if collection.end_date
                    else None,
                    "description": collection.description or "",
                    "location_count": collection.locations.count(),
                }
            )
        return {"trips": trips}
    except Exception:
        logger.exception("list_trips failed")
        return {"error": "An unexpected error occurred while listing trips"}


@agent_tool(
    name="web_search",
    description=(
        "Search the web for current travel information. "
        "Required: provide a non-empty 'query' string describing exactly what to look up. "
        "Use when you need up-to-date info that may not be in training data."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "The search query (e.g., 'best restaurants Paris 2024', 'weather Tokyo March')",
            "required": True,
        },
        "location_context": {
            "type": "string",
            "description": "Optional location to bias search results (e.g., 'Paris, France')",
        },
    },
)
def web_search(user, query: str, location_context: str | None = None) -> dict:
    """
    Search the web for current information about destinations, events, prices, etc.

    Args:
        user: The user making the request (for auth/logging)
        query: The search query
        location_context: Optional location to bias results

    Returns:
        dict with 'results' list or 'error' string
    """
    if not query:
        return {"error": "query is required", "results": []}

    try:
        from duckduckgo_search import DDGS  # type: ignore[import-not-found]

        full_query = query
        if location_context:
            full_query = f"{query} {location_context}"

        with DDGS() as ddgs:
            results = list(ddgs.text(full_query, max_results=5))

        formatted = []
        for result in results:
            formatted.append(
                {
                    "title": result.get("title", ""),
                    "snippet": result.get("body", ""),
                    "url": result.get("href", ""),
                }
            )

        return {"results": formatted}

    except ImportError:
        return {
            "error": "Web search is not available (duckduckgo-search not installed)",
            "results": [],
            "retryable": False,
        }
    except Exception as exc:
        error_str = str(exc).lower()
        if "rate" in error_str or "limit" in error_str:
            return {
                "error": "Search rate limit reached. Please wait a moment and try again.",
                "results": [],
            }
        logger.error("Web search error: %s", exc)
        return {"error": "Web search failed. Please try again.", "results": []}


@agent_tool(
    name="get_trip_details",
    description="Get full details of a trip including all itinerary items, locations, transportation, and lodging",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        }
    },
)
def get_trip_details(user, collection_id: str | None = None):
    try:
        if not collection_id:
            return {"error": "collection_id is required"}

        collection = (
            Collection.objects.filter(Q(user=user) | Q(shared_with=user))
            .distinct()
            .prefetch_related(
                "locations",
                "transportation_set",
                "lodging_set",
                "itinerary_items__content_type",
            )
            .get(id=collection_id)
        )

        itinerary = []
        for item in collection.itinerary_items.all():
            content_obj = item.item
            itinerary.append(
                {
                    "id": str(item.id),
                    "date": item.date.isoformat() if item.date else None,
                    "order": item.order,
                    "is_global": item.is_global,
                    "content_type": item.content_type.model,
                    "object_id": str(item.object_id),
                    "name": getattr(content_obj, "name", ""),
                }
            )

        return {
            "trip": {
                "id": str(collection.id),
                "name": collection.name,
                "description": collection.description or "",
                "start_date": collection.start_date.isoformat()
                if collection.start_date
                else None,
                "end_date": collection.end_date.isoformat()
                if collection.end_date
                else None,
                "locations": [
                    {
                        "id": str(location.id),
                        "name": location.name,
                        "description": location.description or "",
                        "location": location.location or "",
                        "latitude": float(location.latitude)
                        if location.latitude is not None
                        else None,
                        "longitude": float(location.longitude)
                        if location.longitude is not None
                        else None,
                    }
                    for location in collection.locations.all()
                ],
                "transportation": [
                    {
                        "id": str(t.id),
                        "name": t.name,
                        "type": t.type,
                        "date": t.date.isoformat() if t.date else None,
                        "end_date": t.end_date.isoformat() if t.end_date else None,
                    }
                    for t in collection.transportation_set.all()
                ],
                "lodging": [
                    {
                        "id": str(l.id),
                        "name": l.name,
                        "type": l.type,
                        "check_in": l.check_in.isoformat() if l.check_in else None,
                        "check_out": l.check_out.isoformat() if l.check_out else None,
                        "location": l.location or "",
                    }
                    for l in collection.lodging_set.all()
                ],
                "itinerary": itinerary,
            }
        }
    except Collection.DoesNotExist:
        return {
            "error": "collection_id is required and must reference a trip you can access"
        }
    except Exception:
        logger.exception("get_trip_details failed")
        return {"error": "An unexpected error occurred while fetching trip details"}


@agent_tool(
    name="add_to_itinerary",
    description="Add a new location to a trip's itinerary on a specific date",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "name": {
            "type": "string",
            "description": "Name of the location",
            "required": True,
        },
        "description": {
            "type": "string",
            "description": "Description of why to visit",
        },
        "latitude": {
            "type": "number",
            "description": "Latitude coordinate",
            "required": True,
        },
        "longitude": {
            "type": "number",
            "description": "Longitude coordinate",
            "required": True,
        },
        "date": {
            "type": "string",
            "description": "Date in YYYY-MM-DD format",
        },
        "location_address": {
            "type": "string",
            "description": "Full address of the location",
        },
    },
)
def add_to_itinerary(
    user,
    collection_id: str | None = None,
    name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    description: str | None = None,
    date: str | None = None,
    location_address: str | None = None,
):
    try:
        if not collection_id or not name or latitude is None or longitude is None:
            return {
                "error": "collection_id, name, latitude, and longitude are required"
            }

        collection = (
            Collection.objects.filter(Q(user=user) | Q(shared_with=user))
            .distinct()
            .get(id=collection_id)
        )

        itinerary_date = date
        if not itinerary_date:
            if collection.start_date:
                itinerary_date = collection.start_date.isoformat()
            else:
                itinerary_date = date_cls.today().isoformat()

        try:
            itinerary_date_obj = date_cls.fromisoformat(itinerary_date)
        except ValueError:
            return {"error": "date must be in YYYY-MM-DD format"}

        latitude_min = latitude - LOCATION_COORD_TOLERANCE
        latitude_max = latitude + LOCATION_COORD_TOLERANCE
        longitude_min = longitude - LOCATION_COORD_TOLERANCE
        longitude_max = longitude + LOCATION_COORD_TOLERANCE

        location = (
            Location.objects.filter(
                user=user,
                name=name,
                latitude__gte=latitude_min,
                latitude__lte=latitude_max,
                longitude__gte=longitude_min,
                longitude__lte=longitude_max,
            )
            .order_by("created_at")
            .first()
        )

        if location is None:
            location = Location.objects.create(
                user=user,
                name=name,
                latitude=latitude,
                longitude=longitude,
                description=description or "",
                location=location_address or "",
            )

        collection.locations.add(location)
        content_type = ContentType.objects.get_for_model(Location)

        existing_item = CollectionItineraryItem.objects.filter(
            collection=collection,
            content_type=content_type,
            object_id=location.id,
            date=itinerary_date_obj,
            is_global=False,
        ).first()

        if existing_item:
            return {
                "success": True,
                "note": "Location is already in the itinerary for this date",
                "location": {
                    "id": str(location.id),
                    "name": location.name,
                    "latitude": float(location.latitude),
                    "longitude": float(location.longitude),
                },
                "itinerary_item": {
                    "id": str(existing_item.id),
                    "date": itinerary_date_obj.isoformat(),
                    "order": existing_item.order,
                },
            }

        max_order = (
            CollectionItineraryItem.objects.filter(
                collection=collection,
                date=itinerary_date_obj,
                is_global=False,
            ).aggregate(models.Max("order"))["order__max"]
            or 0
        )

        itinerary_item = CollectionItineraryItem.objects.create(
            collection=collection,
            content_type=content_type,
            object_id=location.id,
            date=itinerary_date_obj,
            order=max_order + 1,
        )

        return {
            "success": True,
            "location": {
                "id": str(location.id),
                "name": location.name,
                "latitude": float(location.latitude),
                "longitude": float(location.longitude),
            },
            "itinerary_item": {
                "id": str(itinerary_item.id),
                "date": itinerary_date_obj.isoformat(),
                "order": itinerary_item.order,
            },
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("add_to_itinerary failed")
        return {"error": "An unexpected error occurred while adding to itinerary"}


@agent_tool(
    name="move_itinerary_item",
    description="Move or reorder an existing itinerary item to another day/order in a trip",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "itinerary_item_id": {
            "type": "string",
            "description": "UUID of the itinerary item to move",
            "required": True,
        },
        "date": {
            "type": "string",
            "description": "Target date in YYYY-MM-DD format",
            "required": True,
        },
        "order": {
            "type": "number",
            "description": "Optional zero-based position for the target day",
        },
    },
)
def move_itinerary_item(
    user,
    collection_id: str | None = None,
    itinerary_item_id: str | None = None,
    date: str | None = None,
    order: int | None = None,
):
    try:
        if not collection_id or not itinerary_item_id or not date:
            return {"error": "collection_id, itinerary_item_id, and date are required"}

        collection = _get_accessible_collection(user, collection_id)
        target_date = _normalize_date_input(date)
        if target_date is None:
            return {"error": "date must be in YYYY-MM-DD format"}

        itinerary_item = CollectionItineraryItem.objects.filter(
            collection=collection,
            id=itinerary_item_id,
        ).first()
        if itinerary_item is None:
            return {"error": "Itinerary item not found"}

        desired_order = None
        if order is not None:
            try:
                desired_order = int(order)
            except (TypeError, ValueError):
                return {"error": "order must be numeric"}
            desired_order = max(0, desired_order)

        source_date = itinerary_item.date
        target_items = list(
            CollectionItineraryItem.objects.filter(
                collection=collection,
                date=target_date,
                is_global=False,
            )
            .exclude(id=itinerary_item.id)
            .order_by("order")
        )

        insert_at = len(target_items)
        if desired_order is not None:
            insert_at = min(desired_order, len(target_items))

        updates = []
        for idx, item in enumerate(target_items):
            if idx == insert_at:
                updates.append(
                    {
                        "id": str(itinerary_item.id),
                        "date": target_date,
                        "order": insert_at,
                        "is_global": False,
                    }
                )
            updates.append(
                {
                    "id": str(item.id),
                    "date": target_date,
                    "order": idx + (1 if idx >= insert_at else 0),
                    "is_global": False,
                }
            )

        if insert_at == len(target_items):
            updates.append(
                {
                    "id": str(itinerary_item.id),
                    "date": target_date,
                    "order": insert_at,
                    "is_global": False,
                }
            )

        if source_date and source_date != target_date:
            remaining_source = CollectionItineraryItem.objects.filter(
                collection=collection,
                date=source_date,
                is_global=False,
            ).exclude(id=itinerary_item.id)
            for idx, item in enumerate(remaining_source.order_by("order")):
                updates.append(
                    {
                        "id": str(item.id),
                        "date": source_date,
                        "order": idx,
                        "is_global": False,
                    }
                )

        try:
            updated_items = reorder_itinerary_items(user, updates)
        except ValidationError as exc:
            return {
                "error": _extract_exception_message(
                    exc,
                    "Unable to move itinerary item due to invalid itinerary update",
                )
            }
        except PermissionDenied as exc:
            return {
                "error": _extract_exception_message(
                    exc,
                    "You do not have permission to modify this itinerary item",
                )
            }

        moved_item = next(
            (item for item in updated_items if str(item.id) == str(itinerary_item.id)),
            itinerary_item,
        )
        moved_date = _normalize_date_input(getattr(moved_item, "date", None))
        return {
            "success": True,
            "itinerary_item": {
                "id": str(moved_item.id),
                "date": moved_date.isoformat() if moved_date else None,
                "order": moved_item.order,
            },
            "source_date": source_date.isoformat() if source_date else None,
            "target_date": target_date.isoformat(),
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("move_itinerary_item failed")
        return {"error": "An unexpected error occurred while moving itinerary item"}


@agent_tool(
    name="remove_itinerary_item",
    description="Remove an itinerary item from a trip day",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "itinerary_item_id": {
            "type": "string",
            "description": "UUID of the itinerary item to remove",
            "required": True,
        },
    },
)
def remove_itinerary_item(
    user,
    collection_id: str | None = None,
    itinerary_item_id: str | None = None,
):
    try:
        if not collection_id or not itinerary_item_id:
            return {"error": "collection_id and itinerary_item_id are required"}

        collection = _get_accessible_collection(user, collection_id)
        itinerary_item = CollectionItineraryItem.objects.filter(
            collection=collection,
            id=itinerary_item_id,
        ).first()
        if itinerary_item is None:
            return {"error": "Itinerary item not found"}

        object_type = itinerary_item.content_type.model
        deleted_visit_count = 0

        if object_type == "location" and itinerary_item.date:
            location = Location.objects.filter(id=itinerary_item.object_id).first()
            if location:
                visits = Visit.objects.filter(
                    location=location,
                    start_date__date=itinerary_item.date,
                )
                deleted_visit_count = visits.count()
                visits.delete()

        itinerary_item.delete()

        return {
            "success": True,
            "removed_itinerary_item_id": itinerary_item_id,
            "removed_object_type": object_type,
            "deleted_visit_count": deleted_visit_count,
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("remove_itinerary_item failed")
        return {"error": "An unexpected error occurred while removing itinerary item"}


@agent_tool(
    name="update_location_details",
    description="Update itinerary-relevant details for a location in a trip",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "location_id": {
            "type": "string",
            "description": "UUID of the location",
            "required": True,
        },
        "name": {"type": "string", "description": "Updated location name"},
        "description": {
            "type": "string",
            "description": "Updated location description",
        },
        "location": {"type": "string", "description": "Updated address/location text"},
        "latitude": {"type": "number", "description": "Updated latitude"},
        "longitude": {"type": "number", "description": "Updated longitude"},
    },
)
def update_location_details(
    user,
    collection_id: str | None = None,
    location_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    location: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
):
    try:
        if not collection_id or not location_id:
            return {"error": "collection_id and location_id are required"}

        collection = _get_accessible_collection(user, collection_id)
        location_obj = collection.locations.filter(id=location_id).first()
        if location_obj is None:
            return {"error": "Location not found in this trip"}

        updated_fields = []
        if isinstance(name, str) and name.strip():
            location_obj.name = name.strip()
            updated_fields.append("name")
        if description is not None:
            location_obj.description = str(description)
            updated_fields.append("description")
        if location is not None:
            location_obj.location = str(location)
            updated_fields.append("location")

        parsed_lat = _parse_float(latitude)
        parsed_lon = _parse_float(longitude)
        if latitude is not None and parsed_lat is None:
            return {"error": "latitude must be numeric"}
        if longitude is not None and parsed_lon is None:
            return {"error": "longitude must be numeric"}
        if latitude is not None:
            location_obj.latitude = parsed_lat
            updated_fields.append("latitude")
        if longitude is not None:
            location_obj.longitude = parsed_lon
            updated_fields.append("longitude")

        if not updated_fields:
            return {"error": "At least one field to update is required"}

        location_obj.save(update_fields=updated_fields)

        return {
            "success": True,
            "location": {
                "id": str(location_obj.id),
                "name": location_obj.name,
                "description": location_obj.description or "",
                "location": location_obj.location or "",
                "latitude": float(location_obj.latitude)
                if location_obj.latitude is not None
                else None,
                "longitude": float(location_obj.longitude)
                if location_obj.longitude is not None
                else None,
            },
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("update_location_details failed")
        return {"error": "An unexpected error occurred while updating location"}


@agent_tool(
    name="add_lodging",
    description="Add a lodging stay to a trip and optionally add it to itinerary day",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "name": {"type": "string", "description": "Lodging name", "required": True},
        "type": {
            "type": "string",
            "description": "Lodging type (hotel, hostel, resort, bnb, campground, cabin, apartment, house, villa, motel, other)",
        },
        "location": {"type": "string", "description": "Address or location text"},
        "check_in": {
            "type": "string",
            "description": "Check-in datetime or date (ISO format)",
        },
        "check_out": {
            "type": "string",
            "description": "Check-out datetime or date (ISO format)",
        },
        "latitude": {"type": "number", "description": "Latitude"},
        "longitude": {"type": "number", "description": "Longitude"},
        "itinerary_date": {
            "type": "string",
            "description": "Optional day in YYYY-MM-DD to add this lodging to itinerary",
        },
    },
)
def add_lodging(
    user,
    collection_id: str | None = None,
    name: str | None = None,
    type: str | None = None,
    location: str | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    itinerary_date: str | None = None,
):
    try:
        if not collection_id or not name:
            return {"error": "collection_id and name are required"}

        collection = _get_accessible_collection(user, collection_id)

        parsed_check_in = _normalize_datetime_input(check_in)
        parsed_check_out = _normalize_datetime_input(check_out)
        if check_in and parsed_check_in is None:
            return {"error": "check_in must be a valid ISO date or datetime"}
        if check_out and parsed_check_out is None:
            return {"error": "check_out must be a valid ISO date or datetime"}

        parsed_lat = _parse_float(latitude)
        parsed_lon = _parse_float(longitude)
        if latitude is not None and parsed_lat is None:
            return {"error": "latitude must be numeric"}
        if longitude is not None and parsed_lon is None:
            return {"error": "longitude must be numeric"}

        lodging = Lodging.objects.create(
            user=collection.user,
            collection=collection,
            name=name,
            type=(type or "other"),
            location=location or "",
            check_in=parsed_check_in,
            check_out=parsed_check_out,
            latitude=parsed_lat,
            longitude=parsed_lon,
        )

        itinerary_item = None
        if itinerary_date:
            itinerary_day = _normalize_date_input(itinerary_date)
            if itinerary_day is None:
                return {"error": "itinerary_date must be in YYYY-MM-DD format"}

            max_order = (
                CollectionItineraryItem.objects.filter(
                    collection=collection,
                    date=itinerary_day,
                    is_global=False,
                ).aggregate(models.Max("order"))["order__max"]
                or 0
            )
            itinerary_item = CollectionItineraryItem.objects.create(
                collection=collection,
                content_type=ContentType.objects.get_for_model(Lodging),
                object_id=lodging.id,
                date=itinerary_day,
                order=max_order + 1,
            )

        return {
            "success": True,
            "lodging": _serialize_lodging(lodging),
            "itinerary_item": {
                "id": str(itinerary_item.id),
                "date": itinerary_item.date.isoformat() if itinerary_item else None,
                "order": itinerary_item.order if itinerary_item else None,
            }
            if itinerary_item
            else None,
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("add_lodging failed")
        return {"error": "An unexpected error occurred while adding lodging"}


@agent_tool(
    name="update_lodging",
    description="Update lodging details for an existing trip lodging item",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "lodging_id": {
            "type": "string",
            "description": "UUID of the lodging",
            "required": True,
        },
        "name": {"type": "string", "description": "Updated lodging name"},
        "type": {"type": "string", "description": "Updated lodging type"},
        "location": {"type": "string", "description": "Updated location text"},
        "check_in": {
            "type": "string",
            "description": "Updated check-in datetime/date (ISO)",
        },
        "check_out": {
            "type": "string",
            "description": "Updated check-out datetime/date (ISO)",
        },
        "latitude": {"type": "number", "description": "Updated latitude"},
        "longitude": {"type": "number", "description": "Updated longitude"},
    },
)
def update_lodging(
    user,
    collection_id: str | None = None,
    lodging_id: str | None = None,
    name: str | None = None,
    type: str | None = None,
    location: str | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
):
    try:
        if not collection_id or not lodging_id:
            return {"error": "collection_id and lodging_id are required"}

        collection = _get_accessible_collection(user, collection_id)
        lodging = Lodging.objects.filter(id=lodging_id, collection=collection).first()
        if lodging is None:
            return {"error": "Lodging not found"}

        updates = []
        if isinstance(name, str) and name.strip():
            lodging.name = name.strip()
            updates.append("name")
        if isinstance(type, str) and type.strip():
            lodging.type = type.strip()
            updates.append("type")
        if location is not None:
            lodging.location = str(location)
            updates.append("location")

        parsed_check_in = _normalize_datetime_input(check_in)
        parsed_check_out = _normalize_datetime_input(check_out)
        if check_in is not None and parsed_check_in is None:
            return {"error": "check_in must be a valid ISO date or datetime"}
        if check_out is not None and parsed_check_out is None:
            return {"error": "check_out must be a valid ISO date or datetime"}
        if check_in is not None:
            lodging.check_in = parsed_check_in
            updates.append("check_in")
        if check_out is not None:
            lodging.check_out = parsed_check_out
            updates.append("check_out")

        parsed_lat = _parse_float(latitude)
        parsed_lon = _parse_float(longitude)
        if latitude is not None and parsed_lat is None:
            return {"error": "latitude must be numeric"}
        if longitude is not None and parsed_lon is None:
            return {"error": "longitude must be numeric"}
        if latitude is not None:
            lodging.latitude = parsed_lat
            updates.append("latitude")
        if longitude is not None:
            lodging.longitude = parsed_lon
            updates.append("longitude")

        if not updates:
            return {"error": "At least one field to update is required"}

        lodging.save(update_fields=updates)
        return {"success": True, "lodging": _serialize_lodging(lodging)}
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("update_lodging failed")
        return {"error": "An unexpected error occurred while updating lodging"}


@agent_tool(
    name="remove_lodging",
    description="Remove a lodging record from a trip",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "lodging_id": {
            "type": "string",
            "description": "UUID of the lodging",
            "required": True,
        },
    },
)
def remove_lodging(
    user,
    collection_id: str | None = None,
    lodging_id: str | None = None,
):
    try:
        if not collection_id or not lodging_id:
            return {"error": "collection_id and lodging_id are required"}

        collection = _get_accessible_collection(user, collection_id)
        lodging = Lodging.objects.filter(id=lodging_id, collection=collection).first()
        if lodging is None:
            return {"error": "Lodging not found"}

        itinerary_deleted = CollectionItineraryItem.objects.filter(
            collection=collection,
            content_type=ContentType.objects.get_for_model(Lodging),
            object_id=lodging.id,
        ).delete()[0]
        lodging.delete()
        return {
            "success": True,
            "removed_lodging_id": lodging_id,
            "removed_itinerary_items": itinerary_deleted,
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("remove_lodging failed")
        return {"error": "An unexpected error occurred while removing lodging"}


@agent_tool(
    name="add_transportation",
    description="Add transportation to a trip and optionally add it to itinerary day",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "name": {
            "type": "string",
            "description": "Transportation name",
            "required": True,
        },
        "type": {
            "type": "string",
            "description": "Transportation type (car, plane, train, bus, boat, bike, walking, other)",
            "required": True,
        },
        "date": {
            "type": "string",
            "description": "Departure datetime/date (ISO)",
        },
        "end_date": {
            "type": "string",
            "description": "Arrival datetime/date (ISO)",
        },
        "from_location": {"type": "string", "description": "Origin location text"},
        "to_location": {"type": "string", "description": "Destination location text"},
        "origin_latitude": {"type": "number", "description": "Origin latitude"},
        "origin_longitude": {"type": "number", "description": "Origin longitude"},
        "destination_latitude": {
            "type": "number",
            "description": "Destination latitude",
        },
        "destination_longitude": {
            "type": "number",
            "description": "Destination longitude",
        },
        "itinerary_date": {
            "type": "string",
            "description": "Optional day in YYYY-MM-DD to add this transportation to itinerary",
        },
    },
)
def add_transportation(
    user,
    collection_id: str | None = None,
    name: str | None = None,
    type: str | None = None,
    date: str | None = None,
    end_date: str | None = None,
    from_location: str | None = None,
    to_location: str | None = None,
    origin_latitude: float | None = None,
    origin_longitude: float | None = None,
    destination_latitude: float | None = None,
    destination_longitude: float | None = None,
    itinerary_date: str | None = None,
):
    try:
        if not collection_id or not name or not type:
            return {"error": "collection_id, name, and type are required"}

        collection = _get_accessible_collection(user, collection_id)

        parsed_date = _normalize_datetime_input(date)
        parsed_end_date = _normalize_datetime_input(end_date)
        if date and parsed_date is None:
            return {"error": "date must be a valid ISO date or datetime"}
        if end_date and parsed_end_date is None:
            return {"error": "end_date must be a valid ISO date or datetime"}

        parsed_origin_lat = _parse_float(origin_latitude)
        parsed_origin_lon = _parse_float(origin_longitude)
        parsed_destination_lat = _parse_float(destination_latitude)
        parsed_destination_lon = _parse_float(destination_longitude)
        if origin_latitude is not None and parsed_origin_lat is None:
            return {"error": "origin_latitude must be numeric"}
        if origin_longitude is not None and parsed_origin_lon is None:
            return {"error": "origin_longitude must be numeric"}
        if destination_latitude is not None and parsed_destination_lat is None:
            return {"error": "destination_latitude must be numeric"}
        if destination_longitude is not None and parsed_destination_lon is None:
            return {"error": "destination_longitude must be numeric"}

        transportation = Transportation.objects.create(
            user=collection.user,
            collection=collection,
            name=name,
            type=type,
            date=parsed_date,
            end_date=parsed_end_date,
            from_location=from_location or "",
            to_location=to_location or "",
            origin_latitude=parsed_origin_lat,
            origin_longitude=parsed_origin_lon,
            destination_latitude=parsed_destination_lat,
            destination_longitude=parsed_destination_lon,
        )

        itinerary_item = None
        if itinerary_date:
            itinerary_day = _normalize_date_input(itinerary_date)
            if itinerary_day is None:
                return {"error": "itinerary_date must be in YYYY-MM-DD format"}

            max_order = (
                CollectionItineraryItem.objects.filter(
                    collection=collection,
                    date=itinerary_day,
                    is_global=False,
                ).aggregate(models.Max("order"))["order__max"]
                or 0
            )
            itinerary_item = CollectionItineraryItem.objects.create(
                collection=collection,
                content_type=ContentType.objects.get_for_model(Transportation),
                object_id=transportation.id,
                date=itinerary_day,
                order=max_order + 1,
            )

        return {
            "success": True,
            "transportation": _serialize_transportation(transportation),
            "itinerary_item": {
                "id": str(itinerary_item.id),
                "date": itinerary_item.date.isoformat() if itinerary_item else None,
                "order": itinerary_item.order if itinerary_item else None,
            }
            if itinerary_item
            else None,
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("add_transportation failed")
        return {"error": "An unexpected error occurred while adding transportation"}


@agent_tool(
    name="update_transportation",
    description="Update details for an existing transportation item",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "transportation_id": {
            "type": "string",
            "description": "UUID of the transportation",
            "required": True,
        },
        "name": {"type": "string", "description": "Updated transportation name"},
        "type": {"type": "string", "description": "Updated transportation type"},
        "date": {"type": "string", "description": "Updated departure datetime/date"},
        "end_date": {
            "type": "string",
            "description": "Updated arrival datetime/date",
        },
        "from_location": {
            "type": "string",
            "description": "Updated origin location text",
        },
        "to_location": {
            "type": "string",
            "description": "Updated destination location text",
        },
        "origin_latitude": {"type": "number", "description": "Updated origin latitude"},
        "origin_longitude": {
            "type": "number",
            "description": "Updated origin longitude",
        },
        "destination_latitude": {
            "type": "number",
            "description": "Updated destination latitude",
        },
        "destination_longitude": {
            "type": "number",
            "description": "Updated destination longitude",
        },
    },
)
def update_transportation(
    user,
    collection_id: str | None = None,
    transportation_id: str | None = None,
    name: str | None = None,
    type: str | None = None,
    date: str | None = None,
    end_date: str | None = None,
    from_location: str | None = None,
    to_location: str | None = None,
    origin_latitude: float | None = None,
    origin_longitude: float | None = None,
    destination_latitude: float | None = None,
    destination_longitude: float | None = None,
):
    try:
        if not collection_id or not transportation_id:
            return {"error": "collection_id and transportation_id are required"}

        collection = _get_accessible_collection(user, collection_id)
        transportation = Transportation.objects.filter(
            id=transportation_id,
            collection=collection,
        ).first()
        if transportation is None:
            return {"error": "Transportation not found"}

        updates = []
        if isinstance(name, str) and name.strip():
            transportation.name = name.strip()
            updates.append("name")
        if isinstance(type, str) and type.strip():
            transportation.type = type.strip()
            updates.append("type")
        if from_location is not None:
            transportation.from_location = str(from_location)
            updates.append("from_location")
        if to_location is not None:
            transportation.to_location = str(to_location)
            updates.append("to_location")

        parsed_date = _normalize_datetime_input(date)
        parsed_end_date = _normalize_datetime_input(end_date)
        if date is not None and parsed_date is None:
            return {"error": "date must be a valid ISO date or datetime"}
        if end_date is not None and parsed_end_date is None:
            return {"error": "end_date must be a valid ISO date or datetime"}
        if date is not None:
            transportation.date = parsed_date
            updates.append("date")
        if end_date is not None:
            transportation.end_date = parsed_end_date
            updates.append("end_date")

        parsed_origin_lat = _parse_float(origin_latitude)
        parsed_origin_lon = _parse_float(origin_longitude)
        parsed_destination_lat = _parse_float(destination_latitude)
        parsed_destination_lon = _parse_float(destination_longitude)
        if origin_latitude is not None and parsed_origin_lat is None:
            return {"error": "origin_latitude must be numeric"}
        if origin_longitude is not None and parsed_origin_lon is None:
            return {"error": "origin_longitude must be numeric"}
        if destination_latitude is not None and parsed_destination_lat is None:
            return {"error": "destination_latitude must be numeric"}
        if destination_longitude is not None and parsed_destination_lon is None:
            return {"error": "destination_longitude must be numeric"}
        if origin_latitude is not None:
            transportation.origin_latitude = parsed_origin_lat
            updates.append("origin_latitude")
        if origin_longitude is not None:
            transportation.origin_longitude = parsed_origin_lon
            updates.append("origin_longitude")
        if destination_latitude is not None:
            transportation.destination_latitude = parsed_destination_lat
            updates.append("destination_latitude")
        if destination_longitude is not None:
            transportation.destination_longitude = parsed_destination_lon
            updates.append("destination_longitude")

        if not updates:
            return {"error": "At least one field to update is required"}

        transportation.save(update_fields=updates)
        return {
            "success": True,
            "transportation": _serialize_transportation(transportation),
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("update_transportation failed")
        return {"error": "An unexpected error occurred while updating transportation"}


@agent_tool(
    name="remove_transportation",
    description="Remove transportation from a trip",
    parameters={
        "collection_id": {
            "type": "string",
            "description": "UUID of the collection/trip",
            "required": True,
        },
        "transportation_id": {
            "type": "string",
            "description": "UUID of the transportation",
            "required": True,
        },
    },
)
def remove_transportation(
    user,
    collection_id: str | None = None,
    transportation_id: str | None = None,
):
    try:
        if not collection_id or not transportation_id:
            return {"error": "collection_id and transportation_id are required"}

        collection = _get_accessible_collection(user, collection_id)
        transportation = Transportation.objects.filter(
            id=transportation_id,
            collection=collection,
        ).first()
        if transportation is None:
            return {"error": "Transportation not found"}

        itinerary_deleted = CollectionItineraryItem.objects.filter(
            collection=collection,
            content_type=ContentType.objects.get_for_model(Transportation),
            object_id=transportation.id,
        ).delete()[0]
        transportation.delete()
        return {
            "success": True,
            "removed_transportation_id": transportation_id,
            "removed_itinerary_items": itinerary_deleted,
        }
    except Collection.DoesNotExist:
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("remove_transportation failed")
        return {"error": "An unexpected error occurred while removing transportation"}


@agent_tool(
    name="get_weather",
    description="Get temperature/weather data for a location on specific dates",
    parameters={
        "latitude": {"type": "number", "description": "Latitude", "required": True},
        "longitude": {
            "type": "number",
            "description": "Longitude",
            "required": True,
        },
        "dates": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of dates in YYYY-MM-DD format",
            "required": True,
        },
    },
)
def get_weather(user, latitude=None, longitude=None, dates=None):
    try:
        raw_latitude = latitude
        raw_longitude = longitude
        if raw_latitude is None or raw_longitude is None:
            return {"error": "latitude and longitude are required"}

        latitude = float(raw_latitude)
        longitude = float(raw_longitude)
        dates = dates or []

        if not isinstance(dates, list) or not dates:
            return {"error": "dates is required"}

        results = [
            fetch_daily_temperature(
                date=date_value, latitude=latitude, longitude=longitude
            )
            for date_value in dates
        ]
        return {
            "latitude": latitude,
            "longitude": longitude,
            "results": results,
        }
    except (TypeError, ValueError):
        return {"error": "latitude and longitude must be numeric"}
    except Exception:
        logger.exception("get_weather failed")
        return {"error": "An unexpected error occurred while fetching weather data"}


def execute_tool(tool_name, user, **kwargs):
    if tool_name not in _REGISTERED_TOOLS:
        return {"error": f"Unknown tool: {tool_name}"}

    tool_fn = _REGISTERED_TOOLS[tool_name]

    sig = inspect.signature(tool_fn)
    allowed = set(sig.parameters.keys()) - {"user"}
    filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed}

    try:
        return tool_fn(user=user, **filtered_kwargs)
    except Exception:
        logger.exception("Tool %s failed", tool_name)
        return {"error": "Tool execution failed"}


AGENT_TOOLS = get_tool_schemas()


def serialize_tool_result(result):
    try:
        return json.dumps(result)
    except TypeError:
        return json.dumps({"error": "Tool returned non-serializable data"})
