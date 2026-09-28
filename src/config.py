"""Central config loaded from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
CACHE_DIR = DATA_DIR / "cache"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
OUTPUT_DIR = DATA_DIR / "output"

for _d in (INPUT_DIR, CACHE_DIR, CHECKPOINT_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SEARCH_PROVIDERS = [
    p.strip().lower()
    for p in os.getenv("SEARCH_PROVIDERS", os.getenv("SEARCH_PROVIDER", "tavily")).split(",")
    if p.strip()
]
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")

PRODUCTHUNT_DEVELOPER_TOKEN = os.getenv("PRODUCTHUNT_DEVELOPER_TOKEN", "")

GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

MAX_SEARCH_QUERIES_PER_RUN = int(os.getenv("MAX_SEARCH_QUERIES_PER_RUN", "2000"))
MAX_CANDIDATES_STAGE2 = int(os.getenv("MAX_CANDIDATES_STAGE2", "500"))
