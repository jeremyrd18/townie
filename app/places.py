"""Location facts from OpenStreetMap (free, no keys): Overpass for nearby places,
Nominatim for search and reverse geocoding, plus distance and direction maths."""
import asyncio
import json
import math
import time
from pathlib import Path

import httpx

from . import config
from .landmarks import LANDMARKS

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
# left, top, right, bottom
TORONTO_VIEWBOX = "-79.64,43.86,-79.11,43.58"

# Category -> Overpass tag filters.
CATEGORY_TAGS = {
    "coffee": ['["amenity"="cafe"]'],
    "food": ['["amenity"="restaurant"]', '["amenity"="fast_food"]'],
    "washroom": ['["amenity"="toilets"]'],
    "subway": ['["station"="subway"]'],
    "bar": ['["amenity"="bar"]', '["amenity"="pub"]'],
    "atm": ['["amenity"="atm"]'],
    "pharmacy": ['["amenity"="pharmacy"]'],
    "attraction": ['["tourism"="attraction"]', '["tourism"="museum"]', '["tourism"="viewpoint"]', '["tourism"="gallery"]'],
    "building": ['["building"]["name"]', '["historic"]["name"]', '["tourism"]["name"]'],
}

# Category -> Nominatim POI search term (fast and reliable; Overpass is often at capacity).
NOMINATIM_TERMS = {
    "coffee": "cafe", "food": "restaurant", "washroom": "toilets", "subway": "subway station",
    "bar": "bar", "atm": "atm", "pharmacy": "pharmacy", "attraction": "museum",
}

# TTC subway stations in and around downtown (OSM search returns the lines, not the stations).
TTC_STATIONS = [
    ("Union", 43.6455, -79.3806, "Front Street"), ("St. Andrew", 43.6476, -79.3848, "King Street West"),
    ("King", 43.6491, -79.3779, "Yonge Street"), ("Osgoode", 43.6508, -79.3868, "Queen Street West"),
    ("Queen", 43.6524, -79.3792, "Yonge Street"), ("St. Patrick", 43.6548, -79.3883, "University Avenue"),
    ("Dundas", 43.6561, -79.3802, "Yonge Street"), ("Queen's Park", 43.6600, -79.3904, "University Avenue"),
    ("College", 43.6613, -79.3830, "Yonge Street"), ("Wellesley", 43.6653, -79.3838, "Yonge Street"),
    ("Museum", 43.6671, -79.3935, "Queen's Park"), ("St. George", 43.6683, -79.3997, "St. George Street"),
    ("Bay", 43.6702, -79.3901, "Bloor Street West"), ("Bloor-Yonge", 43.6709, -79.3857, "Yonge Street"),
    ("Spadina", 43.6673, -79.4037, "Spadina Road"), ("Bathurst", 43.6660, -79.4113, "Bathurst Street"),
    ("Christie", 43.6643, -79.4185, "Christie Street"), ("Sherbourne", 43.6722, -79.3765, "Sherbourne Street"),
    ("Castle Frank", 43.6738, -79.3689, "Bloor Street East"), ("Broadview", 43.6770, -79.3583, "Broadview Avenue"),
    ("Rosedale", 43.6769, -79.3888, "Yonge Street"), ("Dupont", 43.6749, -79.4070, "Spadina Road"),
    ("Summerhill", 43.6823, -79.3909, "Yonge Street"), ("St. Clair", 43.6880, -79.3934, "Yonge Street"),
    ("St. Clair West", 43.6840, -79.4153, "St. Clair Avenue West"),
]

# Big chains, for "somewhere that isn't a chain".
CHAINS = {
    "starbucks", "tim hortons", "mccafé", "mccafe", "mcdonald's", "second cup", "subway", "pizza pizza", "a&w",
    "burger king", "wendy's", "aroma espresso bar", "pret a manger", "chipotle", "popeyes", "kfc", "domino's",
    "freshii", "booster juice", "dairy queen", "five guys", "the keg", "jack astor's", "milestones", "kelseys",
    "shoppers drug mart", "rexall", "starbucks reserve", "coffee time", "country style", "david's tea",
}


def is_chain(name: str | None, brand: str | None = None) -> bool:
    return bool(brand) or (name or "").strip().lower() in CHAINS


UNNAMED_LABEL = {"washroom": "a public washroom", "atm": "an ATM", "subway": "the subway"}

# Saved results for the demo areas, so the demo works even when the free OSM servers are busy.
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "osm_snapshot.json"
_spots_cache: dict = {}
try:
    _spots_cache.update(json.loads(SNAPSHOT_PATH.read_text()))
except Exception:
    pass

_overpass_cache: dict = {}
_nominatim_cache: dict = {}
_nominatim_lock = asyncio.Lock()
_nominatim_last = 0.0


# ---------- maths ----------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walk_minutes(km: float) -> int:
    """Straight-line km times 1.3 for street detours, at 5 km/h."""
    return max(1, round(km * 1.3 / 5 * 60))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def direction_words(bearing: float, heading: float | None = None) -> str:
    """With a phone heading: ahead / left / right / behind. Without: a compass direction."""
    if heading is not None:
        rel = (bearing - heading + 360) % 360
        if rel < 45 or rel > 315:
            return "straight ahead"
        if rel < 135:
            return "on your right"
        if rel < 225:
            return "behind you"
        return "on your left"
    return COMPASS[round(bearing / 45) % 8]


def offset_point(lat, lon, bearing, meters):
    """The point `meters` away in direction `bearing`."""
    d = meters / 6_371_000
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def describe(name, lat, lon, from_lat, from_lon, heading=None, **extra) -> dict:
    km = haversine_km(from_lat, from_lon, lat, lon)
    b = bearing_deg(from_lat, from_lon, lat, lon)
    return {
        "name": name,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "distance_m": round(km * 1000),
        "distance_km": round(km * 1.3, 1),  # walking route, not a straight line
        "walk_min": walk_minutes(km),
        "direction": direction_words(b, heading),
        "bearing": round(b),
        **{k: v for k, v in extra.items() if v},
    }


# ---------- landmarks ----------

def nearest_landmarks(lat, lon, heading=None, limit=3, max_km=2.5) -> list:
    out = []
    for lm in LANDMARKS:
        km = haversine_km(lat, lon, lm["lat"], lm["lon"])
        if km <= max_km:
            out.append(describe(lm["name"], lm["lat"], lm["lon"], lat, lon, heading, fun_fact=lm["fact"]))
    out.sort(key=lambda p: p["distance_m"])
    return out[:limit]


# ---------- Overpass ----------

def _spot_key(lat, lon, category, radius) -> str:
    return f"{round(lat, 3)},{round(lon, 3)},{category},{radius}"


async def nearby(lat, lon, category, radius=500, heading=None, limit=5, skip_chains=False) -> list:
    """Closest named places of a category, sorted by distance.
    Order: saved snapshot / memory cache, then Nominatim, then Overpass."""
    if category == "subway":
        stations = [describe(f"{n} station", la, lo, lat, lon, heading, street=st) for n, la, lo, st in TTC_STATIONS]
        stations.sort(key=lambda p: p["distance_m"])
        return stations[:limit]

    tier = 600 if radius <= 600 else 1200  # fetch in two sizes so the cache is reusable
    key = _spot_key(lat, lon, category, tier)
    raw = _spots_cache.get(key)
    if raw is None:
        raw = await _nominatim_spots(lat, lon, category, tier) if category in NOMINATIM_TERMS else []
        if not raw:
            raw = await _overpass_spots(lat, lon, category, tier)
        if raw:
            _spots_cache[key] = raw

    out, seen = [], set()
    for r in raw:
        chain = is_chain(r.get("name"), r.get("brand"))
        if skip_chains and chain:
            continue
        name = r.get("name") or UNNAMED_LABEL.get(category)
        if not name:
            continue
        p = describe(name, r["lat"], r["lon"], lat, lon, heading,
                     street=r.get("street"), opening_hours=r.get("opening_hours"),
                     cuisine=r.get("cuisine"), chain=chain)
        if p["distance_m"] > radius * 1.2:
            continue
        dedupe = (name, round(r["lat"], 4), round(r["lon"], 4))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append(p)
    out.sort(key=lambda p: p["distance_m"])
    return out[:limit]


async def _nominatim_spots(lat, lon, category, radius) -> list:
    dlat = radius / 111_000
    dlon = radius / (111_000 * math.cos(math.radians(lat)))
    viewbox = f"{lon - dlon},{lat + dlat},{lon + dlon},{lat - dlat}"
    data = await _nominatim("search", {
        "amenity": NOMINATIM_TERMS[category], "viewbox": viewbox, "bounded": 1,
        "limit": 40, "extratags": 1, "addressdetails": 1,
    })
    out = []
    for d in data or []:
        extra = d.get("extratags") or {}
        out.append({
            "name": d.get("name") or None,
            "lat": float(d["lat"]), "lon": float(d["lon"]),
            "street": (d.get("address") or {}).get("road"),
            "brand": extra.get("brand"),
            "opening_hours": extra.get("opening_hours"),
            "cuisine": extra.get("cuisine"),
        })
    return out


async def _overpass_spots(lat, lon, category, radius) -> list:
    filters = CATEGORY_TAGS.get(category, CATEGORY_TAGS["attraction"])
    parts = "".join(f"nwr{f}(around:{radius},{lat},{lon});" for f in filters)
    elements = await _overpass(f"[out:json][timeout:5];({parts});out center tags 60;") or []
    out = []
    for el in elements:
        tags = el.get("tags", {})
        plat = el.get("lat") or el.get("center", {}).get("lat")
        plon = el.get("lon") or el.get("center", {}).get("lon")
        if plat is None or plon is None:
            continue
        out.append({
            "name": tags.get("name"), "lat": plat, "lon": plon,
            "street": tags.get("addr:street"), "brand": tags.get("brand"),
            "opening_hours": tags.get("opening_hours"), "cuisine": tags.get("cuisine"),
        })
    return out


def save_snapshot() -> int:
    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(_spots_cache, indent=0, ensure_ascii=False))
    return len(_spots_cache)


async def _overpass(query: str):
    headers = {"User-Agent": config.OSM_USER_AGENT}
    for i, url in enumerate(OVERPASS_URLS):
        try:
            async with httpx.AsyncClient(timeout=3.5, headers=headers) as client:
                r = await client.post(url, data={"data": query})
                r.raise_for_status()
                return r.json().get("elements", [])
        except Exception as e:  # try the next mirror
            print(f"[overpass] {url} failed: {e!r}")
    return None


# ---------- Nominatim ----------

async def _nominatim(path: str, params: dict):
    """Polite Nominatim call: descriptive User-Agent, max 1 request per second, cached."""
    global _nominatim_last
    key = (path, tuple(sorted(params.items())))
    if key in _nominatim_cache:
        return _nominatim_cache[key]
    async with _nominatim_lock:
        wait = 1.0 - (time.monotonic() - _nominatim_last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=4.0, headers={"User-Agent": config.OSM_USER_AGENT}) as client:
                r = await client.get(f"{NOMINATIM_URL}/{path}", params={**params, "format": "jsonv2"})
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            print(f"[nominatim] {path} failed: {e!r}")
            data = None
        finally:
            _nominatim_last = time.monotonic()
    if data is not None:
        _nominatim_cache[key] = data
    return data


async def search(query: str):
    """Find a place in Toronto by name. Returns {name, lat, lon} or None."""
    data = await _nominatim("search", {
        "q": query, "limit": 1, "viewbox": TORONTO_VIEWBOX, "bounded": 1, "countrycodes": "ca",
    })
    if not data:
        return None
    top = data[0]
    name = top.get("name") or top.get("display_name", query).split(",")[0]
    return {"name": name, "lat": float(top["lat"]), "lon": float(top["lon"])}


async def search_near(query: str, lat: float, lon: float, radius: int = 1500, heading=None, limit: int = 3) -> list:
    """Named places matching a search (e.g. "chinese restaurant", "sushi") near a point, closest first."""
    dlat = radius / 111_000
    dlon = radius / (111_000 * math.cos(math.radians(lat)))
    data = await _nominatim("search", {
        "q": query, "viewbox": f"{lon - dlon},{lat + dlat},{lon + dlon},{lat - dlat}", "bounded": 1,
        "limit": 15, "extratags": 1, "addressdetails": 1,
    })
    out = []
    for d in data or []:
        if not d.get("name"):
            continue
        extra = d.get("extratags") or {}
        out.append(describe(d["name"], float(d["lat"]), float(d["lon"]), lat, lon, heading,
                            street=(d.get("address") or {}).get("road"), cuisine=extra.get("cuisine")))
    out.sort(key=lambda p: p["distance_m"])
    return out[:limit]


async def reverse(lat, lon):
    """What is at these coordinates: {name, road, neighbourhood} or None."""
    data = await _nominatim("reverse", {"lat": round(lat, 5), "lon": round(lon, 5), "zoom": 18, "addressdetails": 1})
    if not data or "error" in data:
        return None
    addr = data.get("address", {})
    return {
        "name": data.get("name") or None,
        "road": addr.get("road"),
        "neighbourhood": addr.get("neighbourhood") or addr.get("suburb") or addr.get("quarter"),
    }
