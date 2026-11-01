"""Townie web service: /api/ask for the whisper, /live for the judges, /prep for Prep mode."""
import base64
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import brain, config, llm, mail, places, prep, voice

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="Townie")
LIVE: deque = deque(maxlen=10)
_counter = 0

DEMO_SPOTS = [
    {"id": "venue", "name": config.DEMO_NAME, "lat": config.DEMO_LAT, "lon": config.DEMO_LON},
    {"id": "union", "name": "Union Station", "lat": 43.6453, "lon": -79.3806},
    {"id": "cn", "name": "CN Tower", "lat": 43.6426, "lon": -79.3871},
    {"id": "nps", "name": "Nathan Phillips Square", "lat": 43.6525, "lon": -79.3835},
    {"id": "kensington", "name": "Kensington Market", "lat": 43.6547, "lon": -79.4005},
    {"id": "distillery", "name": "Distillery District", "lat": 43.6503, "lon": -79.3596},
]


# ---------- pages ----------

@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html")


@app.get("/live")
async def live_page():
    return FileResponse(STATIC / "live.html")


@app.get("/prep")
async def prep_page():
    return FileResponse(STATIC / "prep.html")


@app.get("/static/{name}")
async def static_file(name: str):
    path = (STATIC / name).resolve()
    if path.parent != STATIC or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/config")
async def api_config():
    return {
        "demo_spots": DEMO_SPOTS,
        "voice": bool(config.ELEVENLABS_API_KEY),
        "llm": llm.describe(),
        "workflow": bool(config.RENDER_API_KEY and config.WORKFLOW_SLUG),
        "email": mail.enabled(),
    }


# ---------- ask ----------

def _num(v):
    try:
        return float(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


@app.post("/api/ask")
async def ask(request: Request):
    """JSON {question, lat, lon, heading?} from the iPhone Shortcut,
    or multipart {audio, lat, lon, heading?} from the web app.
    ?format=mp3 returns audio/mpeg with the text in X-Say. ?format=json returns everything.
    ?demo=1 (or a spot id like ?demo=union) ignores GPS and uses a demo location."""
    started = time.perf_counter()
    fmt = request.query_params.get("format", "json").lower()
    source = request.query_params.get("source", "shortcut")
    fields: dict = {}
    question = ""

    try:
        if "multipart/form-data" in request.headers.get("content-type", ""):
            form = await request.form()
            fields = {k: v for k, v in form.items() if isinstance(v, str)}
            audio = form.get("audio")
            if audio is not None and not isinstance(audio, str):
                data = await audio.read()
                question = await voice.transcribe(data, audio.filename or "audio.webm", audio.content_type or "audio/webm") or ""
            source = fields.get("source", "web")
        else:
            fields = await request.json()
    except Exception as e:
        print(f"[ask] bad request body: {e!r}")

    question = (question or str(fields.get("question") or "")).strip()
    lat, lon, heading = _num(fields.get("lat")), _num(fields.get("lon")), _num(fields.get("heading"))
    demo = request.query_params.get("demo") or fields.get("demo")
    if demo or lat is None or lon is None:
        spot = next((s for s in DEMO_SPOTS if s["id"] == demo), DEMO_SPOTS[0])
        lat, lon = spot["lat"], spot["lon"]

    if not question:
        result = {"say": "Sorry, say that again? It's loud out here.", "intent": {"intent": "other"}, "facts": {}}
    else:
        result = await brain.answer(question, lat, lon, heading)

    say = result["say"]
    want_audio = fmt == "mp3" or fields.get("want_audio") in (True, "1", "true")
    audio_bytes, engine = await voice.speak_with_engine(say) if want_audio else (None, None)
    elapsed = round(time.perf_counter() - started, 2)
    _log(question, say, result, lat, lon, heading, source, elapsed, engine)

    if fmt == "mp3":
        headers = {"X-Say": _header_safe(say), "X-Seconds": str(elapsed), "Access-Control-Expose-Headers": "X-Say"}
        if audio_bytes:
            return Response(audio_bytes, media_type="audio/mpeg", headers=headers)
        fallback = STATIC / "fallback.m4a"
        if fallback.exists():
            return Response(fallback.read_bytes(), media_type="audio/mp4", headers=headers)
        return Response(say, media_type="text/plain", headers=headers)

    return {
        "say": say,
        "question": question,
        "intent": result["intent"],
        "facts": result["facts"],
        "seconds": elapsed,
        "voice": engine,
        "audio_b64": base64.b64encode(audio_bytes).decode() if audio_bytes else None,
    }


def _header_safe(text: str) -> str:
    for a, b in {"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-", "\u2011": "-", "\u00a0": " ", "é": "e"}.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "ignore").decode("latin-1")


def _log(question, say, result, lat, lon, heading, source, seconds, voice_engine=None):
    global _counter
    _counter += 1
    near = places.nearest_landmarks(lat, lon, limit=1, max_km=3)
    LIVE.appendleft({
        "id": _counter,
        "time": datetime.now(ZoneInfo("America/Toronto")).strftime("%-I:%M:%S %p"),
        "question": question or "(didn't catch that)",
        "say": say,
        "intent": result["intent"].get("intent"),
        "near": near[0]["name"] if near else None,
        "lat": lat, "lon": lon, "heading": heading,
        "points": brain.map_points(result.get("facts") or {}),
        "source": source,
        "seconds": seconds,
        "voice": voice_engine,
        "llm": result["intent"].get("writer"),
    })


@app.get("/api/live")
async def api_live():
    return {"entries": list(LIVE)}


# ---------- prep mode (Render Workflow + Agentboxd) ----------

async def _run_prep(area: str, interests: str) -> tuple[dict, dict]:
    """Run Prep mode on the Render Workflow if configured, otherwise in-process."""
    if config.RENDER_API_KEY and config.WORKFLOW_SLUG:
        try:
            from render import RenderAsync
            client = RenderAsync()
            run = await client.workflows.start_task(f"{config.WORKFLOW_SLUG}/prep_day",
                                                    {"area": area, "interests": interests})
            done = await run
            results = done.results
            plan = results[0] if isinstance(results, list) and results else results
            if isinstance(plan, dict) and plan.get("stops"):
                return plan, {"via": "render-workflow", "run_id": getattr(done, "id", None)}
        except Exception as e:
            print(f"[prep] workflow failed, running locally: {e!r}")
    return await prep.build_prep(area, interests), {"via": "web-service", "run_id": None}


@app.post("/api/prep")
async def api_prep(request: Request):
    body = await request.json()
    area = str(body.get("area") or "Union Station")
    interests = str(body.get("interests") or "")
    email = str(body.get("email") or "").strip()
    started = time.perf_counter()

    plan, run = await _run_prep(area, interests)
    briefing = await voice.speak(prep.briefing_text(plan))

    emailed = None
    if email and mail.enabled():
        try:
            text, html = prep.email_bodies(plan)
            await mail.send(email, f"Townie cheat sheet: {plan.get('title', 'your day')}", text, html)
            emailed = email
        except Exception as e:
            print(f"[prep] email failed: {e!r}")

    return {
        "plan": plan,
        **run,
        "emailed": emailed,
        "seconds": round(time.perf_counter() - started, 1),
        "briefing_b64": base64.b64encode(briefing).decode() if briefing else None,
    }


@app.get("/api/inbox")
async def api_inbox():
    if not mail.enabled():
        return {"enabled": False}
    try:
        box = await mail.inbox()
        msgs = await mail.recent(8)
        return {
            "enabled": True,
            "address": box.get("address"),
            "messages": [{
                "id": m.get("id"),
                "from": mail.sender(m),
                "subject": m.get("subject"),
                "direction": m.get("direction"),
                "preview": (m.get("extracted_text") or m.get("text") or "")[:160],
                "is_read": m.get("is_read"),
            } for m in msgs],
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)}


@app.post("/api/inbox/process")
async def api_inbox_process():
    """Answer every unread email: treat it as a visit plan, reply with a cheat sheet."""
    if not mail.enabled():
        return {"enabled": False, "replied": []}
    replied = []
    for msg in await mail.unread():
        body = msg.get("extracted_text") or msg.get("text") or ""
        request_text = f"{msg.get('subject') or ''}\n{body}"
        plan, run = await _run_prep(request_text, body[:300])
        text, html = prep.email_bodies(plan)
        try:
            await mail.reply(msg["id"], text, html)
            replied.append({"to": mail.sender(msg), "title": plan.get("title"), **run})
        except Exception as e:
            print(f"[inbox] reply failed: {e!r}")
    return {"enabled": True, "replied": replied}
