"""Saved search result store for the eispy CLI.

Captures search results per query so they can be reviewed independently
without being lost when a new search is issued.

Results are stored as JSON files under
``$XDG_CONFIG_HOME/eispy/searches/`` (default ``~/.config/eispy/searches/``).
Override with the ``EISPY_SEARCHES_DIR`` environment variable.

Each saved search contains the query string, search parameters, a
timestamp, and the list of results.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any


def _get_searches_dir() -> Path:
    """Return the directory for saved search results."""
    env = os.environ.get("EISPY_SEARCHES_DIR")
    if env:
        return Path(env)
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    )
    return config_home / "eispy" / "searches"


def _safe_filename(name: str) -> str:
    """Sanitise a name for use as a filename (no path traversal)."""
    # Allow alphanumeric, dash, underscore, dot
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    # Prevent empty or dot-only names
    safe = safe.strip("._ ") or "search"
    return safe


def save_search(
    name: str,
    query: str,
    results: list[dict[str, Any]],
    *,
    file_type: int = 0,
    size_mode: int = 0,
    size: int = 0,
    hub_url: str = "",
) -> Path:
    """Save a set of search results under the given name.

    Returns the path to the saved file.
    """
    d = _get_searches_dir()
    d.mkdir(parents=True, exist_ok=True)

    data = {
        "name": name,
        "query": query,
        "file_type": file_type,
        "size_mode": size_mode,
        "size": size,
        "hub_url": hub_url,
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "count": len(results),
        "results": results,
    }

    path = d / f"{_safe_filename(name)}.json"
    path.write_text(
        json.dumps(data, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def load_search(name: str) -> dict[str, Any] | None:
    """Load a saved search by name. Returns None if not found."""
    path = _get_searches_dir() / f"{_safe_filename(name)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_saved_searches() -> list[dict[str, Any]]:
    """List all saved searches (metadata only, no results).

    Returns a list of dicts with: name, query, count, timestamp_iso, hub_url.
    """
    d = _get_searches_dir()
    if not d.exists():
        return []
    entries = []
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entries.append({
                "name": data.get("name", f.stem),
                "query": data.get("query", ""),
                "count": data.get("count", 0),
                "timestamp": data.get("timestamp_iso", ""),
                "hub_url": data.get("hub_url", ""),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def purge_search(name: str) -> bool:
    """Delete a saved search. Returns True if it existed."""
    path = _get_searches_dir() / f"{_safe_filename(name)}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def purge_all_searches() -> int:
    """Delete all saved searches. Returns the count removed."""
    d = _get_searches_dir()
    if not d.exists():
        return 0
    count = 0
    for f in d.glob("*.json"):
        f.unlink()
        count += 1
    return count
