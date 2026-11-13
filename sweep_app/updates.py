"""Check for, download and apply a newer Sweep release.

Sweep is a portable app, so updating it must not need an installer, a package
manager or Administrator rights. The model is deliberately boring:

1. fetch a small JSON manifest (one request, no identifiers, no cookies);
2. compare versions with a semver-ish comparator;
3. download the release zip and verify its SHA-256;
4. extract it to a staging folder and check that it really is Sweep;
5. hand a plan to :mod:`sweep_app.updater`, which waits for this process to
   exit, backs up what it replaces, overlays the new files and restarts Sweep.

Everything network-facing lives here, and only here. The rest of the app stays
offline; if the update check is turned off, Sweep makes no outbound request at
all.

Failure philosophy: ``check()`` never raises. It returns a result with a
status, a concrete reason and a hint, so a missing network is a sentence in the
interface rather than a traceback at launch. ``download()``, ``stage()`` and
``apply()`` do raise :class:`UpdateError`, because those are explicit actions.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import __version__, config, paths

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #
# Every copy checks for updates with no setup. A release build can stamp a
# different feed into ``sweep_app/_build_info.py`` (a fork, or a beta channel);
# without that stamp -- a source checkout, an older zip, a build that still
# carries the ``OWNER/REPO`` placeholder -- the official feed below is used.
# The opt-out is the explicit ``updates.enabled = false`` setting, never a
# missing address, so nobody is silently left without updates.
OFFICIAL_MANIFEST_URL = (
    "https://github.com/Anassh780/Clean-up-tool/releases/latest/download/latest.json"
)
try:  # pragma: no cover - only exists in built releases
    from ._build_info import MANIFEST_URL as _BUILT_MANIFEST_URL  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 - a missing build stamp is normal in a checkout
    _BUILT_MANIFEST_URL = ""

_PLACEHOLDER = "OWNER/REPO"
DEFAULT_MANIFEST_URL = (
    _BUILT_MANIFEST_URL
    if _BUILT_MANIFEST_URL and _PLACEHOLDER not in _BUILT_MANIFEST_URL
    else OFFICIAL_MANIFEST_URL
)

USER_AGENT = f"Sweep/{__version__} (+local update check)"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
CHUNK = 64 * 1024
CHECK_TIMEOUT = 6.0
DOWNLOAD_TIMEOUT = 60.0
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

STATUS_AVAILABLE = "available"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_DISABLED = "disabled"
STATUS_UNCONFIGURED = "unconfigured"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"
STATUS_CACHED = "cached"

_VERSION_RE = re.compile(
    r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?"
    r"(?:[-+._]?(alpha|beta|rc|pre|preview|dev)[-._]?(\d*))?\s*$",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class UpdateError(Exception):
    """A failure with the same what/reason/hint shape as the rest of Sweep."""

    def __init__(
        self,
        code: str,
        message: str,
        reason: str,
        hint: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.reason = reason
        self.hint = hint
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "reason": self.reason,
            "hint": self.hint,
            "details": self.details,
        }


# --------------------------------------------------------------------------- #
# versions
# --------------------------------------------------------------------------- #
def _parse_version(text: str) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    match = _VERSION_RE.match(str(text or ""))
    if not match:
        raise ValueError(f"“{text}” is not a version number")
    numbers = [int(part) if part is not None else 0 for part in match.groups()[:4]]
    while len(numbers) < 4:
        numbers.append(0)
    label = match.group(5)
    ordinal = match.group(6)
    prerelease: tuple[tuple[int, int], ...] = ()
    if label:
        rank = {"alpha": 0, "beta": 1, "pre": 2, "preview": 2, "rc": 3, "dev": -1}[label.lower()]
        prerelease = ((0, rank), (1, int(ordinal) if ordinal else 0))
    return tuple(numbers), prerelease


def parse_version(text: str) -> tuple[int, int, int, int]:
    """Public, forgiving parse: ``"v1.2"`` -> ``(1, 2, 0, 0)``."""
    return _parse_version(text)[0]


def compare_versions(left: str, right: str) -> int:
    """Return -1/0/1. A prerelease sorts before its final release."""
    left_nums, left_pre = _parse_version(left)
    right_nums, right_pre = _parse_version(right)
    if left_nums != right_nums:
        return -1 if left_nums < right_nums else 1
    if left_pre == right_pre:
        return 0
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    return -1 if left_pre < right_pre else 1


def is_newer(candidate: str, current: str = __version__) -> bool:
    try:
        return compare_versions(candidate, current) > 0
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# release + result shapes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str = ""
    size: int = 0
    notes: str = ""
    released: str = ""
    channel: str = "stable"
    min_version: str = ""
    homepage: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
            "notes": self.notes,
            "released": self.released,
            "channel": self.channel,
            "min_version": self.min_version,
            "homepage": self.homepage,
            "source": self.source,
        }


@dataclass
class CheckResult:
    status: str
    current: str = __version__
    latest: str = ""
    release: Release | None = None
    checked_at: float = 0.0
    message: str = ""
    reason: str = ""
    hint: str = ""
    cached: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "current": self.current,
            "latest": self.latest,
            "release": self.release.to_dict() if self.release else None,
            "checked_at": self.checked_at,
            "message": self.message,
            "reason": self.reason,
            "hint": self.hint,
            "cached": self.cached,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckResult":
        release = data.get("release")
        return cls(
            status=str(data.get("status") or STATUS_ERROR),
            current=str(data.get("current") or __version__),
            latest=str(data.get("latest") or ""),
            release=Release(**{k: release[k] for k in Release.__dataclass_fields__ if k in release})
            if isinstance(release, dict)
            else None,
            checked_at=float(data.get("checked_at") or 0.0),
            message=str(data.get("message") or ""),
            reason=str(data.get("reason") or ""),
            hint=str(data.get("hint") or ""),
            cached=True,
            details=dict(data.get("details") or {}),
        )


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def app_root() -> Path:
    """The folder that holds ``main.py`` and ``sweep_app``."""
    return Path(__file__).resolve().parent.parent


def updates_dir() -> Path:
    return paths.UPDATES


def download_dir(version: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", version or "unknown")
    return updates_dir() / f"v{safe}"


def archive_name(version: str) -> str:
    return f"Sweep-{version}.zip"


def install_kind() -> str:
    return "frozen" if getattr(sys, "frozen", False) else "source"


# --------------------------------------------------------------------------- #
# source resolution
# --------------------------------------------------------------------------- #
def resolve_source(manifest_url: str | None = None) -> tuple[str, bool]:
    """Return ``(url, configured)``.

    Order: explicit argument, saved setting, ``SWEEP_UPDATE_URL``, then the
    build's stamped feed or the official one. The placeholder check only fires
    when a test (or a deliberately blanked build) sets the default back to
    ``OWNER/REPO``; ordinary copies are always configured.
    """
    if manifest_url:
        return str(manifest_url).strip(), True
    saved = config.updates().get("manifest_url") or ""
    if saved:
        return str(saved).strip(), True
    env = os.environ.get("SWEEP_UPDATE_URL", "").strip()
    if env:
        return env, True
    if _PLACEHOLDER in DEFAULT_MANIFEST_URL:
        return "", False
    return DEFAULT_MANIFEST_URL, True


def _validate_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.netloc:
        return
    if parts.scheme == "http" and (parts.hostname or "").lower() in LOCAL_HOSTS:
        return
    raise UpdateError(
        "insecure_source",
        "The update address is not secure",
        f"“{url}” is not an https:// address. Sweep refuses plain http because an "
        "update is code that will run on this PC.",
        "Use the https:// URL of your release manifest (localhost is allowed for testing).",
    )


# --------------------------------------------------------------------------- #
# manifest parsing
# --------------------------------------------------------------------------- #
def _text(value: Any, limit: int = 0) -> str:
    text = str(value or "").strip()
    return text[:limit] if limit else text


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _github_release(data: dict[str, Any], source: str) -> Release:
    """Accept a GitHub ``/releases/latest`` payload as well as our own schema."""
    tag = _text(data.get("tag_name") or data.get("name"))
    if not tag:
        raise UpdateError(
            "manifest_invalid",
            "The release manifest has no version",
            "The JSON came back without a “version” (or GitHub “tag_name”) field.",
            "Publish latest.json with tools/build_release.py, or point the setting at "
            "a GitHub /releases/latest API URL.",
        )
    assets = data.get("assets") or []
    archive = None
    for asset in assets if isinstance(assets, list) else []:
        name = _text(asset.get("name")).lower()
        if name.endswith(".zip") and "sweep" in name:
            archive = asset
            break
    if archive is None:
        for asset in assets if isinstance(assets, list) else []:
            if _text(asset.get("name")).lower().endswith(".zip"):
                archive = asset
                break
    if archive is None:
        raise UpdateError(
            "manifest_invalid",
            "That release has no download",
            f"GitHub release “{tag}” does not contain a .zip asset.",
            "Attach the portable Sweep zip to the release, then check again.",
        )
    digest = _text(archive.get("digest"))
    sha256 = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else ""
    return Release(
        version=tag.lstrip("vV"),
        url=_text(archive.get("browser_download_url")),
        sha256=sha256,
        size=_int(archive.get("size")),
        notes=_text(data.get("body"), 12000),
        released=_text(data.get("published_at") or data.get("created_at")),
        channel="beta" if data.get("prerelease") else "stable",
        homepage=_text(data.get("html_url")),
        source=source,
    )


def parse_release(data: Any, source: str = "") -> Release:
    if not isinstance(data, dict):
        raise UpdateError(
            "manifest_invalid",
            "The update manifest is not an object",
            f"The server sent {type(data).__name__} instead of a JSON object.",
            "Check the manifest URL; latest.json must contain one release object.",
        )
    if "assets" in data or "tag_name" in data:
        return _github_release(data, source)
    version = _text(data.get("version") or data.get("tag"))
    if not version:
        raise UpdateError(
            "manifest_invalid",
            "The update manifest has no version",
            "The JSON has no “version” field, so Sweep cannot tell what it is.",
            "Publish latest.json with tools/build_release.py.",
        )
    try:
        parse_version(version)
    except ValueError:
        raise UpdateError(
            "manifest_invalid",
            "The update manifest has an unreadable version",
            f"“{version}” is not a version such as 1.2.0.",
            "Fix the version in latest.json and check again.",
        ) from None
    url = _text(data.get("url") or data.get("download_url"))
    if not url:
        raise UpdateError(
            "manifest_invalid",
            "The update manifest has no download link",
            "The JSON has no “url” field pointing at the release zip.",
            "Regenerate latest.json with tools/build_release.py.",
        )
    sha = _text(data.get("sha256")).lower()
    if sha.startswith("sha256:"):
        sha = sha.split(":", 1)[1]
    if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError(
            "manifest_invalid",
            "The checksum in the manifest is malformed",
            f"“{sha[:20]}…” is not a 64-character SHA-256 hex digest.",
            "Regenerate latest.json; the file was probably edited by hand.",
        )
    return Release(
        version=version.lstrip("vV"),
        url=url,
        sha256=sha,
        size=_int(data.get("size")),
        notes=_text(data.get("notes") or data.get("changelog"), 12000),
        released=_text(data.get("released") or data.get("date")),
        channel=_text(data.get("channel") or "stable").lower() or "stable",
        min_version=_text(data.get("min_version")),
        homepage=_text(data.get("homepage")),
        source=source,
    )


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
class _SecureRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse an https -> http redirect.

    urllib follows redirects by default, including a downgrade to plain http.
    The first request carries the checksum, so a redirect must not be allowed
    to move it onto an unencrypted connection.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SecureRedirects())


def fetch_manifest(url: str, timeout: float = CHECK_TIMEOUT) -> Any:
    _validate_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_MANIFEST_BYTES + 1)
    except UpdateError:
        raise
    except urllib.error.HTTPError as exc:
        hints = {
            404: "The manifest is not published at that address yet. Check the URL, "
            "or run tools/build_release.py and upload latest.json.",
            403: "The server refused the request (rate limit or private repository). "
            "Use the public release asset URL.",
            401: "That address needs a login. The update check only uses public URLs.",
        }
        raise UpdateError(
            "http_error",
            f"The update server answered HTTP {exc.code}",
            f"{url} returned {exc.code} {exc.reason}.",
            hints.get(exc.code, "Check the manifest URL, then try again."),
            {"status": exc.code, "url": url},
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(
            "network_error",
            "Sweep could not reach the update server",
            f"{url} did not answer: {reason}.",
            "Sweep works normally offline. Check the connection (or proxy), then "
            "use “Check again”.",
            {"url": url},
        ) from None
    if len(raw) > MAX_MANIFEST_BYTES:
        raise UpdateError(
            "manifest_too_large",
            "The update manifest is unreasonably large",
            f"The response exceeded {MAX_MANIFEST_BYTES // 1024} KB.",
            "Point the setting at latest.json, not at a whole release page.",
        )
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(
            "manifest_invalid",
            "The update server did not send JSON",
            f"{type(exc).__name__}: {exc}",
            "The URL probably points at an HTML page. Use the raw latest.json asset URL.",
        ) from None


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def _throttle_seconds(prefs: dict[str, Any]) -> float:
    try:
        hours = int(prefs.get("check_interval_hours", 6))
    except (TypeError, ValueError):
        hours = 6
    return max(0, hours) * 3600.0


def _cached_result(prefs: dict[str, Any]) -> CheckResult | None:
    stored = prefs.get("last_result")
    if not isinstance(stored, dict) or not stored.get("status"):
        return None
    try:
        return CheckResult.from_dict(stored)
    except (TypeError, ValueError):
        return None


def check(
    *,
    force: bool = False,
    timeout: float = CHECK_TIMEOUT,
    manifest_url: str | None = None,
    record: bool = True,
) -> CheckResult:
    """Ask the release manifest whether a newer Sweep exists.

    Never raises. ``force`` ignores the interval cache (the manual button and
    ``sweep update --check``), but never overrides ``enabled = false``.
    """
    prefs = config.updates()
    now = time.time()

    if not prefs.get("enabled", True):
        return CheckResult(
            status=STATUS_DISABLED,
            checked_at=now,
            message="Update checks are off",
            reason="“Check for updates” is disabled in Settings.",
            hint="Turn it on in Settings → Updates, or run “sweep update --check”.",
        )

    url, configured = resolve_source(manifest_url)
    if not configured:
        return CheckResult(
            status=STATUS_UNCONFIGURED,
            checked_at=now,
            message="No update source is configured",
            reason="This build has no release manifest URL, so there is nothing to ask.",
            hint="Open Settings → Updates and paste the address of your latest.json "
            "(or set updates.manifest_url in config.json). See docs/RELEASING.md.",
        )

    interval = _throttle_seconds(prefs)
    if not force and interval:
        last = float(prefs.get("last_check") or 0.0)
        cached = _cached_result(prefs)
        # A result cached by the version we just replaced must not outlive the
        # update, or the fresh copy keeps showing "1.1.0 -> 1.1.1" for six
        # hours and offers the same update again.
        if (
            cached is not None
            and cached.current == __version__
            and last
            and (now - last) < interval
        ):
            cached.cached = True
            return cached

    try:
        payload = fetch_manifest(url, timeout=timeout)
        release = parse_release(payload, url)
    except UpdateError as exc:
        result = CheckResult(
            status=STATUS_ERROR,
            checked_at=now,
            message=exc.message,
            reason=exc.reason,
            hint=exc.hint,
            details=exc.details,
        )
        if record:
            _record(result)
        return result
    except Exception as exc:  # noqa: BLE001 - a check must never break startup
        result = CheckResult(
            status=STATUS_ERROR,
            checked_at=now,
            message="The update check failed unexpectedly",
            reason=f"{type(exc).__name__}: {exc}",
            hint="Try again; if it repeats, the log in %LOCALAPPDATA%\\Sweep\\logs has the detail.",
        )
        if record:
            _record(result)
        return result

    result = CheckResult(
        status=STATUS_UP_TO_DATE,
        latest=release.version,
        release=release,
        checked_at=now,
        message=f"Sweep {release.version} is the latest release",
        reason=f"Installed version is {__version__}.",
    )
    channel = str(prefs.get("channel") or "stable")
    if release.channel == "beta" and channel != "beta":
        result.message = "A beta is available, but this copy follows the stable channel"
        result.reason = f"The newest release ({release.version}) is marked beta."
        result.hint = "Switch the channel to beta in Settings → Updates if you want it."
    elif is_newer(release.version, __version__):
        if str(prefs.get("skipped") or "") == release.version:
            result.status = STATUS_SKIPPED
            result.message = f"Sweep {release.version} is available (skipped)"
            result.reason = "You chose “Not now” for this version."
            result.hint = "Open Settings → Updates to install it anyway."
        else:
            result.status = STATUS_AVAILABLE
            result.message = f"Sweep {release.version} is available"
            result.reason = f"You have {__version__}."
            result.hint = (
                "Download it from Settings → Updates; the update keeps your "
                "quarantine, logs and settings."
            )
    elif release.version != __version__:
        result.message = f"Sweep {__version__} is newer than the published {release.version}"
        result.reason = "This copy is ahead of the release manifest (a local build?)."

    if record:
        _record(result)
    return result


def _record(result: CheckResult) -> None:
    try:
        config.record_check(result.to_dict())
    except OSError:
        # A read-only install can still check; it just cannot remember the answer.
        pass


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(
    release: Release,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancel: Any = None,
    timeout: float = DOWNLOAD_TIMEOUT,
) -> Path:
    """Download the release zip and verify it. Returns the local path."""
    if not release.sha256:
        raise UpdateError(
            "missing_checksum",
            "This release cannot be verified",
            "The manifest has no SHA-256 checksum for the download.",
            "Regenerate latest.json with tools/build_release.py so every release "
            "carries a checksum.",
        )
    _validate_url(release.url)
    folder = download_dir(release.version)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / archive_name(release.version)

    if target.is_file() and _sha256(target) == release.sha256:
        if progress:
            progress(target.stat().st_size, target.stat().st_size)
        return target

    partial = target.with_suffix(".part")
    request = urllib.request.Request(
        release.url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/zip, application/octet-stream"},
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            total = _int(response.headers.get("Content-Length")) or release.size
            done = 0
            with partial.open("wb") as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise UpdateError(
                            "cancelled",
                            "Download cancelled",
                            "The download was stopped before the file was complete.",
                            "Start it again from Settings → Updates.",
                        )
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > MAX_ARCHIVE_BYTES:
                        raise UpdateError(
                            "archive_too_large",
                            "The download is unreasonably large",
                            f"It exceeded {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB.",
                            "Check that the manifest points at the Sweep zip.",
                        )
                    handle.write(chunk)
                    if progress:
                        progress(done, total)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            "download_failed",
            "The update could not be downloaded",
            f"{release.url} failed: {getattr(exc, 'reason', exc)}.",
            "Check the connection and try again; the previous version is untouched.",
            {"url": release.url},
        ) from None

    if release.size and partial.stat().st_size != release.size:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            "size_mismatch",
            "The download is incomplete",
            f"Expected {release.size} bytes, received {partial.stat().st_size}.",
            "Try the download again.",
        )
    actual = _sha256(partial)
    if actual != release.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            "checksum_mismatch",
            "The download did not match its checksum",
            f"Expected {release.sha256[:16]}…, got {actual[:16]}…. The file was "
            "corrupted or replaced in transit.",
            "Do not install it. Try again; if it repeats, check the manifest's sha256.",
        )
    partial.replace(target)
    return target


# --------------------------------------------------------------------------- #
# staging
# --------------------------------------------------------------------------- #
def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        if name.endswith("/"):
            continue
        if name.startswith("__MACOSX/") or name.split("/")[-1] in (".DS_Store", "Thumbs.db"):
            continue
        parts = Path(name).parts
        if not parts:
            continue
        if name.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", name):
            raise UpdateError(
                "unsafe_archive",
                "The update archive is not safe to extract",
                f"It contains “{info.filename}”, which would escape the staging folder.",
                "Do not install this archive. Rebuild it with tools/build_release.py.",
            )
        # Reject symlinks and other special entries.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise UpdateError(
                "unsafe_archive",
                "The update archive contains a symbolic link",
                f"“{info.filename}” is a symlink, which Sweep refuses to extract.",
                "Rebuild the release archive without links.",
            )
        members.append(info)
    return members


def _find_app_root(folder: Path) -> Path | None:
    if (folder / "main.py").is_file() and (folder / "sweep_app" / "__init__.py").is_file():
        return folder
    for child in folder.iterdir():
        if child.is_dir() and (child / "main.py").is_file() and (
            child / "sweep_app" / "__init__.py"
        ).is_file():
            return child
    return None


def stage(zip_path: Path, release: Release) -> Path:
    """Extract and validate a downloaded zip. Returns the staged app root."""
    folder = zip_path.parent / "staged"
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad = archive.testzip()
            if bad:
                raise UpdateError(
                    "archive_corrupt",
                    "The update archive is damaged",
                    f"“{bad}” failed the zip integrity check.",
                    "Download the release again.",
                )
            for info in _safe_members(archive):
                archive.extract(info, folder)
    except zipfile.BadZipFile as exc:
        raise UpdateError(
            "archive_corrupt",
            "The update is not a valid zip file",
            f"{type(exc).__name__}: {exc}",
            "Download the release again, or rebuild it with tools/build_release.py.",
        ) from None

    root = _find_app_root(folder)
    if root is None:
        raise UpdateError(
            "archive_invalid",
            "The update does not look like Sweep",
            "The zip has no main.py and sweep_app/__init__.py at its root.",
            "The manifest probably points at the wrong asset. Use the portable Sweep zip.",
        )
    init_file = root / "sweep_app" / "__init__.py"
    try:
        found = re.search(
            r"__version__\s*=\s*[\"']([^\"']+)[\"']", init_file.read_text(encoding="utf-8")
        )
    except OSError:
        found = None
    if not found:
        raise UpdateError(
            "archive_invalid",
            "The update has no version stamp",
            f"{init_file} does not define __version__.",
            "Rebuild the release archive from a clean checkout.",
        )
    if compare_versions(found.group(1), release.version) != 0:
        raise UpdateError(
            "version_mismatch",
            "The download is not the version the manifest promised",
            f"The manifest says {release.version}, the archive says {found.group(1)}.",
            "Do not install it. Republish the release so the manifest matches the zip.",
        )
    return root


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #
def writable_install() -> tuple[bool, str]:
    """Can this process replace files in the app folder?"""
    root = app_root()
    probe = root / f".sweep-write-test-{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def relaunch_argv() -> list[str]:
    """The command that starts this same interface again."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, str(app_root() / "main.py"), *sys.argv[1:]]


def _helper_interpreter() -> str:
    """Return a Python that can run while the app folder is rewritten.

    A portable release runs on its own bundled ``runtime\\python.exe``. That
    file sits inside the folder an update replaces, and Windows will not let a
    running executable be overwritten. When the current interpreter lives
    inside the app folder, copy the runtime to ``updates\\helper-runtime`` and
    run the helper from there; the copy is outside the tree being replaced, so
    every file — including ``runtime\\python.exe`` — can be updated.

    A system Python (the source checkout case) is already outside the folder
    and is used as-is.
    """
    exe = Path(sys.executable).resolve()
    root = app_root().resolve()
    try:
        exe.relative_to(root)
    except ValueError:
        return str(exe)

    source = exe.parent
    target = updates_dir() / "helper-runtime"
    stamp = target / ".sweep-helper-stamp"
    marker = f"{source}|{exe.stat().st_mtime_ns}|{exe.stat().st_size}"
    if stamp.is_file():
        try:
            if stamp.read_text(encoding="utf-8").strip() == marker:
                return str(target / "python.exe")
        except OSError:
            pass

    target.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, target, dirs_exist_ok=True)
    except OSError as exc:
        raise UpdateError(
            "helper_runtime_failed",
            "The update helper could not be prepared",
            f"Copying {source} to {target} failed: {type(exc).__name__}: {exc}",
            "Free some space in %LOCALAPPDATA%\\Sweep\\updates and try again.",
        ) from None

    # Absolute paths: the helper now lives outside the app, so relative
    # ``..\\vendor`` entries would point at the wrong place.
    stdlib = sorted(source.glob("python*.zip"))
    # Reference the *copied* stdlib zip, not the one in the app folder: the
    # overlay is about to replace that file, and the helper must keep importing
    # standard-library modules after it does.
    lines = [stdlib[0].name] if stdlib else []
    lines += [".", str(root), str(root / "vendor"), "import site"]
    pth_name = (stdlib[0].stem if stdlib else "python312") + "._pth"
    (target / pth_name).write_text("\n".join(lines) + "\n", encoding="ascii")
    # A copied runtime may carry a differently-named ._pth; remove extras so
    # only the one we just wrote is read.
    for extra in target.glob("python*._pth"):
        if extra.name != pth_name:
            extra.unlink(missing_ok=True)
    try:
        stamp.write_text(marker, encoding="utf-8")
    except OSError:
        pass
    return str(target / "python.exe")


def apply(
    staged: Path,
    release: Release,
    *,
    relaunch: list[str] | None = None,
    keep_backup: bool = True,
) -> Path:
    """Write an update plan and start the detached helper.

    The caller must exit shortly after this returns: the helper waits for this
    PID, then replaces files. Returns the plan path (useful in logs/tests).
    """
    ok, error = writable_install()
    if not ok:
        raise UpdateError(
            "install_not_writable",
            "Sweep cannot replace its own files",
            f"{app_root()} is not writable: {error}",
            "Move the Sweep folder somewhere under your user profile (for example "
            "Documents\\Sweep) and update again. Running as administrator also works.",
        )
    if install_kind() == "frozen":
        raise UpdateError(
            "frozen_update",
            "This build cannot update itself",
            "Sweep is running as a single .exe, which a running process cannot replace.",
            "Download the new Sweep.exe from the release page and replace the old one; "
            "your quarantine, logs and settings stay in %LOCALAPPDATA%\\Sweep.",
        )

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = updates_dir() / f"backup-{__version__}-{stamp}"
    plan_path = updates_dir() / f"apply-{stamp}.json"
    plan = {
        "schema": 1,
        "version": release.version,
        "from_version": __version__,
        "app_root": str(app_root()),
        "staged": str(staged),
        "backup": str(backup),
        "keep_backup": bool(keep_backup),
        "relaunch": list(relaunch or relaunch_argv()),
        "pid": os.getpid(),
        "created": time.time(),
    }
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    # The next launch is a different version; a cached "available" answer from
    # this one must not be shown as if the update had not happened.
    config.clear_check()

    helper = Path(__file__).with_name("updater.py")
    cmd = [_helper_interpreter(), str(helper), "--plan", str(plan_path)]
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            cmd,
            cwd=tempfile.gettempdir(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        raise UpdateError(
            "apply_failed",
            "The update helper could not start",
            f"{type(exc).__name__}: {exc}",
            "Close other copies of Sweep and try again, or update by hand from the "
            "release zip.",
        ) from None
    return plan_path


# --------------------------------------------------------------------------- #
# housekeeping + state
# --------------------------------------------------------------------------- #
def cleanup(keep: int = 2) -> int:
    """Remove old downloads and backups. Returns bytes freed."""
    freed = 0
    root = updates_dir()
    if not root.is_dir():
        return 0

    def _size(path: Path) -> int:
        total = 0
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                pass
        return total

    downloads = sorted(
        (p for p in root.glob("v*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for old in downloads[max(1, keep):]:
        freed += _size(old)
        shutil.rmtree(old, ignore_errors=True)

    backups = sorted(
        (p for p in root.glob("backup-*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for old in backups[max(1, keep):]:
        freed += _size(old)
        shutil.rmtree(old, ignore_errors=True)
    return freed


def backups() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = updates_dir()
    for folder in sorted(root.glob("backup-*"), reverse=True):
        if not folder.is_dir():
            continue
        try:
            stat = folder.stat()
        except OSError:
            continue
        rows.append(
            {
                "name": folder.name,
                "path": str(folder),
                "created": stat.st_mtime,
                "bytes": sum(
                    item.stat().st_size for item in folder.rglob("*") if item.is_file()
                ),
            }
        )
    return rows


def state() -> dict[str, Any]:
    """Everything the settings page needs to render the update card."""
    prefs = config.updates()
    url, configured = resolve_source()
    last = prefs.get("last_result")
    if not isinstance(last, dict) or not last.get("status"):
        last = None
    return {
        "current": __version__,
        "install": install_kind(),
        "app_root": str(app_root()),
        "updates_dir": str(updates_dir()),
        "platform": platform.platform(),
        "enabled": bool(prefs.get("enabled", True)),
        "channel": str(prefs.get("channel") or "stable"),
        "check_interval_hours": int(prefs.get("check_interval_hours") or 0),
        "manifest_url": url,
        "configured": configured,
        "skipped": str(prefs.get("skipped") or ""),
        "last_check": float(prefs.get("last_check") or 0.0),
        "last_result": last,
        "can_apply": install_kind() == "source" and writable_install()[0],
        "backups": backups()[:5],
    }


def start_check(**kwargs: Any) -> CheckResult:
    """Convenience alias used by interfaces that want the name to read well."""
    return check(**kwargs)
