# AgentVet Lead Qualification Pipeline

Turns AgentVet's existing 3,000+ AI agent database into a ranked, evidence-backed
outreach shortlist. Does not discover new agents — that's solved. This answers:
*which of these companies should AgentVet contact first, who, why now, and what's
the proof?*

Output: a 3-tab XLSX matching `AgentVet_Lead_Intelligence_Structure.pdf` exactly —
**HIGH PRIORITY**, **ALL QUALIFIED LEADS**, **RESEARCH - EVIDENCE**. The original
input database is never modified.

## Target ICP

**As of 2026-09-28, this deliberately inverts the original spec's fundraising
priority.** The spec as originally written scored active-fundraising signals
highest (companies mid-raise = hot prospects, since they're actively courting
outside scrutiny). Per explicit direction, the actual target is the opposite:
**agents with confirmed NO funding who need it** — the underfunded, not the
well-backed. The thesis: a company already raising or already funded has
external validation and less need for AgentVet; a company with no funding and
no independent verification is the one AgentVet certification can actually
help (a credibility lever to attract investors/customers they don't have
yet). `src/scoring.py` and the Claude prompt in `src/claude_analysis.py` both
reflect this — see the "TARGET ICP" note at the top of each file if this
changes again.

## Architecture

```
Input DB (3,000+ rows)
      -> Stage 1: deterministic keyword/homepage filter (free, no LLM)   [run_stage1.py]
      -> Candidate shortlist (~300-500)
      -> Stage 2: cached web search -> Claude analysis -> deterministic scoring [run_stage2.py]
      -> Per-candidate checkpoints (resumable, never re-pays for a company twice)
      -> Export: dedupe + write XLSX                                     [run_export.py]
```

Claude never searches the web itself — `research.py` retrieves evidence via
search APIs + Product Hunt, and `claude_analysis.py` only classifies/reasons
over the snippets already collected. Scoring (`scoring.py`) is plain
arithmetic against the spec's fixed point system, not LLM math, so it's
auditable and reproducible.

**Search backend:** two free-tier providers, tried in order with automatic
fallback when one runs out of quota for the run (`src/search_client.py`):
Tavily (1,000/month, no daily cap) and Brave Search (2,000/month, independent
index). ~3,000 combined free queries/month. To add another provider (Google
CSE, Exa, SerpAPI), implement `SearchClient` and add it to `_build_provider()`
— nothing else changes.

**Product Hunt:** `src/producthunt_client.py` looks up each candidate's exact
launch date via the Product Hunt v2 GraphQL API using a developer token
(no OAuth flow needed). Its `posts()` query has no free-text search — only
exact `slug`/`url`/`id` lookups — so this guesses a few plausible slugs from
the company name and does an exact match. A hit gives a verified `createdAt`
date (used in preference to any search-snippet inference); a miss just means
no Product Hunt evidence, never a false positive. This costs nothing against
the Tavily/Brave budget above.

**Realistic free-tier throughput (Tavily only, current setup):** Stage 2 is
budget-gated in two phases (`src/research.py`). Phase 1 is identification —
2 queries at Tavily's "advanced" depth, plus the free Product Hunt lookup.
The remaining 11 queries (fundraising/launch/enterprise/verification/
decision-maker) only fire if that actually identified a real company. Across
the first real 50-candidate run, 44% couldn't be identified at all — under
the old flat-13-queries-always design that was pure waste; now those cost
~2 queries instead of 13. Net effect (weighting the advanced-depth cost):
~10 credits/candidate on average instead of 13, and unidentifiable
candidates cost ~85% less. At Tavily's 1,000 free queries/month that's
roughly **~100 companies/month**, up from ~76. The 500-candidate Stage 1
shortlist will take a few monthly batches to fully clear — `run_stage2.py`
is checkpointed per company so you just re-run it each month and it picks up
where it left off.

## Setup

```
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:
- `TAVILY_API_KEY` — free key at tavily.com.
- `BRAVE_API_KEY` — free key at brave.com/search/api.
- `PRODUCTHUNT_DEVELOPER_TOKEN` — from your app at
  producthunt.com/v2/oauth/applications ("Developer Token" section — use it
  directly, no OAuth exchange needed). Treat it like a password: it never
  expires, so if it's ever pasted somewhere outside your own `.env`, rotate
  it (Delete Token, generate a new one).
- `ANTHROPIC_API_KEY` — your Claude API key.
- `MAX_SEARCH_QUERIES_PER_RUN` / `MAX_CANDIDATES_STAGE2` — spend caps so a
  3,000-row file can't silently blow through a free-tier quota in one run.

## Google Sheets output (optional)

`run_export.py --gsheet` pushes the same 3 tabs to a live Google Sheet
instead of/alongside the local `.xlsx`, via `src/sheets_writer.py`. Setup:

1. Enable the Sheets API on your GCP project:
   console.cloud.google.com/apis/library/sheets.googleapis.com
2. Generate a JSON key for your service account (IAM & Admin > Service
   Accounts > your account > Keys > Add Key > JSON) and save it as
   `credentials/service_account.json` (gitignored — never commit it).
3. Create a blank Google Sheet in your own Drive and **share it** with the
   service account's email (looks like `...@<project>.iam.gserviceaccount.com`)
   as **Editor** — the service account can't see a sheet it isn't shared on.
4. Copy the Sheet ID from its URL
   (`docs.google.com/spreadsheets/d/<THIS PART>/edit`) into `GOOGLE_SHEET_ID`
   in `.env`.

Once `GOOGLE_SHEET_ID` is set, `run_export.py` pushes to it automatically
(no `--gsheet` flag needed); pass `--no-xlsx` to skip the local file
entirely and only write to the Sheet.

## Stage 1 category weighting

The input dataset only has Name/Categories/Source — no descriptions or
websites for most rows — so plain keyword matching on bare product names is
noisy (e.g. "LaunchLemonade" matches the word "launch" because it's in the
brand name, not because of a real launch signal). `src/keywords.py` adds a
zero-cost prior over the ~270 Category values in the real dataset, biasing
Stage 1 toward categories the spec's own rules treat as more likely
TRUE_AGENT (Sales, Customer Service, Digital Workers, Coding Agent, Workflow,
Lead Generation, ...) and away from ones it treats as more likely AI_TOOL
(Image/Video Generation, Music, Gaming, ...). This only affects who gets
Stage 2's limited budget first — it never rejects anything outright; that
call is Stage 2/Claude's, backed by real evidence.

## Running it

Drop your input file (columns: Name, Categories, Source — extra columns like
a Website/URL column are used automatically if present) into `data/input/`.

```
python run_stage1.py data/input/your_agents.csv --top-n 400
python run_stage2.py --max-candidates 50   # try a small batch first
python run_export.py
```

Re-running `run_stage2.py` is safe and cheap: each company is checkpointed to
`data/checkpoints/stage2/<row_id>.json` the moment it's processed, and every
individual search query is cached in `data/cache/` keyed by the exact query
string. Nothing gets re-researched or re-billed unless you delete the
checkpoint/cache files yourself.

`run_export.py` can be re-run at any time — it reads whatever checkpoints
exist so far, so you can export a partial result while Stage 2 is still
working through the rest of the candidate list.

## Notes on scoring/classification rules

- Fundraising (per the current ICP, see above): confirmed no funding scores
  highest — `NO_FUNDRAISING_SIGNAL` (+40) — while `RECENTLY_FUNDED` (-20) and
  active-fundraising statuses (0) are explicitly deprioritized, not rewarded.
  See `src/scoring.py`.
- Emails, launch dates, and funding amounts are never invented — Claude is
  instructed to return `null` rather than guess, per the spec's evidence
  requirement.
- `HIGH` priority requires score >= 70 **and** `TRUE_AGENT` **and** a
  confirmed `NO_FUNDRAISING_SIGNAL` **and** at least one evidence record —
  matching the current ICP, not score alone.
#   a g e n t l e a d g e n  
 