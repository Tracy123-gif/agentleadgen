"""Product Hunt v2 GraphQL client — structured launch-date evidence.

Verified live against the real API (2026-09-26): v2 has NO free-text search
field. `posts()` only filters by id/slug/url/twitterUrl/topic/date/featured —
there is no `query`/`search` argument like topics() has. So exact company
name matching isn't possible through a single call.

Approach used here: guess a handful of plausible slugs from the
company/agent name (PH slugs are near-always a lowercase, hyphenated form of
the launch title) and look each up with `post(slug: ...)`, which is an exact
match — a hit is high-confidence structured data (real createdAt, votesCount,
url), a miss is simply no PH evidence (never a false positive, since it's an
exact slug match, not a fuzzy one). This is a real limitation of the API, not
a shortcut: some genuine PH launches will be missed if their slug doesn't
match any guessed variant.

Uses the developer token directly as a Bearer token — no OAuth
client-credentials exchange needed for read-only public data.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

from . import cache, config

ENDPOINT = "https://api.producthunt.com/v2/api/graphql"

POST_BY_SLUG_QUERY = """
query PostBySlug($slug: String!) {
  post(slug: $slug) {
    name
    slug
    tagline
    url
    website
    createdAt
    featuredAt
    votesCount
  }
}
"""


@dataclass
class ProductHuntPost:
    name: str
    slug: str
    tagline: str
    url: str
    website: str
    created_at: str
    featured_at: Optional[str]
    votes_count: int


def _slug_variants(name: str) -> list[str]:
    base = name.strip().lower()
    # Strip common suffixes that rarely appear in PH slugs.
    base = re.sub(r"\.(ai|io|app|co)$", "", base)
    variants = set()

    hyphenated = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    variants.add(hyphenated)

    no_dots = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    variants.add(no_dots)

    squashed = re.sub(r"[^a-z0-9]+", "", base)
    variants.add(squashed)

    return [v for v in variants if v]


class ProductHuntClient:
    def __init__(self, token: str):
        if not token:
            raise ValueError(
                "PRODUCTHUNT_DEVELOPER_TOKEN is not set. Add it to .env."
            )
        self.token = token
        self._count = 0

    def _post_by_slug(self, slug: str) -> Optional[dict]:
        def fetch():
            resp = requests.post(
                ENDPOINT,
                json={"query": POST_BY_SLUG_QUERY, "variables": {"slug": slug}},
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=20,
            )
            if resp.status_code == 429:
                return {"__rate_limited__": True}
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("post")

        raw, was_cached = cache.cached_or_fetch("producthunt_slug", slug, fetch)
        if not was_cached:
            self._count += 1
            if self._count % 30 == 0:
                time.sleep(1)
        return raw

    def find_launch(self, name: str) -> Optional[ProductHuntPost]:
        """Best-effort: try a few slug guesses, return the first exact hit."""
        for slug in _slug_variants(name):
            post = self._post_by_slug(slug)
            if post and not post.get("__rate_limited__"):
                return ProductHuntPost(
                    name=post["name"],
                    slug=post["slug"],
                    tagline=post.get("tagline", ""),
                    url=post.get("url", ""),
                    website=post.get("website", ""),
                    created_at=post.get("createdAt", ""),
                    featured_at=post.get("featuredAt"),
                    votes_count=post.get("votesCount", 0),
                )
        return None

    def query_count(self) -> int:
        return self._count


_client_singleton: ProductHuntClient | None = None


def get_client() -> Optional[ProductHuntClient]:
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton
    if not config.PRODUCTHUNT_DEVELOPER_TOKEN:
        return None
    _client_singleton = ProductHuntClient(config.PRODUCTHUNT_DEVELOPER_TOKEN)
    return _client_singleton
