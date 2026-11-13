# Updating Sweep

Sweep is portable, so its updates are portable too: no installer, no
Administrator prompt, no Python to install, no package manager. A release is a zip of
files, and updating means downloading it, checking it, and swapping the files
while your quarantine, logs and settings stay exactly where they are.

This page is for the person using Sweep. If you are the one cutting the release,
see [RELEASING.md](RELEASING.md).

## The short version

- Sweep asks for the latest release when it starts, at most once every six
  hours.
- When a newer version exists, **Settings → Updates** shows its version and
  notes, with **Download & install** (or **Download only**, if you want to
  install later).
- Sweep downloads the zip, verifies its SHA-256, backs up every file it is about
  to replace, and restarts itself.
- If any step fails, it puts the old files back automatically.
- You can turn the check off. Sweep then makes no outbound request at all and
  works completely offline.

## How the check works

On launch, Sweep reads one small JSON file — the release manifest — from the
address configured for this build. It remembers the answer and the time in
`%LOCALAPPDATA%\Sweep\config.json`, and will not ask again for six hours by
default. That interval is a preference: set it anywhere from 0 to 720 hours
(0 means "ask on every launch"), or turn the check off.

The result is one of these:

| Status | What it means |
| --- | --- |
| `available` | A newer release exists. **Install** is offered. |
| `up_to_date` | The published version is not newer than this copy. |
| `disabled` | "Check for updates" is off in Settings. No request was made. |
| `unconfigured` | This copy has no manifest address (common in a source checkout). No request was made. |
| `skipped` | A newer release exists, but you chose **Skip this version**. It stops being promoted; the next release is offered normally. |
| `error` | The check could not finish. The message says what failed, why, and what to try. |

A launch inside the six-hour window shows the remembered answer — the result is
marked `cached` — without touching the network. The **Check again** button and
`update --check` ignore the interval, but they do not override a disabled check.

## Checking now

**Web interface** — open **Settings → Updates**. The card shows your version,
the install type, the last check time and the last answer, plus the release
channel and the update-source URL.

- **Check now** / **Check again** asks immediately.
- When a release is offered: **Download & install** does the whole thing,
  **Download only** verifies and stages it (the later **Install update** button
  uses it), **Later** dismisses the card for this page load, and **Skip this
  version** stops that version being offered again.
- **Clean up downloads** removes old downloaded zips and old backups, keeping
  the newest two of each.

Installing asks you to type `update` to confirm, because it replaces the
program's own files and briefly closes the app.

**Terminal console** — press `s` to open Settings and use the **Updates** block:
**Check now**, **Install update**, **Skip version**, **Turn checks off**. On the
main screen, `u` starts a check. The install confirmation shows the version,
size, and the fact that the download is checksum-verified and the old files are
backed up; **Install update** then downloads, verifies and installs in one
step.

**Command line** — from the Sweep folder:

```bat
py -3 main.py update                    :: report the status, using a fresh cached answer
py -3 main.py update --check            :: force a request to the manifest
py -3 main.py update --install --dry-run :: download, verify and stage, then stop
py -3 main.py update --install --yes    :: download, verify and install
```

`update --check` prints the same status, version and hint the interfaces show.
If a `sweep` command is on your PATH (`sweep.cmd` ships in the release folder),
`sweep update --check` is the same thing.

Other flags:

| Flag | Effect |
| --- | --- |
| `--json` | print the raw check result (or the action's result) as JSON on stdout; prose goes to stderr |
| `--force` | ignore the cached check and a saved "skip this version" for this run |
| `--rollback` | restore the newest backup; see [Rolling back](#rolling-back) |
| `--skip [VERSION]` | save "not now" for a version (with no value, the newest one found) |
| `--cleanup` | delete old downloads and backups, keeping the newest two of each |
| `--enable` / `--disable` | turn update checks on or off |
| `--channel stable\|beta` | save the channel |
| `--source URL` | save the manifest URL (an empty value clears the saved URL) |

`--install` requires `--yes`; it never prompts, it refuses. That is deliberate:
a command that can replace the program's files should be explicit. Without
`--install` the command only reports and exits.

Exit codes: `0` success/up to date/checks off/unconfigured/skipped, `10` a newer
release is available (check only), `2` the check failed or an action was
refused, `130` interrupted.

## Channels

| Channel | What you get |
| --- | --- |
| **stable** (default) | Only final releases. A manifest entry marked `beta` is ignored with a note that it exists. |
| **beta** | Final releases **and** prereleases (`1.2.0-beta.1`, `1.2.0-rc.1`, …). |

The channel is a filter, not a different server: both channels read the same
manifest. Prereleases sort before the matching final release, so
`1.2.0-beta.2` is offered to beta users and then superseded by `1.2.0`.

Change it in **Settings → Updates → Release channel**, or in `config.json`:

```json
{
  "updates": {
    "channel": "beta"
  }
}
```

## What "Install" does, step by step

Sweep never rewrites itself while it is running. It prepares the update, exits,
and lets a small standalone helper do the swap.

1. **Resolve the release.** Sweep uses the release from the last check, or asks
   the manifest again if it has no usable offer. The browser or console cannot
   name an arbitrary URL or file on disk: only a release the manifest offered
   can be downloaded. In the web interface you type `update` to confirm; in the
   terminal console you confirm the version and size.
2. **Download.** The release zip goes to
   `%LOCALAPPDATA%\Sweep\updates\v<version>\Sweep-<version>.zip`. Bytes are
   written to a `.part` file, so a cancelled or interrupted download never looks
   complete. A download you already have with the right checksum is reused.
3. **Verify.** If the manifest declares a size, it must match. The SHA-256 of the
   file must match the manifest's `sha256` exactly. A release without a checksum
   is refused: an update is code that will run on your PC.
4. **Stage.** The zip is extracted to `...\v<version>\staged`, after a CRC test.
   Entries that are absolute paths, contain `..`, name a drive, or are symlinks
   are refused. The result must contain `main.py` and `sweep_app\__init__.py`,
   and its `__version__` must equal the version the manifest promised.
   If you chose **Download only**, the update waits here: **Install update**
   picks up the staged folder and continues at step 5.
5. **Plan.** Sweep writes `apply-<timestamp>.json` under
   `%LOCALAPPDATA%\Sweep\updates\` with the staged folder, the install folder,
   the backup folder and the command that should start Sweep again.
6. **Exit.** The helper `sweep_app\updater.py` is started detached. Sweep closes;
   the helper waits up to three minutes for the old process to go away. If it
   does not, the helper stops without touching the app files (it records the
   failure in `update-status.json`).
7. **Back up.** Every file that will be overwritten is copied to
   `backup-<old-version>-<timestamp>\`, and a `manifest.json` records what was
   backed up and what was newly created. Python modules the new release drops
   are moved to `backup-<...>\removed\`.
8. **Overlay.** The staged files are copied over the install folder. Python
   modules the new release no longer ships are moved to
   `backup-<...>\removed\`, and every `__pycache__` is deleted so no stale
   bytecode survives.
9. **Record and restart.** `update-status.json` is written, and Sweep starts
   again: the web interface with the same folder, arguments and port; the
   terminal console as before; a CLI install opens the terminal console.

Your quarantine, logs, settings and backups are outside the install folder, so
none of them is touched. An update changes the app, not your data.

## Rolling back

### Automatic

If anything fails between the backup and the end of the overlay — a locked file,
a full disk, a permission problem — the helper restores every backed-up file,
deletes the files the new release had just created, puts removed modules back,
clears `__pycache__`, writes `update-status.json` with `"rolled_back": true`, and
starts the old version. A failed update is supposed to look like it never
happened.

### By hand

Close Sweep first. The helper is a plain Python script, so this needs a Python
3.10+ interpreter (in a release that does not include one, extract the previous
release zip over the folder instead — see
[INSTALL.md](INSTALL.md#upgrading)). List the backups:

```bat
py -3 sweep_app\updater.py --list
```

Each row gives the folder name, the version it was taken from, the version it
was replaced by, the time, and how many files it holds. Restore one:

```bat
py -3 sweep_app\updater.py --restore "%LOCALAPPDATA%\Sweep\updates\backup-1.1.0-20261113-041500" --relaunch
```

`--app-root` is optional when you run the helper from inside the install folder;
it defaults to the parent of `sweep_app`. `--relaunch` reads the start command
from the backup's `manifest.json` and opens Sweep when the restore is done.

Or, from the app:

```bat
py -3 main.py update --rollback
```

which restores the **newest** backup and prints what it restored. It does not
start Sweep again, so open it normally afterwards. For a specific older backup,
use the helper's `--restore` with that folder.

Restoring copies files back and removes files that only existed in the newer
version. It does not touch your data folder.

Backups are kept until you delete them. Each one is a copy of the files that
were replaced, so they are worth keeping until the new version has proven
itself. **Clean up downloads** (web) or `update --cleanup` keeps the newest two
downloads and the newest two backups and removes the rest; deleting old
`backup-*` folders by hand is also safe. Keep at least the newest one.

## Turning the check off

**Settings → Updates** has a **Check for updates automatically** switch. Turn it
off and Sweep makes no outbound request — not at launch, not from the manual
button. Everything else keeps working; you simply install new versions yourself
from the release page.

Clearing the **Update source** box is not a way to disable checks: an empty
saved URL falls back to `SWEEP_UPDATE_URL` if that is set, then to the manifest
address baked into the build. Use the switch.

The same switch lives in `%LOCALAPPDATA%\Sweep\config.json`:

```json
{
  "updates": {
    "enabled": false
  }
}
```

Edit it while Sweep is closed, and keep the rest of the file intact — Sweep
preserves keys it does not recognise, but hand-editing is easy to get wrong.
The settings interfaces are the safer route.

Setting `check_interval_hours` to `0` does **not** disable the check; it removes
the throttle, so Sweep asks on every launch.

## Files and logs

Everything update-related lives under `%LOCALAPPDATA%\Sweep`:

| Path | Contents |
| --- | --- |
| `updates\v<version>\` | the downloaded zip and its `staged\` extraction |
| `updates\backup-<old-version>-<stamp>\` | files replaced by an update, `removed\` modules, and `manifest.json` |
| `updates\apply-<stamp>.json` | the plan handed to the helper; deleted after a successful update |
| `updates\update-status.json` | the last apply result: `ok`, version, backup path, log path, or the error and whether it rolled back |
| `logs\update-<stamp>.log` | the helper's own log: file counts, failures, traceback, relaunch command |
| `logs\sweep-<date>.log` | the app's normal activity log |
| `config.json` | your update preferences and the last check result |

If an update misbehaves, `update-status.json` and the newest `update-*.log` are
the two files to read. They are plain text and contain paths, versions and
Windows error messages — nothing about you or your files.

## Troubleshooting

| What you see | What it means | What to do |
| --- | --- | --- |
| "No update source is configured" | This copy has no manifest URL. A source checkout still carries the `OWNER/REPO` placeholder, so Sweep refuses to fire a request at a dead address. | Set the address in **Settings → Updates**, in `config.json` under `updates.manifest_url`, or with the `SWEEP_UPDATE_URL` environment variable. Release builds ship with one baked in. |
| "The update server answered HTTP 404" | The manifest is not published at that address, or the release has no `latest.json` asset yet. | Open the URL in a browser. It must be the raw JSON, normally `…/releases/latest/download/latest.json`. Rebuild and upload `latest.json`. |
| "The download did not match its checksum" | The zip was corrupted or replaced in transit, or the manifest's `sha256` is wrong. | Do not install it. Try the download again. If it repeats, compare the file's SHA-256 with the manifest and regenerate the manifest. |
| "Sweep cannot replace its own files" | The install folder is not writable by your user — typically `C:\Program Files`, a read-only USB stick, or a folder owned by another account. | Move the Sweep folder somewhere under your profile (for example `Documents\Sweep`) and update again, or run Sweep as administrator. |
| "This build cannot update itself" | You are running the standalone `Sweep.exe` build. A frozen build cannot safely replace its own running executable and runtime folder. | Download the new release from the release page and replace the old folder by hand. Your quarantine, logs and settings stay in `%LOCALAPPDATA%\Sweep`. |
| "Sweep could not reach the update server" | Offline, DNS failure, firewall, proxy, or a TLS problem. | Sweep works normally offline. Check the connection and any proxy, then **Check again**. If you are behind a proxy that needs credentials, install the update by hand from the release page. |
| An update is offered but **Install** is disabled | `can_apply` is false: the build is a frozen exe, or the install folder failed the write test. | Same fixes as the two rows above. The status card shows the reason. |
| "The update is not a valid zip file" or "does not look like Sweep" | The manifest points at the wrong asset, or the zip is truncated. | The manifest's `url` must be the portable Sweep zip. Rebuild the release with `tools/build_release.py`. |
| Sweep restarts as the old version | The helper failed and rolled back, or it never got to run. | Read `updates\update-status.json` and the newest `logs\update-*.log`. The backup is intact and nothing was lost. |
| Nothing happens after **Install** | Sweep did not exit, so the helper refused to touch files (it waits up to 180 seconds). | Close every Sweep window and try again. Check the helper log for "did not exit within". |

## What goes over the network

Exactly one request, and only when the check is enabled:

```http
GET https://github.com/OWNER/REPO/releases/latest/download/latest.json
User-Agent: Sweep/1.1.0 (+local update check)
Accept: application/json
Cache-Control: no-cache
```

No query string, no cookies, no identifiers. Nothing about you, your PC, your
Windows version, your files, your quarantine or how you use Sweep is sent. The
request says only "Sweep 1.1.0 would like to know what the latest release is".

If you choose to install, a second `GET` fetches the release zip from the URL in
that manifest, with the same User-Agent. That is the only other request Sweep
can make.

- HTTPS is required; plain `http://` is refused (localhost is allowed for
  testing). An update is code that runs on your PC.
- The manifest is capped at 1 MB and the archive at 512 MB, so a wrong URL
  cannot fill your disk.
- There is no telemetry, no analytics, no CDN, no font or asset download, and no
  background service. With updates disabled, Sweep is completely offline.

If you host your own manifest, it must be served over HTTPS and carry a SHA-256
for the zip; see [RELEASING.md](RELEASING.md) for the schema.
