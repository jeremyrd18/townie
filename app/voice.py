"""Voice in and out.
Speech out: ElevenLabs (the whisper), then free Edge voices as a backup.
Speech in (web app only): ElevenLabs Scribe, then Groq Whisper."""
from collections import OrderedDict

import httpx

from . import config

API = "https://api.elevenlabs.io/v1"
_tts_cache: OrderedDict = OrderedDict()


async def speak(text: str) -> bytes | None:
    """Turn a line into MP3 bytes. Returns None only if every voice fails."""
    audio, _ = await speak_with_engine(text)
    return audio


async def speak_with_engine(text: str) -> tuple[bytes | None, str | None]:
    if not text:
        return None, None
    if text in _tts_cache:
        _tts_cache.move_to_end(text)
        return _tts_cache[text]
    audio, engine = await _elevenlabs(text), "elevenlabs"
    if not audio:
        audio, engine = await _edge(text), "edge"
    if not audio:
        return None, None
    _tts_cache[text] = (audio, engine)
    if len(_tts_cache) > 50:
        _tts_cache.popitem(last=False)
    return audio, engine


async def _edge(text: str) -> bytes | None:
    try:
        import edge_tts
        data = b""
        async for chunk in edge_tts.Communicate(text, voice=config.BACKUP_VOICE, rate=f"{round((config.VOICE_SPEED - 1) * 100):+d}%").stream():
            if chunk["type"] == "audio":
                data += chunk["data"]
        return data or None
    except Exception as e:
        print(f"[edge tts] failed: {e!r}")
        return None


async def _elevenlabs(text: str) -> bytes | None:
    if not config.ELEVENLABS_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                f"{API}/text-to-speech/{config.WHISPER_VOICE_ID}",
                params={"output_format": "mp3_44100_64"},
                headers={"xi-api-key": config.ELEVENLABS_API_KEY, "accept": "audio/mpeg"},
                json={
                    "text": text,
                    "model_id": config.TTS_MODEL,
                    # Low style + high stability keeps it soft and even, like a whisper in your ear.
                    "voice_settings": {"stability": 0.6, "similarity_boost": 0.8, "style": 0.0, "speed": config.VOICE_SPEED},
                },
            )
            if r.status_code >= 400:
                print(f"[elevenlabs tts] {r.status_code}: {r.text[:200]}")
                return None
            return r.content
    except Exception as e:
        print(f"[elevenlabs tts] failed: {e!r}")
        return None


async def transcribe(audio: bytes, filename: str = "audio.webm", content_type: str = "audio/webm") -> str | None:
    """Speech to text: ElevenLabs Scribe, then Groq Whisper."""
    if not audio:
        return None
    return await _scribe(audio, filename, content_type) or await _groq_whisper(audio, filename, content_type)


async def _groq_whisper(audio: bytes, filename: str, content_type: str) -> str | None:
    if not config.GROQ_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                data={"model": config.GROQ_STT_MODEL, "language": "en", "response_format": "json"},
                files={"file": (filename, audio, content_type)},
            )
            r.raise_for_status()
            return (r.json().get("text") or "").strip()
    except Exception as e:
        print(f"[groq whisper] failed: {e!r}")
        return None


async def _scribe(audio: bytes, filename: str, content_type: str) -> str | None:
    if not config.ELEVENLABS_API_KEY:
        return None
    models = [config.STT_MODEL] + (["scribe_v1"] if config.STT_MODEL != "scribe_v1" else [])
    for model in models:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{API}/speech-to-text",
                    headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                    data={"model_id": model, "language_code": "en"},
                    files={"file": (filename, audio, content_type)},
                )
                r.raise_for_status()
                return (r.json().get("text") or "").strip()
        except Exception as e:
            print(f"[elevenlabs stt] {model} failed: {e!r}")
    return None
