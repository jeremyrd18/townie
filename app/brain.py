"""The answer pipeline: question + location -> intent -> real facts -> one line to say."""
import json
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, llm, places, web
from .landmarks import find_in_text

FALLBACK_LINES = [
    "One sec, still checking.",
    "No answer yet. Try asking again.",
]

CATEGORY_WORDS = {
    "coffee": ["coffee", "cafe", "café", "latte", "espresso", "tim hortons", "timmies", "tea"],
    "food": ["eat", "food", "restaurant", "hungry", "lunch", "dinner", "breakfast", "brunch", "bite", "snack"],
    "washroom": ["washroom", "bathroom", "restroom", "toilet", "loo", "pee"],
    "subway": ["subway", "ttc", "metro", "subway station", "train station"],
    "bar": ["bar", "pub", "beer", "drink", "drinks", "cocktail", "cocktails", "brewery"],
    "atm": ["atm", "cash", "bank machine"],
    "pharmacy": ["pharmacy", "drugstore", "drug store", "shoppers", "medicine", "advil"],
    "attraction": ["attraction", "museum", "sightseeing", "touristy", "viewpoint", "gallery"],
}

# Cuisine word in the question -> words to look for in OSM cuisine tags or names.
CUISINES = {
    "chinese": ["chinese"], "dim sum": ["dim_sum", "dim sum", "chinese"], "japanese": ["japanese", "sushi", "ramen"],
    "sushi": ["sushi"], "ramen": ["ramen"], "korean": ["korean"], "thai": ["thai"], "vietnamese": ["vietnamese", "pho"],
    "pho": ["vietnamese", "pho"], "indian": ["indian"], "italian": ["italian", "pizza", "pasta"], "pizza": ["pizza"],
    "mexican": ["mexican", "taco"], "tacos": ["mexican", "taco"], "burger": ["burger"], "burgers": ["burger"],
    "vegan": ["vegan"], "vegetarian": ["vegetarian", "vegan"], "greek": ["greek"], "shawarma": ["shawarma", "lebanese"],
    "middle eastern": ["middle_eastern", "lebanese", "shawarma"], "caribbean": ["caribbean", "jamaican"],
    "jamaican": ["jamaican", "caribbean"], "french": ["french"], "ethiopian": ["ethiopian"],
    "portuguese": ["portuguese"], "bbq": ["bbq", "barbecue"], "halal": ["halal"], "poutine": ["poutine"],
    "seafood": ["seafood", "fish"], "brunch": ["breakfast", "brunch"], "bakery": ["bakery"], "dessert": ["dessert", "ice_cream"],
}


def find_cuisine(question: str) -> str | None:
    q = question.lower()
    return next((c for c in sorted(CUISINES, key=len, reverse=True) if _has(q, [c])), None)


INTENTS = ["nearest", "distance", "whats_here", "recommend", "fact", "general", "other"]

# Questions that need up-to-date info from the web, not the model's memory.
FRESH_WORDS = ["now", "right now", "today", "tonight", "this week", "this weekend", "weekend", "tomorrow",
               "latest", "current", "currently", "recent", "recently", "still", "new", "newest", "these days",
               "open", "closed", "hours", "event", "events", "happening", "going on", "concert", "show", "shows",
               "festival", "game", "playing", "score", "weather", "forecast", "mayor", "who runs", "price",
               "cost", "tickets", "schedule", "news", "2025", "2026"]


def needs_web(question: str) -> bool:
    return _has(question.lower().replace("’", "'"), FRESH_WORDS)

# Questions answered from the model's own knowledge, not a map lookup.
GENERAL_STARTS = ("who ", "when ", "why ", "how tall", "how old", "how big", "how many", "how much", "what year",
                  "what is a ", "what's a ", "whats a ", "what does ", "is it true", "do you know")
GENERAL_WORDS = ["known for", "famous for", "population", "mayor", "nickname", "called the", "the six", "the 6ix",
                 "safe", "weather", "tip", "tipping", "currency", "history of", "invented", "championship",
                 "won the", "slang", "accent", "tax", "pronounce"]


def _has(text: str, words) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) for w in words)


def rule_intent(question: str) -> dict | None:
    """Fast keyword rules. Most demo questions never need the model for intent."""
    q = question.lower().replace("’", "'")
    category = next((c for c, words in CATEGORY_WORDS.items() if _has(q, words)), None)
    if not category and find_cuisine(q):
        category = "food"
    landmark = find_in_text(q)

    if _has(q, ["what's that", "what is that", "whats that", "what's this", "what is this", "whats this",
                "that building", "this building", "where are we", "what building", "what are we looking at"]):
        return {"intent": "whats_here", "category": "building", "destination": None}

    asks_where = _has(q, ["where", "nearest", "closest", "nearby", "near here", "around here", "is there"])
    if (q.startswith(GENERAL_STARTS) or _has(q, GENERAL_WORDS)) and not (category and asks_where):
        return {"intent": "general", "category": None, "destination": landmark["name"] if landmark else None}

    if _has(q, ["walk to", "walking to", "how far", "how long", "get to", "close enough", "far is", "far are",
                "minutes to", "far from", "distance", "walkable", "go to", "head to"]):
        dest = landmark["name"] if landmark else _destination_text(q)
        if dest:
            return {"intent": "distance", "category": None, "destination": dest}

    if _has(q, ["fun fact", "something cool", "something interesting", "tell me about", "history", "story"]):
        return {"intent": "fact", "category": None, "destination": landmark["name"] if landmark else None}

    if category:
        wants_rec = _has(q, ["should", "recommend", "best", "good", "favourite", "favorite", "isn't a chain",
                             "not a chain", "local", "worth"])
        return {"intent": "recommend" if wants_rec else "nearest", "category": category, "destination": None}

    if _has(q, ["tonight", "this weekend", "happening", "going on", "events", "concert", "festival", "game tonight"]):
        return {"intent": "general", "category": None, "destination": landmark["name"] if landmark else None}

    if _has(q, ["what should we do", "what to do", "thing to do", "things to do", "recommend", "worth seeing"]):
        return {"intent": "recommend", "category": "attraction", "destination": None}

    if landmark and _has(q, ["where", "which way", "direction"]):
        return {"intent": "distance", "category": None, "destination": landmark["name"]}
    return None


def _destination_text(q: str) -> str | None:
    m = re.search(r"(?:walk to|walking to|get to|go to|head to|far is|far to|minutes to|from here to)\s+(?:the\s+)?([a-z0-9' .&-]{3,40})", q)
    if not m:
        return None
    dest = re.sub(r"\b(from here|from us|right now|now|please|tonight)\b.*$", "", m.group(1)).strip(" ?.!")
    return dest or None


async def llm_intent(question: str) -> dict:
    reply = await llm.chat([
        {"role": "system", "content": (
            "Classify a tourist's question in Toronto. Use general for knowledge questions that need no map "
            "(history, sports, food culture, how things work). Reply with JSON only: "
            '{"intent": one of nearest|distance|whats_here|recommend|fact|general|other, '
            '"category": one of coffee|food|washroom|subway|bar|atm|pharmacy|attraction|null, '
            '"destination": a place name or null}'
        )},
        {"role": "user", "content": question},
    ], max_tokens=60, temperature=0, timeout=4.0, hedge=1.5)
    data = llm.parse_json(reply) or {}
    intent = data.get("intent") if data.get("intent") in INTENTS else "other"
    category = data.get("category") if data.get("category") in CATEGORY_WORDS else None
    return {"intent": intent, "category": category, "destination": data.get("destination") or None}


async def get_intent(question: str) -> dict:
    found = rule_intent(question)
    if found:
        found["source"] = "rules"
        return found
    found = await llm_intent(question)
    found["source"] = "llm"
    return found


async def gather_facts(intent: dict, question: str, lat: float, lon: float, heading: float | None) -> dict:
    kind = intent["intent"]
    facts: dict = {"intent": kind}

    if kind in ("nearest", "recommend") and intent.get("category"):
        cat = intent["category"]
        skip_chains = "chain" in question.lower() or "local" in question.lower()
        cuisine = find_cuisine(question) if cat == "food" else None
        if cuisine:
            # A specific cuisine: filter nearby restaurants by cuisine tag or name, else search by name.
            terms = CUISINES[cuisine]
            pool = await places.nearby(lat, lon, "food", radius=1200, heading=heading, limit=60, skip_chains=skip_chains)
            found = [p for p in pool if any(t in f"{p.get('cuisine', '')} {p['name']}".lower() for t in terms)]
            if not found:
                found = await places.search_near(f"{cuisine} restaurant" if cuisine not in ("sushi", "pho", "ramen", "pizza") else cuisine,
                                                 lat, lon, radius=1500, heading=heading)
            facts["cuisine"] = cuisine
        else:
            radius = 500 if kind == "nearest" else 800
            found = await places.nearby(lat, lon, cat, radius=radius, heading=heading, skip_chains=skip_chains)
            if not found:
                found = await places.nearby(lat, lon, cat, radius=1200, heading=heading, skip_chains=skip_chains)
        facts["category"] = cat
        if kind == "nearest":  # only what a "where's the nearest" answer needs
            keep = ("name", "lat", "lon", "walk_min", "direction", "street", "distance_km")
            found = [{k: p[k] for k in keep if k in p} for p in found]
        facts["places"] = found[:3]
        if kind == "recommend" or cat == "attraction":
            facts["landmarks"] = places.nearest_landmarks(lat, lon, heading, limit=2)

    elif kind == "distance":
        dest = intent.get("destination") or ""
        lm = find_in_text(dest) or find_in_text(question)
        target = {"name": lm["name"], "lat": lm["lat"], "lon": lm["lon"]} if lm else await places.search(dest)
        if target:
            info = places.describe(target["name"], target["lat"], target["lon"], lat, lon, heading)
            info["walkable"] = info["walk_min"] <= 25
            if info["walk_min"] > 40:
                info["too_far_to_walk"] = True
            facts["destination"] = info

    elif kind == "whats_here":
        if heading is not None:
            # Look up what is about 60 m in front of the phone.
            alat, alon = places.offset_point(lat, lon, heading, 60)
            ahead = await places.reverse(alat, alon)
            if ahead and ahead.get("name"):
                facts["ahead"] = places.describe(ahead["name"], alat, alon, lat, lon, heading, street=ahead.get("road"))
        facts["here"] = await places.reverse(lat, lon)
        facts["landmarks"] = places.nearest_landmarks(lat, lon, heading, limit=2, max_km=1.2)

    elif kind == "general":
        lm = find_in_text(question)
        if lm:
            facts["landmarks"] = [places.describe(lm["name"], lm["lat"], lm["lon"], lat, lon, heading, fun_fact=lm["fact"])]
        facts["note"] = "General knowledge question. Answer from what you know; no directions needed."

    elif kind == "fact":
        lm = find_in_text(question)
        if lm:
            facts["landmarks"] = [places.describe(lm["name"], lm["lat"], lm["lon"], lat, lon, heading, fun_fact=lm["fact"])]
        else:
            facts["landmarks"] = places.nearest_landmarks(lat, lon, heading, limit=2)
            facts["here"] = await places.reverse(lat, lon)

    else:  # other: give the model the general surroundings
        facts["landmarks"] = places.nearest_landmarks(lat, lon, heading, limit=2)
        facts["here"] = await places.reverse(lat, lon)

    return facts


SAY_SYSTEM = (
    "You are Townie, a quiet earpiece for someone showing friends around Toronto. "
    "Whisper the answer in plain, simple words. They will say it in their own words, so do not write a script.\n"
    "Rules:\n"
    "- Answer ONLY the exact question. Nothing extra: no fun facts, history, tips or descriptions "
    "unless the question asks for them. 12 words or fewer.\n"
    "- Where is X / how far / can we walk: walking minutes and direction, plus distance in km if it is over 1 km. "
    "Nothing else. Always give the walking time, even for long walks, "
    "UNLESS too_far_to_walk is true: only then give the best way there instead "
    "(TTC line, UP Express, streetcar, or cab) with a rough travel time.\n"
    "- Nearest / find a place: the place name, walking minutes and direction or street. Nothing else.\n"
    "- Knowledge questions (how tall, when, why, what is): just the direct answer, like a number, year or short definition.\n"
    "- Fun fact, tell me about, what's that building: a short answer with one interesting detail is fine.\n"
    "- If FACTS include web_results, answer from them; they are live and newer than what you know. "
    "Never invent specific times, games, scores or events that are not in FACTS.\n"
    "- Places, distances, walking times and directions: use ONLY what FACTS give. Never invent a business or address. "
    "Other knowledge comes from what you know, accurately.\n"
    "- Minutes, never metres. Simple words, short fragments are fine. No filler like honestly, yeah, sure, let's, just.\n"
    "- Plain punctuation, no dashes. Never mention apps, maps, GPS, data, FACTS, or a list. Never say you don't know.\n"
    "- If no place in FACTS matches what they asked for, say none is close by and name the closest option.\n"
    "Examples of the style (not real answers):\n"
    "Q: where is the CN Tower -> 32 minutes southeast, about 2.5 km.\n"
    "Q: can we walk to the CN Tower -> Yes, about 9 minutes southwest.\n"
    "Q: how tall is the CN Tower -> 553 metres.\n"
    "Q: how do we get to Pearson airport -> UP Express from Union, about 25 minutes.\n"
    "Q: nearest coffee -> [cafe from FACTS], 2 minutes south on [street from FACTS].\n"
    "Q: tell me something cool about the CN Tower -> You can walk around the outside ledge, 356 metres up.\n"
    "Output only the answer, no quotes."
)


SEARCH_SYSTEM = (
    "You are Townie, a quiet earpiece for someone showing friends around Toronto. Search the web for current info, "
    "then whisper the answer in plain, simple words, 20 words or fewer, at most two items. Answer only the exact question. "
    "Prefer results for today's date and for Toronto near the given location. Name specific places, events or people. "
    "No citations, links, dashes, or filler. Never say you searched. Output only the answer."
)


async def write_line(question: str, facts: dict, here: str = "") -> str:
    now = datetime.now(ZoneInfo("America/Toronto")).strftime("%A %B %-d, %Y, %-I:%M %p")
    kind = facts.get("intent")
    # Up-to-date questions: answer from live web results. Directions to nearby places stay on map data.
    if config.WEB_SEARCH and kind in ("general", "fact", "other", "recommend") and needs_web(question):
        reply = await llm.search_chat([
            {"role": "system", "content": SEARCH_SYSTEM},
            {"role": "user", "content": f"Question: {question}\nNow in Toronto: {now}\nWe are near: {here or 'downtown Toronto'}"},
        ])
        line = _clean(reply) if reply else ""
        if line:
            return line, llm.describe()
        # Groq search is busy: use quick search results instead.
        results = await web.snippets(f"{question} Toronto {datetime.now(ZoneInfo('America/Toronto')):%B %-d %Y}")
        facts = {**facts, "web_results": results} if results else {
            **facts, "note": "No live info available. Do not invent specific times, games, scores or events; "
                             "give a safe general answer instead."}
    compact = json.dumps(_trim(facts), ensure_ascii=False)
    reply = await llm.chat([
        {"role": "system", "content": SAY_SYSTEM},
        {"role": "user", "content": f"Friend asked: {question}\nTime in Toronto: {now}\nFACTS: {compact}"},
    ], max_tokens=40, temperature=0.2, timeout=5.0)
    line = _clean(reply) if reply else ""
    return (line, llm.describe()) if line else (template_line(facts), "template")


def _trim(facts: dict) -> dict:
    drop = {"lat", "lon", "bearing", "walkable"}
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k not in drop}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return strip(facts)


def _clean(text: str) -> str:
    data = llm.parse_json(text)
    if data and isinstance(data.get("say"), str):
        text = data["say"]
    text = text.strip().strip('"“”').split("\n")[0].strip()
    for a, b in {"\u2011": "-", "\u2010": "-", "\u00a0": " ", " — ": ", ", "—": ", ", " – ": ", ", "–": "-"}.items():
        text = text.replace(a, b)
    if text:
        text = text[0].upper() + text[1:]
    return _shorten(text, 28)


def _shorten(text: str, limit: int) -> str:
    """Cut long answers at a sentence or list break, never mid-phrase."""
    words = text.split()
    if len(words) <= limit:
        return text
    cut = " ".join(words[:limit])
    stop = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(".") if cut.endswith(".") else -1)
    if stop > len(cut) * 0.4:
        return cut[:stop].rstrip(" .;,") + "."
    comma = cut.rfind(", ")
    return (cut[:comma] if comma > len(cut) * 0.5 else cut).rstrip(" .;,") + "."


def template_line(facts: dict) -> str:
    """No model needed: a short summary built from the facts, so the demo survives an outage."""
    kind = facts.get("intent")
    if facts.get("places"):
        p = facts["places"][0]
        street = f" on {p['street']}" if p.get("street") else ""
        line = f"{p['name']}, {_mins(p['walk_min'])} {_dir(p['direction'])}{street}."
        return line[0].upper() + line[1:]
    if kind == "distance" and facts.get("destination"):
        d = facts["destination"]
        km = f", about {d['distance_km']} km" if d["distance_km"] >= 1 else ""
        if d.get("too_far_to_walk"):
            return f"Too far to walk, about {d['distance_km']} km {d['direction']}. Take the TTC or a cab."
        if d["walkable"]:
            return f"About {d['walk_min']} minutes {d['direction']}{km}."
        return f"{d['walk_min']} minutes {d['direction']} on foot{km}. Better to take the TTC."
    if kind == "whats_here":
        if facts.get("ahead"):
            return f"That's {facts['ahead']['name']}."
        here = facts.get("here") or {}
        lm = (facts.get("landmarks") or [None])[0]
        if lm and lm["distance_m"] < 250:
            return f"{lm['name']}. {lm['fun_fact'][0].upper() + lm['fun_fact'][1:]}."
        if here.get("name"):
            return f"That's {here['name']}" + (f" on {here['road']}." if here.get("road") else ".")
    if facts.get("landmarks"):
        lm = facts["landmarks"][0]
        if lm.get("fun_fact"):
            return f"{lm['name']}: {lm['fun_fact']}."
        return f"{lm['name']}, {_mins(lm['walk_min'])} {lm['direction']}."
    return random.choice(FALLBACK_LINES)


def _mins(n: int) -> str:
    return "a minute" if n <= 1 else f"{n} minutes"


def _dir(direction: str) -> str:
    return direction


def map_points(facts: dict) -> list:
    """Places to pin on the judge screen map."""
    pts = []
    for key in ("places", "landmarks"):
        for p in facts.get(key) or []:
            pts.append({"name": p["name"], "lat": p["lat"], "lon": p["lon"]})
    for key in ("destination", "ahead"):
        d = facts.get(key)
        if d:
            pts.append({"name": d["name"], "lat": d["lat"], "lon": d["lon"]})
    return pts[:6]


async def answer(question: str, lat: float, lon: float, heading: float | None = None) -> dict:
    """Full pipeline. Never raises: any failure becomes a spoken fallback line."""
    intent: dict = {"intent": "other"}
    facts: dict = {}
    try:
        intent = await get_intent(question)
        facts = await gather_facts(intent, question, lat, lon, heading)
        near = places.nearest_landmarks(lat, lon, limit=1, max_km=3)
        say, writer = await write_line(question, facts, near[0]["name"] if near else "")
        intent["writer"] = writer
    except Exception as e:
        print(f"[answer] failed: {e!r}")
        say = template_line(facts) if facts else random.choice(FALLBACK_LINES)
    return {"say": say, "intent": intent, "facts": facts}
