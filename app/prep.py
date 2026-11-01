"""Prep mode: before friends arrive, build a day plan plus five fun facts to drop into conversation.
These steps run as Render Workflow tasks (see workflow.py), or directly inside the web service as a fallback."""
import html
import json

from . import llm, places
from .landmarks import LANDMARKS, find_in_text


async def locate_area(area: str) -> dict:
    """Where the day starts: a known landmark, else a Nominatim search, else downtown."""
    lm = find_in_text(area or "")
    if lm:
        return {"name": lm["name"], "lat": lm["lat"], "lon": lm["lon"]}
    if area and len(area) <= 60:
        found = await places.search(area)
        if found:
            return found
    return {"name": "Union Station", "lat": 43.6453, "lon": -79.3806}


async def scout_spots(lat: float, lon: float, category: str) -> list:
    """Top real places of one category near the start point."""
    found = await places.nearby(lat, lon, category, radius=900, limit=6, skip_chains=category in ("coffee", "food", "bar"))
    return [{"name": p["name"], "walk_min": p["walk_min"], "direction": p["direction"],
             "street": p.get("street"), "cuisine": p.get("cuisine")} for p in found[:4]]


def nearby_landmarks(lat: float, lon: float) -> list:
    out = []
    for lm in LANDMARKS:
        km = places.haversine_km(lat, lon, lm["lat"], lm["lon"])
        out.append({"name": lm["name"], "walk_min": places.walk_minutes(km), "fact": lm["fact"]})
    out.sort(key=lambda x: x["walk_min"])
    return out[:6]


PLAN_SYSTEM = (
    "You help a homebody fake being a seasoned Toronto local for visiting friends. "
    "Using ONLY the places in DATA, write a relaxed day plan and talking points. Reply with JSON only:\n"
    '{"title": short catchy title, '
    '"stops": [{"time": "11:00 AM", "place": exact name from DATA, "line": a short plain note on why go there, under 12 words}] (4 to 5 stops, walkable order), '
    '"fun_facts": [exactly 5 short, simple facts from DATA], '
    '"opener": one simple sentence summing up the day}'
)


async def write_plan(area: dict, interests: str, coffee: list, food: list, sights: list, landmarks: list) -> dict:
    data = {"start": area["name"], "friends_like": interests or "a bit of everything",
            "coffee": coffee, "food": food, "sights": sights, "landmarks": landmarks}
    reply = await llm.chat([
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": "DATA: " + json.dumps(data, ensure_ascii=False)},
    ], max_tokens=700, temperature=0.6, timeout=30.0)
    plan = llm.parse_json(reply)
    if not plan or not plan.get("stops"):
        plan = template_plan(area, coffee, food, landmarks)
        plan["source"] = "template"
    else:
        plan["source"] = "llm"
    plan["fun_facts"] = (plan.get("fun_facts") or [f"{l['name']}: {l['fact']}" for l in landmarks])[:5]
    plan["area"] = area["name"]
    return plan


def template_plan(area: dict, coffee: list, food: list, landmarks: list) -> dict:
    stops = []
    if coffee:
        stops.append({"time": "10:30 AM", "place": coffee[0]["name"], "line": "Coffee to start the day."})
    for t, lm in zip(["11:30 AM", "1:30 PM", "3:30 PM"], landmarks[:3]):
        stops.append({"time": t, "place": lm["name"], "line": lm["fact"][0].upper() + lm["fact"][1:] + "."})
    if food:
        stops.insert(2, {"time": "12:45 PM", "place": food[0]["name"], "line": "Lunch."})
    return {
        "title": f"A day around {area['name']}",
        "stops": stops,
        "fun_facts": [f"{l['name']}: {l['fact']}" for l in landmarks[:5]],
        "opener": f"A walkable day around {area['name']}.",
    }


async def build_prep(area_text: str, interests: str = "") -> dict:
    """Same steps as the Render Workflow, run in-process."""
    import asyncio
    area = await locate_area(area_text)
    coffee, food, sights = await asyncio.gather(
        scout_spots(area["lat"], area["lon"], "coffee"),
        scout_spots(area["lat"], area["lon"], "food"),
        scout_spots(area["lat"], area["lon"], "attraction"),
    )
    return await write_plan(area, interests, coffee, food, sights, nearby_landmarks(area["lat"], area["lon"]))


def briefing_text(plan: dict) -> str:
    """A short spoken briefing for the walk over."""
    first = plan["stops"][0]["place"] if plan.get("stops") else plan.get("area", "downtown")
    facts = plan.get("fun_facts", [])[:2]
    return (f"Here's your briefing. Today is {plan.get('title', 'the plan')}. Start at {first}. "
            + " ".join(f"Drop this: {f}" for f in facts)
            + " You've got this. You've lived here forever.")


def email_bodies(plan: dict) -> tuple[str, str]:
    text_lines = [plan.get("title", "Your Townie plan"), "", plan.get("opener", ""), "", "The day:"]
    for s in plan.get("stops", []):
        text_lines.append(f"  {s.get('time', '')}  {s.get('place', '')}: {s.get('line', '')}")
    text_lines += ["", "Five fun facts:"] + [f"  - {f}" for f in plan.get("fun_facts", [])]
    text_lines += ["", "Ask Townie anything on the day with a double-tap. Nobody has to know.", "- Townie"]

    e = html.escape
    rows = "".join(
        f"<tr><td style='padding:6px 12px 6px 0;color:#888;white-space:nowrap'>{e(s.get('time',''))}</td>"
        f"<td style='padding:6px 0'><b>{e(s.get('place',''))}</b><br><i>{e(s.get('line',''))}</i></td></tr>"
        for s in plan.get("stops", [])
    )
    facts = "".join(f"<li>{e(f)}</li>" for f in plan.get("fun_facts", []))
    body = (
        f"<div style='font-family:system-ui,sans-serif;max-width:560px'>"
        f"<h2 style='margin:0 0 4px'>{e(plan.get('title','Your Townie plan'))}</h2>"
        f"<p style='color:#555'>{e(plan.get('opener',''))}</p>"
        f"<table>{rows}</table><h3>Five fun facts</h3><ul>{facts}</ul>"
        f"<p style='color:#888'>Double-tap the back of your phone to ask Townie anything. Nobody has to know.</p></div>"
    )
    return "\n".join(text_lines), body
