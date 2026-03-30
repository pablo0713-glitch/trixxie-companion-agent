from __future__ import annotations

import httpx

from core.persona import MessageContext


async def handle_web_search(
    tool_input: dict,
    context: MessageContext,
    search_provider: str,
    search_api_key: str,
) -> str:
    query = tool_input.get("query", "").strip()
    num_results = min(int(tool_input.get("num_results", 5)), 10)

    if not query:
        return "No query provided."

    if search_provider == "serper":
        results = await _serper_search(query, num_results, search_api_key)
    elif search_provider == "brave":
        results = await _brave_search(query, num_results, search_api_key)
    else:
        return f"Unknown search provider: {search_provider}"

    if not results:
        return "No results found."

    return _format_results(results)


async def _serper_search(query: str, num_results: int, api_key: str) -> list[dict]:
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": num_results}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    items = []
    for r in data.get("organic", [])[:num_results]:
        items.append({
            "title": r.get("title", ""),
            "snippet": r.get("snippet", ""),
            "url": r.get("link", ""),
        })
    return items


async def _brave_search(query: str, num_results: int, api_key: str) -> list[dict]:
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": query, "count": num_results}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    items = []
    for r in data.get("web", {}).get("results", [])[:num_results]:
        items.append({
            "title": r.get("title", ""),
            "snippet": r.get("description", ""),
            "url": r.get("url", ""),
        })
    return items


def _format_results(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        if r["url"]:
            lines.append(f"   {r['url']}")
    return "\n".join(lines)
