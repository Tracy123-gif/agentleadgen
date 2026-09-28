"""Stage 1 — cheap deterministic filter: 3,000+ rows -> a few hundred candidates.

Per the spec, this stage must NOT do deep LLM research. It only uses:
  1. Free-text keyword matching against fields already in the input row.
  2. A free homepage fetch (if a website/URL column exists in the input),
     also keyword-matched.
  3. Optionally, one lightweight cached search query per row IF a website
     column is not available and search budget remains — this is the only
     part of Stage 1 that spends search credits, and it's capped by
     config.MAX_SEARCH_QUERIES_PER_RUN so a 3,000-row file can't silently
     blow through a free-tier quota.

Output: a ranked candidate list, checkpointed to JSON, plus a CSV for human
review before Stage 2 spends real research budget on them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import requests

from . import config
from .keywords import score_categories, score_text
from .models import InputRow, Stage1Candidate
from .search_client import get_client

HOMEPAGE_FETCH_TIMEOUT = 8


def _find_url(row: InputRow) -> str | None:
    for key, val in row.extra.items():
        kl = key.lower()
        if "url" in kl or "website" in kl or "link" in kl:
            val_s = str(val).strip()
            if val_s.startswith("http"):
                return val_s
    return None


def _fetch_homepage_text(url: str) -> str:
    try:
        resp = requests.get(url, timeout=HOMEPAGE_FETCH_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AgentVetResearch/1.0)"
        })
        resp.raise_for_status()
        return resp.text[:20000]
    except requests.RequestException:
        return ""


def run_stage1(
    rows: List[InputRow],
    top_n: int = 500,
    min_score: int = 1,
    use_homepage_fetch: bool = True,
    use_search_fallback: bool = False,
) -> List[Stage1Candidate]:
    client = get_client() if use_search_fallback else None
    queries_used = 0
    candidates: List[Stage1Candidate] = []

    for row in rows:
        base_text = " ".join([row.name, row.categories, row.source] + [str(v) for v in row.extra.values()])
        score, matched = score_text(base_text)
        cat_score = score_categories(row.categories)
        score += cat_score
        if cat_score:
            matched.append(f"category_prior:{cat_score:+d}")
        website = _find_url(row)

        if website and use_homepage_fetch:
            homepage_text = _fetch_homepage_text(website)
            hp_score, hp_matched = score_text(homepage_text)
            score += hp_score
            matched += [f"homepage:{m}" for m in hp_matched]
        elif not website and use_search_fallback and queries_used < config.MAX_SEARCH_QUERIES_PER_RUN:
            results = client.search(f'"{row.name}" (raising OR funding OR launch OR enterprise)', max_results=3)
            queries_used += 1
            search_text = " ".join(f"{r.title} {r.snippet}" for r in results)
            s_score, s_matched = score_text(search_text)
            score += s_score
            matched += [f"search:{m}" for m in s_matched]
            if results:
                website = results[0].url

        candidates.append(Stage1Candidate(
            row_id=row.row_id,
            name=row.name,
            categories=row.categories,
            source=row.source,
            signal_score=score,
            matched_keywords=matched,
            website_guess=website,
        ))

    candidates = [c for c in candidates if c.signal_score >= min_score]
    candidates.sort(key=lambda c: c.signal_score, reverse=True)
    return candidates[:top_n]


def save_candidates(candidates: List[Stage1Candidate], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([c.__dict__ for c in candidates], f, indent=2)


def load_candidates(path: Path) -> List[Stage1Candidate]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Stage1Candidate(**d) for d in data]
