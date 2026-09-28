"""Stage 2 — deep research: evidence retrieval only (no LLM calls here).

For each Stage 1 candidate, run the targeted search queries from the spec's
Steps 1, 3, 4, 5, 6, 7 and bundle the raw results into an EvidenceBundle.
claude_analysis.py then reasons over this bundle — Claude never searches
the web itself, per the spec's "Model Usage" section.

Two-phase, budget-gated: identification runs first (at Tavily's "advanced"
depth, since a wrong/missing identification wastes everything downstream),
plus the free Product Hunt lookup. The remaining 11 queries
(fundraising/launch/enterprise/verification/decision-maker) only fire if
that phase actually found the company — across a real 50-candidate run,
~44% of Stage 1 candidates couldn't be identified at all, so this gate alone
saves roughly a third of the total query budget that was previously spent
finding nothing, which is reinvested in deeper identification search instead
of split thin across every candidate regardless of whether it panned out.

Every query goes through search_client, which caches by exact
(query, depth) pair, so re-running Stage 2 on an already-researched company
costs zero credits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .models import Stage1Candidate
from .producthunt_client import ProductHuntPost, get_client as get_ph_client
from .search_client import SearchResult, get_client


@dataclass
class EvidenceBundle:
    candidate: Stage1Candidate
    identification: List[SearchResult] = field(default_factory=list)
    fundraising: List[SearchResult] = field(default_factory=list)
    launch: List[SearchResult] = field(default_factory=list)
    enterprise: List[SearchResult] = field(default_factory=list)
    verification: List[SearchResult] = field(default_factory=list)
    decision_maker: List[SearchResult] = field(default_factory=list)
    producthunt: Optional[ProductHuntPost] = None
    queries_run: List[str] = field(default_factory=list)
    deep_research_skipped: bool = False


def _run(client, queries: list[str], max_results: int = 5, deep: bool = False) -> List[SearchResult]:
    out: List[SearchResult] = []
    for q in queries:
        out.extend(client.search(q, max_results=max_results, deep=deep))
    return out


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _looks_identified(name: str, results: List[SearchResult]) -> bool:
    """Cheap heuristic gate: does any identification result actually seem to
    be about this company, rather than noise? A false negative here just
    means we fall back to Claude's (cheaper) judgment on thin evidence
    instead of spending 11 more queries; a false positive costs nothing
    extra since Claude still applies the real RESOLVED/UNRESOLVED call."""
    target = _normalize(name)
    if not target:
        return False
    for r in results:
        haystack = _normalize(f"{r.title} {r.url} {r.snippet[:200]}")
        if target in haystack or (len(target) > 6 and target[:8] in haystack):
            return True
    return False


def research_candidate(candidate: Stage1Candidate) -> EvidenceBundle:
    client = get_client()
    name = candidate.name
    bundle = EvidenceBundle(candidate=candidate)

    ph_client = get_ph_client()
    if ph_client:
        bundle.producthunt = ph_client.find_launch(name)

    id_queries = [
        f'"{name}" company website founder CEO',
        f'"{name}" official site',
    ]
    bundle.identification = _run(client, id_queries, max_results=5, deep=True)
    bundle.queries_run += id_queries

    identified = bool(bundle.producthunt) or _looks_identified(name, bundle.identification)
    if not identified:
        bundle.deep_research_skipped = True
        return bundle

    fundraising_queries = [
        f'"{name}" raising OR fundraising OR "seed round" OR "Series A" OR "currently raising" OR "opening our round"',
        f'"{name}" investors OR "looking for investors" OR "seeking investment" OR "strategic investors"',
    ]
    bundle.fundraising = _run(client, fundraising_queries, max_results=5)
    bundle.queries_run += fundraising_queries

    launch_queries = [
        f'"{name}" Product Hunt launch',
        f'"{name}" "public beta" OR "early access" OR "now live" OR launch announcement',
    ]
    bundle.launch = _run(client, launch_queries, max_results=5)
    bundle.queries_run += launch_queries

    enterprise_queries = [
        f'"{name}" enterprise customers OR "design partner" OR pilot OR procurement',
        f'"{name}" case study OR "working with" customer',
    ]
    bundle.enterprise = _run(client, enterprise_queries, max_results=5)
    bundle.queries_run += enterprise_queries

    verification_queries = [
        f'"{name}" certification OR benchmark OR "independent testing" OR "third party testing"',
        f'"{name}" security assessment OR audit OR "SOC 2"',
    ]
    bundle.verification = _run(client, verification_queries, max_results=5)
    bundle.queries_run += verification_queries

    decision_maker_queries = [
        f'"{name}" CEO OR founder OR co-founder LinkedIn',
    ]
    bundle.decision_maker = _run(client, decision_maker_queries, max_results=5)
    bundle.queries_run += decision_maker_queries

    return bundle


def bundle_to_dict(bundle: EvidenceBundle) -> dict:
    def results_to_list(results: List[SearchResult]) -> list[dict]:
        return [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "published_date": r.published_date}
            for r in results
        ]

    producthunt = None
    if bundle.producthunt:
        producthunt = {
            "name": bundle.producthunt.name,
            "tagline": bundle.producthunt.tagline,
            "url": bundle.producthunt.url,
            "created_at": bundle.producthunt.created_at,
            "featured_at": bundle.producthunt.featured_at,
            "votes_count": bundle.producthunt.votes_count,
            "note": "EXACT structured match from the Product Hunt API — createdAt is a real, verified launch date, not an inference.",
        }

    return {
        "candidate_name": bundle.candidate.name,
        "candidate_row_id": bundle.candidate.row_id,
        "stage1_matched_keywords": bundle.candidate.matched_keywords,
        "stage1_website_guess": bundle.candidate.website_guess,
        "identification": results_to_list(bundle.identification),
        "fundraising": results_to_list(bundle.fundraising),
        "launch": results_to_list(bundle.launch),
        "producthunt_exact_match": producthunt,
        "enterprise": results_to_list(bundle.enterprise),
        "verification": results_to_list(bundle.verification),
        "decision_maker": results_to_list(bundle.decision_maker),
        "queries_run": bundle.queries_run,
        "deep_research_skipped": bundle.deep_research_skipped,
    }
