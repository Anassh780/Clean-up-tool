# Releasing Sweep

This is the maintainer runbook: how to cut a version, build the portable zip and
its update manifest, publish them, and take a bad release back down. For the
user-facing side of updates, see [UPDATES.md](UPDATES.md).

## What a release is

Two files that belong together:

| File | Purpose |
| --- | --- |
| `dist/Sweep-<version>.zip` | the portable app: `Sweep-<version>/` with `main.py`, `sweep_app/`, the launchers, `README.md`, `docs/*.md`, `vendor/`, `runtime/` (a private Python 3.12), and a generated `sweep_app/_build_info.py` |
| `dist/latest.json` | the manifest the app fetches: version, download URL, size, SHA-256, notes, channel |

The zip's `_build_info.py` is written **into the archive only**. It carries the
manifest URL, so a fork or a beta channel can point its build at a different
feed without changing code. Builds without that stamp -- a source checkout, an
older zip, anything still carrying `OWNER/REPO` -- fall back to the official
feed in `sweep_app/updates.py`, so every copy can check for updates with no
setup.

`tools/build_release.py` produces both, and `--verify` proves the result runs.

### The bundled runtime

By default the builder downloads the official embeddable CPython 3.12 from
python.org (SHA-256 pinned in `tools/bundle_runtime.py`), caches it in
`.build-cache/`, and adds it to the zip as `runtime/`. That is what makes a
release usable by someone who has never installed Python, and it keeps the
install a *source* install, so the verified self-update path still works. The
download is about 11 MB and is cached between builds. `--verify` runs the
extracted zip with `runtime\python.exe` and no `PYTHONPATH`, so a missing or
broken runtime fails the build instead of shipping. Pass `--no-runtime` only
for a slim, developer-only zip.

## 1. Bump the version

`__version__` in `sweep_app/__init__.py` is the single source of truth.
`pyproject.toml` reads it dynamically, and the build tool parses it, so there is
only one line to change:

```python
__version__ = "1.2.0"
```

Use `MAJOR.MINOR.PATCH` for a stable release and `X.Y.Z-beta.N` / `X.Y.Z-rc.N`
for a prerelease. The comparator treats a prerelease as older than its final
release, so `1.2.0-beta.2 < 1.2.0`.

## 2. Add the changelog entry

Add a `## 1.2.0` section at the top of [CHANGELOG.md](../CHANGELOG.md). Keep the
heading exactly the version, because `--notes-file CHANGELOG.md` extracts that
section for the manifest and the GitHub release body.

```markdown
## 1.2.0

### Added

- ...
```

If you prefer a separate file, pass any markdown file; the tool takes the
matching version section when it finds one and otherwise uses the whole file.

## 3. Run the tests

From the repository root:

```powershell
$py = "py"   # or a full path to python.exe
& $py -m unittest discover -s tests -v
```

The update suite is `tests/test_updates.py`. It covers version comparison,
manifest parsing, the throttled check, checksum failures, archive safety,
staging, the apply plan, the helper's backup/overlay/restore, and the state
shape. It never touches the real install or the real `%LOCALAPPDATA%`.

A smoke run from the checkout is also worth it (and `--verify` runs the built
artifact itself):

```powershell
& $py main.py --version
& $py main.py update --check
```

## 4. Build

Run from the repository root. The minimal build:

```powershell
& $py tools\build_release.py --verify
```

A realistic release build, with the real manifest URL, the URL the asset will
live at, and notes taken from the changelog:

```powershell
& $py tools\build_release.py `
    --manifest-url "https://github.com/OWNER/REPO/releases/latest/download/latest.json" `
    --base-url "https://github.com/OWNER/REPO/releases/download/v1.2.0" `
    --notes-file CHANGELOG.md `
    --channel stable `
    --verify
```

Replace `OWNER/REPO` with the actual repository. Flags that matter:

| Flag | Effect |
| --- | --- |
| `--manifest-url URL` | bakes the update address into `_build_info.py` and prints it; without it the tool uses `$SWEEP_MANIFEST_URL`, then the `OWNER/REPO` placeholder |
| `--base-url URL` | where the zip will be hosted. The asset URL is `base/Sweep-<version>.zip`; `{version}` and `{filename}` placeholders are supported |
| `--notes-file PATH` | release notes; a `## <version>` section is extracted when present |
| `--channel stable\|beta` | written to the manifest and the build stamp |
| `--min-version X.Y.Z` | written to the manifest (default `1.0.0`); recorded, not yet enforced by the app |
| `--homepage URL` | written to the manifest; defaults to the GitHub repository |
| `--out DIR` | output folder (default `dist`) |
| `--no-vendor` | build a zip that relies on installed dependencies (for testing only; the portable release needs `vendor/`) |
| `--no-runtime` | omit the private Python runtime (developer-only zip; needs Python 3.10+) |
| `--runtime-version X.Y.Z` | bundle a different embeddable CPython (default: the pinned 3.12.10) |
| `--force` | replace an existing zip at the same version |
| `--verify` | extract the zip to a temp folder and run `python main.py --version` there |

Without `--base-url`, the download URL is
`https://github.com/<repo>/releases/download/v<version>/Sweep-<version>.zip`,
which is correct for a normal GitHub release.

The build is strict on purpose:

- it refuses to overwrite an existing zip without `--force`;
- it refuses to build without `main.py`, `README.md`, the three launchers and
  `sweep_app/__init__.py`;
- `--verify` fails if the archive's version stamp or manifest URL disagrees with
  the build.

The zip is reproducible: entries are sorted and carry a fixed timestamp, and
notes/release time live only in `latest.json`. The same source with the same
flags produces the same SHA-256.

The workflow publishes the portable zip and manifest only. The optional
standalone `Sweep.exe` build is separate:

```powershell
py -m PyInstaller --noconfirm --clean Sweep.spec
```

It lands in `dist\Sweep\` and needs no Python, but a frozen build cannot replace
itself, so its users upgrade by replacing the folder by hand. Do not advertise
it as the self-updating download.

## 5. Publish

Commit the version bump and changelog, then tag and push:

```powershell
git add sweep_app/__init__.py CHANGELOG.md
git commit -m "Release 1.2.0"
git tag v1.2.0
git push origin main
git push origin v1.2.0
```

The release workflow (`.github/workflows/release.yml`) runs on a `v*` tag, and
can also be started by hand with a channel choice. It:

1. checks out the tag and sets up Python 3.12;
2. runs the unit tests;
3. reads `__version__`, derives the channel (`beta` when the version contains a
   `-`, otherwise `stable`), and refuses a tag that does not match the version;
4. calls `tools/build_release.py` with
   `--manifest-url https://github.com/<repo>/releases/latest/download/latest.json`,
   `--homepage`, `--channel`, `--notes-file CHANGELOG.md` and `--verify`; the
   download URL defaults to the matching
   `releases/download/v<version>/Sweep-<version>.zip`;
5. publishes a GitHub release for the tag with `Sweep-<version>.zip` and
   `latest.json` attached, using the manifest's notes as the release body;
6. marks the release as a pre-release when the channel is `beta`.

Because step 4 always bakes `releases/latest/download/latest.json`, a beta tag
published this way is marked pre-release and therefore **not** reachable at
that URL. See [Beta releases](#beta-releases) before shipping a beta.

You can do the same by hand with the GitHub CLI, which is what the build tool
prints at the end:

```powershell
gh release create v1.2.0 "dist\Sweep-1.2.0.zip" "dist\latest.json" `
    --title "Sweep 1.2.0" --notes-file CHANGELOG.md
```

Attach **both** files to the **same** release. The manifest's `sha256` and
`size` describe that exact zip; splitting them across releases makes every
download fail verification.

## 6. Verify the published manifest

Wait for the asset upload to finish, then fetch the URL the app will use:

```powershell
Invoke-WebRequest `
  "https://github.com/OWNER/REPO/releases/latest/download/latest.json" `
  -UseBasicParsing | Select-Object -ExpandProperty Content
```

Check that:

- `version` is the version you just tagged;
- `url` downloads the zip (open it in a browser);
- `sha256` matches `Get-FileHash dist\Sweep-1.2.0.zip -Algorithm SHA256`;
- `channel` is what you intended;
- `notes` is not empty.

`releases/latest` follows GitHub's "Latest release" marker, which **excludes
pre-releases**. A pre-release published alone will not appear there — see
[Beta releases](#beta-releases).

## 7. Test the upgrade path

Never trust a release you have not upgraded to. The cheapest realistic test
uses a local HTTP server, which the app allows even over plain `http://` when
the host is localhost:

```powershell
# 1. Keep a copy of the previous release extracted somewhere writable.
# 2. Build the new version with LOCAL urls into a THROWAWAY folder, then serve it:
py tools\build_release.py `
    --out dist-test `
    --manifest-url "http://127.0.0.1:8000/latest.json" `
    --base-url "http://127.0.0.1:8000" `
    --notes-file CHANGELOG.md `
    --force
py -m http.server 8000 --directory dist-test

# 3. Point the OLD copy at that manifest and start it from its own folder:
$env:SWEEP_UPDATE_URL = "http://127.0.0.1:8000/latest.json"
py main.py
```

Then:

1. **Settings → Updates → Check now** — the new version must be offered.
2. Install it: web **Download & install** (type `update` to confirm), TUI
   **Install update**, or `py main.py update --install --yes`.
3. Sweep closes, the helper runs, Sweep restarts on the new version.
4. Confirm `py main.py --version` prints the new version.
5. Confirm `%LOCALAPPDATA%\Sweep\updates\backup-<old>-<stamp>\manifest.json`
   exists and `updates\update-status.json` has `"ok": true`.
6. Roll back once (`py main.py update --rollback`), start Sweep again, confirm
   the old version, then update again.
7. Check that quarantine, logs and settings survived both directions.

Also test the unhappy path once: corrupt the manifest's `sha256` in a local copy
and confirm the app refuses the download with "did not match its checksum"
instead of installing it.

## 8. Beta releases

The app's channel is a filter over one manifest: a release whose `channel` is
`beta` is ignored by stable copies and offered to beta copies. There are two
workable ways to publish one.

**A. Fixed beta manifest (recommended).** Keep a long-lived GitHub release
tagged `beta` that holds only `latest.json` — its asset URL never changes —
and attach the zip to the version's own release. Replace the `beta` release's
`latest.json` each time, and build with:

```powershell
& $py tools\build_release.py `
    --manifest-url "https://github.com/OWNER/REPO/releases/download/beta/latest.json" `
    --base-url "https://github.com/OWNER/REPO/releases/download/v1.2.0-beta.1" `
    --channel beta `
    --notes-file CHANGELOG.md `
    --verify
```

Publish the version itself as a pre-release (so it stays out of `latest`), with
the zip attached. Beta users are opted in once, in **Settings → Updates →
Release channel → Beta** (or by using a beta build).

**B. Single manifest.** Publish the beta as a normal (not pre-release) release
whose manifest says `"channel": "beta"`. Stable copies see "A beta is
available, but this copy follows the stable channel" and do not install it;
beta copies do. This is simpler but makes the stable `latest.json` temporarily
advertise a beta, and it removes the previous stable from `releases/latest`.

Do not mark the only beta manifest as a GitHub pre-release *and* rely on
`releases/latest` — that URL will keep resolving to the last stable release.

The shipped release workflow implements only the simple path: it always bakes
`releases/latest/download/latest.json` and marks a `-beta`/`-rc` tag as a
pre-release, so a beta built by the workflow is not reachable at that URL. For a
fixed beta manifest, build locally with `--manifest-url` and attach the result
to the beta release, or extend the workflow with a manifest-URL input. If you
need betas delivered through the default URL, use option B and accept that
stable copies will see the "a beta is available" note.

## 9. Yanking a bad release

The app never downgrades: it offers a release only when the manifest version is
newer than the installed one. That shapes the options.

| Situation | What to do |
| --- | --- |
| Bad release, not yet widely installed | Publish a fixed, **higher** version. This is always the cleanest yank. |
| Bad release, want to stop new installs | Mark the GitHub release as a pre-release (removes it from `releases/latest`), or repoint `latest.json` to the previous stable version. Copies already on the bad version will see "up to date" and stay there until a higher version appears. |
| Bad release already installed | Tell users to roll back with `py main.py update --rollback` (or the helper's `--restore`), or to extract the previous release zip over the folder, then publish the fix as a higher version. |
| Broken asset (wrong zip, bad checksum) | Do not silently replace a different zip under the same version: the manifest and zip must match. Rebuild with the same version and `--force`, re-upload both files, and bump the version if anything about the code changed. |
| Compromised or malicious asset | Delete the release and its assets, publish a higher version, and say so publicly. Installed copies are not affected until they update again. |

Avoid deleting a tag that users may already have. The tag is also the download
path in the manifest (`releases/download/v<version>/...`), so deleting it breaks
the update for anyone still on the previous version.

## Manifest JSON schema

`latest.json` is one JSON object. This is what `tools/build_release.py` writes:

```json
{
  "schema": 1,
  "name": "Sweep",
  "version": "1.2.0",
  "channel": "stable",
  "released": "2026-11-13T12:00:00Z",
  "notes": "## 1.2.0\n\n### Added\n\n- ...",
  "url": "https://github.com/OWNER/REPO/releases/download/v1.2.0/Sweep-1.2.0.zip",
  "size": 8123456,
  "sha256": "9f2c...64 hex characters...",
  "min_version": "1.0.0",
  "homepage": "https://github.com/OWNER/REPO"
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `version` | yes | release version, with or without a leading `v`; must match `__version__` inside the zip |
| `url` | yes | direct HTTPS URL of the release zip (localhost `http://` is allowed for testing) |
| `sha256` | yes for install | 64 hex characters. `download()` refuses a release without it; `"sha256:<hex>"` is also accepted |
| `size` | no | expected byte count; when present it is checked before the digest |
| `notes` | no | release notes shown in the interface; truncated at 12,000 characters |
| `channel` | no | `stable` (default) or `beta`; a beta entry is ignored by stable copies |
| `released` | no | ISO timestamp, informational |
| `min_version` | no | minimum compatible version. **Recorded, not enforced** by the 1.1.0 checker; treat it as documentation for now |
| `homepage` | no | project page, informational |
| `schema` / `name` | no | ignored by the parser; useful to humans |
| `source` | no | filled in by the app with the URL it fetched |

Aliases accepted by the parser: `tag` for `version`, `download_url` for `url`,
`changelog` for `notes`, `date` for `released`.

A GitHub release API payload (`/repos/OWNER/REPO/releases/latest`) also works:
`tag_name` supplies the version, the first `.zip` asset supplies the URL and
size, an asset digest of the form `sha256:<hex>` supplies the checksum, and
`prerelease: true` maps to the beta channel. GitHub's payload has no checksum
unless the asset carries a digest, and `download()` refuses an unverified
release — prefer publishing `latest.json`.

Limits enforced by the app: manifest at most 1 MB, archive at most 512 MB,
HTTPS required (except localhost), and no query string is added. The manifest
request sends `User-Agent: Sweep/<version> (+local update check)`,
`Accept: application/json` and `Cache-Control: no-cache`; the download sends the
same `User-Agent` and `Accept: application/zip, application/octet-stream`.

## Release checklist

- [ ] `__version__` bumped, and the same version appears in `CHANGELOG.md`
- [ ] tests pass (`py -m unittest discover -s tests -v`)
- [ ] `py tools\build_release.py ... --verify` succeeds
- [ ] `latest.json` `sha256` and `size` match the zip
- [ ] zip and `latest.json` attached to the same release
- [ ] `releases/latest/download/latest.json` returns the new version
- [ ] upgrade from the previous version tested, including one rollback
- [ ] for a beta: `--channel beta` and the beta manifest URL are correct
- [ ] release notes in the manifest are readable and mention anything that
      needs a manual step
