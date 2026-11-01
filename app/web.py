"""Free web search with no API key (DuckDuckGo), used when Groq's built-in search is at its limit."""
import asyncio


def _search(query: str, max_results: int) -> list:
    from ddgs import DDGS
    return DDGS().text(query, region="ca-en", max_results=max_results) or []


async def snippets(query: str, max_results: int = 5, timeout: float = 4.0) -> list[dict]:
    """Top results as [{title, text}], or [] on any failure or timeout."""
    try:
        results = await asyncio.wait_for(asyncio.to_thread(_search, query, max_results), timeout)
    except Exception as e:
        print(f"[web] search failed: {e!r}")
        return []
    return [{"title": r.get("title", "")[:120], "text": r.get("body", "")[:300]} for r in results]
