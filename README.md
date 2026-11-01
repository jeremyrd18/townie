# Townie

**LARP as a Toronto local.** Your friends are visiting and think you know the city, but you barely leave home. Double-tap the back of your iPhone, ask a question ("closest coffee?", "can we walk to the CN Tower?", "anything on tonight?"), and Townie whispers a short answer into your AirPods in about two seconds. Say it in your own words, and nobody knows.

LarpHacks 2026 · Theme: *Create a product to help you LARP as someone you are not.*

- **Live app:** https://townie.onrender.com
- **Judge screen:** https://townie.onrender.com/live
- **Code:** https://github.com/jeremyrd18/townie

## What it uses

| Piece | What it does | Cost |
|---|---|---|
| **ElevenLabs** | Speaks every answer (`eleven_flash_v2_5`). Scribe turns speech into text in the web app | Free plan |
| **Groq** | Main AI: writes the short answer (`openai/gpt-oss-120b`, backup `qwen/qwen3.8-27b`). Its built-in web search answers live questions | Free plan |
| **Featherless AI** | Backup AI if Groq is slow or at its limit (`Qwen/Qwen2.5-72B-Instruct`) | LarpHacks promo |
| **OpenStreetMap** | Real places, streets and addresses through Nominatim, with Overpass as backup | Free, no key |
| **Render** | Runs the whole backend live. Every push to GitHub redeploys | Free web plan |
| **Apple Shortcuts** | The trigger: Back Tap or Action Button, no app to install | Free |

## How it works

```
Back Tap → iPhone Shortcut (dictate + GPS) → POST /api/ask on Render
  → 1. Sort the question (keyword rules, AI only if unclear)
  → 2. Gather real facts (landmark list, OpenStreetMap, or live web search)
  → 3. Groq writes one short answer from those facts
  → 4. ElevenLabs turns it into audio → plays in the AirPods
  → 5. /live judge screen shows the question, answer, time and a map
```

| Question type | Example | Answer comes from |
|---|---|---|
| Nearest place | "Closest coffee?", "Chinese food nearby?" | OpenStreetMap, filtered by cuisine when asked |
| Distance | "Can we walk to the CN Tower?" | 22 curated landmarks, or a map search |
| What's here | "What's that building?" | Map lookup, using the compass heading in the web app |
| General knowledge | "How tall is the CN Tower?" | The AI's own knowledge |
| Happening now | "Anything on tonight?", "Is it open?", "Who's the mayor?" | Live web search |

**Answer style:** plain words, about 12 words, only what was asked. For example "32 minutes southeast, about 2.7 km." or "553 metres." Fun facts only when asked.

**Never made up:** the AI only phrases the answer. Places, walking times and directions come from map data and our own maths (walking time = straight-line km × 1.3 ÷ 5 km/h).

**Speed:** about 1 to 2 seconds for normal questions, 3 to 5 for live web questions.

### Backups at every step

| If this fails | Townie uses |
|---|---|
| Groq's main model is slow (over 2.5s) or at its limit | Groq's second model, then Featherless. The first good answer wins |
| An AI reply is garbled | It's thrown out and the next model answers |
| Groq web search is at its limit | Free DuckDuckGo results passed to the normal model. It's told never to invent times or events |
| Every AI | A plain sentence built straight from the map data |
| ElevenLabs | A free Edge voice (`en-CA-ClaraNeural`). `/live` shows which voice spoke |
| Busy OpenStreetMap servers | `data/osm_snapshot.json`: saved places for the demo areas |
| Everything | "One sec, still checking." Never an error |

## Pages and API

| URL | What |
|---|---|
| `/` | Backup web app: type or hold to talk, GPS, compass, demo-location picker |
| `/live` | **Judge screen.** Put it on the projector |
| `/prep` | Prep mode (extra): a day plan and five fun facts before friends arrive |
| `POST /api/ask?format=mp3` | JSON `{question, lat, lon, heading?}`. Returns MP3, with the text in the `X-Say` header |
| `POST /api/ask?format=json` | Returns `{say, intent, facts, seconds, voice, audio_b64}`. Add `"want_audio": true` for audio |
| `?demo=1` or `?demo=union` | Ignore GPS and use a demo spot (`venue`, `union`, `cn`, `nps`, `kensington`, `distillery`) |
| `GET /api/live` | Last 10 questions and answers |
| `GET /api/config` | Which AI models are set up, in order (never shows keys) |
| `GET /api/check` | Pings each AI model from the server and shows its status and time |

`/api/ask` is forgiving: `question`, `lat` and `lon` can come from the JSON body, headers or URL, and `long`, `lng` or `longitude` also work for `lon`.

## Run it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # paste the keys in
uvicorn app.main:app --reload
```

Ask a question as if you're at Union Station:

```bash
curl -s -X POST "http://localhost:8000/api/ask?format=json" -H "Content-Type: application/json" -d '{"question":"where is the nearest coffee shop","lat":43.6453,"lon":-79.3806}'
```

Save nearby places for a new spot, such as the venue, then commit `data/osm_snapshot.json`:

```bash
python scripts/build_snapshot.py 43.6596 -79.3977
```

### Settings (`.env` locally, Environment tab on Render)

| Setting | What it does |
|---|---|
| `GROQ_API_KEY`, `ELEVENLABS_API_KEY` | Needed for the full experience |
| `FEATHERLESS_API_KEY`, `GEMINI_API_KEY` | Optional backup AIs |
| `LLM_ORDER` | Which AI to try first. Default `groq,featherless,gemini`. Only providers with a key are used |
| `VOICE_SPEED` | 1.0 is normal; default 0.9 is calmer (range 0.7 to 1.2) |
| `WHISPER_VOICE_ID` | ElevenLabs voice |
| `WEB_SEARCH` | `off` to turn live web search off |
| `DEMO_LAT`, `DEMO_LON`, `DEMO_NAME` | The `venue` demo spot (defaults to Union Station) |

## Deploy on Render (free)

1. On render.com: **New → Blueprint**, then pick this repo. `render.yaml` sets everything up. Paste the keys when asked.
2. If Render asks for a card, use **New → Web Service** instead: Python 3, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, instance type Free.
3. The free plan sleeps after 15 idle minutes, and the first request then takes about 50 seconds. Open `/live` a few minutes before a demo and leave it open; it keeps the app awake. `.github/workflows/keep-warm.yml` can also ping it every 10 minutes once you set a GitHub Actions variable `TOWNIE_URL`.

**Free-plan limits:** Groq allows about 1,000 requests and 200,000 tokens per model per day. A normal answer uses about 1,000 tokens; a web search about 12,000. ElevenLabs' free plan covers roughly 150 to 300 answers a month. Avoid heavy testing right before a demo.

## The iPhone Shortcut ("Ask Townie")

1. Open Shortcuts, tap **+**, and name it **Ask Townie**.
2. **Dictate Text**: Language English, Stop Listening **After Pause**.
3. **Get Current Location**: Precision **Best**.
4. **Get Contents of URL**: `https://townie.onrender.com/api/ask?format=mp3`. Method **POST**, Request Body **JSON**:
   - `question` (Text) = Dictated Text
   - `lat` (Number) = Current Location → Latitude
   - `lon` (Number) = Current Location → Longitude
5. **Play Sound**: Contents of URL.
6. Run it once by hand and tap **Always Allow** on every prompt.
7. **Back Tap:** Settings → Accessibility → Touch → Back Tap → Double Tap → Ask Townie.
   **Action Button** (15 Pro or newer): Settings → Action Button → Shortcut → Ask Townie.

Indoors with bad GPS, add `&demo=1` to the URL. Backup if Play Sound fails: use `format=json`, then **Get Dictionary Value** `say`, then **Speak Text**.

## Project layout

```
app/main.py        Web routes: /api/ask, /live, /api/live, /prep, /api/check
app/brain.py       Question sorting, fact gathering, prompts, fallback sentences
app/places.py      OpenStreetMap lookups, walking time, directions, TTC stations
app/landmarks.py   22 Toronto landmarks with aliases and one fun fact each
app/llm.py         Groq / Featherless / Gemini with automatic backups and web search
app/web.py         Free DuckDuckGo search (backup for live questions)
app/voice.py       ElevenLabs speech, backup voice, speech-to-text
app/prep.py        Prep mode day plans
app/mail.py        Agentboxd inbox (built, not set up)
workflow.py        Prep mode as a Render Workflow (built, not deployed)
static/            Web app, judge screen, prep page
data/              Saved map results for the demo areas
```

**Built but not switched on:** Prep mode can run as a Render Workflow (`workflow.py`, which needs a Workflow service plus `RENDER_API_KEY` and `WORKFLOW_SLUG`), and can email cheat sheets through an Agentboxd inbox (needs `AGENTBOXD_API_KEY`). Without them, Prep mode runs inside the web service.

## The two-minute demo

1. "My friends are visiting Toronto and think I'm a local. Truth is, I barely leave my apartment. So we built Townie."
2. Put `/live` on the projector: "You can't hear my AirPod, so this screen shows what Townie whispers."
3. A teammate asks "Where's the closest coffee?" Double-tap, stall ("hmm, okay so…"), then say the answer in your own words.
4. "Can we walk to the CN Tower?", then "How tall is it anyway?"
5. Backend in 20 seconds: "My phone sends the question and my location to our server on Render. We find real places with OpenStreetMap and calculate the walking time ourselves, so nothing is made up. Groq turns it into one short answer, and ElevenLabs whispers it in my ear, all in about two seconds."
