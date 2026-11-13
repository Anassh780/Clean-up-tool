"""Build the portable Sweep release zip and the update manifest it advertises.

One command produces two files that belong together:

``dist/Sweep-<version>.zip``
    A folder ``Sweep-<version>/`` with ``main.py``, ``sweep_app/``, the
    launchers, the docs, (unless ``--no-vendor``) ``vendor/`` and (unless
    ``--no-runtime``) a private ``runtime/`` Python. A generated
    ``sweep_app/_build_info.py`` is written **into the zip only**, so a shipped
    copy knows where its update manifest lives without changing the checkout.

``dist/latest.json``
    Exactly the schema :func:`sweep_app.updates.parse_release` accepts, with the
    real size and SHA-256 of the zip above. This is the file the app fetches.

The builder is deliberately strict: it refuses to overwrite an existing zip
without ``--force``, and ``--verify`` extracts the result to a temporary folder
and runs ``main.py --version`` there. When the zip carries ``runtime/`` it uses
that interpreter with no ``PYTHONPATH``, which proves the release needs nothing
installed. That catches the two mistakes that break portable releases: a missing
asset and a version stamp that does not match the manifest.

Run from the repository root:

    python tools/build_release.py --verify
    python tools/build_release.py --manifest-url https://github.com/me/sweep/releases/latest/download/latest.json --verify
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bundle_runtime  # noqa: E402 - sibling tool, imported after sys.path
DEFAULT_GITHUB = "https://github.com/OWNER/REPO"
PLACEHOLDER = "OWNER/REPO"
MANIFEST_NAME = "latest.json"
SCHEMA = 1
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # fixed for reproducible archives
EXCLUDED_DIRS = {"__pycache__", ".git", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db", "_build_info.py"}

VERSION_RE = re.compile(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)


class BuildError(Exception):
    """A release cannot be built or verified; the message says what to fix."""


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def read_version(root: Path = ROOT) -> str:
    """Read the single source of truth: ``sweep_app/__init__.py``."""
    init_file = root / "sweep_app" / "__init__.py"
    try:
        text = init_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(
            f"Cannot read {init_file}: {exc}. Run this script from a full Sweep checkout."
        ) from None
    match = VERSION_RE.search(text)
    if not match:
        raise BuildError(
            f"{init_file} does not define __version__ = \"x.y.z\". "
            "Add the version stamp before building a release."
        )
    return match.group(1)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "bytes" else f"{int(value)} bytes"
        value /= 1024
    return f"{size} bytes"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _github_base() -> str:
    """Use the Actions repository when present, otherwise the placeholder."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and "/" in repo and not repo.startswith("/"):
        return f"https://github.com/{repo}"
    return DEFAULT_GITHUB


def release_url(version: str, filename: str, base_url: str | None) -> str:
    """Where the zip will live once it is uploaded."""
    if base_url:
        base = base_url.strip()
        if "{version}" in base or "{filename}" in base:
            return base.format(version=version, filename=filename)
        return base.rstrip("/") + "/" + filename
    return f"{_github_base()}/releases/download/v{version}/{filename}"


def default_manifest_url(explicit: str | None) -> str:
    """Explicit flag, then the environment, then the documented placeholder."""
    if explicit:
        return explicit.strip()
    env = os.environ.get("SWEEP_MANIFEST_URL", "").strip()
    if env:
        return env
    return f"{DEFAULT_GITHUB}/releases/latest/download/{MANIFEST_NAME}"


# --------------------------------------------------------------------------- #
# file collection
# --------------------------------------------------------------------------- #
def _tree_files(base: Path, prefix: str) -> Iterable[tuple[Path, str]]:
    """Every real file under *base*, with a zip-relative path under *prefix*."""
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES or path.name in EXCLUDED_NAMES:
            continue
        yield path, f"{prefix}/{rel.as_posix()}"


def collect_files(include_vendor: bool = True) -> list[tuple[Path, str]]:
    """The exact payload of a portable release, sorted by destination name."""
    required = ["main.py", "README.md", "run.bat", "Sweep Web.bat", "sweep.cmd"]
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise BuildError(
            "The checkout is missing release files: " + ", ".join(missing) + ". "
            "Restore them before building; a release without a launcher is not usable."
        )

    files: list[tuple[Path, str]] = []
    for name in required:
        files.append((ROOT / name, name))

    docs = ROOT / "docs"
    if docs.is_dir():
        for path in sorted(docs.glob("*.md")):
            if path.is_file():
                files.append((path, f"docs/{path.name}"))

    app = ROOT / "sweep_app"
    if not (app / "__init__.py").is_file():
        raise BuildError(f"{app} is missing __init__.py; this is not the Sweep package.")
    files.extend(_tree_files(app, "sweep_app"))

    if include_vendor:
        vendor = ROOT / "vendor"
        if not vendor.is_dir():
            raise BuildError(
                f"{vendor} is missing. Use --no-vendor to build a zip that needs "
                "pip-installed dependencies, or restore the vendored libraries."
            )
        files.extend(_tree_files(vendor, "vendor"))

    # Stable order makes the zip reproducible and the diff of two builds sane.
    files.sort(key=lambda pair: pair[1])
    return files


def build_info_text(manifest_url: str, version: str, channel: str) -> str:
    """The generated module that gives a shipped copy its update address."""
    return (
        '"""Build stamp written by tools/build_release.py - do not edit.\n'
        "\n"
        "This file is generated inside the release zip, not in the source tree.\n"
        '"""\n'
        "from __future__ import annotations\n"
        "\n"
        f"MANIFEST_URL = {json.dumps(manifest_url)}\n"
        f"BUILD_VERSION = {json.dumps(version)}\n"
        f"BUILD_CHANNEL = {json.dumps(channel)}\n"
    )


# --------------------------------------------------------------------------- #
# zip
# --------------------------------------------------------------------------- #
def _write_member(archive: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def write_zip(
    zip_path: Path,
    version: str,
    files: list[tuple[Path, str]],
    build_info: str,
    force: bool,
) -> int:
    """Write the archive atomically. Returns the number of entries."""
    if zip_path.exists() and not force:
        raise BuildError(
            f"{zip_path} already exists. Bump the version, delete the old zip, "
            "or pass --force to replace it."
        )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = zip_path.with_name(zip_path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    top = f"Sweep-{version}"
    count = 0
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for source, rel in files:
                _write_member(archive, f"{top}/{rel}", source.read_bytes())
                count += 1
            _write_member(
                archive, f"{top}/sweep_app/_build_info.py", build_info.encode("utf-8")
            )
            count += 1
        temporary.replace(zip_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise BuildError(f"Could not write {zip_path}: {exc}") from None
    return count


# --------------------------------------------------------------------------- #
# notes
# --------------------------------------------------------------------------- #
def section_for_version(text: str, version: str) -> str:
    """Pull the ``## 1.1.0`` section out of a changelog, if it is there."""
    lines = text.splitlines()
    heading_re = re.compile(
        rf"^\s*#{{1,4}}\s*(?:\[)?\s*v?{re.escape(version)}(?:\])?(?:\s|$)",
        re.IGNORECASE,
    )
    start = next((i for i, line in enumerate(lines) if heading_re.match(line)), None)
    if start is None:
        return ""
    match = re.match(r"^(#+)\s", lines[start])
    level = len(match.group(1)) if match else 2
    end = len(lines)
    for index in range(start + 1, len(lines)):
        next_heading = re.match(r"^(#+)\s", lines[index])
        if next_heading and len(next_heading.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def read_notes(path: Path, version: str) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BuildError(
            f"Cannot read the notes file {path}: {exc}. "
            "Pass an existing file to --notes-file, or omit the flag."
        ) from None
    section = section_for_version(text, version)
    return (section or text).strip()


# --------------------------------------------------------------------------- #
# verification
# --------------------------------------------------------------------------- #
def _read_stamp(root: Path) -> dict[str, str]:
    stamp = root / "sweep_app" / "_build_info.py"
    if not stamp.is_file():
        raise BuildError(
            f"The archive has no {stamp.relative_to(root)}. "
            "It was probably built by hand instead of tools/build_release.py."
        )
    try:
        tree = ast.parse(stamp.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise BuildError(f"Cannot parse the injected build stamp: {exc}") from None
    values: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
    return values


def verify_zip(zip_path: Path, version: str, manifest_url: str) -> None:
    """Extract to a temp folder and prove the app starts and reports its version."""
    print(f"\nVerifying {zip_path} ...")
    with tempfile.TemporaryDirectory(prefix="sweep-verify-") as temporary:
        folder = Path(temporary)
        try:
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(folder)
        except (OSError, zipfile.BadZipFile) as exc:
            raise BuildError(f"The archive cannot be extracted: {exc}") from None

        roots = [p for p in folder.iterdir() if p.is_dir()]
        root = roots[0] if len(roots) == 1 else folder / f"Sweep-{version}"
        if not (root / "main.py").is_file():
            raise BuildError(
                f"The archive does not contain main.py at {root.name}/main.py."
            )

        stamp = _read_stamp(root)
        if stamp.get("MANIFEST_URL") != manifest_url:
            raise BuildError(
                "The injected MANIFEST_URL does not match the build: "
                f"expected {manifest_url!r}, found {stamp.get('MANIFEST_URL')!r}."
            )
        if stamp.get("BUILD_VERSION") != version:
            raise BuildError(
                "The injected BUILD_VERSION does not match the package version: "
                f"expected {version!r}, found {stamp.get('BUILD_VERSION')!r}."
            )
        print(f"  build stamp  MANIFEST_URL={stamp['MANIFEST_URL']}")
        print(f"  build stamp  BUILD_VERSION={stamp['BUILD_VERSION']}")

        env = os.environ.copy()
        path_parts = [str(root)]
        vendor = root / "vendor"
        if vendor.is_dir():
            path_parts.append(str(vendor))
        if env.get("PYTHONPATH"):
            path_parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(path_parts)
        env["PYTHONIOENCODING"] = "utf-8"

        # A universal release carries its own interpreter. Test *that* one, with
        # the checkout's Python off sys.path, or a missing runtime ships silently.
        interpreter = sys.executable
        bundled = root / "runtime" / "python.exe"
        if bundled.is_file():
            interpreter = str(bundled)
            env.pop("PYTHONPATH", None)
            print(f"  bundled runtime {bundled}")
        else:
            print("  runtime        no bundled interpreter (system Python needed)")

        # A file can be present and still not be imported (wrong package on
        # sys.path, a shadowing checkout, a typo in the module). Ask the
        # extracted app what it actually resolved.
        try:
            runtime = subprocess.run(
                [
                    interpreter,
                    "-c",
                    "from sweep_app import updates; print(updates.DEFAULT_MANIFEST_URL)",
                ],
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BuildError(f"Could not query the extracted app's build stamp: {exc}") from None
        active_url = (runtime.stdout or "").strip()
        if runtime.returncode != 0:
            detail = (runtime.stderr or runtime.stdout or "").strip()
            raise BuildError(
                f"The extracted app could not import its build stamp: {detail or 'no output'}"
            )
        if active_url != manifest_url:
            raise BuildError(
                "The extracted app resolved a different update URL: "
                f"expected {manifest_url!r}, got {active_url!r}. The stamp is present "
                "but not the package being imported."
            )
        print(f"  runtime stamp  {active_url}")

        try:
            result = subprocess.run(
                [interpreter, "main.py", "--version"],
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BuildError(f"Could not start the extracted app: {exc}") from None

        output = (result.stdout or "").strip()
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise BuildError(
                f"The extracted app exited {result.returncode}: {detail or 'no output'}. "
                "Check that the payload and vendor folder are complete."
            )
        expected = f"Sweep {version}"
        if output != expected:
            raise BuildError(
                f"The extracted app printed {output!r}, expected {expected!r}."
            )
        print(f"  extracted app  {output}")
    print("  OK - the zip runs and carries the right version and manifest URL.")


# --------------------------------------------------------------------------- #
# manifest + summary
# --------------------------------------------------------------------------- #
def write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def print_summary(
    *,
    version: str,
    channel: str,
    zip_path: Path,
    size: int,
    sha256: str,
    manifest_path: Path,
    manifest_url: str,
    release_url_value: str,
    notes: str,
    file_count: int,
    vendor: bool,
    runtime: bool,
) -> None:
    print(f"\nSweep {version} ({channel})")
    print(f"  zip        {zip_path}")
    print(f"  size       {size:,} bytes ({human_size(size)})")
    print(f"  sha256     {sha256}")
    print(f"  manifest   {manifest_path}")
    print(f"  download   {release_url_value}")
    print(f"  update URL {manifest_url}")
    print(f"  files      {file_count} entries, vendor {'bundled' if vendor else 'NOT bundled'}")
    print(
        "  runtime    "
        + (
            f"bundled Python {bundle_runtime.RUNTIME_VERSION} (nothing to install)"
            if runtime
            else "NOT bundled (needs Python 3.10+)"
        )
    )
    print(f"  notes      {len(notes)} characters")
    placeholders = []
    if PLACEHOLDER in manifest_url:
        placeholders.append("manifest URL")
    if PLACEHOLDER in release_url_value:
        placeholders.append("download URL")
    if placeholders:
        print(
            f"\nWARNING: the {' and '.join(placeholders)} still contain the "
            "OWNER/REPO placeholder.\n"
            "         Shipped copies will report 'unconfigured' (and the download\n"
            "         link will 404) until you rebuild with --manifest-url /\n"
            "         --base-url, or set SWEEP_MANIFEST_URL."
        )
    print("\nUpload both files to the release:")
    print(f"  1. Create the GitHub release tagged v{version}.")
    print(f"  2. Attach {zip_path.name} and {manifest_path.name}.")
    print("  3. Mark that release as \"Latest\" (or pre-release for a beta), so the")
    print(f"     app's manifest URL resolves: {manifest_url}")
    print("\n  GitHub CLI:")
    print(
        f'    gh release create v{version} "{zip_path}" "{manifest_path}" '
        f'--title "Sweep {version}"'
    )
    if channel == "beta":
        print("    (tick \"Set as a pre-release\"; stable-channel copies ignore it)")
    print("\nKeep the zip and latest.json together: the manifest's sha256 and size")
    print("describe this exact zip, and the app refuses a download that does not match.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_release.py",
        description="Build dist/Sweep-<version>.zip and dist/latest.json.",
    )
    parser.add_argument(
        "--notes-file",
        metavar="PATH",
        help="release notes; a CHANGELOG.md section for this version is preferred",
    )
    parser.add_argument(
        "--channel", choices=("stable", "beta"), default="stable", help="release channel"
    )
    parser.add_argument("--homepage", help="project homepage written to the manifest")
    parser.add_argument(
        "--out", metavar="DIR", default="dist", help="output folder (default: dist)"
    )
    parser.add_argument(
        "--no-vendor", action="store_true", help="do not ship the vendored libraries"
    )
    parser.add_argument(
        "--no-runtime",
        action="store_true",
        help="do not bundle the private Python runtime; the zip then needs Python 3.10+",
    )
    parser.add_argument(
        "--runtime-version",
        default=bundle_runtime.RUNTIME_VERSION,
        help=f"embeddable CPython to bundle (default: {bundle_runtime.RUNTIME_VERSION})",
    )
    parser.add_argument(
        "--manifest-url",
        help="URL baked into the build and advertised in the summary "
        "(default: $SWEEP_MANIFEST_URL, then the GitHub placeholder)",
    )
    parser.add_argument(
        "--base-url",
        help="where the zip will be hosted; the asset URL is base/Sweep-<version>.zip "
        "unless the value contains {version} or {filename}",
    )
    parser.add_argument(
        "--min-version",
        default="1.0.0",
        help="minimum compatible version written to the manifest (default: 1.0.0)",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing zip at the same version"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="extract the result and run 'python main.py --version' in a temp folder",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    try:
        version = read_version()
        manifest_url = default_manifest_url(args.manifest_url)
        homepage = args.homepage or _github_base()
        out_dir = Path(args.out)
        if not out_dir.is_absolute():
            out_dir = (ROOT / out_dir).resolve()
        zip_path = out_dir / f"Sweep-{version}.zip"
        manifest_path = out_dir / MANIFEST_NAME
        filename = zip_path.name
        url = release_url(version, filename, args.base_url)

        notes = (
            read_notes(Path(args.notes_file), version)
            if args.notes_file
            else f"Sweep {version}"
        )
        if not notes:
            notes = f"Sweep {version}"

        files = collect_files(include_vendor=not args.no_vendor)
        runtime_staging: Path | None = None
        if not args.no_runtime:
            runtime_staging = Path(tempfile.mkdtemp(prefix="sweep-runtime-"))
            try:
                runtime_dir = bundle_runtime.prepare(
                    runtime_staging, app_root=ROOT, version=args.runtime_version
                )
            except bundle_runtime.RuntimeError_ as exc:
                shutil.rmtree(runtime_staging, ignore_errors=True)
                raise BuildError(
                    f"The Python runtime could not be bundled: {exc}. "
                    "Use --no-runtime to build a zip that needs Python installed."
                ) from None
            files.extend(_tree_files(runtime_dir, "runtime"))
            files.sort(key=lambda pair: pair[1])
        stamp = build_info_text(manifest_url, version, args.channel)
        try:
            count = write_zip(zip_path, version, files, stamp, force=args.force)
        finally:
            # The zip now owns the bytes; the staging copy is no longer needed.
            if runtime_staging is not None:
                shutil.rmtree(runtime_staging, ignore_errors=True)
        size = zip_path.stat().st_size
        sha256 = sha256_file(zip_path)

        released = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        manifest = {
            "schema": SCHEMA,
            "name": "Sweep",
            "version": version,
            "channel": args.channel,
            "released": released,
            "notes": notes,
            "url": url,
            "size": size,
            "sha256": sha256,
            "min_version": args.min_version,
            "homepage": homepage,
        }
        write_manifest(manifest_path, manifest)

        print_summary(
            version=version,
            channel=args.channel,
            zip_path=zip_path,
            size=size,
            sha256=sha256,
            manifest_path=manifest_path,
            manifest_url=manifest_url,
            release_url_value=url,
            notes=notes,
            file_count=count,
            vendor=not args.no_vendor,
            runtime=not args.no_runtime,
        )

        if args.verify:
            verify_zip(zip_path, version, manifest_url)
        return 0
    except BuildError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"\nERROR: {exc}. Check that the output folder is writable and that "
            "the zip is not open in another program.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
