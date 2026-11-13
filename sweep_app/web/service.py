"""Domain layer shared by the HTTP routes.

Everything here returns plain JSON-ready values. All failures raise
``ApiError`` so the transport can answer with a status code *and* a reason.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .. import (
    __version__,
    admin,
    appfiles,
    config,
    junk,
    leftovers,
    paths,
    procs,
    safety,
    updates,
    util,
)
from .errors import (
    ApiError,
    confirmation_required,
    explain,
    invalid,
    operation_busy,
)
from .jobs import Job, JobManager

MANAGER: JobManager | None = None

# A release becomes installable only by being downloaded, checksum-verified and
# staged by *this* process. The browser may name a version, never a path, so a
# malicious or stale request cannot point the installer at an arbitrary folder.
PENDING: dict[str, Path] = {}
PENDING_RELEASES: dict[str, updates.Release] = {}
PENDING_LOCK = threading.Lock()

MUTATING_KINDS = {"clean", "kill", "remove-leftovers", "remove-hits", "restore", "purge"}
MODE_PERMANENT = "permanent"
MODE_QUARANTINE = "quarantine"

STATE_LOCK = threading.Lock()
STATE: dict[str, Any] = {
    "mode": "quarantine",
    "junk": {"at": 0.0, "results": {}, "stale": False},
    "procs": {"at": 0.0, "items": []},
    "leftovers": {"at": 0.0, "items": [], "index": None},
    "search": {"at": 0.0, "query": "", "hits": [], "meta": {}},
}

LOG_RE = re.compile(
    r"^\[(?P<time>[^\]]+)\]\s+(?P<level>OK|ERR)\s+(?P<action>[^:]+):\s*(?P<detail>.*)$"
)


def configure(manager: JobManager) -> None:
    global MANAGER
    MANAGER = manager
    with STATE_LOCK:
        STATE["mode"] = config.get_mode()


def manager() -> JobManager:
    if MANAGER is None:  # pragma: no cover - server always configures first
        raise ApiError(
            "not_ready",
            "The Sweep engine is not initialised",
            "service.configure() was not called before the first request.",
            "Restart the server.",
            500,
        )
    return MANAGER


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def get_mode() -> str:
    with STATE_LOCK:
        return STATE["mode"]


def set_mode(mode: Any) -> dict[str, Any]:
    if mode not in (MODE_QUARANTINE, MODE_PERMANENT):
        raise invalid("mode", "Mode must be “quarantine” or “permanent”.", "Use the toggle in Settings.")
    try:
        # config owns the whole settings tree, so this updates ``mode`` in place
        # and leaves the ``updates`` section (and any unknown keys) untouched.
        config.set_mode(str(mode))
    except ValueError as exc:
        raise invalid("mode", str(exc), "Use the toggle in Settings.") from None
    except OSError as exc:
        raise explain(exc) from None
    with STATE_LOCK:
        STATE["mode"] = str(mode)
    safety.log_event("mode", f"web mode set to {mode}")
    return {"mode": mode}


# --------------------------------------------------------------------------- #
# serialisers
# --------------------------------------------------------------------------- #
def category_json(category: junk.Category) -> dict[str, Any]:
    return {
        "key": category.key,
        "title": category.title,
        "blurb": category.blurb,
        "risk": category.risk,
        "admin": category.admin,
        "default": category.default,
        "note": category.note,
        "kind": category.kind,
    }


def scan_json(category: junk.Category, scan: junk.CategoryScan) -> dict[str, Any]:
    data = category_json(category)
    data.update(
        {
            "size": scan.size,
            "files": scan.files,
            "items": scan.items,
            "status": scan.status,
            "detail": scan.detail,
        }
    )
    return data


def process_json(info: procs.ProcessInfo) -> dict[str, Any]:
    return {
        "pid": info.pid,
        "ppid": info.ppid,
        "name": info.name,
        "exe": info.exe,
        "cmdline": info.cmdline,
        "user": info.user,
        "session": info.session,
        "state": info.state,
        "group": info.group,
        "reason": info.reason,
        "protected": info.protected,
        "killable": info.killable,
        "rss": info.rss,
        "cpu": round(info.cpu, 1),
        "age": round(info.age, 1),
        "age_label": info.age_label,
        "visible_windows": info.visible_windows,
        "hidden_windows": info.hidden_windows,
        "window_title": info.window_title,
    }


def orphan_json(orphan: leftovers.Orphan) -> dict[str, Any]:
    return {
        "path": orphan.path,
        "name": orphan.name,
        "root": orphan.root_label,
        "size": orphan.size,
        "files": orphan.files,
        "last_used": orphan.last_used,
        "mtime": orphan.mtime,
        "confidence": orphan.confidence,
        "reason": orphan.reason,
    }


def hit_json(index: int, hit: appfiles.Hit) -> dict[str, Any]:
    return {
        "id": f"h{index}",
        "kind": hit.kind,
        "kind_label": hit.kind_label,
        "name": hit.name,
        "path": hit.path,
        "size": hit.size,
        "extra": hit.extra,
        "age": hit.age_label,
        "mtime": hit.mtime,
    }


def batch_json(batch: dict[str, Any]) -> dict[str, Any]:
    items = batch.get("items", []) or []
    size = sum(int(item.get("size") or 0) for item in items)
    created = str(batch.get("created", ""))
    return {
        "id": batch.get("id", "?"),
        "created": created,
        "created_label": created[:19].replace("T", " "),
        "items": len(items),
        "files": [
            {"src": item.get("src", ""), "size": int(item.get("size") or 0),
             "category": item.get("category", "")}
            for item in items[:200]
        ],
        "size": size,
        "note": batch.get("note", ""),
    }


def _junk_totals(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    return {
        "bytes": sum(int(r.get("size") or 0) for r in rows),
        "files": sum(int(r.get("files") or 0) for r in rows),
        "categories": sum(1 for r in rows if (r.get("size") or r.get("items"))),
        "total_categories": len(rows),
    }


def _hint_for(text: str) -> str:
    low = (text or "").lower()
    if "dosvcstate" in low or "deliveryoptimization" in low:
        return (
            "Windows Delivery Optimization (the DoSvc service) keeps these files open. "
            "Stop that service, or skip this category."
        )
    if "softwaredistribution" in low:
        return (
            "The Windows Update service (wuauserv) holds these files. Stop it, or skip "
            "this category."
        )
    if "\\prefetch" in low:
        return (
            "The SysMain service keeps Prefetch open. Skip this category, or clean it "
            "right after a restart."
        )
    if "winerror 32" in low or "being used" in low or "in use" in low or "locked" in low:
        return (
            "Close the program that has this file open (browsers, Explorer and "
            "antivirus are the usual suspects), then retry."
        )
    if "access is denied" in low or "winerror 5" in low or "permission" in low:
        return "This needs Administrator rights. Restart Sweep as administrator."
    if "winerror 2" in low or "not found" in low or "no such" in low or "missing" in low:
        return "The item disappeared after the scan. Rescan to refresh the list."
    if "protected" in low or "approved folder" in low:
        return "Sweep's safety rules refuse this path by design."
    if "winerror 112" in low or "space" in low:
        return "Free some space on that drive and retry."
    return "Check the Sweep log for the exact call, then retry."


def _error_entry(path: str, reason: str, code: str = "failed", **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": path,
        "code": code,
        "reason": reason or "no reason reported",
        "short": util.short_reason(reason),
        "hint": _hint_for(reason),
    }
    entry.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    return entry


def _result_entry(result: safety.DeleteResult, category: str = "") -> dict[str, Any]:
    """One API error entry per failed item, with every locked file inside it."""
    details = [
        {
            "path": str(item.get("path", "")),
            "reason": str(item.get("reason", "")),
            "short": util.short_reason(str(item.get("reason", ""))),
        }
        for item in result.failures
    ]
    return _error_entry(
        result.path,
        result.reason,
        "delete_failed",
        category=category,
        details=details,
        short=details[0]["short"] if details else util.short_reason(result.reason),
    )


def _begin_operation() -> None:
    jobs = manager()
    if not jobs.operation_lock.acquire(blocking=False):
        active = next(
            (j.title for j in jobs.active() if j.kind in MUTATING_KINDS),
            "another cleanup",
        )
        raise operation_busy(active)


def _end_operation() -> None:
    try:
        manager().operation_lock.release()
    except RuntimeError:  # pragma: no cover - defensive
        pass


def require_word(confirm: Any, word: str, why: str) -> None:
    if str(confirm or "").strip().lower() != word:
        raise confirmation_required(word, why)


# --------------------------------------------------------------------------- #
# updates
# --------------------------------------------------------------------------- #
def _normalise_version(version: Any) -> str:
    return str(version or "").strip().lstrip("vV")


def _update_error(exc: updates.UpdateError, status: int = 409) -> ApiError:
    """Keep the engine's what/reason/hint shape all the way to the browser."""
    return ApiError(
        exc.code,
        exc.message,
        exc.reason,
        exc.hint,
        status,
        dict(exc.details),
    )


def _settings_error(exc: ValueError) -> ApiError:
    """A bad setting is a request problem, not a server problem."""
    return ApiError(
        "invalid_request",
        str(exc),
        "Sweep validates update settings before writing them, so a bad value "
        "cannot leave a broken config.json behind.",
        "Use Settings → Updates to pick a supported value, or edit the “updates” "
        "section of config.json and reload the page.",
        400,
        {"field": "updates"},
    )


def _release_from_cached() -> updates.Release | None:
    """The last checked release, if it is still a newer, downloadable one."""
    stored = config.updates().get("last_result")
    if not isinstance(stored, dict) or stored.get("status") not in (
        updates.STATUS_AVAILABLE,
        updates.STATUS_SKIPPED,
    ):
        return None
    data = stored.get("release")
    if not isinstance(data, dict) or not data.get("url"):
        return None
    fields = updates.Release.__dataclass_fields__
    try:
        release = updates.Release(**{key: data[key] for key in fields if key in data})
    except (TypeError, ValueError):
        return None
    return release if updates.is_newer(release.version) else None


def _resolve_release(version: Any) -> updates.Release:
    """Pick the manifest release to download.

    ``version`` is only a selector: it must match what the manifest (or the last
    recorded check) offers, so the client can never substitute its own URL.
    """
    wanted = _normalise_version(version)
    cached = _release_from_cached()
    if cached is not None and (not wanted or cached.version == wanted):
        return cached
    result = updates.check(force=True)
    if result.status not in (updates.STATUS_AVAILABLE, updates.STATUS_SKIPPED) or result.release is None:
        raise ApiError(
            "update_unavailable",
            result.message or "No update is available to download",
            result.reason
            or f"Sweep {__version__} is the newest release the manifest offers.",
            result.hint or "Press “Check again” in Settings → Updates.",
            409,
            {"status": result.status},
        )
    release = result.release
    if wanted and release.version != wanted:
        raise ApiError(
            "update_unavailable",
            f"Sweep {release.version} is the only release on offer",
            f"You asked for {wanted}, but the manifest currently offers "
            f"{release.version}.",
            "Press “Check again”, then download the version the manifest names.",
            409,
            {"requested": wanted, "latest": release.version},
        )
    return release


def update_state() -> dict[str, Any]:
    """The update card's state plus the cached ``CheckResult``, if any."""
    state = updates.state()
    last = state.get("last_result")
    result = last if isinstance(last, dict) and last.get("status") else None
    return {"state": state, "result": result}


def check_updates(force: Any = False) -> dict[str, Any]:
    """Run a check now. ``check()`` never raises; its result is the answer."""
    result = updates.check(force=bool(force))
    safety.log_event("update", f"web update check: {result.status} {result.latest}".strip())
    return result.to_dict()


def save_update_settings(patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise invalid(
            "settings",
            "Update settings must be a JSON object",
            "Send only the fields to change, for example {\"channel\": \"beta\"}.",
        )
    try:
        config.set_updates(patch)
    except ValueError as exc:
        raise _settings_error(exc) from None
    except OSError as exc:
        raise explain(exc) from None
    safety.log_event("settings", "web update settings saved")
    return updates.state()


def start_update_download(version: Any = None) -> Job:
    jobs = manager()
    if any(job.kind == "update-download" for job in jobs.active()):
        # Two downloads would race for the same .part file and staging folder.
        raise ApiError(
            "update_busy",
            "An update is already downloading",
            "Sweep downloads one release at a time so two downloads cannot "
            "overwrite the same file and fail their checksums.",
            "Wait for the current download to finish, or cancel it first.",
            409,
        )
    wanted = _normalise_version(version)
    title = f"Downloading Sweep {wanted}" if wanted else "Downloading update"
    return jobs.submit("update-download", title, _run_update_download, wanted or None)


def _download_payload(
    release: updates.Release, staged: Path | None, cancelled: bool = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": release.version,
        "staged": str(staged) if staged is not None else None,
        "release": release.to_dict(),
    }
    if cancelled:
        payload["cancelled"] = True
    return payload


def _run_update_download(job: Job, version: str | None) -> dict[str, Any]:
    job.progress(
        current=0,
        total=1,
        phase="Resolving release",
        message="Reading the release manifest…",
    )
    release = _resolve_release(version)
    if job.cancel.is_set():
        return _download_payload(release, None, cancelled=True)

    job.progress(
        current=0,
        total=1,
        phase="Downloading",
        message=f"Downloading Sweep {release.version}…",
    )
    job.publish(version=release.version, downloaded=0, bytes_total=release.size)

    def on_progress(done: int, total: int) -> None:
        expected = max(1, int(total or release.size or done or 1))
        job.progress(
            current=min(1.0, done / expected),
            total=1,
            phase="Downloading",
            message=f"{util.human_size(done)} of {util.human_size(expected)}",
        )
        job.publish(version=release.version, downloaded=done, bytes_total=expected)

    try:
        archive = updates.download(release, progress=on_progress, cancel=job.cancel)
    except updates.UpdateError as exc:
        if job.cancel.is_set() or exc.code == "cancelled":
            return _download_payload(release, None, cancelled=True)
        raise _update_error(exc) from None
    if job.cancel.is_set():
        return _download_payload(release, None, cancelled=True)

    job.progress(
        current=0.99,
        total=1,
        phase="Verifying",
        message="Checking the archive and its version stamp…",
    )
    try:
        staged = updates.stage(archive, release)
    except updates.UpdateError as exc:
        raise _update_error(exc) from None
    if job.cancel.is_set():
        return _download_payload(release, None, cancelled=True)

    with PENDING_LOCK:
        PENDING[release.version] = staged
        PENDING_RELEASES[release.version] = release
    job.progress(
        current=1,
        total=1,
        phase="Ready",
        message=f"Sweep {release.version} is ready to install",
    )
    safety.log_event("update", f"web downloaded and staged Sweep {release.version}")
    return _download_payload(release, staged)


def _release_for(version: str) -> updates.Release:
    """Metadata for a staged version; the staged path is what actually matters."""
    release = PENDING_RELEASES.get(version)
    if release is not None:
        return release
    cached = _release_from_cached()
    if cached is not None and cached.version == version:
        return cached
    # apply() only reads ``version`` from this object (the plan's staged path is
    # the trusted PENDING entry), so a bare version is enough.
    return updates.Release(version=version, url="")


def _pending_entry(version: Any) -> tuple[Path, updates.Release]:
    """Look up a staged release by version (or the most recent one)."""
    wanted = _normalise_version(version)
    with PENDING_LOCK:
        if wanted:
            staged = PENDING.get(wanted)
            if staged is None:
                raise ApiError(
                    "no_pending_update",
                    f"Sweep {wanted} has not been downloaded in this session",
                    "Sweep only installs a release it downloaded, verified and "
                    "staged itself; the browser cannot name a file on disk.",
                    "Download that version from Settings → Updates, then install it.",
                    409,
                    {"version": wanted},
                )
            return staged, _release_for(wanted)
        if not PENDING:
            raise ApiError(
                "no_pending_update",
                "No update is ready to install",
                "Nothing has been downloaded and verified in this server session.",
                "Open Settings → Updates, press “Download”, then install.",
                409,
            )
        latest = next(reversed(PENDING))
        return PENDING[latest], _release_for(latest)


def apply_update(confirm: Any, version: Any = None) -> dict[str, Any]:
    """Start the detached helper that swaps the files, then let the caller exit.

    The operation lock is deliberately *not* released on success: the server is
    about to stop, and holding it keeps a cleanup from starting in the window
    before the helper takes over the files.
    """
    require_word(
        confirm,
        "update",
        "Installing an update replaces Sweep's program files. The app closes for "
        "a few seconds and restarts on the new version; quarantine, logs and "
        "settings are kept.",
    )
    staged, release = _pending_entry(version)
    if not staged.is_dir():
        with PENDING_LOCK:
            PENDING.pop(release.version, None)
            PENDING_RELEASES.pop(release.version, None)
        raise ApiError(
            "no_pending_update",
            "The staged update is no longer on disk",
            f"{staged} disappeared after it was downloaded, so there is nothing "
            "to install.",
            "Download the update again from Settings → Updates.",
            409,
            {"version": release.version},
        )
    _begin_operation()  # operation_busy while a destructive job is running
    try:
        plan = updates.apply(staged, release, relaunch=updates.relaunch_argv())
    except updates.UpdateError as exc:
        _end_operation()
        raise _update_error(exc) from None
    except BaseException:
        _end_operation()
        raise
    with PENDING_LOCK:
        PENDING.pop(release.version, None)
        PENDING_RELEASES.pop(release.version, None)
    safety.log_event(
        "update", f"web update to {release.version} scheduled; helper plan {plan}"
    )
    return {"applying": True, "version": release.version}


def skip_update(version: Any) -> dict[str, Any]:
    text = _normalise_version(version)
    if not text:
        raise invalid(
            "version",
            "Which version should Sweep skip?",
            "Pass the release version, for example \"1.2.0\".",
        )
    try:
        config.set_updates({"skipped": text[:40]})
    except ValueError as exc:
        raise _settings_error(exc) from None
    except OSError as exc:
        raise explain(exc) from None
    # Keep the cached card in step with the choice: without this the page would
    # still render the old "available" result until the next network check, and
    # the install button would look like it had been ignored.
    cached = updates.state().get("last_result")
    if isinstance(cached, dict) and str(cached.get("latest") or "") == text:
        updated = dict(cached)
        updated.update(
            status=updates.STATUS_SKIPPED,
            message=f"Sweep {text} is available (skipped)",
            reason="You chose “Not now” for this version.",
            hint="Install it from Settings → Updates whenever you are ready.",
        )
        try:
            config.record_check(updated)
        except OSError:
            pass
    safety.log_event("update", f"web update {text} skipped")
    return updates.state()


def cleanup_updates() -> dict[str, Any]:
    try:
        freed = updates.cleanup(keep=2)
    except OSError as exc:
        raise explain(exc) from None
    safety.log_event("update", f"web update cleanup freed {freed} bytes")
    return {"freed": freed, "state": updates.state()}


# --------------------------------------------------------------------------- #
# meta / overview
# --------------------------------------------------------------------------- #
def meta() -> dict[str, Any]:
    jobs = manager()
    with STATE_LOCK:
        junk_at = STATE["junk"]["at"]
        junk_results = [
            scan_json(junk.CATEGORY_MAP[k], v)
            for k, v in STATE["junk"]["results"].items()
            if k in junk.CATEGORY_MAP
        ]
        procs_at = STATE["procs"]["at"]
        proc_items = list(STATE["procs"]["items"])
        leftovers_at = STATE["leftovers"]["at"]
        orphan_items = list(STATE["leftovers"]["items"])
        mode = STATE["mode"]

    q_bytes, q_items = safety.quarantine_usage()
    batches = safety.quarantine_batches()
    drives = []
    for drive in paths.drive_usage():
        drives.append(
            {
                "letter": drive["letter"],
                "mount": drive["mount"],
                "total": drive["total"],
                "used": drive["used"],
                "free": drive["free"],
                "percent": drive["percent"],
            }
        )

    counts: dict[str, int] = {}
    for item in proc_items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1

    # The dashboard can draw the update banner from the cached answer, so a
    # page load never waits for (or repeats) a network check.
    prefs = config.updates()
    last = prefs.get("last_result")
    last = last if isinstance(last, dict) else {}
    try:
        checked_at = float(last.get("checked_at") or prefs.get("last_check") or 0.0)
    except (TypeError, ValueError):
        checked_at = 0.0
    update_meta = {
        "status": str(last.get("status") or ""),
        "latest": str(last.get("latest") or prefs.get("last_version") or ""),
        "checked_at": checked_at,
    }

    active = jobs.active()
    return {
        "app": {
            "name": "Sweep",
            "version": __version__,
            "tagline": "Windows cleanup console",
            "started": _STARTED,
        },
        "admin": admin.is_admin(),
        "mode": mode,
        "update": update_meta,
        "drives": drives,
        "junk": {
            "scanned_at": junk_at,
            "totals": _junk_totals(junk_results),
        },
        "procs": {
            "collected_at": procs_at,
            "total": len(proc_items),
            "summary": {
                "active": counts.get("active", 0),
                "tray": counts.get("tray", 0),
                "idle": counts.get("idle", 0),
                "service": counts.get("service", 0),
                "windows": counts.get("windows", 0),
                "linked": counts.get("linked", 0),
            },
        },
        "leftovers": {
            "scanned_at": leftovers_at,
            "count": len(orphan_items),
            "bytes": sum(int(o.get("size") or 0) for o in orphan_items),
        },
        "quarantine": {
            "bytes": q_bytes,
            "items": q_items,
            "batches": len(batches),
        },
        "paths": {
            "home": str(paths.SWEEP_HOME),
            "quarantine": str(paths.QUARANTINE),
            "logs": str(paths.LOGS),
            "config": str(paths.CONFIG_FILE),
            "temp": os.path.realpath(str(paths.TEMP)),
            "windows": str(paths.WINDIR),
        },
        "active_job": active[0].to_dict(include_result=False) if active else None,
    }


_STARTED = time.time()


# --------------------------------------------------------------------------- #
# junk
# --------------------------------------------------------------------------- #
def junk_state() -> dict[str, Any]:
    with STATE_LOCK:
        at = STATE["junk"]["at"]
        results = [
            scan_json(junk.CATEGORY_MAP[key], scan)
            for key, scan in STATE["junk"]["results"].items()
            if key in junk.CATEGORY_MAP
        ]
    order = {category.key: i for i, category in enumerate(junk.CATEGORIES)}
    results.sort(key=lambda row: order.get(row["key"], 999))
    return {
        "scanned_at": at,
        "stale": bool(STATE["junk"].get("stale")),
        "results": results,
        "totals": _junk_totals(results),
    }


def start_junk_scan() -> Job:
    return manager().submit("scan-junk", "Scanning junk files", _run_junk_scan)


def _run_junk_scan(job: Job) -> dict[str, Any]:
    total = len(junk.CATEGORIES)
    results: dict[str, junk.CategoryScan] = {}

    def on_result(scan: junk.CategoryScan) -> None:
        results[scan.key] = scan
        category = junk.CATEGORY_MAP[scan.key]
        job.progress(
            current=len(results),
            total=total,
            phase="Scanning categories",
            message=f"{category.title} — {util.human_size(scan.size)}",
        )
        job.publish(
            results=[
                scan_json(junk.CATEGORY_MAP[key], value)
                for key, value in results.items()
                if key in junk.CATEGORY_MAP
            ],
            scanned=len(results),
            categories=total,
        )

    junk.scan_all(cancel=job.cancel, on_result=on_result)
    if job.cancel.is_set():
        job.publish(results=[])

    with STATE_LOCK:
        STATE["junk"] = {"at": time.time(), "results": results, "stale": False}
    payload = junk_state()
    safety.log_event("scan", f"web junk scan: {payload['totals']['bytes']} bytes")
    return payload


def start_clean(keys: Any, permanent: Any, confirm: Any) -> Job:
    if not isinstance(keys, list) or not keys:
        raise invalid("keys", "Pick at least one category to clean.", "Tick a category in the Junk files table.")
    unknown = [k for k in keys if k not in junk.CATEGORY_MAP]
    if unknown:
        raise invalid(
            "keys",
            "One of the categories is unknown",
            f"Unknown category key(s): {', '.join(map(str, unknown[:6]))}.",
            "Rescan and pick from the list.",
        )
    mode = MODE_PERMANENT if permanent else MODE_QUARANTINE
    with STATE_LOCK:
        scans = dict(STATE["junk"]["results"])
        scanned = STATE["junk"]["at"]
    if not scanned:
        raise ApiError(
            "scan_required",
            "No junk scan has run yet",
            "Sweep cleans from the results of a scan, so it knows what exists and how big it is.",
            "Run “Scan now” first; it takes about half a minute.",
            409,
        )
    chosen = [junk.CATEGORY_MAP[k] for k in keys]
    empty = [c.title for c in chosen if k_has_no_content(scans, c.key)]
    if len(empty) == len(chosen):
        raise ApiError(
            "nothing_to_clean",
            "The selected categories are empty",
            "Every category you picked reported 0 bytes and 0 files in the last scan.",
            "Select different categories, or rescan — files may have appeared since.",
            409,
        )
    if mode == MODE_PERMANENT:
        require_word(
            confirm,
            "delete",
            "Permanent delete skips quarantine: the selected files are gone and cannot be restored.",
        )
    _begin_operation()
    return manager().submit("clean", "Cleaning junk files", _run_clean, list(keys), mode)


def k_has_no_content(scans: dict[str, junk.CategoryScan], key: str) -> bool:
    scan = scans.get(key)
    return scan is None or not scan.has_content


def _run_clean(job: Job, keys: list[str], mode: str) -> dict[str, Any]:
    try:
        started = time.time()
        with STATE_LOCK:
            scans = dict(STATE["junk"]["results"])
        total = max(1, sum(max(1, scans[k].items) for k in keys if k in scans))
        deleter = safety.Deleter(mode=mode, note="junk clean (web)")
        done = 0
        errors: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        skipped_admin: list[dict[str, Any]] = []
        categories: list[str] = []

        for key in keys:
            category = junk.CATEGORY_MAP[key]
            if job.cancel.is_set():
                break
            categories.append(category.title)
            job.progress(phase="Cleaning", message=f"{category.title}…")
            if category.admin and not admin.is_admin():
                skipped_admin.append(
                    {
                        "key": key,
                        "title": category.title,
                        "reason": (
                            f"“{category.title}” lives in a Windows-protected location that "
                            "requires Administrator rights."
                        ),
                        "hint": "Close Sweep, right-click “Sweep Web.bat” → “Run as administrator”, then retry.",
                    }
                )
                continue
            if category.kind == "recycle":
                ok, message = safety.empty_recycle_bin()
                if ok:
                    done += 1
                    job.progress(current=done, total=total, message="Recycle Bin emptied")
                else:
                    errors.append(
                        _error_entry(
                            "Recycle Bin",
                            message or "The shell refused to empty the Recycle Bin.",
                            "recycle_failed",
                        )
                    )
                continue

            try:
                roots, items = category.spec()
            except OSError as exc:
                errors.append(_error_entry(category.title, f"Could not enumerate targets: {exc}", "enumeration_failed"))
                continue

            for item in items:
                if job.cancel.is_set():
                    break
                try:
                    result = deleter.delete(
                        item, allowed_roots=roots, category=key, cancel=job.cancel
                    )
                except OSError as exc:
                    errors.append(_error_entry(str(item), f"{exc}", "delete_failed"))
                    done += 1
                    continue
                if result.status == "failed":
                    errors.append(_result_entry(result, category.title))
                elif result.status == "skipped":
                    blocked.append(_error_entry(str(item), result.reason, "blocked_by_safety"))
                done += 1
                if done % 4 == 0 or done == total:
                    job.progress(
                        current=done,
                        total=total,
                        phase="Cleaning",
                        message=f"{category.title} — {util.human_size(result.size)}",
                    )

        stats = deleter.finish()
        skipped_keys = {entry["key"] for entry in skipped_admin}
        with STATE_LOCK:
            # Keep every category in the table so the page stays complete; the
            # ones that were just cleaned drop to zero, the admin-blocked ones
            # keep their measured size so the reason is still visible.
            for key in keys:
                if key in skipped_keys:
                    continue
                STATE["junk"]["results"][key] = junk.CategoryScan(
                    key=key, size=0, files=0, status="empty", detail="cleaned just now"
                )
        result = {
            "mode": mode,
            "batch_id": deleter.batch_id,
            "bytes": stats.bytes,
            "moved": stats.moved,
            "deleted": stats.deleted,
            "failed": stats.failed,
            "skipped": stats.skipped,
            "errors": errors[:60],
            "failures": stats.failures,
            "blocked": blocked[:60],
            "skipped_admin": skipped_admin,
            "categories": categories,
            "duration": round(time.time() - started, 1),
            "cancelled": job.cancel.is_set(),
        }
        safety.log_event(
            "clean",
            f"web clean {len(categories)} categories, {stats.bytes} bytes, {stats.failed} failed",
            ok=not stats.failed,
        )
        return result
    finally:
        _end_operation()


# --------------------------------------------------------------------------- #
# processes
# --------------------------------------------------------------------------- #
def procs_state() -> dict[str, Any]:
    with STATE_LOCK:
        at = STATE["procs"]["at"]
        items = list(STATE["procs"]["items"])
    counts: dict[str, int] = {}
    for item in items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    return {
        "collected_at": at,
        "items": items,
        "summary": {
            "total": len(items),
            "active": counts.get("active", 0),
            "tray": counts.get("tray", 0),
            "idle": counts.get("idle", 0),
            "linked": counts.get("linked", 0),
            "locked": counts.get("locked", 0),
            "service": counts.get("service", 0),
            "system": counts.get("system", 0),
            "windows": counts.get("system", 0),
        },
    }


def start_procs_refresh() -> Job:
    return manager().submit("scan-procs", "Reading processes", _run_procs)


def _run_procs(job: Job) -> dict[str, Any]:
    job.progress(phase="Enumerating windows", message="Collecting visible and hidden windows…")
    infos = procs.collect(job.cancel)
    job.progress(
        current=1, total=1, phase="Classifying", message=f"{len(infos)} processes found"
    )
    items = [process_json(info) for info in infos]
    with STATE_LOCK:
        STATE["procs"] = {"at": time.time(), "items": items}
    return procs_state()


def start_kill(pids: Any, confirm: Any) -> Job:
    if not isinstance(pids, list) or not pids:
        raise invalid("pids", "Select at least one process to stop.", "Tick a row in the process table.")
    try:
        clean_pids = sorted({int(pid) for pid in pids})
    except (TypeError, ValueError):
        raise invalid("pids", "Process IDs must be numbers.", "Rescan and pick processes from the list.")
    with STATE_LOCK:
        items = list(STATE["procs"]["items"])
    if not items:
        raise ApiError(
            "scan_required",
            "The process list has not been read yet",
            "Sweep needs a fresh process list to know which processes are safe to stop.",
            "Press “Refresh” first; it takes a few seconds.",
            409,
        )
    targets = [item for item in items if item["pid"] in clean_pids and item["killable"]]
    if not targets:
        raise ApiError(
            "nothing_to_kill",
            "None of those processes can be stopped",
            "They are Windows processes, services, apps with a window, tray apps, or "
            "children of something Sweep is keeping.",
            "Switch the filter to “Idle” to see what Sweep considers safe to stop.",
            409,
        )
    if len(targets) >= 5:
        require_word(
            confirm,
            "kill",
            f"{len(targets)} processes will be terminated. Unsaved work in them is lost.",
        )
    _begin_operation()
    return manager().submit("kill", "Stopping processes", _run_kill, [t["pid"] for t in targets])


def _run_kill(job: Job, pids: list[int]) -> dict[str, Any]:
    try:
        with STATE_LOCK:
            items = list(STATE["procs"]["items"])
        by_pid = {item["pid"]: item for item in items}
        targets = [p for pid, p in by_pid.items() if pid in set(pids)]
        total = len(targets)

        def on_progress(index: int, count: int, name: str) -> None:
            job.progress(current=index, total=count, phase="Stopping", message=name)

        infos = [
            procs.ProcessInfo(
                pid=t["pid"],
                ppid=t["ppid"],
                name=t["name"],
                exe=t["exe"],
                cmdline=t["cmdline"],
                user=t["user"],
                session=t["session"],
                status="running",
                rss=t["rss"],
                cpu=t["cpu"],
                created=0.0,
                visible_windows=t["visible_windows"],
                hidden_windows=t["hidden_windows"],
                window_title=t["window_title"],
                group=t["group"],
                reason=t["reason"],
                protected=t["protected"],
            )
            for t in targets
        ]
        results = procs.kill_processes(infos, job.cancel, on_progress)
        killed = sum(1 for r in results if r.ok)
        failed = [
            {
                "pid": r.pid,
                "name": r.name,
                "reason": r.message or "Windows refused to terminate the process.",
                "hint": _hint_for(r.message),
            }
            for r in results
            if not r.ok
        ]
        with STATE_LOCK:
            STATE["procs"]["at"] = 0.0
        return {
            "requested": total,
            "killed": killed,
            "failed": failed,
            "cancelled": job.cancel.is_set(),
            "results": [{"pid": r.pid, "name": r.name, "ok": r.ok, "message": r.message} for r in results],
        }
    finally:
        _end_operation()


# --------------------------------------------------------------------------- #
# leftovers
# --------------------------------------------------------------------------- #
def leftovers_state() -> dict[str, Any]:
    with STATE_LOCK:
        at = STATE["leftovers"]["at"]
        items = list(STATE["leftovers"]["items"])
        index = STATE["leftovers"].get("index")
    return {
        "scanned_at": at,
        "items": items,
        "total_bytes": sum(int(o.get("size") or 0) for o in items),
        "index": index or {},
    }


def start_leftovers_scan() -> Job:
    return manager().submit("scan-leftovers", "Finding uninstall leftovers", _run_leftovers_scan)


def _run_leftovers_scan(job: Job) -> dict[str, Any]:
    job.progress(phase="Reading installed programs", message="Building the installed-program index…")
    index = leftovers.build_index()
    job.progress(current=0.1, total=1, phase="Scanning folders", message="Checking AppData, ProgramData and Program Files…")

    def on_progress(label: str, fraction: float) -> None:
        job.progress(
            current=0.1 + max(0.0, min(1.0, fraction)) * 0.9,
            total=1,
            phase="Scanning folders",
            message=label,
        )

    orphans = leftovers.scan_orphans(job.cancel, on_progress, index)
    items = [orphan_json(o) for o in orphans]
    meta_info = {"names": len(index.full_names), "words": len(index.name_words)}
    with STATE_LOCK:
        STATE["leftovers"] = {"at": time.time(), "items": items, "index": meta_info}
    safety.log_event("leftovers", f"web scan: {len(items)} candidates")
    return leftovers_state()


def start_leftovers_remove(paths_in: Any, permanent: Any, confirm: Any) -> Job:
    if not isinstance(paths_in, list) or not paths_in:
        raise invalid("paths", "Select at least one folder to remove.", "Tick a row in the leftovers table.")
    mode = MODE_PERMANENT if permanent else MODE_QUARANTINE
    with STATE_LOCK:
        known = {item["path"]: item for item in STATE["leftovers"]["items"]}
        scanned = STATE["leftovers"]["at"]
    if not scanned or not known:
        raise ApiError(
            "scan_required",
            "No leftovers scan has run yet",
            "Sweep only removes folders it found and measured itself.",
            "Press “Scan now” first.",
            409,
        )
    chosen = []
    for path in paths_in:
        if path not in known:
            raise ApiError(
                "path_not_allowed",
                "That folder is not part of the last scan",
                f"{path} was not in the results Sweep produced, so it was refused.",
                "Rescan and pick a folder from the list.",
                400,
            )
        chosen.append(known[path])
    total = sum(int(o["size"]) for o in chosen)
    if mode == MODE_PERMANENT:
        require_word(confirm, "remove", "Permanent removal skips quarantine and cannot be undone.")
    elif total > 500 * 1024 * 1024:
        require_word(
            confirm,
            "remove",
            f"{util.human_size(total)} across {len(chosen)} folders is a large move. "
            "The folders go to quarantine and can be restored.",
        )
    _begin_operation()
    return manager().submit(
        "remove-leftovers", "Removing leftover folders", _run_leftovers_remove,
        [o["path"] for o in chosen], mode,
    )


def _run_leftovers_remove(job: Job, chosen: list[str], mode: str) -> dict[str, Any]:
    try:
        with STATE_LOCK:
            known = {item["path"]: item for item in STATE["leftovers"]["items"]}
        deleter = safety.Deleter(mode=mode, note="leftovers (web)")
        errors: list[dict[str, Any]] = []
        done = 0
        total = max(1, len(chosen))
        for path in chosen:
            if job.cancel.is_set():
                break
            item = known.get(path, {})
            job.progress(
                current=done,
                total=total,
                phase="Removing folders",
                message=f"{item.get('name', path)} — {util.human_size(int(item.get('size') or 0))}",
            )
            try:
                result = deleter.delete(path, allowed_roots=[path], category="leftovers")
            except OSError as exc:
                errors.append(_error_entry(path, f"{exc}", "delete_failed"))
                done += 1
                continue
            if result.status == "failed":
                errors.append(_result_entry(result, "Leftovers"))
            elif result.status == "skipped":
                errors.append(_error_entry(path, result.reason, "blocked_by_safety"))
            done += 1
            job.progress(current=done, total=total)
        stats = deleter.finish()
        with STATE_LOCK:
            remaining = [o for o in STATE["leftovers"]["items"] if o["path"] not in set(chosen)]
            STATE["leftovers"] = {
                "at": STATE["leftovers"]["at"],
                "items": remaining,
                "index": STATE["leftovers"].get("index"),
            }
        return {
            "mode": mode,
            "batch_id": deleter.batch_id,
            "bytes": stats.bytes,
            "moved": stats.moved,
            "deleted": stats.deleted,
            "failed": stats.failed,
            "errors": errors[:40],
            "failures": stats.failures,
            "cancelled": job.cancel.is_set(),
        }
    finally:
        _end_operation()


# --------------------------------------------------------------------------- #
# program remover
# --------------------------------------------------------------------------- #
def search_state() -> dict[str, Any]:
    with STATE_LOCK:
        data = dict(STATE["search"])
    data["hits"] = list(data.get("hits") or [])
    return {
        "query": data.get("query", ""),
        "searched_at": data.get("at", 0.0),
        "hits": data["hits"],
        "meta": data.get("meta", {}),
    }


def start_search(query: Any, registry: Any, services: Any) -> Job:
    text = str(query or "").strip()
    if len(util.norm(text)) < 2:
        raise invalid(
            "query",
            "Type at least two characters of the program name",
            f"“{text}” is too short to match anything without producing noise.",
            "Try the app name as it appears in Settings → Apps, e.g. “OBS Studio”.",
        )
    return manager().submit(
        "search", f"Searching for “{text}”", _run_search,
        text, bool(registry), bool(services),
    )


def _run_search(job: Job, query: str, registry: bool, services: bool) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    job.progress(phase="Walking drives", message="Searching every fixed drive…")

    def on_progress(message: str, fraction: float) -> None:
        job.progress(
            current=fraction * 100,
            total=100,
            phase="Walking drives",
            message=message,
        )

    outcome = appfiles.search_files(query, job.cancel, on_progress)
    hits = list(outcome.hits)
    if registry:
        job.progress(phase="Reading registry", message="Checking installed-program registry entries…")
        try:
            hits.extend(appfiles.registry_hits(query))
        except OSError as exc:
            warnings.append(
                {
                    "source": "registry",
                    "reason": f"Could not read the uninstall registry keys: {exc}",
                    "hint": "The file search results are still complete; registry entries were skipped.",
                }
            )
    if services:
        job.progress(phase="Reading services", message="Checking Windows services…")
        try:
            hits.extend(appfiles.service_hits(query))
        except Exception as exc:  # noqa: BLE001 - service API is flaky
            warnings.append(
                {
                    "source": "services",
                    "reason": f"Could not enumerate services: {exc}",
                    "hint": "File and registry results are still shown.",
                }
            )

    payload = [hit_json(i, hit) for i, hit in enumerate(hits)]
    meta = {
        "scanned": outcome.scanned,
        "elapsed": round(outcome.elapsed, 1),
        "truncated": len(outcome.hits) >= appfiles.MAX_HITS,
        "registry": registry,
        "services": services,
        "warnings": warnings,
    }
    with STATE_LOCK:
        STATE["search"] = {
            "at": time.time(),
            "query": query,
            "hits": payload,
            "meta": meta,
        }
    safety.log_event("search", f"web search “{query}”: {len(payload)} hits")
    return {
        "query": query,
        "hits": payload,
        "meta": meta,
        "cancelled": job.cancel.is_set(),
    }


def start_remove_hits(ids: Any, permanent: Any, confirm: Any) -> Job:
    if not isinstance(ids, list) or not ids:
        raise invalid("ids", "Select at least one result to remove.", "Tick a row in the results table.")
    mode = MODE_PERMANENT if permanent else MODE_QUARANTINE
    with STATE_LOCK:
        known = {hit["id"]: hit for hit in STATE["search"]["hits"]}
        searched = STATE["search"]["at"]
    if not searched or not known:
        raise ApiError(
            "scan_required",
            "No search results are loaded",
            "Sweep only removes paths that came from its own search results.",
            "Search for the program again, then pick from the results.",
            409,
        )
    chosen = []
    for hit_id in ids:
        hit = known.get(str(hit_id))
        if hit is None:
            raise ApiError(
                "path_not_allowed",
                "That result is not part of the last search",
                f"Result id {hit_id!r} was not produced by the current search.",
                "Search again and pick from the fresh results.",
                400,
            )
        chosen.append(hit)
    total = sum(int(h["size"]) for h in chosen)
    sensitive = any(h["kind"] in ("registry", "service") for h in chosen)
    if mode == MODE_PERMANENT:
        require_word(confirm, "remove", "Permanent removal skips quarantine and cannot be undone.")
    elif total > 1024 ** 3 or sensitive:
        reason = (
            f"{util.human_size(total)} across {len(chosen)} items"
            if not sensitive
            else "Registry keys and services are included, and those are changed in place"
        )
        require_word(confirm, "remove", f"{reason}. Review the selection before confirming.")
    _begin_operation()
    return manager().submit(
        "remove-hits", "Removing program files", _run_remove_hits,
        [h["id"] for h in chosen], mode,
    )


def _run_remove_hits(job: Job, ids: list[str], mode: str) -> dict[str, Any]:
    try:
        with STATE_LOCK:
            known = {hit["id"]: hit for hit in STATE["search"]["hits"]}
        hits = [known[i] for i in ids if i in known]
        if not hits:
            raise ApiError(
                "nothing_selected",
                "Those results are no longer in the list",
                "The search results changed after you selected them, so nothing was removed.",
                "Run the search again and reselect.",
                409,
            )
        app_hits = [
            appfiles.Hit(
                kind=h["kind"],
                name=h["name"],
                path=h["path"],
                size=int(h["size"] or 0),
                mtime=float(h["mtime"] or 0),
                extra=h.get("extra", ""),
            )
            for h in hits
        ]

        def on_progress(index: int, total: int, name: str) -> None:
            job.progress(current=index, total=total, phase="Removing", message=name)

        report = appfiles.remove_hits(app_hits, mode, job.cancel, on_progress)
        errors = [
            {"path": "", "code": "remove_failed", "reason": text, "hint": _hint_for(text)}
            for text in report.errors
        ]
        with STATE_LOCK:
            remaining = [h for h in STATE["search"]["hits"] if h["id"] not in set(ids)]
            STATE["search"]["hits"] = remaining
        return {
            "mode": mode,
            "batch_id": report.batch_id,
            "bytes": report.bytes,
            "moved": report.moved,
            "deleted": report.deleted,
            "failed": report.failed,
            "skipped": report.skipped,
            "registry": report.registry,
            "services": report.services,
            "errors": errors,
            "cancelled": job.cancel.is_set(),
        }
    finally:
        _end_operation()


# --------------------------------------------------------------------------- #
# quarantine
# --------------------------------------------------------------------------- #
def quarantine_state() -> dict[str, Any]:
    batches = [batch_json(batch) for batch in safety.quarantine_batches()]
    total_bytes, total_items = safety.quarantine_usage()
    return {
        "batches": batches,
        "total_bytes": total_bytes,
        "total_items": total_items,
    }


def start_restore(ids: Any) -> Job:
    batch_ids = _validate_batches(ids, "restore")
    _begin_operation()
    return manager().submit("restore", "Restoring quarantined files", _run_restore, batch_ids)


def _run_restore(job: Job, ids: list[str]) -> dict[str, Any]:
    try:
        results = []
        errors: list[dict[str, Any]] = []
        total = max(1, len(ids))
        for index, batch_id in enumerate(ids, start=1):
            job.progress(current=index, total=total, phase="Restoring", message=f"Batch {batch_id}")
            restored, failed = safety.restore_batch(batch_id)
            results.append({"id": batch_id, "restored": restored, "failed": failed})
            if failed:
                errors.append(
                    _error_entry(
                        batch_id,
                        f"{failed} item(s) could not be restored — the original path is "
                        "occupied or still locked.",
                        "restore_failed",
                    )
                )
        with STATE_LOCK:
            # Files reappeared on disk, so any junk measurement is out of date.
            STATE["junk"]["stale"] = True
        return {"results": results, "errors": errors, "cancelled": job.cancel.is_set()}
    finally:
        _end_operation()


def start_purge(ids: Any, confirm: Any) -> Job:
    batch_ids = _validate_batches(ids, "purge")
    require_word(
        confirm,
        "purge",
        "Purging deletes the quarantined files for good. There is no undo.",
    )
    _begin_operation()
    return manager().submit("purge", "Purging quarantine", _run_purge, batch_ids)


def _run_purge(job: Job, ids: list[str]) -> dict[str, Any]:
    try:
        ok = 0
        failed: list[dict[str, Any]] = []
        for index, batch_id in enumerate(ids, start=1):
            job.progress(current=index, total=len(ids), phase="Purging", message=batch_id)
            if safety.purge_batch(batch_id):
                ok += 1
            else:
                failed.append(
                    _error_entry(
                        batch_id,
                        "Windows refused to delete the batch folder.",
                        "purge_failed",
                    )
                )
        return {"purged": ok, "failed": failed}
    finally:
        _end_operation()


def start_purge_all(confirm: Any) -> Job:
    require_word(
        confirm,
        "empty",
        "Emptying quarantine deletes every batch on every drive. There is no undo.",
    )
    _begin_operation()
    return manager().submit("purge", "Emptying quarantine", _run_purge_all)


def _run_purge_all(job: Job) -> dict[str, Any]:
    try:
        job.progress(phase="Emptying", message="Deleting every quarantine batch…")
        ok, bad = safety.purge_all()
        return {
            "purged": ok,
            "failed": [
                _error_entry("quarantine", f"{bad} batch(es) could not be deleted.", "purge_failed")
            ] if bad else [],
        }
    finally:
        _end_operation()


def _validate_batches(ids: Any, action: str) -> list[str]:
    if not isinstance(ids, list) or not ids:
        raise invalid("ids", f"Select at least one batch to {action}.", "Tick a row in the quarantine table.")
    known = {batch["id"] for batch in safety.quarantine_batches()}
    missing = [str(i) for i in ids if str(i) not in known]
    if missing:
        raise ApiError(
            "not_found",
            "That quarantine batch no longer exists",
            f"Batch id(s) {', '.join(missing[:4])} are not on disk. They may have been "
            "restored or purged in another window.",
            "Press Refresh to reload the batch list.",
            404,
        )
    return [str(i) for i in ids]


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
def activity(limit: int = 40) -> list[dict[str, Any]]:
    limit = max(1, min(200, int(limit)))
    entries: list[dict[str, Any]] = []
    for line in safety.read_log_tail(limit * 2):
        match = LOG_RE.match(line.strip())
        if not match:
            continue
        entries.append(
            {
                "time": match.group("time"),
                "ok": match.group("level") == "OK",
                "action": match.group("action").strip(),
                "detail": match.group("detail").strip(),
            }
        )
    return list(reversed(entries))[:limit]


def open_path(path: Any) -> dict[str, Any]:
    target = str(path or "").strip()
    if not target:
        raise invalid("path", "No path was given.", "Pass the folder you want to open.")
    if not os.path.exists(target):
        if os.path.normcase(os.path.abspath(target)) == os.path.normcase(str(paths.QUARANTINE)):
            try:
                paths.QUARANTINE.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise explain(exc)
        else:
            raise ApiError(
                "path_missing",
                "That folder does not exist",
                f"Windows cannot find {target}.",
                "Rescan — the folder may have been removed already.",
                404,
            )
    try:
        util.open_in_explorer(target)
    except OSError as exc:
        raise explain(exc)
    return {"opened": target}


def relaunch_admin() -> dict[str, Any]:
    raise ApiError(
        "unsupported",
        "The web server cannot elevate itself",
        "Windows only grants Administrator rights to a process started with a UAC "
        "prompt; a running server cannot ask for them on your behalf.",
        "Close this tab, then right-click “Sweep Web.bat” → “Run as administrator” "
        "and reopen http://127.0.0.1:8765.",
        409,
    )
