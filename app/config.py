"""All settings come from environment variables (a local .env file, or Render's Environment tab)."""
import os

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY")
WHISPER_VOICE_ID = env("WHISPER_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
TTS_MODEL = env("TTS_MODEL", "eleven_flash_v2_5")
STT_MODEL = env("STT_MODEL", "scribe_v2")
# Free backup voice (Microsoft Edge voices, no key) when ElevenLabs fails or runs out of credits.
BACKUP_VOICE = env("BACKUP_VOICE", "en-CA-ClaraNeural")
# Speaking speed: 1.0 is normal, 0.85 is calm and easy to repeat. ElevenLabs allows 0.7 to 1.2.
VOICE_SPEED = min(1.2, max(0.7, float(env("VOICE_SPEED", "0.9"))))

# Language models. Townie uses whichever have keys, in this order.
LLM_ORDER = env("LLM_ORDER", "groq,featherless,gemini")

GROQ_API_KEY = env("GROQ_API_KEY")
GROQ_MODEL = env("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = env("GROQ_FALLBACK_MODEL", "qwen/qwen3.8-27b")
# Model used with live web search for "latest" questions (events, open now, current people).
SEARCH_MODEL = env("SEARCH_MODEL", "openai/gpt-oss-20b")
WEB_SEARCH = env("WEB_SEARCH", "on").lower() != "off"
GROQ_STT_MODEL = env("GROQ_STT_MODEL", "whisper-large-v3-turbo")

GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-2.5-flash")

FEATHERLESS_API_KEY = env("FEATHERLESS_API_KEY")
FEATHERLESS_MODEL = env("FEATHERLESS_MODEL", "Qwen/Qwen2.5-72B-Instruct")
FEATHERLESS_FALLBACK_MODEL = env("FEATHERLESS_FALLBACK_MODEL", "Qwen/Qwen2.5-7B-Instruct")

OSM_USER_AGENT = env("OSM_USER_AGENT", "Townie/1.0 (+https://github.com/jeremyrd18/townie)")

# Union Station by default. Set these to the venue for indoor demos.
DEMO_LAT = float(env("DEMO_LAT", "43.6453"))
DEMO_LON = float(env("DEMO_LON", "-79.3806"))
DEMO_NAME = env("DEMO_NAME", "Demo spot")

# Render Workflows (optional). Without these, Prep mode runs inside the web service.
RENDER_API_KEY = env("RENDER_API_KEY")
WORKFLOW_SLUG = env("WORKFLOW_SLUG")

# Agentboxd email (optional).
AGENTBOXD_API_KEY = env("AGENTBOXD_API_KEY")
AGENTBOXD_BASE_URL = env("AGENTBOXD_BASE_URL", "https://api.agentboxd.com")
AGENTBOXD_USERNAME = env("AGENTBOXD_USERNAME", "townie-larphacks")
