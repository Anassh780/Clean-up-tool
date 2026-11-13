"""One settings store for every Sweep interface.

The terminal console and the web server used to read and write
``%LOCALAPPDATA%\\Sweep\\config.json`` independently, so whichever saved last
won. Everything now goes through this module: one shape, one lock, atomic
writes, and unknown keys are preserved so a newer Sweep can add a setting
without an older build silently erasing it.

Only JSON-serialisable values live here. Nothing in this file touches the
network or Windows APIs, which keeps it cheap to import from the CLI.
"""
from __future__ import annotations

import copy
import json
import threading
from typing import Any

from . import paths

_LOCK = threading.RLock()

CHANNELS = ("stable", "beta")

DEFAULTS: dict[str, Any] = {
    "mode": "quarantine",
    "updates": {
        # Check for a newer release at launch (and every ``check_interval_hours``).
        "enabled": True,
        # "stable" ignores beta manifests; "beta" accepts both.
        "channel": "stable",
        # Empty means "use the URL baked into this build".
        "manifest_url": "",
        # 0 disables the automatic throttle; the manual button always checks.
        "check_interval_hours": 6,
        # A version the person said "not now" to; it is not offered again.
        "skipped": "",
        # Filled in by the update checker so the interface can show the last
        # answer without touching the network.
        "last_check": 0.0,
        "last_version": "",
        "last_status": "",
        "last_result": {},
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive merge that keeps defaults for missing keys."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load() -> dict[str, Any]:
    """Read the settings file, falling back to defaults on any problem.

    A corrupt or unreadable file must never stop Sweep from starting: the
    user's data (quarantine, logs) is elsewhere, and defaults are safe.
    """
    with _LOCK:
        try:
            # utf-8-sig: a BOM added by Notepad must not reset every setting.
            raw = json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return _merge(DEFAULTS, raw)


def save(data: dict[str, Any]) -> None:
    """Write settings atomically so a crash cannot truncate the file."""
    with _LOCK:
        paths.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.CONFIG_FILE.with_name(paths.CONFIG_FILE.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(paths.CONFIG_FILE)


def get(dotted: str, default: Any = None) -> Any:
    """Read a nested setting, e.g. ``get("updates.channel")``."""
    value: Any = load()
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def data() -> dict[str, Any]:
    """The full, merged settings tree (a copy)."""
    return load()


def get_mode() -> str:
    mode = get("mode", "quarantine")
    return mode if mode in ("quarantine", "permanent") else "quarantine"


def set_mode(mode: str) -> dict[str, Any]:
    if mode not in ("quarantine", "permanent"):
        raise ValueError("Mode must be “quarantine” or “permanent”.")
    current = load()
    current["mode"] = mode
    save(current)
    return {"mode": mode}


def updates() -> dict[str, Any]:
    """The ``updates`` section with defaults filled in."""
    return copy.deepcopy(load()["updates"])


def _clean_manifest_url(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    from urllib.parse import urlsplit

    parts = urlsplit(text)
    if parts.scheme == "https" and parts.netloc:
        return text
    # Plain http is refused because an update is code that will run on this PC.
    # Loopback stays allowed so a maintainer can test a local manifest.
    if parts.scheme == "http" and (parts.hostname or "").lower() in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        return text
    raise ValueError(
        "The update address must be an https:// URL "
        "(http://127.0.0.1 is allowed for local testing)."
    )


def validate_updates(patch: dict[str, Any]) -> dict[str, Any]:
    """Return a cleaned copy of an ``updates`` patch or raise ``ValueError``.

    Interfaces call this before saving so a bad field is explained next to the
    control that produced it instead of surfacing as a broken config file.
    """
    if not isinstance(patch, dict):
        raise ValueError("Settings must be an object.")
    cleaned: dict[str, Any] = {}
    if "enabled" in patch:
        cleaned["enabled"] = bool(patch["enabled"])
    if "channel" in patch:
        channel = str(patch["channel"]).strip().lower()
        if channel not in CHANNELS:
            raise ValueError("Channel must be “stable” or “beta”.")
        cleaned["channel"] = channel
    if "manifest_url" in patch:
        cleaned["manifest_url"] = _clean_manifest_url(patch["manifest_url"])
    if "check_interval_hours" in patch:
        try:
            hours = int(patch["check_interval_hours"])
        except (TypeError, ValueError):
            raise ValueError("The check interval must be a whole number of hours.") from None
        if hours < 0 or hours > 24 * 30:
            raise ValueError("The check interval must be between 0 and 720 hours.")
        cleaned["check_interval_hours"] = hours
    if "skipped" in patch:
        cleaned["skipped"] = str(patch["skipped"]).strip()[:40]
    return cleaned


def set_updates(patch: dict[str, Any]) -> dict[str, Any]:
    """Validate, merge and save a partial ``updates`` change."""
    cleaned = validate_updates(patch)
    current = load()
    current["updates"].update(cleaned)
    save(current)
    return copy.deepcopy(current["updates"])


def record_check(result: dict[str, Any]) -> None:
    """Store the last check so the UI can render it without a new request."""
    current = load()
    section = current["updates"]
    section["last_check"] = float(result.get("checked_at") or 0.0)
    section["last_version"] = str(result.get("latest") or "")
    section["last_status"] = str(result.get("status") or "")
    section["last_result"] = copy.deepcopy(result)
    save(current)


def clear_check() -> None:
    """Forget the cached answer, e.g. just before an update replaces this build."""
    current = load()
    section = current["updates"]
    section["last_check"] = 0.0
    section["last_version"] = ""
    section["last_status"] = ""
    section["last_result"] = {}
    save(current)
