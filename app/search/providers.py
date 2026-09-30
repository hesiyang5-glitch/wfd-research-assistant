"""Web search adapters. Search is a separate service from the language model: each adapter calls a real
search API over HTTPS. There is deliberately no 'model memory' fallback — if no provider is configured,
automatic discovery is reported as unavailable."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from ..config import env

TIMEOUT = httpx.Timeout(25.0, connect=10.0)


class SearchError(Exception):
    pass


class SearchProvider:
    name = "base"
    supports_paging = True
    is_test = False

    def search(self, query: str, page: int = 1, count: int = 10) -> list[dict]:
        raise NotImplementedError


class BraveSearch(SearchProvider):
    """Brave Search API — https://api.search.brave.com (needs BRAVE_API_KEY)."""
    name = "brave"

    def __init__(self, key: str):
        self.key = key

    def search(self, query, page=1, count=10):
        params = {"q": query, "count": min(count, 20), "offset": max(0, page - 1), "safesearch": "off"}
        try:
            r = httpx.get("https://api.search.brave.com/res/v1/web/search", params=params, timeout=TIMEOUT,
                          headers={"X-Subscription-Token": self.key, "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise SearchError(f"network error: {e}") from e
        if r.status_code != 200:
            raise SearchError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        out = []
        for i, it in enumerate((data.get("web") or {}).get("results", [])):
            out.append({"url": it.get("url"), "title": it.get("title", ""), "snippet": it.get("description", ""),
                        "published": it.get("page_age") or it.get("age") or "", "rank": i + 1})
        return out


class TavilySearch(SearchProvider):
    """Tavily search API — https://api.tavily.com (needs TAVILY_API_KEY). No page offsets; asks for more results instead."""
    name = "tavily"
    supports_paging = False

    def __init__(self, key: str):
        self.key = key

    def search(self, query, page=1, count=10):
        if page > 1:
            return []
        body = {"query": query, "max_results": min(max(count * 2, 10), 20), "search_depth": "advanced",
                "include_answer": False, "api_key": self.key}
        try:
            r = httpx.post("https://api.tavily.com/search", json=body, timeout=TIMEOUT,
                           headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        except httpx.HTTPError as e:
            raise SearchError(f"network error: {e}") from e
        if r.status_code != 200:
            raise SearchError(f"HTTP {r.status_code}: {r.text[:200]}")
        out = []
        for i, it in enumerate(r.json().get("results", [])):
            out.append({"url": it.get("url"), "title": it.get("title", ""), "snippet": (it.get("content") or "")[:500],
                        "published": it.get("published_date") or "", "rank": i + 1})
        return out


class SearxngSearch(SearchProvider):
    """Self-hosted SearXNG metasearch (free). Needs SEARXNG_URL, with JSON output enabled in its settings."""
    name = "searxng"

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def search(self, query, page=1, count=10):
        try:
            r = httpx.get(f"{self.base}/search", params={"q": query, "format": "json", "pageno": page}, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise SearchError(f"network error: {e}") from e
        if r.status_code != 200:
            raise SearchError(f"HTTP {r.status_code}: {r.text[:200]}")
        out = []
        for i, it in enumerate(r.json().get("results", [])[:count]):
            out.append({"url": it.get("url"), "title": it.get("title", ""), "snippet": it.get("content", ""),
                        "published": it.get("publishedDate") or "", "rank": i + 1})
        return out


class FixtureSearch(SearchProvider):
    """TEST ONLY. Replays saved results from a JSON file named by WFD_TEST_FIXTURE, for automated tests in
    environments without internet. Every query it answers is logged with provider 'TEST-FIXTURE' so it can
    never be mistaken for a real search."""
    name = "TEST-FIXTURE"
    is_test = True

    def __init__(self, path: str):
        self.data = json.loads(Path(path).read_text(encoding="utf-8"))

    def search(self, query, page=1, count=10):
        if page > 1:
            return []
        ql = query.lower()
        out = []
        for it in self.data.get("results", []):
            keys = [k.lower() for k in it.get("match", [])]
            if not keys or any(k in ql for k in keys):
                out.append({k: it[k] for k in ("url", "title", "snippet", "published") if k in it})
        for i, o in enumerate(out):
            o["rank"] = i + 1
        return out[:count]


def get_provider(choice: str = "auto") -> SearchProvider | None:
    if os.environ.get("WFD_TEST_FIXTURE"):
        return FixtureSearch(os.environ["WFD_TEST_FIXTURE"])
    order = [choice] if choice not in ("auto", "", None) else ["tavily", "brave", "searxng"]
    for c in order:
        if c == "brave" and env("BRAVE_API_KEY"):
            return BraveSearch(env("BRAVE_API_KEY"))
        if c == "tavily" and env("TAVILY_API_KEY"):
            return TavilySearch(env("TAVILY_API_KEY"))
        if c == "searxng" and env("SEARXNG_URL"):
            return SearxngSearch(env("SEARXNG_URL"))
    return None
