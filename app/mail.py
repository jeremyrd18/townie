"""Agentboxd: gives Townie its own email inbox. Friends (or you) email it a plan, Townie replies with a cheat sheet."""
import httpx

from . import config

_inbox: dict | None = None


def enabled() -> bool:
    return bool(config.AGENTBOXD_API_KEY)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=config.AGENTBOXD_BASE_URL,
        headers={"Authorization": f"Bearer {config.AGENTBOXD_API_KEY}"},
        timeout=10.0,
    )


async def inbox() -> dict:
    """Create the Townie inbox once (idempotent on client_id) and remember it."""
    global _inbox
    if _inbox:
        return _inbox
    async with _client() as c:
        r = await c.post("/v1/inboxes", json={
            "username": config.AGENTBOXD_USERNAME, "display_name": "Townie", "client_id": "townie",
        })
        if r.status_code >= 400:  # username taken: let Agentboxd pick one
            r = await c.post("/v1/inboxes", json={"display_name": "Townie", "client_id": "townie"})
        r.raise_for_status()
        _inbox = r.json()
    return _inbox


async def send(to: str, subject: str, text: str, html: str) -> dict:
    box = await inbox()
    async with _client() as c:
        r = await c.post(f"/v1/inboxes/{box['id']}/messages/send",
                         json={"to": to, "subject": subject, "text": text, "html": html})
        r.raise_for_status()
        return r.json()


async def unread(limit: int = 5) -> list:
    box = await inbox()
    async with _client() as c:
        r = await c.get(f"/v1/inboxes/{box['id']}/messages",
                        params={"is_read": "false", "direction": "inbound", "limit": limit})
        r.raise_for_status()
        return r.json().get("data", [])


async def recent(limit: int = 10) -> list:
    box = await inbox()
    async with _client() as c:
        r = await c.get(f"/v1/inboxes/{box['id']}/messages", params={"limit": limit})
        r.raise_for_status()
        return r.json().get("data", [])


async def reply(message_id: str, text: str, html: str) -> None:
    box = await inbox()
    async with _client() as c:
        r = await c.post(f"/v1/inboxes/{box['id']}/messages/{message_id}/reply", json={"text": text, "html": html})
        r.raise_for_status()
        await c.patch(f"/v1/messages/{message_id}", json={"is_read": True})


def sender(msg: dict) -> str:
    f = msg.get("from")
    if isinstance(f, dict):
        return f.get("address") or f.get("email") or f.get("name") or ""
    if isinstance(f, list) and f:
        return sender({"from": f[0]})
    return str(f or "")
