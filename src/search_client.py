"""Pluggable web search backend with automatic provider fallback.

Providers wired in: Tavily (1,000 queries/month free, no daily cap,
LLM-pre-cleaned results), Brave Search (prepaid, ~1,000/month covered by its
$5 free monthly credit), and Google Programmable Search / Custom Search JSON
API (100 queries/day = ~3,000/month, genuinely free, no payment method).
SEARCH_PROVIDERS in .env lists them in try-order; when a provider reports
it's out of quota (429/402/403) for the rest of this run, the pipeline falls
over to the next one instead of failing.

Every call is cached (see cache.py), keyed by (provider, exact query
string), so re-running a stage never re-spends a query already answered —
and each provider's cache is kept separate so switching providers mid-run
never returns another provider's cached result under a shared key.

To add another provider (Google CSE, Exa, SerpAPI): implement SearchClient,
give it a unique `name`, and add it to `_build_provider()` below — nothing
else in the pipeline needs to change.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

import requests

from . import cache, config

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 3


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Retries on transient network errors (timeouts, connection drops) with
    short backoff — a single blip shouldn't crash an hour-long batch. Does
    NOT retry on a received response (even 4xx/5xx); those are handled by
    each client's own status-code logic (e.g. QuotaExhausted on 429)."""
    last_error: Optional[Exception] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < RETRY_ATTEMPTS:
                print(f"[search] network error ({e.__class__.__name__}), retrying ({attempt}/{RETRY_ATTEMPTS})...")
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last_error


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    published_date: str = ""


class SearchClient:
    name: str = "base"

    def search(self, query: str, max_results: int = 5, deep: bool = False) -> List[SearchResult]:
        """`deep=True` asks for a more thorough (costlier) search where the
        provider supports it (currently only Tavily's search_depth="advanced").
        Providers that don't support a depth knob just ignore the flag."""
        raise NotImplementedError

    def query_count(self) -> int:
        raise NotImplementedError


class QuotaExhausted(Exception):
    """Raised by a provider when it detects it's out of free-tier quota."""


class TavilyClient(SearchClient):
    name = "tavily"
    ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("TAVILY_API_KEY is not set.")
        self.api_key = api_key
        self._count = 0

    def search(self, query: str, max_results: int = 5, deep: bool = False) -> List[SearchResult]:
        depth = "advanced" if deep else "basic"

        def fetch():
            resp = _request_with_retry(
                "post",
                self.ENDPOINT,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": depth,
                    "max_results": max_results,
                    "include_answer": False,
                },
                timeout=30,
            )
            if resp.status_code in (429, 432, 433):
                raise QuotaExhausted(f"Tavily: {resp.status_code} {resp.text[:200]}")
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                    "published_date": r.get("published_date", "") or "",
                }
                for r in data.get("results", [])
            ]

        # depth is part of the cache key so a "basic" hit is never silently
        # substituted for an "advanced" request (or vice versa).
        cache_key = f"{query}::depth={depth}"
        raw, was_cached = cache.cached_or_fetch(f"search_{self.name}", cache_key, fetch)
        if not was_cached:
            self._count += 1
            if self._count % 20 == 0:
                time.sleep(1)
        return [SearchResult(**r) for r in raw]

    def query_count(self) -> int:
        return self._count


class BraveClient(SearchClient):
    name = "brave"
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("BRAVE_API_KEY is not set.")
        self.api_key = api_key
        self._count = 0

    def search(self, query: str, max_results: int = 5, deep: bool = False) -> List[SearchResult]:
        # Brave's API has no depth knob; `deep` is accepted for interface
        # compatibility with MultiProviderClient and ignored.
        def fetch():
            resp = _request_with_retry(
                "get",
                self.ENDPOINT,
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=30,
            )
            if resp.status_code == 429:
                raise QuotaExhausted(f"Brave: 429 {resp.text[:200]}")
            resp.raise_for_status()
            data = resp.json()
            results = (data.get("web") or {}).get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", ""),
                    "published_date": r.get("age", "") or "",
                }
                for r in results
            ]

        raw, was_cached = cache.cached_or_fetch(f"search_{self.name}", query, fetch)
        if not was_cached:
            self._count += 1
            if self._count % 20 == 0:
                time.sleep(1)
        return [SearchResult(**r) for r in raw]

    def query_count(self) -> int:
        return self._count


class GoogleCSEClient(SearchClient):
    name = "google_cse"
    ENDPOINT = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str):
        if not api_key or not cx:
            raise ValueError("GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX must both be set.")
        self.api_key = api_key
        self.cx = cx
        self._count = 0

    def search(self, query: str, max_results: int = 5, deep: bool = False) -> List[SearchResult]:
        # Google CSE has no depth knob; `deep` is accepted and ignored.
        def fetch():
            resp = _request_with_retry(
                "get",
                self.ENDPOINT,
                params={
                    "key": self.api_key,
                    "cx": self.cx,
                    "q": query,
                    "num": min(max_results, 10),
                },
                timeout=30,
            )
            if resp.status_code == 429:
                raise QuotaExhausted(f"Google CSE: 429 {resp.text[:200]}")
            if resp.status_code == 403 and "quota" in resp.text.lower():
                raise QuotaExhausted(f"Google CSE: 403 quota {resp.text[:200]}")
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                    "published_date": "",
                }
                for r in data.get("items", [])
            ]

        raw, was_cached = cache.cached_or_fetch(f"search_{self.name}", query, fetch)
        if not was_cached:
            self._count += 1
            if self._count % 20 == 0:
                time.sleep(1)
        return [SearchResult(**r) for r in raw]

    def query_count(self) -> int:
        return self._count


class NullClient(SearchClient):
    """No-op client used when no provider has a usable API key yet, so the
    rest of the pipeline can still be exercised on sample data offline."""
    name = "null"

    def search(self, query: str, max_results: int = 5, deep: bool = False) -> List[SearchResult]:
        return []

    def query_count(self) -> int:
        return 0


class MultiProviderClient(SearchClient):
    """Tries providers in order; once a provider raises QuotaExhausted it's
    skipped for the rest of this process run and the next provider is tried."""
    name = "multi"

    def __init__(self, providers: List[SearchClient]):
        self.providers = providers
        self._exhausted: set[str] = set()

    def search(self, query: str, max_results: int = 5, deep: bool = False) -> List[SearchResult]:
        last_error: Optional[Exception] = None
        for provider in self.providers:
            if provider.name in self._exhausted:
                continue
            try:
                return provider.search(query, max_results=max_results, deep=deep)
            except QuotaExhausted as e:
                print(f"[search] {provider.name} quota exhausted, falling back: {e}")
                self._exhausted.add(provider.name)
                last_error = e
            except requests.RequestException as e:
                print(f"[search] {provider.name} request failed, falling back: {e}")
                last_error = e
        if last_error:
            print(f"[search] all providers failed/exhausted for query: {query!r}")
        return []

    def query_count(self) -> int:
        return sum(p.query_count() for p in self.providers)


def _build_provider(name: str) -> Optional[SearchClient]:
    if name == "tavily" and config.TAVILY_API_KEY:
        return TavilyClient(config.TAVILY_API_KEY)
    if name == "brave" and config.BRAVE_API_KEY:
        return BraveClient(config.BRAVE_API_KEY)
    if name in ("google", "google_cse") and config.GOOGLE_CSE_API_KEY and config.GOOGLE_CSE_CX:
        return GoogleCSEClient(config.GOOGLE_CSE_API_KEY, config.GOOGLE_CSE_CX)
    return None


_client_singleton: SearchClient | None = None


def get_client() -> SearchClient:
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton

    providers = [p for p in (_build_provider(name) for name in config.SEARCH_PROVIDERS) if p is not None]
    if not providers:
        _client_singleton = NullClient()
    elif len(providers) == 1:
        _client_singleton = providers[0]
    else:
        _client_singleton = MultiProviderClient(providers)
    return _client_singleton
