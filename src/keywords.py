"""Keyword sets used by the deterministic Stage 1 filter.

These mirror the search query patterns in the AgentVet spec's Step 3
(fundraising), Step 4 (launch) and Step 5 (enterprise) sections, but are
applied as plain substring/keyword matches against text we already have for
free (input row fields, homepage text) rather than as paid search queries.
"""

FUNDRAISING_KEYWORDS = [
    "raising", "fundraising", "seed round", "series a", "series b",
    "opening our round", "currently raising", "looking for investors",
    "seeking investment", "strategic investors", "pre-seed", "pitch deck",
    "cap table", "term sheet", "lead investor", "closing our round",
]

RECENTLY_FUNDED_KEYWORDS = [
    "raised $", "has raised", "announced funding", "closed its round",
    "led by", "backed by", "secures funding", "funding round",
]

LAUNCH_KEYWORDS = [
    "launch", "launching", "now live", "public beta", "early access",
    "product hunt", "introducing", "we're excited to announce",
    "just shipped", "general availability", "waitlist",
]

ENTERPRISE_KEYWORDS = [
    "enterprise", "enterprise-ready", "design partner", "pilot program",
    "procurement", "security review", "soc 2", "soc2", "case study",
    "fortune 500", "working with", "enterprise pricing", "compliance",
]

VERIFICATION_KEYWORDS = [
    "certified", "certification", "independent audit", "third-party",
    "benchmark", "security assessment", "soc 2 type", "penetration test",
]

ALL_GROUPS = {
    "fundraising": FUNDRAISING_KEYWORDS,
    "recently_funded": RECENTLY_FUNDED_KEYWORDS,
    "launch": LAUNCH_KEYWORDS,
    "enterprise": ENTERPRISE_KEYWORDS,
    "verification": VERIFICATION_KEYWORDS,
}


# Soft prior over the input dataset's ~270 Category values. This does not
# reject anything (that's Stage 2/Claude's job, with real evidence) — it
# only reorders who gets Stage 2's limited search budget first, since a
# category like "Video Generation" is overwhelmingly AI_TOOL (-30 in the
# spec's own scoring) while "Digital Workers"/"Sales" skew TRUE_AGENT (+20).
AGENT_LIKELY_CATEGORIES = {
    "ai agents (general)": 3, "ai agents frameworks": 2, "digital workers": 3,
    "sales": 2, "customer service": 2, "personal assistant": 2,
    "data analysis": 1, "workflow": 2, "lead generation": 2,
    "coding agent": 2, "voice ai agents": 2, "web ai agents": 2,
    "research": 1, "seo agents": 1, "finance": 1, "ai security": 1,
    "marketing": 1,
}
AGENT_UNLIKELY_CATEGORIES = {
    "video generation": -3, "image generation": -3, "music": -3,
    "gaming": -2, "open source project": -1, "ai directories": -2,
    "content creation": -1,
}


def score_categories(categories: str) -> int:
    if not categories:
        return 0
    score = 0
    for token in categories.split(","):
        token = token.strip().lower()
        score += AGENT_LIKELY_CATEGORIES.get(token, 0)
        score += AGENT_UNLIKELY_CATEGORIES.get(token, 0)
    return score


def score_text(text: str) -> tuple[int, list[str]]:
    """Return (score, matched_keywords) for a blob of text across all groups.

    Fundraising and launch matches are weighted highest since those are the
    two signals that make a lead worth deep-researching in Stage 2.
    """
    if not text:
        return 0, []
    lowered = text.lower()
    score = 0
    matched: list[str] = []
    weights = {"fundraising": 3, "recently_funded": 1, "launch": 2, "enterprise": 2, "verification": 1}
    for group, kws in ALL_GROUPS.items():
        for kw in kws:
            if kw in lowered:
                score += weights[group]
                matched.append(f"{group}:{kw}")
    return score, matched
