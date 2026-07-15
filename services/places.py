import math
import requests
from flask import current_app
from services.place_types import normalize_primary_types

PLACES_URI = "https://places.googleapis.com/v1/places:searchNearby"
MAX_RESULTS_PER_REQUEST = 20


def search_places(primary_types, center_lat, center_lng, radius_m, max_results=20):
    normalized_types, invalid_primary_types = normalize_primary_types(primary_types)
    if invalid_primary_types:
        raise ValueError(f"Invalid primary types: {', '.join(invalid_primary_types)}")
    if not normalized_types:
        return []

    api_key = current_app.config["GOOGLE_PLACES_API_KEY"]
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.primaryType,places.types,places.websiteUri,"
            "places.nationalPhoneNumber,places.location"
        ),
    }
    seen = {}

    for tile in _build_search_tiles(center_lat, center_lng, radius_m, max_results):
        body = {
            "includedPrimaryTypes": normalized_types,
            "maxResultCount": MAX_RESULTS_PER_REQUEST,
            "rankPreference": "POPULARITY",
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": tile["center_lat"],
                        "longitude": tile["center_lng"],
                    },
                    "radius": tile["radius_m"],
                }
            },
        }
        resp = requests.post(PLACES_URI, headers=headers, json=body, timeout=15)
        resp.raise_for_status()

        for place in resp.json().get("places", []):
            place_id = place.get("id")
            if not place_id:
                continue

            normalized = _normalize_place(place)
            if not _is_within_radius(
                normalized.get("lat"),
                normalized.get("lng"),
                center_lat,
                center_lng,
                radius_m,
            ):
                continue

            seen[place_id] = normalized

    results = list(seen.values())
    results.sort(key=lambda p: ((p.get("name") or "").lower(), p.get("formatted_address") or ""))
    return results[:max_results]


def _normalize_place(place: dict) -> dict:
    return {
        "place_id": place.get("id"),
        "name": place.get("displayName", {}).get("text"),
        "lat": place.get("location", {}).get("latitude"),
        "lng": place.get("location", {}).get("longitude"),
        "formatted_address": place.get("formattedAddress"),
        "primary_type": place.get("primaryType"),
        "types": place.get("types", []),
        "website": place.get("websiteUri"),
        "phone": place.get("nationalPhoneNumber"),
    }


def _build_search_tiles(center_lat: float, center_lng: float, radius_m: float, max_results: int) -> list[dict]:
    grid_size = _grid_size_for_search(radius_m, max_results)
    if grid_size == 1:
        return [{"center_lat": center_lat, "center_lng": center_lng, "radius_m": radius_m}]

    step_m = (2 * radius_m) / grid_size
    tile_radius_m = min(radius_m, max(1500.0, step_m * 0.9))
    offsets = [(-radius_m + (step_m / 2)) + (i * step_m) for i in range(grid_size)]

    tiles = [{
        "center_lat": center_lat,
        "center_lng": center_lng,
        "radius_m": tile_radius_m,
    }]

    for north_m in offsets:
        for east_m in offsets:
            if math.hypot(north_m, east_m) > radius_m + (step_m * 0.35):
                continue

            tile_lat = center_lat + _meters_to_lat_delta(north_m)
            tile_lng = center_lng + _meters_to_lng_delta(east_m, center_lat)
            if any(
                abs(tile["center_lat"] - tile_lat) < 1e-6 and abs(tile["center_lng"] - tile_lng) < 1e-6
                for tile in tiles
            ):
                continue

            tiles.append({
                "center_lat": tile_lat,
                "center_lng": tile_lng,
                "radius_m": tile_radius_m,
            })

    return tiles


def _grid_size_for_search(radius_m: float, max_results: int) -> int:
    if radius_m <= 3000 and max_results <= MAX_RESULTS_PER_REQUEST:
        return 1

    result_factor = math.sqrt(max(1, max_results) / MAX_RESULTS_PER_REQUEST)
    radius_factor = max(1.0, radius_m / 3000.0)
    return min(4, max(1, math.ceil(max(result_factor, radius_factor))))


def _is_within_radius(lat: float | None, lng: float | None, center_lat: float, center_lng: float, radius_m: float) -> bool:
    if lat is None or lng is None:
        return False
    return _distance_m(lat, lng, center_lat, center_lng) <= radius_m


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lng / 2) ** 2
    )
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _meters_to_lat_delta(meters: float) -> float:
    return meters / 111320.0


def _meters_to_lng_delta(meters: float, at_lat: float) -> float:
    scale = max(math.cos(math.radians(at_lat)), 0.1)
    return meters / (111320.0 * scale)
