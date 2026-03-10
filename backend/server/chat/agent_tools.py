import json
import inspect
import logging
from datetime import date as date_cls

import requests
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from adventures.models import Collection, CollectionItineraryItem, Location

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
        for item in collection.itinerary_items.all().order_by("date", "order"):
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


def _fetch_temperature_for_date(latitude, longitude, date_value):
    for url in (OPEN_METEO_ARCHIVE_URL, OPEN_METEO_FORECAST_URL):
        try:
            response = requests.get(
                url,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "start_date": date_value,
                    "end_date": date_value,
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "timezone": "UTC",
                },
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            continue
        except ValueError:
            continue

        daily = data.get("daily") or {}
        max_values = daily.get("temperature_2m_max") or []
        min_values = daily.get("temperature_2m_min") or []
        if not max_values or not min_values:
            continue

        try:
            avg = (float(max_values[0]) + float(min_values[0])) / 2
        except (TypeError, ValueError, IndexError):
            continue

        return {
            "date": date_value,
            "available": True,
            "temperature_c": round(avg, 1),
        }

    return {
        "date": date_value,
        "available": False,
        "temperature_c": None,
    }


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
            _fetch_temperature_for_date(latitude, longitude, date_value)
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
