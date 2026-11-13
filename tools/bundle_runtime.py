"""Fetch a private, embeddable Python for the portable Sweep release.

A portable release should not ask the person to install Python first. This
module downloads the official *embeddable* CPython distribution from
python.org, checks its SHA-256, and lays it out as::

    <app>/runtime/python.exe
    <app>/runtime/python312.zip
    <app>/runtime/python312._pth   (points at ..\\vendor and ..)

``run.bat`` already looks for ``runtime\\python.exe`` next to itself, so a zip
built with this runtime needs nothing installed: extract, double-click, done.
It also keeps the install a *source* install, which means the normal verified
self-update path works (a frozen .exe cannot replace itself while running).

Only the standard library is used, and the download is cached so repeated
builds do not hit the network.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

# Pinned so a build is reproducible. The hash is python.org's published
# artifact for this exact filename; update both together.
RUNTIME_VERSION = "3.12.10"
RUNTIME_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
RUNTIME_URL = (
    "https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"
)
EMBED_NAME = "python-{version}-embed-amd64.zip"
PTH_TEMPLATE = """python{major}{minor}.zip
.
..\\vendor
..
import site
"""


class RuntimeError_(Exception):
    """A failure the build script can print without a traceback."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(version: str, cache: Path, *, timeout: float = 60.0) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / EMBED_NAME.format(version=version)
    if target.is_file() and _sha256(target) == RUNTIME_SHA256:
        print(f"  runtime        cached {target.name}")
        return target
    url = RUNTIME_URL.format(version=version)
    print(f"  runtime        downloading {url}")
    partial = target.with_suffix(".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Sweep-build"})
        with urllib.request.urlopen(request, timeout=timeout) as response, partial.open(
            "wb"
        ) as handle:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  runtime        {done * 100 // total:3d}%", end="", flush=True)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError_(
            f"could not download the Python runtime: {type(exc).__name__}: {exc}"
        ) from None
    finally:
        print()
    actual = _sha256(partial)
    if actual != RUNTIME_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError_(
            f"runtime checksum mismatch: expected {RUNTIME_SHA256}, got {actual}"
        )
    partial.replace(target)
    return target


def extract(archive: Path, destination: Path, *, version: str) -> Path:
    runtime = destination / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            bad = bundle.testzip()
            if bad:
                raise RuntimeError_(f"the runtime archive is damaged at {bad}")
            bundle.extractall(runtime)
    except zipfile.BadZipFile as exc:
        raise RuntimeError_(f"the runtime archive is not a zip: {exc}") from None
    if not (runtime / "python.exe").is_file():
        raise RuntimeError_("the runtime archive has no python.exe")
    major, minor = version.split(".")[:2]
    (runtime / f"python{major}{minor}._pth").write_text(
        PTH_TEMPLATE.format(major=major, minor=minor), encoding="ascii"
    )
    return runtime


def verify(runtime: Path, app_root: Path) -> str:
    """Run the bundled interpreter against the app's imports."""
    import subprocess

    exe = runtime / "python.exe"
    # The staged runtime is not yet at its final ``<app>/runtime`` home, so the
    # relative ``_pth`` entries cannot resolve during the build. Put the app and
    # vendor folders on sys.path explicitly; the built zip is verified again in
    # its real layout by tools/build_release.py --verify.
    probe = (
        "import sys; "
        "sys.path[:0] = [r'{app}', r'{app}\\vendor']; "
        "import textual, rich, psutil; "
        "from sweep_app import __version__; print(__version__)"
    ).format(app=str(app_root))
    result = subprocess.run(
        [str(exe), "-c", probe],
        cwd=str(app_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError_(
            "the bundled runtime cannot import Sweep: "
            + (result.stderr or result.stdout).strip()
        )
    return (result.stdout or "").strip()


def size_of(runtime: Path) -> int:
    return sum(path.stat().st_size for path in runtime.rglob("*") if path.is_file())


def prepare(
    destination: Path,
    *,
    app_root: Path,
    version: str = RUNTIME_VERSION,
    cache: Path | None = None,
    force: bool = False,
    do_verify: bool = True,
) -> Path:
    """Create ``destination/runtime`` and return it."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    cache = Path(cache or app_root / ".build-cache")
    archive = download(version, cache)
    runtime = extract(archive, destination, version=version)
    if do_verify:
        found = verify(runtime, app_root)
        if found != _app_version(app_root):
            raise RuntimeError_(
                f"the runtime loaded Sweep {found}, expected {_app_version(app_root)}"
            )
    print(
        f"  runtime        {runtime} "
        f"({size_of(runtime) / (1024 * 1024):.1f} MB, Python {version})"
    )
    return runtime


def _app_version(app_root: Path) -> str:
    import re

    text = (app_root / "sweep_app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)", text)
    return match.group(1) if match else "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bundle an embeddable Python for Sweep")
    parser.add_argument("--dest", required=True, help="folder that will receive runtime/")
    parser.add_argument("--app-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--version", default=RUNTIME_VERSION)
    parser.add_argument("--cache", help="download cache (default: <app>/.build-cache)")
    parser.add_argument("--force", action="store_true", help="re-extract even if present")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args(argv)
    app_root = Path(args.app_root).resolve()
    try:
        runtime = prepare(
            Path(args.dest),
            app_root=app_root,
            version=args.version,
            cache=Path(args.cache) if args.cache else None,
            force=args.force,
            do_verify=not args.no_verify,
        )
    except RuntimeError_ as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"runtime ready: {runtime}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
