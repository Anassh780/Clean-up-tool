"""``sweep update`` — check, download, install and roll back a release.

The update engine (:mod:`sweep_app.updates`) and the apply helper
(:mod:`sweep_app.updater`) already know how to do the dangerous parts. This
module is the command-line front end: it decides what the person asked for,
prints a report a script can read, and never performs a destructive step
without an explicit ``--yes``.

It lives beside ``cli.py`` rather than inside it because the flag handling and
the progress rendering are long enough to drown the other commands.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

from . import __version__, config, paths, updates, updater, util

EXIT_OK = 0
EXIT_AVAILABLE = 10
EXIT_ERROR = 2
EXIT_CANCELLED = 130

# A check-only run maps the engine's status to the documented exit codes.
# Keep this in sync with the STATUS_* constants in sweep_app.updates.
_STATUS_EXIT = {
    updates.STATUS_AVAILABLE: EXIT_AVAILABLE,
    updates.STATUS_UP_TO_DATE: EXIT_OK,
    updates.STATUS_DISABLED: EXIT_OK,
    updates.STATUS_UNCONFIGURED: EXIT_OK,
    updates.STATUS_SKIPPED: EXIT_OK,
    updates.STATUS_ERROR: EXIT_ERROR,
}

_TITLE_STYLE = {
    updates.STATUS_AVAILABLE: "yellow",
    updates.STATUS_UP_TO_DATE: "green",
    updates.STATUS_SKIPPED: "yellow",
    updates.STATUS_ERROR: "red",
    updates.STATUS_DISABLED: "dim",
    updates.STATUS_UNCONFIGURED: "dim",
}

_ANSI = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "reset": "\033[0m",
}

DESCRIPTION = """Check for a newer Sweep, then download, verify, install or roll it back.

With no flags it asks the release manifest (or reuses a fresh saved answer)
and prints a readable report. Nothing is downloaded and nothing changes.
"""

EPILOG = """exit codes:
  0    up to date, checks disabled, unconfigured, skipped, or the action succeeded
  10   a plain check found a newer release (nothing was installed)
  2    the check failed, or an action was refused
  130  interrupted (Ctrl+C during a download)

examples:
  sweep update
  sweep update --check --json
  sweep update --install --dry-run
  sweep update --install --yes
  sweep update --rollback
"""


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
def _is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _paint(text: str, style: str, stream: TextIO) -> str:
    """Add colour only when a person is watching, so pipes stay clean."""
    if os.environ.get("NO_COLOR") or not _is_tty(stream):
        return text
    code = _ANSI.get(style)
    return f"{code}{text}{_ANSI['reset']}" if code else text


def _human_stream(args: argparse.Namespace) -> TextIO:
    """Where prose goes. With --json, stdout belongs to the JSON only."""
    return sys.stderr if getattr(args, "json", False) else sys.stdout


def _say(args: argparse.Namespace, text: str = "") -> None:
    """Prose for a person. A closed pipe must not abort an update."""
    stream = _human_stream(args)
    try:
        print(text, file=stream)
        stream.flush()
    except (OSError, ValueError):
        pass


def _emit_json(payload: Any) -> None:
    """Write one JSON document to stdout, falling back to ASCII if needed."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        try:
            sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
            sys.stdout.flush()
        except OSError:
            pass
    except OSError:
        pass


def _flush() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass


def _problem(
    args: argparse.Namespace,
    headline: str,
    reason: str,
    hint: str = "",
    *,
    code: str = "",
    style: str = "red",
) -> None:
    """Print the same what/reason/hint shape the rest of Sweep uses."""
    stream = _human_stream(args)
    print(_paint(headline, style, stream), file=stream)
    if code:
        print(f"  {'Code':<8} {code}", file=stream)
    if reason:
        print(f"  {'Reason':<8} {reason}", file=stream)
    if hint:
        print(f"  {'Hint':<8} {hint}", file=stream)
    stream.flush()


def _refuse(
    args: argparse.Namespace, headline: str, reason: str, hint: str = ""
) -> int:
    _problem(args, headline, reason, hint, style="yellow")
    return EXIT_ERROR


def _report_error(args: argparse.Namespace, exc: updates.UpdateError) -> None:
    _problem(
        args,
        f"Update failed: {exc.message}",
        exc.reason,
        exc.hint,
        code=exc.code,
    )


# --------------------------------------------------------------------------- #
# readable check report
# --------------------------------------------------------------------------- #
def _checked_label(result: updates.CheckResult) -> str:
    if not result.checked_at:
        return "—"
    label = f"{util.human_age(result.checked_at)} ({util.short_time(result.checked_at)})"
    if result.cached:
        label += " — cached; use --check for a fresh answer"
    return label


def _notes_excerpt(notes: str, limit: int = 8, width: int = 96) -> list[str]:
    """At most ``limit`` non-repeating lines, so a long changelog stays a report."""
    if not notes:
        return []
    raw = str(notes).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in (part.strip() for part in raw):
        if not line and (not lines or not lines[-1]):
            continue
        lines.append(line)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return []
    out = [util.truncate(line, width) for line in lines[:limit]]
    if len(lines) > limit:
        out.append("…")
    return out


def _cli_hint(result: updates.CheckResult) -> str:
    """A command-line next step, instead of the TUI's “Settings → Updates”.

    The engine's hint is written for the interface. A terminal user needs the
    flag to type, so the common statuses get a CLI-specific sentence; errors
    keep the engine's hint because it names the HTTP or network problem.
    """
    if result.status == updates.STATUS_AVAILABLE:
        return (
            "Run “sweep update --install --yes” to download and install it. "
            "Your quarantine, logs and settings are kept."
        )
    if result.status == updates.STATUS_SKIPPED:
        return "Install it anyway with “sweep update --install --yes --force”."
    if result.status == updates.STATUS_DISABLED:
        return "Turn checks on with “sweep update --enable”."
    if result.status == updates.STATUS_UNCONFIGURED:
        return "Set the manifest URL with “sweep update --source https://…/latest.json”."
    return result.hint


def _report_result(result: updates.CheckResult, stream: TextIO) -> None:
    label = result.status.replace("_", " ")
    title = f"Sweep update — {label}"
    style = _TITLE_STYLE.get(result.status, "bold")
    print(_paint(title, style, stream), file=stream)
    print(_paint("─" * min(78, max(24, len(title))), "dim", stream), file=stream)

    rows: list[tuple[str, str]] = [
        ("Status", result.status),
        ("Current", result.current),
    ]
    if result.latest:
        rows.append(("Latest", result.latest))
    release = result.release
    if release is not None:
        bits = [release.channel or "stable"]
        if release.released:
            bits.append(f"released {release.released[:10]}")
        if release.size:
            bits.append(util.human_size(release.size))
        rows.append(("Release", " · ".join(bits)))
    rows.append(("Checked", _checked_label(result)))
    if result.message:
        rows.append(("Message", result.message))
    for name, value in rows:
        print(f"  {name:<8} {value}", file=stream)

    notes = _notes_excerpt(release.notes if release is not None else "")
    if notes:
        print(f"  {'Notes':<8}".rstrip(), file=stream)
        for line in notes:
            print(f"           {line}", file=stream)

    if result.reason:
        print(f"  {'Reason':<8} {result.reason}", file=stream)
    hint = _cli_hint(result)
    if hint:
        print(f"  {'Hint':<8} {hint}", file=stream)
    stream.flush()


# --------------------------------------------------------------------------- #
# download progress
# --------------------------------------------------------------------------- #
class _Progress:
    """One rewritten line on a terminal, about ten lines when redirected.

    The downloader calls this once per 64 KB chunk. Printing every call would
    bury the rest of the command in a log file, so a terminal gets ``\\r`` and
    a pipe gets a line only when the percentage crosses a 10% boundary.
    """

    def __init__(self, stream: TextIO, label: str = "Downloading") -> None:
        self.stream = stream
        self.label = label
        self.tty = _is_tty(stream)
        self.total = 0
        self.done = 0
        self._bucket = -1
        self._next_bytes = 0
        self._last_emit = 0.0
        self._wrote = False
        self._finished = False
        self._enabled = True

    def __call__(self, done: int, total: int) -> None:
        self.done = max(0, int(done))
        self.total = max(0, int(total))
        now = time.monotonic()

        if self.total:
            percent = min(100, int(self.done * 100 / self.total))
            if self.tty:
                if now - self._last_emit < 0.08 and percent != 100:
                    return
                self._last_emit = now
                self._write(
                    f"\r  {self.label}  {percent:3d}%  "
                    f"({util.human_size(self.done)} / {util.human_size(self.total)})"
                )
                return
            bucket = percent // 10
            if bucket <= self._bucket:
                return
            self._bucket = bucket
            self._line(
                f"  {self.label}  {percent:3d}%  "
                f"({util.human_size(self.done)} / {util.human_size(self.total)})"
            )
            return

        # The server sent no Content-Length: report bytes, not a fake percent.
        if self.tty:
            if now - self._last_emit < 0.1:
                return
            self._last_emit = now
            self._write(f"\r  {self.label}  {util.human_size(self.done)}")
            return
        if self.done >= self._next_bytes:
            self._line(f"  {self.label}  {util.human_size(self.done)}")
            self._next_bytes = self.done + 5 * 1024 * 1024

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
            self._wrote = True
        except (OSError, ValueError):
            self.tty = False

    def _line(self, text: str) -> None:
        """A complete line for a redirected stream; stop quietly if it closes."""
        if not self._enabled:
            return
        try:
            print(text, file=self.stream, flush=True)
        except (OSError, ValueError):
            self._enabled = False

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self.tty and self._wrote:
            if self.total:
                line = (
                    f"\r  {self.label}  100%  "
                    f"({util.human_size(self.done)} / {util.human_size(self.total)})"
                )
            else:
                line = f"\r  {self.label}  {util.human_size(self.done)}"
            self._write(line + "\n")
            return
        if not self.total and self.done:
            self._line(f"  {self.label}  {util.human_size(self.done)}")

    def abort(self) -> None:
        """Close the rewritten line after a failure, without inventing 100%."""
        if self._finished:
            return
        self._finished = True
        if self.tty and self._wrote:
            self._write("\n")


def _discard_partial(version: str) -> None:
    """Remove the half-written archive after Ctrl+C, so a retry starts clean."""
    target = updates.download_dir(version) / updates.archive_name(version)
    try:
        target.with_suffix(".part").unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# settings / skip helpers
# --------------------------------------------------------------------------- #
def _public_prefs() -> dict[str, Any]:
    """The settings a script cares about, without the cached last result."""
    prefs = config.updates()
    return {
        "enabled": bool(prefs.get("enabled", True)),
        "channel": str(prefs.get("channel") or "stable"),
        "manifest_url": str(prefs.get("manifest_url") or ""),
        "check_interval_hours": int(prefs.get("check_interval_hours") or 0),
        "skipped": str(prefs.get("skipped") or ""),
    }


def _clean_version(raw: str) -> str:
    text = str(raw or "").strip().lstrip("vV")
    if not text:
        raise ValueError("A version such as 9.9.9 is required.")
    updates.parse_version(text)  # raises ValueError with the offending text
    return text


def _save_skip(args: argparse.Namespace, version: str) -> int:
    try:
        config.set_updates({"skipped": version})
    except ValueError as exc:
        return _refuse(args, "The skip was not saved", str(exc), "Use a version such as 9.9.9.")
    except OSError as exc:
        return _refuse(
            args,
            "The skip was not saved",
            f"{type(exc).__name__}: {exc}",
            f"Check that {paths.CONFIG_FILE.parent} is writable, then retry.",
        )
    if args.json:
        _emit_json({"ok": True, "action": "skip", "skipped": version})
    else:
        print(f"Sweep {version} will not be offered again.")
        print("  Install it anyway with: sweep update --install --yes --force")
    return EXIT_OK


def _skip_version(args: argparse.Namespace, raw: str) -> int:
    try:
        version = _clean_version(raw)
    except ValueError as exc:
        return _refuse(
            args,
            "That is not a version Sweep can skip",
            str(exc),
            "Use a version such as 9.9.9.",
        )
    return _save_skip(args, version)


def _skip_latest(args: argparse.Namespace, result: updates.CheckResult) -> int:
    """``--skip`` with no value: look up the newest release, then remember it."""
    if result.status == updates.STATUS_ERROR:
        if args.json:
            _emit_json(result.to_dict())
        else:
            _report_result(result, sys.stdout)
        return EXIT_ERROR
    if not result.latest:
        if args.json:
            _emit_json(
                {
                    "ok": False,
                    "action": "skip",
                    "status": result.status,
                    "reason": result.reason,
                    "hint": result.hint,
                }
            )
        else:
            _problem(
                args,
                "There is no version to skip",
                result.reason or result.message or f"The check reported “{result.status}”.",
                result.hint or "Run “sweep update --check” first, then try again.",
                style="yellow",
            )
        return EXIT_ERROR
    if not updates.is_newer(result.latest, __version__):
        if args.json:
            _emit_json(
                {
                    "ok": True,
                    "action": "skip",
                    "skipped": "",
                    "message": f"Sweep {__version__} is already the latest release",
                }
            )
        else:
            print(f"Sweep {__version__} is already the latest release; there is nothing to skip.")
        return EXIT_OK
    return _save_skip(args, result.latest)


# --------------------------------------------------------------------------- #
# install / dry run
# --------------------------------------------------------------------------- #
def _relaunch_argv() -> list[str]:
    """Start the same interface again after the helper replaces files."""
    return [sys.executable, str(updates.app_root() / "main.py"), "tui"]


def _plan_value(plan_path: Path, key: str) -> str:
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get(key) or "")


def _install_hint(result: updates.CheckResult) -> str:
    if result.status == updates.STATUS_SKIPPED:
        return "Install it anyway with “sweep update --install --yes --force”."
    if result.status == updates.STATUS_UP_TO_DATE:
        return "Sweep is already current; there is nothing to download."
    if result.status == updates.STATUS_DISABLED:
        return "Turn update checks on with “sweep update --enable”, then retry."
    if result.status == updates.STATUS_UNCONFIGURED:
        return (
            "Set the manifest URL with “sweep update --source https://…/latest.json”, "
            "then retry."
        )
    if result.hint:
        return result.hint
    return "Run “sweep update --check” to see the current state."


def _print_dry_run(
    args: argparse.Namespace,
    release: updates.Release,
    zip_path: Path,
    staged: Path,
) -> int:
    stream = _human_stream(args)
    files = sum(1 for path in staged.rglob("*") if path.is_file())
    kind = updates.install_kind()
    writable, why = updates.writable_install()

    print(file=stream)
    print(_paint("Dry run — no files were changed", "yellow", stream), file=stream)
    print(f"  {'Version':<12} {release.version}  (current {__version__})", file=stream)
    print(f"  {'Download':<12} {zip_path}", file=stream)
    print(f"  {'Staged':<12} {staged}  ({files} files)", file=stream)
    print(
        f"  {'Backup':<12} {updates.updates_dir() / f'backup-{__version__}-<timestamp>'}",
        file=stream,
    )
    print(f"  {'Relaunch':<12} {' '.join(_relaunch_argv())}", file=stream)

    if kind == "frozen":
        print(
            f"  {'Can apply':<12} no — this build runs as a single .exe",
            file=stream,
        )
        print(
            "  Download the new Sweep.exe from the release page and replace the old one.",
            file=stream,
        )
        return EXIT_ERROR
    if not writable:
        print(
            f"  {'Can apply':<12} no — {updates.app_root()} is not writable",
            file=stream,
        )
        print(f"  {'Reason':<12} {why}", file=stream)
        print(
            "  Move Sweep under your user profile (for example Documents\\Sweep), then retry.",
            file=stream,
        )
        return EXIT_ERROR

    print(f"  {'Can apply':<12} yes", file=stream)
    print(file=stream)
    print("  Run “sweep update --install --yes” to apply it.", file=stream)
    stream.flush()
    return EXIT_OK


def _install(args: argparse.Namespace, result: updates.CheckResult) -> int:
    stream = _human_stream(args)
    if result.status != updates.STATUS_AVAILABLE:
        _report_result(result, stream)
        headline = (
            "The update check failed"
            if result.status == updates.STATUS_ERROR
            else "There is nothing to install"
        )
        _problem(
            args,
            headline,
            f"The check reported “{result.status}”"
            + (f" for Sweep {result.latest}" if result.latest else "")
            + ".",
            _install_hint(result),
            style="yellow",
        )
        if args.json:
            _emit_json(result.to_dict())
        return EXIT_ERROR

    release = result.release
    if release is None:
        _problem(
            args,
            "There is nothing to install",
            "The check says an update is available but carried no release details.",
            "Run “sweep update --check” again; if it repeats, the manifest is incomplete.",
        )
        if args.json:
            _emit_json(result.to_dict())
        return EXIT_ERROR

    cancel = threading.Event()
    progress = _Progress(stream)
    try:
        try:
            zip_path = updates.download(release, progress=progress, cancel=cancel)
        except KeyboardInterrupt:
            cancel.set()
            progress.abort()
            _discard_partial(release.version)
            _problem(
                args,
                "Download cancelled",
                "You interrupted the download; the partial file was removed.",
                "Run the command again when you are ready. Nothing was changed.",
                style="yellow",
            )
            return EXIT_CANCELLED

        progress.finish()
        _say(
            args,
            f"  Downloaded {util.human_size(zip_path.stat().st_size)} — SHA-256 verified.",
        )
        _say(args, "  Extracting and checking the version stamp …")
        try:
            staged = updates.stage(zip_path, release)
        except KeyboardInterrupt:
            _problem(
                args,
                "Update cancelled",
                "You interrupted the extraction; the staging folder will be replaced "
                "on the next attempt.",
                "Run the command again when you are ready. Nothing was changed.",
                style="yellow",
            )
            return EXIT_CANCELLED
        _say(args, f"  Staged in {staged}")
    except updates.UpdateError as exc:
        progress.abort()
        _report_error(args, exc)
        return EXIT_ERROR
    except OSError as exc:
        progress.abort()
        _problem(
            args,
            "The update could not be prepared",
            f"{type(exc).__name__}: {exc}",
            "Check free disk space and permissions on "
            f"{updates.updates_dir()}, then retry.",
        )
        return EXIT_ERROR

    if args.dry_run:
        code = _print_dry_run(args, release, zip_path, staged)
        if args.json:
            _emit_json(result.to_dict())
        return code

    try:
        plan_path = updates.apply(staged, release, relaunch=_relaunch_argv())
    except updates.UpdateError as exc:
        _report_error(args, exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        _problem(
            args,
            "Update interrupted",
            "The update helper may already be running.",
            "Wait a moment; if Sweep does not restart, run “sweep update --check”.",
            style="yellow",
        )
        return EXIT_CANCELLED
    except OSError as exc:
        _problem(
            args,
            "The update helper could not be prepared",
            f"{type(exc).__name__}: {exc}",
            f"Check that {updates.updates_dir()} is writable, then retry.",
        )
        return EXIT_ERROR

    backup = _plan_value(plan_path, "backup") or str(updates.updates_dir())
    print(file=stream)
    print(
        _paint(f"Update ready: Sweep {__version__} → {release.version}", "green", stream),
        file=stream,
    )
    print(f"  {'Version':<12} {release.version}", file=stream)
    print(f"  {'Backup':<12} {backup}", file=stream)
    print("  Sweep will restart.", file=stream)
    stream.flush()

    if args.json:
        _emit_json(result.to_dict())
    _flush()
    return EXIT_OK


# --------------------------------------------------------------------------- #
# rollback
# --------------------------------------------------------------------------- #
def _rollback(args: argparse.Namespace) -> int:
    stream = _human_stream(args)
    if updates.install_kind() == "frozen":
        return _refuse(
            args,
            "This build cannot roll back",
            "Sweep is running as a single .exe, and its install folder is temporary.",
            "Download the previous Sweep.exe from the release page; your settings and "
            "quarantine are untouched.",
        )

    try:
        rows = sorted(
            updates.backups(),
            key=lambda row: float(row.get("created") or 0.0),
            reverse=True,
        )
    except OSError as exc:
        return _refuse(
            args,
            "The backups could not be listed",
            f"{type(exc).__name__}: {exc}",
            f"Check that {updates.updates_dir()} is readable, then retry.",
        )
    if not rows:
        return _refuse(
            args,
            "There is no backup to roll back to",
            f"No backup-* folder exists in {updates.updates_dir()}.",
            "Backups are made automatically by “sweep update --install”. Nothing was changed.",
        )

    row = rows[0]
    backup = Path(str(row.get("path") or ""))
    manifest = backup / "manifest.json"
    if not manifest.is_file():
        return _refuse(
            args,
            "That backup is incomplete",
            f"{backup} has no manifest.json, so Sweep cannot tell what to restore.",
            "Try an older backup folder, or reinstall the previous release by hand.",
        )
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _refuse(
            args,
            "That backup cannot be read",
            f"{type(exc).__name__}: {exc}",
            "Try an older backup folder. Nothing was changed.",
        )

    log = updater.Log()
    try:
        try:
            code = updater.restore(updates.app_root(), backup, log)
        except (OSError, ValueError) as exc:
            return _refuse(
                args,
                "The backup could not be restored",
                f"{type(exc).__name__}: {exc}",
                "Close every other Sweep window and retry. Nothing was changed unless "
                "the message above says otherwise.",
            )
    finally:
        log.close()

    if code != 0:
        return _refuse(
            args,
            "The backup could not be restored",
            f"The helper returned {code}; see {log.path}.",
            "Try an older backup folder, or reinstall the previous release by hand.",
        )

    from_version = str(data.get("from_version") or "")
    installed_version = str(data.get("version") or "")
    backed_up = len(data.get("backed_up") or [])
    created = len(data.get("created") or [])
    label = f"Sweep {from_version}" if from_version else "the previous version"

    if args.json:
        _emit_json(
            {
                "ok": True,
                "action": "rollback",
                "backup": str(backup),
                "version": from_version,
                "restored": backed_up,
                "removed": created,
                "log": str(log.path),
            }
        )
        return EXIT_OK

    print(_paint(f"Rolled back to {label}", "green", stream), file=stream)
    print(f"  {'Backup':<10} {backup.name}", file=stream)
    print(f"  {'Restored':<10} {backed_up} file(s)", file=stream)
    print(f"  {'Removed':<10} {created} file(s) added by the update", file=stream)
    if installed_version:
        print(f"  {'Replaced':<10} Sweep {installed_version}", file=stream)
    print(f"  {'Log':<10} {log.path}", file=stream)
    print("  Restart Sweep to run the restored files.", file=stream)
    stream.flush()
    return EXIT_OK


# --------------------------------------------------------------------------- #
# command
# --------------------------------------------------------------------------- #
def _unskip(result: updates.CheckResult) -> None:
    """--force turns a saved “not now” into an installable release for this run."""
    if result.status != updates.STATUS_SKIPPED:
        return
    result.status = updates.STATUS_AVAILABLE
    result.message = f"Sweep {result.latest} is available"
    result.reason = (
        f"You have {result.current}. The saved “not now” choice was ignored because "
        "--force was used."
    )
    result.hint = "Download it with “sweep update --install --yes”."


def cmd_update(args: argparse.Namespace) -> int:
    install_mode = bool(args.install or args.dry_run)

    # Refuse contradictory requests before touching the network or the disk.
    if args.rollback and (
        install_mode or args.cleanup or args.check or args.skip is not None
    ):
        return _refuse(
            args,
            "Those flags cannot be combined",
            "--rollback restores a backup; it cannot run with --install, --dry-run, "
            "--check, --cleanup or --skip.",
            "Run “sweep update --rollback” on its own.",
        )
    if install_mode and args.skip is not None:
        return _refuse(
            args,
            "Those flags cannot be combined",
            "--install and --skip ask for opposite things.",
            "Install with “sweep update --install --yes”, or skip with "
            "“sweep update --skip”.",
        )
    if args.install and not args.dry_run and not args.yes:
        return _refuse(
            args,
            "Confirmation required",
            "--install replaces files in the Sweep folder, so it needs an explicit --yes.",
            "Re-run with --yes to install, or add --dry-run to preview first.",
        )

    # Save any settings first, so the check that follows uses the new values.
    patch: dict[str, Any] = {}
    if args.enable:
        patch["enabled"] = True
    if args.disable:
        patch["enabled"] = False
    if args.channel:
        patch["channel"] = args.channel
    if args.source is not None:
        patch["manifest_url"] = args.source

    saved: dict[str, Any] = {}
    if patch:
        try:
            saved = config.set_updates(patch)
        except ValueError as exc:
            return _refuse(
                args,
                "Update settings were not saved",
                str(exc),
                "--channel takes stable or beta; --source takes a full http(s) URL "
                "(an empty value clears it).",
            )
        except OSError as exc:
            return _refuse(
                args,
                "Update settings were not saved",
                f"{type(exc).__name__}: {exc}",
                f"Check that {paths.CONFIG_FILE.parent} is writable, then retry.",
            )
        if "enabled" in patch:
            _say(args, "Update checks are on." if patch["enabled"] else "Update checks are off.")
        if "channel" in patch:
            _say(args, f"Update channel set to {saved.get('channel', args.channel)}.")
        if "manifest_url" in patch:
            shown = saved.get("manifest_url") or "(build default)"
            _say(args, f"Update source saved: {shown}")

    freed = 0
    if args.cleanup:
        try:
            freed = updates.cleanup(keep=2)
        except OSError as exc:
            return _refuse(
                args,
                "Old update files could not be cleaned up",
                f"{type(exc).__name__}: {exc}",
                f"Close other Sweep windows, check {updates.updates_dir()}, then retry.",
            )
        _say(
            args,
            f"Cleaned old update files — freed {util.human_size(freed)}."
            if freed
            else "Nothing to clean up.",
        )

    if args.rollback:
        return _rollback(args)

    if args.skip is not None and args.skip != "":
        return _skip_version(args, args.skip)

    # Only "update" talks to the release server.  A settings-only or cleanup-only
    # invocation stays offline; a bare `sweep update` uses the cached answer when
    # it is still fresh.
    needs_check = bool(
        args.check
        or args.install
        or args.dry_run
        or args.skip == ""
        or not (patch or args.cleanup or args.rollback or args.skip is not None)
    )
    if needs_check:
        force = bool(
            args.check or args.force or args.install or args.dry_run or args.skip == ""
        )
        result = updates.check(force=force)
        if args.force:
            _unskip(result)
        if args.skip == "":
            return _skip_latest(args, result)
        if install_mode:
            return _install(args, result)
        if args.json:
            _emit_json(result.to_dict())
        else:
            _report_result(result, sys.stdout)
        return _STATUS_EXIT.get(result.status, EXIT_ERROR)

    # Settings and/or cleanup only: no network, no check.
    if args.json:
        summary: dict[str, Any] = {"ok": True}
        if patch:
            summary["settings"] = _public_prefs()
        if args.cleanup:
            summary["cleanup"] = {"freed": freed}
        _emit_json(summary)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def add_parser(sub: Any) -> argparse.ArgumentParser:
    """Register ``sweep update`` on the main subparser collection."""
    parser = sub.add_parser(
        "update",
        help="check for, install or roll back a Sweep release",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="ask the server now instead of using the cached answer",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON (the raw check result for checks)",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="download, verify, stage and apply a newer release (needs --yes)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="download and stage, then print what --install would do; never applies "
        "and never needs --yes",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm --install; without it nothing is replaced",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore a saved “not now” and the cached check result",
    )
    parser.add_argument(
        "--channel",
        choices=config.CHANNELS,
        type=str.lower,
        help="save the release channel to follow",
    )
    parser.add_argument(
        "--source",
        metavar="URL",
        help="save the release manifest URL (an empty value clears it)",
    )
    switch = parser.add_mutually_exclusive_group()
    switch.add_argument("--enable", action="store_true", help="turn update checks on")
    switch.add_argument("--disable", action="store_true", help="turn update checks off")
    parser.add_argument(
        "--skip",
        nargs="?",
        const="",
        default=None,
        metavar="VERSION",
        help="remember a version as “not now”; with no value, skip the newest release found",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="delete old downloads and backups (keeps the newest two of each)",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="restore the newest backup made by a previous update",
    )
    parser.set_defaults(func=cmd_update)
    return parser
