"""Provider-neutral geocoding and straight-line organization distances.

Set GEOCODER_LAMBDA_NAME to an approved adapter when one is available. An
optional GEOCODE_CACHE_TABLE stores successful coordinates across cold starts.
Without a configured provider, address-only results are marked ``deferred``.
"""

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping


EARTH_RADIUS_MILES = 3958.7613
_MEMORY_CACHE = {}


def _pair(latitude, longitude):
    try:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            return None
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def parse_coordinates(value):
    """Return (latitude, longitude) from supported DB/GenAI location forms."""
    if isinstance(value, Mapping):
        lat = value.get("latitude", value.get("lat"))
        lon = value.get("longitude", value.get("lon", value.get("lng")))
        if lat is not None and lon is not None:
            return _pair(lat, lon)
        coordinates = value.get("coordinates")
        if isinstance(coordinates, (list, tuple)) and len(coordinates) == 2:
            return _pair(coordinates[1], coordinates[0])  # GeoJSON lon, lat
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _pair(value[0], value[1])
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except ValueError:
        decoded = None
    if decoded is not None:
        return parse_coordinates(decoded)
    pattern = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    lat = re.search(r"\blat(?:itude)?\s*[:=]\s*(" + pattern + r")", text, re.I)
    lon = re.search(r"\blon(?:gitude)?\s*[:=]\s*(" + pattern + r")", text, re.I)
    if lat and lon:
        return _pair(lat.group(1), lon.group(1))
    point = re.fullmatch(
        r"(?:SRID=4326;)?POINT\s*\(\s*(" + pattern + r")\s+(" + pattern + r")\s*\)",
        text, re.I,
    )
    return _pair(point.group(2), point.group(1)) if point else None


def haversine_miles(origin, destination):
    """Great-circle (not driving) distance; identical points are a valid zero."""
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return EARTH_RADIUS_MILES * 2 * math.asin(min(1, math.sqrt(a)))


def address_from_parts(row, fields):
    return ", ".join(
        str(row[field]).strip() for field in fields
        if row.get(field) is not None and str(row[field]).strip()
    )


def organization_address(row):
    if row.get("db_or_ai") == "db":
        return address_from_parts(row, (
            "street", "city_name", "state_name", "zip_code", "country_name",
        ))
    location = row.get("location") or row.get("address")
    if isinstance(location, str):
        return location.strip()
    return address_from_parts(row, (
        "street", "city", "state", "zip_code", "country",
    ))


class GeocodeService:
    """Reuse coordinates in memory, optionally DynamoDB, then an injected provider.

    The default provider is an approved geocoding Lambda named by environment.
    No geocoding vendor or endpoint is embedded in this implementation.
    """

    def __init__(self, provider=None, cache=None):
        self.provider = provider
        self.cache = cache if cache is not None else _MEMORY_CACHE

    def _cache_key(self, address):
        return hashlib.sha256(address.casefold().strip().encode()).hexdigest()

    def _load_persistent(self, key):
        table = os.environ.get("GEOCODE_CACHE_TABLE")
        if not table:
            return None
        import boto3
        item = boto3.resource("dynamodb").Table(table).get_item(Key={"address_key": key}).get("Item")
        return parse_coordinates(item) if item else None

    def _save_persistent(self, key, coordinates):
        table = os.environ.get("GEOCODE_CACHE_TABLE")
        if table:
            import boto3
            from decimal import Decimal
            boto3.resource("dynamodb").Table(table).put_item(Item={
                "address_key": key,
                "latitude": Decimal(str(coordinates[0])),
                "longitude": Decimal(str(coordinates[1])),
            })

    def _call_provider(self, address):
        if self.provider is not None:
            return self.provider(address)
        function_name = os.environ.get("GEOCODER_LAMBDA_NAME")
        if not function_name:
            return None
        import boto3
        from botocore.config import Config
        client = boto3.client("lambda", config=Config(
            connect_timeout=2, read_timeout=3, retries={"max_attempts": 1},
        ))
        result = client.invoke(
            FunctionName=function_name, InvocationType="RequestResponse",
            Payload=json.dumps({"address": address}).encode(),
        )
        if result.get("FunctionError"):
            raise RuntimeError("Geocoder Lambda failed")
        payload = json.loads(result["Payload"].read())
        body = payload.get("body", payload)
        return json.loads(body) if isinstance(body, str) else body

    def lookup(self, address):
        """Return (coordinates or None, status) without raising to callers."""
        if not address:
            return None, "unknown_location"
        key = self._cache_key(address)
        cached = parse_coordinates(self.cache.get(key))
        if cached is not None:
            return cached, "ok"
        try:
            cached = self._load_persistent(key)
            if cached is not None:
                self.cache[key] = cached
                return cached, "ok"
        except Exception:
            # A cache outage must not prevent a provider lookup.
            pass
        if self.provider is None and not os.environ.get("GEOCODER_LAMBDA_NAME"):
            return None, "deferred"
        try:
            coordinates = parse_coordinates(self._call_provider(address))
        except Exception:
            return None, "error"
        if coordinates is None:
            return None, "not_found"
        self.cache[key] = coordinates
        try:
            self._save_persistent(key, coordinates)
        except Exception:
            pass
        return coordinates, "ok"


def add_distances(organizations, beneficiary, geocoder):
    """Decorate every record independently; a failed geocode never drops it."""
    beneficiary_status = "unknown_location"
    if isinstance(beneficiary, Mapping):
        beneficiary_status = beneficiary.get("status", beneficiary_status)
        beneficiary = parse_coordinates(beneficiary.get("coordinates"))
    results = []
    for original in organizations:
        row = original.copy()
        row.update({
            "distance": None,
            "distance_unit": "miles",
            "distance_method": "straight_line",
            "distance_status": "unknown_location",
        })
        try:
            if row.get("online_only") is True or str(row.get("location", "")).strip().lower() in {"online", "online only", "virtual"}:
                row["distance_status"] = "online"
                results.append(row)
                continue
            if beneficiary is None:
                row["distance_status"] = beneficiary_status
                results.append(row)
                continue
            coordinates = parse_coordinates(row)
            if coordinates is None:
                coordinates = parse_coordinates(row.get("location"))
            if coordinates is None:
                coordinates, status = geocoder.lookup(organization_address(row))
                if coordinates is None:
                    row["distance_status"] = status
                    results.append(row)
                    continue
            row["distance"] = round(haversine_miles(beneficiary, coordinates), 1)
            row["distance_status"] = "ok"
        except Exception:
            row["distance_status"] = "error"
        results.append(row)
    return results
