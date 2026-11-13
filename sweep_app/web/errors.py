"""Structured errors.

Every failure that reaches the browser carries four things:

* ``code``    - a stable machine key the UI can branch on
* ``message`` - one line saying *what* failed
* ``reason``  - the concrete cause (WinError, path, missing field, ...)
* ``hint``    - what the person can do about it

The goal is that nobody ever sees "something went wrong" without a why.
"""
from __future__ import annotations

import errno
import os
from dataclasses import dataclass, field
from typing import Any

# Windows system error codes worth naming explicitly.
WINERROR_REASONS: dict[int, tuple[str, str, str]] = {
    2: (
        "path_missing",
        "The path no longer exists",
        "It was probably removed or renamed after the scan.",
    ),
    3: (
        "path_missing",
        "The folder no longer exists",
        "It was probably removed or renamed after the scan.",
    ),
    5: (
        "permission_denied",
        "Windows denied access to this path",
        "It needs Administrator rights, or another process is holding it. "
        "Run Sweep as administrator, or close the program that owns it.",
    ),
    19: (
        "write_protected",
        "The volume is write-protected",
        "Remove the write protection (or the physical lock on the card) and retry.",
    ),
    21: (
        "device_not_ready",
        "The drive is not ready",
        "Reconnect the drive and rescan.",
    ),
    32: (
        "file_in_use",
        "Another process has this file open",
        "Close the app that is using it (browser, Explorer, antivirus) and retry. "
        "A reboot also releases it.",
    ),
    33: (
        "file_locked",
        "Part of this file is locked by another process",
        "Close the program that is using it and retry.",
    ),
    87: (
        "invalid_path",
        "Windows rejected the path as invalid",
        "The name contains a character Windows does not allow, or the path is malformed.",
    ),
    112: (
        "disk_full",
        "The drive ran out of space",
        "Free some space, then retry. Quarantine needs room for the files it moves.",
    ),
    122: (
        "name_too_long",
        "The path exceeds the Windows length limit",
        "Enable long paths, or move the folder closer to the drive root first.",
    ),
    123: (
        "invalid_name",
        "A file name in this path is invalid",
        "Windows rejected one of the names while walking the folder.",
    ),
    145: (
        "folder_not_empty",
        "The folder still has files inside",
        "Something recreated files while Sweep was deleting. Close the app and retry.",
    ),
    183: (
        "already_exists",
        "A file with the quarantine name already exists",
        "The batch already holds an item with this name; restore or purge it first.",
    ),
    206: (
        "name_too_long",
        "The combined path is too long for Windows",
        "Shorten the folder path and retry.",
    ),
    225: (
        "virus_detected",
        "Antivirus blocked the operation",
        "Windows Defender or another scanner intercepted the file. "
        "Check the protection history, then retry.",
    ),
    1392: (
        "corrupt_file",
        "The file or folder is corrupted",
        "Run ``chkdsk`` on the volume, then retry.",
    ),
    5_000_000: (
        "internal",
        "Windows reported an internal error",
        "Retry; if it persists, check the Sweep log for the exact call.",
    ),
}

ERRNO_REASONS: dict[int, tuple[str, str, str]] = {
    errno.EACCES: (
        "permission_denied",
        "Windows denied access to this path",
        "Run Sweep as administrator, or close the program holding it.",
    ),
    errno.EPERM: (
        "permission_denied",
        "The operation is not permitted",
        "The file may be a system file or marked read-only.",
    ),
    errno.ENOENT: (
        "path_missing",
        "The path no longer exists",
        "It was probably removed or renamed after the scan.",
    ),
    errno.ENOTEMPTY: (
        "folder_not_empty",
        "The folder still has files inside",
        "Something recreated files while Sweep was deleting.",
    ),
    errno.EEXIST: (
        "already_exists",
        "The destination already exists",
        "The quarantine batch already contains an item with this name.",
    ),
    errno.ENOSPC: (
        "disk_full",
        "The drive ran out of space",
        "Free some space, then retry.",
    ),
    errno.EROFS: (
        "write_protected",
        "The volume is read-only",
        "Remove the write protection and retry.",
    ),
    errno.EBUSY: (
        "file_in_use",
        "The file is in use",
        "Close the program that is using it and retry.",
    ),
}


@dataclass
class ApiError(Exception):
    """A failure with a reason the interface can show verbatim."""

    code: str
    message: str
    reason: str
    hint: str = ""
    status: int = 400
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(f"{self.code}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "reason": self.reason,
            "hint": self.hint,
            "details": self.details,
        }


def invalid(field_name: str, message: str, hint: str = "") -> ApiError:
    return ApiError(
        "invalid_request",
        message,
        f"The request field “{field_name}” is missing or invalid.",
        hint or "Reload the page and try again.",
        400,
        {"field": field_name},
    )


def confirmation_required(word: str, why: str) -> ApiError:
    return ApiError(
        "confirmation_required",
        f"Type “{word}” to confirm this action",
        why,
        f"Type the word {word} exactly. Nothing has been changed.",
        400,
        {"word": word},
    )


def operation_busy(active: str) -> ApiError:
    return ApiError(
        "operation_in_progress",
        "Another cleanup is already running",
        f"Sweep runs one destructive operation at a time so two cleanups cannot "
        f"fight over the same files. “{active}” is still running.",
        "Wait for it to finish or cancel it, then retry.",
        409,
    )


def explain_os_error(exc: BaseException, path: str | None = None) -> ApiError:
    """Turn an OSError/PermissionError into a specific, actionable error."""
    winerror = getattr(exc, "winerror", None)
    code = getattr(exc, "errno", None)

    reason_row = WINERROR_REASONS.get(winerror) if winerror else None
    if reason_row is None and code is not None:
        reason_row = ERRNO_REASONS.get(code)
    if reason_row is None:
        if isinstance(exc, PermissionError):
            reason_row = ERRNO_REASONS[errno.EACCES]
        elif isinstance(exc, FileNotFoundError):
            reason_row = ERRNO_REASONS[errno.ENOENT]
        elif isinstance(exc, NotADirectoryError):
            reason_row = ("invalid_path", "That path is not a folder", "Pick a file or a folder that exists.")
        elif isinstance(exc, IsADirectoryError):
            reason_row = ("invalid_path", "That path is a folder, not a file", "Pick a file inside it instead.")

    if reason_row is None:
        return ApiError(
            "os_error",
            "Windows refused the operation",
            f"{type(exc).__name__}: {exc}" + (f" (path: {path})" if path else ""),
            "Check the Sweep log for the full call, then retry.",
            500,
        )

    slug, message, hint = reason_row
    detail = f"{type(exc).__name__}: {exc}"
    if winerror:
        detail += f" [WinError {winerror}]"
    elif code:
        detail += f" [errno {code}]"
    if path:
        detail += f" — {path}"

    status = 403 if slug == "permission_denied" else 409
    return ApiError(slug, message, detail, hint, status)


def explain(exc: BaseException) -> ApiError:
    """Map any exception to the structured error shape."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, OSError):
        return explain_os_error(exc)
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return ApiError(
            "invalid_request",
            "Sweep could not understand that request",
            f"{type(exc).__name__}: {exc}",
            "Reload the page and try again. If you used the API directly, check the "
            "field types in the request body.",
            400,
        )
    return ApiError(
        "internal",
        "An unexpected error stopped the operation",
        f"{type(exc).__name__}: {exc}",
        "The full traceback is in the server console and in "
        "%LOCALAPPDATA%\\Sweep\\logs\\web.log. Retry, and if it repeats, that log "
        "has the exact failing call.",
        500,
    )


def describe_path_error(path: str, exc: BaseException) -> dict[str, Any]:
    """Compact per-item failure entry used by cleanup reports."""
    error = explain_os_error(exc, path)
    return {
        "path": path,
        "code": error.code,
        "reason": error.reason,
        "hint": error.hint,
    }


def validate_under(path: str, roots: list[str], field_name: str = "path") -> None:
    """Refuse a path that is not inside one of the roots we handed out."""
    target = os.path.normcase(os.path.abspath(path))
    for root in roots:
        base = os.path.normcase(os.path.abspath(root))
        if target == base or target.startswith(base + os.sep):
            return
    raise ApiError(
        "path_not_allowed",
        "That path is not part of this scan",
        f"{path} is not inside any folder Sweep listed for this action, so it was "
        "refused. Sweep only deletes paths it produced itself.",
        "Rescan and pick an item from the list.",
        400,
        {"field": field_name, "path": path},
    )
