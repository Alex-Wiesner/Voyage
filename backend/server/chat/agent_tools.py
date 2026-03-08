import json
import logging
from datetime import date as date_cls

import requests
from django.contrib.contenttypes.models import ContentType
from django.db import models

from adventures.models import Collection, CollectionItineraryItem, Location

logger = logging.getLogger(__name__)

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": "Search for places of interest near a location. Returns tourist attractions, restaurants, hotels, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Location name or address to search near",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["tourism", "food", "lodging"],
                        "description": "Category of places",
                    },
                    "radius": {
                        "type": "number",
                        "description": "Search radius in km (default 10)",
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_trips",
            "description": "List the user's trip collections with dates and descriptions",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trip_details",
            "description": "Get full details of a trip including all itinerary items, locations, transportation, and lodging",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection_id": {
                        "type": "string",
                        "description": "UUID of the collection/trip",
                    }
                },
                "required": ["collection_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_itinerary",
            "description": "Add a new location to a trip's itinerary on a specific date",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection_id": {
                        "type": "string",
                        "description": "UUID of the collection/trip",
                    },
                    "name": {"type": "string", "description": "Name of the location"},
                    "description": {
                        "type": "string",
                        "description": "Description of why to visit",
                    },
                    "latitude": {
                        "type": "number",
                        "description": "Latitude coordinate",
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Longitude coordinate",
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
                "required": ["collection_id", "name", "latitude", "longitude"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get temperature/weather data for a location on specific dates",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "description": "Latitude"},
                    "longitude": {"type": "number", "description": "Longitude"},
                    "dates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of dates in YYYY-MM-DD format",
                    },
                },
                "required": ["latitude", "longitude", "dates"],
            },
        },
    },
]

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


def search_places(user, **kwargs):
    try:
        location_name = kwargs.get("location")
        if not location_name:
            return {"error": "location is required"}

        category = kwargs.get("category") or "tourism"
        radius_km = float(kwargs.get("radius") or 10)
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


def list_trips(user, **kwargs):
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


def get_trip_details(user, **kwargs):
    try:
        collection_id = kwargs.get("collection_id")
        if not collection_id:
            return {"error": "collection_id is required"}

        collection = (
            Collection.objects.filter(user=user)
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
        return {"error": "Trip not found"}
    except Exception:
        logger.exception("get_trip_details failed")
        return {"error": "An unexpected error occurred while fetching trip details"}


def add_to_itinerary(user, **kwargs):
    try:
        collection_id = kwargs.get("collection_id")
        name = kwargs.get("name")
        latitude = kwargs.get("latitude")
        longitude = kwargs.get("longitude")
        description = kwargs.get("description")
        location_address = kwargs.get("location_address")
        date = kwargs.get("date")

        if not collection_id or not name or latitude is None or longitude is None:
            return {
                "error": "collection_id, name, latitude, and longitude are required"
            }

        collection = Collection.objects.get(id=collection_id, user=user)

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


def get_weather(user, **kwargs):
    try:
        raw_latitude = kwargs.get("latitude")
        raw_longitude = kwargs.get("longitude")
        if raw_latitude is None or raw_longitude is None:
            return {"error": "latitude and longitude are required"}

        latitude = float(raw_latitude)
        longitude = float(raw_longitude)
        dates = kwargs.get("dates") or []

        if not isinstance(dates, list) or not dates:
            return {"error": "dates must be a non-empty list"}

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


ALLOWED_KWARGS = {
    "search_places": {"location", "category", "radius"},
    "list_trips": set(),
    "get_trip_details": {"collection_id"},
    "add_to_itinerary": {
        "collection_id",
        "name",
        "description",
        "latitude",
        "longitude",
        "date",
        "location_address",
    },
    "get_weather": {"latitude", "longitude", "dates"},
}


def execute_tool(tool_name, user, **kwargs):
    tool_map = {
        "search_places": search_places,
        "list_trips": list_trips,
        "get_trip_details": get_trip_details,
        "add_to_itinerary": add_to_itinerary,
        "get_weather": get_weather,
    }

    tool_fn = tool_map.get(tool_name)
    if not tool_fn:
        return {"error": f"Unknown tool: {tool_name}"}

    allowed = ALLOWED_KWARGS.get(tool_name, set())
    filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed}

    try:
        return tool_fn(user, **filtered_kwargs)
    except Exception:
        logger.exception("Tool execution failed: %s", tool_name)
        return {"error": "An unexpected error occurred while executing the tool"}


def serialize_tool_result(result):
    try:
        return json.dumps(result)
    except TypeError:
        return json.dumps({"error": "Tool returned non-serializable data"})
