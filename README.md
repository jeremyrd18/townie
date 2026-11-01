# Townie

**LARP as a Toronto local.** Townie is for homebodies whose friends expect a tour. When a friend asks "where's the nearest coffee?" or "can we walk to the CN Tower?", double-tap the back of your iPhone. Townie hears the question, works out where you are, and whispers one confident sentence into your AirPods. Repeat it out loud like you always knew.

LarpHacks 2026 · Theme: *Create a product to help you LARP as someone you are not.*

| Piece | What it does | Cost |
|---|---|---|
| **ElevenLabs** | The whisper (TTS, `eleven_flash_v2_5`), the spoken prep briefing, and speech-to-text (Scribe) in the web app | Free plan (coupon adds credits) |
| **Groq** (main, fastest) / **Featherless**, **Gemini** (backups) | Writes the line to say, classifies unusual questions, and writes Prep mode plans | Free |
| **Render** | Hosts the web service. Prep mode runs as a **Render Workflow** with parallel subtasks | Free web plan; Workflows use hacker credits |
| **Agentboxd** | Townie's own email inbox: email it your friends' plans, and it replies with a cheat sheet | Free Builder plan, code `LARPHACKS-2026` |
| **OpenStreetMap** | Real places via Nominatim, with Overpass as backup. No key needed | Free |

## How it works

```
Back Tap → iPhone Shortcut (dictate + GPS) → POST /api/ask → intent (keyword rules, LLM if unclear)
→ real facts (landmark list + OpenStreetMap) → Groq writes a short answer → ElevenLabs MP3 → AirPods
                                                                   └→ /live judge screen (big text + map)
```

- **Switching language models needs no code change.** Townie tries every provider that has a key, in `LLM_ORDER` (default `groq,featherless,gemini`). Change the order to switch, no code needed.
- If ElevenLabs fails or runs out of free credits, a free Edge voice (`en-CA-ClaraNeural`) speaks instead. The `/live` screen shows which voice was used.
- Answers use only real places. If the language model is down, a template line is built from the same facts. If everything is down, it says "Give me one sec, let me check my maps."
- `data/osm_snapshot.json` stores nearby places for the demo spots, so the demo works even when the free OpenStreetMap servers are busy.

## Pages and API

| URL | What |
|---|---|
| `/` | Backup web app: hold to talk, GPS, compass, and a demo-location picker |
| `/live` | **Judge screen.** Put it on the projector. It shows the question, the whisper, and a map |
| `/prep` | Prep mode: day plan, five fun facts, spoken briefing, email cheat sheet, Townie's inbox |
| `POST /api/ask?format=mp3` | JSON `{question, lat, lon, heading?}` returns MP3. The text is in the `X-Say` header |
| `POST /api/ask?format=json` | Returns `{say, intent, facts, seconds, audio_b64}`. Add `"want_audio": true` for audio |
| `?demo=1` or `?demo=union` | Ignore GPS and use the venue or a demo spot (`union`, `cn`, `nps`, `kensington`, `distillery`) |
| `GET /api/live` | Last 10 Q&As |
| `POST /api/prep` | `{area, interests, email?}` returns a plan (via Render Workflow when configured) |

## Run it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # paste the keys in
uvicorn app.main:app --reload
```

Test it as if you're standing at Union Station:

```bash
curl -s -X POST "http://localhost:8000/api/ask?format=json" -H "Content-Type: application/json" -d '{"question":"where is the nearest coffee shop","lat":43.6453,"lon":-79.3806}'
```

Add the venue to the snapshot once you know its coordinates, then commit `data/osm_snapshot.json`:

```bash
python scripts/build_snapshot.py 43.6596 -79.3977
```

## Deploy on Render (free)

1. Push to GitHub. On render.com: **New → Blueprint**, then pick this repo. Paste the keys when it asks.
2. The free plan sleeps after 15 idle minutes, and the first request then takes about 50 seconds. To keep it awake:
   - Add a GitHub Actions variable `TOWNIE_URL` (Settings → Secrets and variables → Actions → Variables). `.github/workflows/keep-warm.yml` pings it every 10 minutes.
   - Open `/live` before your judging slot. It polls every second, which keeps the app awake.

### Prep mode as a Render Workflow (for the Render prize)

1. On Render: **New → Workflow**, same repo. Name it `townie-prep`.
   - Build command: `pip install -r requirements.txt`
   - Start command: `python workflow.py`
   - Add env vars `GROQ_API_KEY` (and/or `FEATHERLESS_API_KEY`) and `OSM_USER_AGENT`.
2. Create an API key in Render (Account Settings → API Keys). On the **web** service, set `RENDER_API_KEY` to that key and `WORKFLOW_SLUG=townie-prep`.
3. On `/prep`, click **Prep me**. The badge says "Ran on Render Workflows". In the dashboard, `prep_day` fans out to `locate_area`, three parallel `scout_spots` runs (coffee, food, sights), then `write_plan`.

Without these two env vars, Prep mode runs inside the web service, so nothing breaks.

### Agentboxd inbox

Sign up at agentboxd.com, then go to Settings → Redeem a code → `LARPHACKS-2026`. Create an API key (it starts with `mr_`) and set `AGENTBOXD_API_KEY`. `/prep` then shows Townie's address. Email it something like "my friends land Saturday, they love food and history, meeting at Kensington", then click **Check inbox and reply**.

## The iPhone Shortcut ("Ask Townie")

1. Open Shortcuts, tap **+**, and name it **Ask Townie**.
2. **Dictate Text**: Language English, Stop Listening **After Pause**.
3. **Get Current Location**.
4. **Get Contents of URL**: `https://YOUR-APP.onrender.com/api/ask?format=mp3`. Show More, then set Method **POST** and Request Body **JSON**:
   - `question` (Text) = Dictated Text
   - `lat` (Number) = Current Location → Latitude
   - `lon` (Number) = Current Location → Longitude
5. **Play Sound** with Contents of URL.
6. Run it once by hand and tap **Always Allow** on every prompt.
7. **Back Tap:** Settings → Accessibility → Touch → Back Tap → Double Tap → Ask Townie.
   **Action Button** (15 Pro or newer): Settings → Action Button → Shortcut → Ask Townie.

Indoors with bad GPS, add `&demo=1` to the URL to use the venue location.
Backup: use `format=json`, then **Get Dictionary Value** `say`, then **Speak Text**.

## The two-minute demo

1. "I've barely left my apartment in three years. My friends are visiting. Watch me host."
2. A teammate asks where the nearest coffee is. Double-tap, stall ("ooh, okay so…"), then repeat the whisper. `/live` shows it on the projector.
3. "Can we walk to the CN Tower from here?" Answer in minutes.
4. Flash `/prep`: the Render Workflow run and the cheat sheet in Townie's Agentboxd inbox.
5. Close: "ElevenLabs is the whisper, OpenStreetMap is the city, the language model is the local knowledge, Render is where it runs."
