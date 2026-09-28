"""Disk cache for search results and fetched pages.

Cost control requirement from the spec: never re-research the same
company/query twice. Every entry is keyed by a hash of (kind, key) and
stores the retrieval date + a content hash so unchanged sources are
detected without reprocessing.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from . import config


def _key_to_path(kind: str, key: str) -> Path:
    digest = hashlib.sha256(f"{kind}:{key}".encode("utf-8")).hexdigest()
    sub = digest[:2]
    d = config.CACHE_DIR / kind / sub
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{digest}.json"


def get(kind: str, key: str) -> Optional[dict]:
    path = _key_to_path(kind, key)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def set(kind: str, key: str, value: Any, source_url: str = "") -> None:
    path = _key_to_path(kind, key)
    content_str = json.dumps(value, sort_keys=True, default=str)
    content_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
    record = {
        "kind": kind,
        "key": key,
        "source_url": source_url,
        "retrieved_at": time.strftime("%Y-%m-%d"),
        "content_hash": content_hash,
        "value": value,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)


def cached_or_fetch(kind: str, key: str, fetch_fn, source_url: str = ""):
    """Return cached value if present, else call fetch_fn(), cache, and return it.

    fetch_fn should take no arguments and return a JSON-serializable value.
    """
    hit = get(kind, key)
    if hit is not None:
        return hit["value"], True
    value = fetch_fn()
    set(kind, key, value, source_url=source_url)
    return value, False
