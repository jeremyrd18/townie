"""The answer pipeline: question + location -> intent -> real facts -> one line to say."""
import json
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from . import llm, places
from .landmarks import find_in_text

FALLBACK_LINES = [
    "Give me one sec, let me check my maps.",
    "Ooh, good question, hold on, I'm blanking on the name.",
    "Okay so, give me a second, I always mix those two up.",
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

INTENTS = ["nearest", "distance", "whats_here", "recommend", "fact", "other"]


def _has(text: str, words) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) for w in words)


def rule_intent(question: str) -> dict | None:
    """Fast keyword rules. Most demo questions never need the model for intent."""
    q = question.lower().replace("’", "'")
    category = next((c for c, words in CATEGORY_WORDS.items() if _has(q, words)), None)
    landmark = find_in_text(q)

    if _has(q, ["what's that", "what is that", "whats that", "what's this", "what is this", "whats this",
                "that building", "this building", "where are we", "what building", "what are we looking at"]):
        return {"intent": "whats_here", "category": "building", "destination": None}

    if _has(q, ["walk", "walking", "how far", "how long", "get to", "close enough", "far is", "far are",
                "minutes to", "far from", "distance"]):
        dest = landmark["name"] if landmark else _destination_text(q)
        if dest:
            return {"intent": "distance", "category": None, "destination": dest}

    if _has(q, ["fun fact", "something cool", "something interesting", "tell me about", "history", "story"]):
        return {"intent": "fact", "category": None, "destination": landmark["name"] if landmark else None}

    if category:
        wants_rec = _has(q, ["should", "recommend", "best", "good", "favourite", "favorite", "isn't a chain",
                             "not a chain", "local", "worth"])
        return {"intent": "recommend" if wants_rec else "nearest", "category": category, "destination": None}

    if _has(q, ["what should we do", "what to do", "thing to do", "things to do", "tonight", "recommend", "worth seeing"]):
        return {"intent": "recommend", "category": "attraction", "destination": None}

    if landmark and _has(q, ["where", "which way", "direction"]):
        return {"intent": "distance", "category": None, "destination": landmark["name"]}
    return None


def _destination_text(q: str) -> str | None:
    m = re.search(r"(?:walk to|get to|go to|far is|far to|to get to|minutes to|from here to|to)\s+(?:the\s+)?([a-z0-9' .&-]{3,40})", q)
    if not m:
        return None
    dest = re.sub(r"\b(from here|from us|right now|now|please|tonight)\b.*$", "", m.group(1)).strip(" ?.!")
    return dest or None


async def llm_intent(question: str) -> dict:
    reply = await llm.chat([
        {"role": "system", "content": (
            "Classify a tourist's question in Toronto. Reply with JSON only: "
            '{"intent": one of nearest|distance|whats_here|recommend|fact|other, '
            '"category": one of coffee|food|washroom|subway|bar|atm|pharmacy|attraction|null, '
            '"destination": a place name or null}'
        )},
        {"role": "user", "content": question},
    ], max_tokens=60, temperature=0, timeout=4.0)
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
        radius = 500 if kind == "nearest" else 800
        found = await places.nearby(lat, lon, cat, radius=radius, heading=heading, skip_chains=skip_chains)
        if not found:
            found = await places.nearby(lat, lon, cat, radius=1200, heading=heading, skip_chains=skip_chains)
        facts["category"] = cat
        facts["places"] = found[:3]
        if kind == "recommend" or cat == "attraction":
            facts["landmarks"] = places.nearest_landmarks(lat, lon, heading, limit=2)

    elif kind == "distance":
        dest = intent.get("destination") or ""
        lm = find_in_text(dest) or find_in_text(question)
        target = {"name": lm["name"], "lat": lm["lat"], "lon": lm["lon"]} if lm else await places.search(dest)
        if target:
            info = places.describe(target["name"], target["lat"], target["lon"], lat, lon, heading,
                                   fun_fact=lm["fact"] if lm else None)
            info["walkable"] = info["walk_min"] <= 25
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
    "You are Townie, a secret earpiece whispering to someone who is pretending to be a confident Toronto local "
    "while showing friends around. Write ONE sentence they will say out loud, word for word.\n"
    "Rules:\n"
    "- First person, casual, confident, like a born-and-raised Torontonian. Under 20 words, easy to say in one breath.\n"
    "- Use ONLY places, names, and numbers that appear in FACTS. Never invent a place.\n"
    "- Give walking time in minutes, never metres. Include the direction or street when FACTS have it.\n"
    "- When it fits, add one short local touch from FACTS, like a fun fact. Plain punctuation: no dashes.\n"
    "- Never mention apps, maps, GPS, data, or that you looked anything up.\n"
    "- If FACTS have nothing useful, give a natural stalling line.\n"
    "Output only the sentence, no quotes."
)


async def write_line(question: str, facts: dict) -> str:
    now = datetime.now(ZoneInfo("America/Toronto")).strftime("%A %-I:%M %p")
    compact = json.dumps(_trim(facts), ensure_ascii=False)
    reply = await llm.chat([
        {"role": "system", "content": SAY_SYSTEM},
        {"role": "user", "content": f"Friend asked: {question}\nTime in Toronto: {now}\nFACTS: {compact}"},
    ], max_tokens=70, temperature=0.6, timeout=5.0)
    line = _clean(reply) if reply else ""
    return (line, llm.describe()) if line else (template_line(facts), "template")


def _trim(facts: dict) -> dict:
    drop = {"lat", "lon", "bearing"}
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
    words = text.split()
    if len(words) > 28:
        text = " ".join(words[:26]).rstrip(",;") + "."
    return text


def template_line(facts: dict) -> str:
    """No model needed: a plain line built from the facts, so the demo survives an outage."""
    kind = facts.get("intent")
    if facts.get("places"):
        p = facts["places"][0]
        street = f" on {p['street']}" if p.get("street") else ""
        line = f"{p['name']} is about {_mins(p['walk_min'])} away, {_dir(p['direction'])}{street}."
        return line[0].upper() + line[1:]
    if kind == "distance" and facts.get("destination"):
        d = facts["destination"]
        if d["walkable"]:
            return f"Yeah, {d['name']} is about a {d['walk_min']} minute walk, head {d['direction']}."
        return f"{d['name']} is more like {d['walk_min']} minutes on foot, honestly let's hop on the TTC."
    if kind == "whats_here":
        if facts.get("ahead"):
            return f"Oh, that's {facts['ahead']['name']}, right in front of us."
        here = facts.get("here") or {}
        lm = (facts.get("landmarks") or [None])[0]
        if lm and lm["distance_m"] < 250:
            return f"That's {lm['name']}. Fun fact, {lm['fun_fact']}."
        if here.get("name"):
            return f"That's {here['name']}" + (f", right on {here['road']}." if here.get("road") else ".")
    if facts.get("landmarks"):
        lm = facts["landmarks"][0]
        if lm.get("fun_fact"):
            return f"Fun fact about {lm['name']}: {lm['fun_fact']}."
        return f"We're right by {lm['name']}, about {_mins(lm['walk_min'])} {lm['direction']}."
    return random.choice(FALLBACK_LINES)


def _mins(n: int) -> str:
    return "a minute" if n <= 1 else f"{n} minutes"


def _dir(direction: str) -> str:
    return direction if direction.startswith(("on your", "straight", "behind")) else f"just {direction}"


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
        say, writer = await write_line(question, facts)
        intent["writer"] = writer
    except Exception as e:
        print(f"[answer] failed: {e!r}")
        say = template_line(facts) if facts else random.choice(FALLBACK_LINES)
    return {"say": say, "intent": intent, "facts": facts}
