"""Hub alias management for the eispy CLI.

Maps short alias names to full hub URLs so users can type::

    eispy hub connect winter

instead of::

    eispy hub connect nmdcs://wintermute.sublevels.net:411

Aliases are stored in a JSON file at
``$XDG_CONFIG_HOME/eispy/hubs.json`` (default ``~/.config/eispy/hubs.json``).
Override with the ``EISPY_HUBS_FILE`` environment variable.

Supported URL schemes: ``dchub://``, ``nmdcs://``, ``adc://``, ``adcs://``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _get_hubs_file() -> Path:
    """Return the path to the hub aliases JSON file."""
    env = os.environ.get("EISPY_HUBS_FILE")
    if env:
        return Path(env)
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    )
    return config_home / "eispy" / "hubs.json"


def load_aliases() -> dict[str, str]:
    """Load hub aliases from the config file.

    Returns an empty dict if the file does not exist or is invalid.
    """
    path = _get_hubs_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def save_aliases(aliases: dict[str, str]) -> None:
    """Persist hub aliases to the config file."""
    path = _get_hubs_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(aliases, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve(url_or_alias: str) -> str:
    """Resolve a hub URL or alias to a full URL.

    If the string contains ``://`` it is assumed to be a URL and
    returned unchanged. Otherwise it is looked up in the alias file.

    Raises:
        KeyError: If the alias is not found.
    """
    if "://" in url_or_alias:
        return url_or_alias
    aliases = load_aliases()
    if url_or_alias in aliases:
        return aliases[url_or_alias]
    available = ", ".join(sorted(aliases)) if aliases else "(none)"
    raise KeyError(
        f"Unknown hub alias: {url_or_alias!r}. "
        f"Known aliases: {available}. "
        f"Use 'eispy hub alias add <name> <url>' to create one, "
        f"or provide a full URL (e.g. dchub://host:port, nmdcs://host:port)."
    )


def add_alias(name: str, url: str) -> None:
    """Add or update a hub alias."""
    aliases = load_aliases()
    aliases[name] = url
    save_aliases(aliases)


def remove_alias(name: str) -> bool:
    """Remove a hub alias. Returns True if it existed."""
    aliases = load_aliases()
    if name not in aliases:
        return False
    del aliases[name]
    save_aliases(aliases)
    return True


def list_aliases() -> dict[str, str]:
    """Return all hub aliases."""
    return load_aliases()
