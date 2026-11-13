# Installing Sweep

Sweep is a portable Windows app. "Portable" here means what it says:

- no installer and no "Next → Next → Finish";
- no Administrator rights needed;
- no service, no startup entry, no registry entry, nothing in **Add or remove
  programs**;
- uninstalling is deleting a folder.

You download a zip, extract it, and double-click one of the two launchers. There
are three shapes of build, and the difference matters for updates:

| Build | Python needed? | Updates itself? |
| --- | --- | --- |
| Portable zip with the bundled runtime | No | Yes |
| Portable zip without the runtime (source-style) | Yes, Python 3.10+ | Yes |
| Standalone `Sweep.exe` folder | No | No — replace it by hand |

The zip that can update itself is the recommended one. A bundled zip contains a
`runtime\` folder next to `main.py` (a private Python 3.12, about 13 MB
compressed); `run.bat` and `Sweep Web.bat` find it automatically. If the release
page only offers the source-style zip and you do not have Python, install Python
3.10+ once from python.org (tick "Add python.exe to PATH"); Sweep needs nothing
else.

## What you need

| | |
| --- | --- |
| Windows | Windows 10 or Windows 11, 64-bit. |
| Disk | Room for the Sweep folder, plus whatever you quarantine. Quarantined files stay on the drive they came from until you purge them. |
| Permissions | A normal user account. Administrator is optional and only unlocks extra cleanup categories. |
| Python | Not needed when the release ships its bundled runtime or a standalone `Sweep.exe` build. The source-style zip and a source checkout need Python 3.10 or newer. |
| Screen | Anything from a 1366×768 laptop upward. Smaller works too: the web interface collapses to one column, and the terminal console is happy in a normal terminal window. |
| Network | Only for the optional update check. Sweep is fully usable offline. |

## Install from a release zip

1. **Download** `Sweep-<version>.zip` from the project's Releases page.
2. **Extract it.** Right-click the zip → **Extract All…**, and choose a folder
   you can write to. Good choices:
   - `C:\Users\<you>\Documents\Sweep`
   - `D:\Tools\Sweep`
   - a USB drive, for a copy you carry between PCs
   - a OneDrive folder, if you want it on several PCs

   Do not run Sweep from inside the zip. Windows mounts a zip read-only, so
   settings, updates and quarantine would fail in confusing ways.
3. **Start it.** Open the extracted folder and double-click:
   - **`Sweep Web.bat`** — the web interface. It starts a local server, prints
     the address, and opens `http://127.0.0.1:8765` in your browser.
   - **`run.bat`** — the terminal console, for keyboard-driven work.

   If the release includes its bundled runtime, the launchers ask you to install
   nothing (a standalone `Sweep.exe` needs no Python either). If you see "Sweep
   needs Python 3.10 or newer", you have the source-style zip — see
   [Running from source](#running-from-source), or download the release that
   bundles the runtime.
4. **Optional:** right-click `Sweep Web.bat` → **Send to → Desktop (create
   shortcut)**. The shortcut still points into the folder, so keep the folder
   where it is (or update the shortcut if you move it).

That is the whole install. The first time Sweep saves a setting, writes a log or
quarantines a file, it creates `%LOCALAPPDATA%\Sweep\` for settings, logs,
quarantine and updates.

### A note on Program Files

Do not extract Sweep into `C:\Program Files` or `C:\Program Files (x86)` unless
you always run it as administrator. A standard user cannot write there, so Sweep
cannot replace its own files and the update is refused. Any folder under your
user profile avoids the problem entirely.

## Where your data lives

The app folder and your data are deliberately separate:

| Path | Contents |
| --- | --- |
| the folder you extracted | the program: `main.py`, `sweep_app\`, `vendor\`, launchers |
| `%LOCALAPPDATA%\Sweep\config.json` | settings, including update preferences |
| `%LOCALAPPDATA%\Sweep\quarantine\` | restorable batches and their manifests |
| `%LOCALAPPDATA%\Sweep\logs\` | activity logs and update helper logs |
| `%LOCALAPPDATA%\Sweep\updates\` | downloaded releases, staging, backups, `update-status.json` |

This has two consequences worth knowing:

- **Moving or replacing the app folder keeps your data.** Extract the new zip
  and copy its contents over the old folder (or extract into a new folder); your
  settings and quarantine are still there.
- **A USB copy does not carry your data.** Quarantine has to sit on the same
  volume as the files it removes, so it is always per-PC, per-user. The USB stick
  carries the program, not the history.

## Permissions

Sweep runs as a standard user. That is enough for the user-level categories:
user temp, browser caches, thumbnails, crash dumps, the Recycle Bin, process
cleanup, leftovers and the program remover.

Some categories touch `C:\Windows` or `C:\ProgramData` and need elevation:
Windows temp, Prefetch, the Windows Update cache, Delivery Optimization,
`Windows.old`, Windows logs, and the `ProgramData` package cache. Sweep labels
them `needs admin` and explains the refusal instead of pretending to clean them.

To unlock them, right-click `Sweep Web.bat` (or `run.bat`) → **Run as
administrator**. Everything else is identical; there is no separate admin mode
to configure. Sweep never asks for elevation by itself.

## Laptops and small screens

- **1366×768** is the common small-laptop size and is fully supported. The web
  interface switches to a single column, cards instead of tables, and
  bottom-sheet dialogs; the terminal console uses the space it is given.
- On a 1280×720 or smaller display, browser zoom (Ctrl + `-`) still works
  because the layout is fluid, not fixed-width.
- For the terminal console, use **Windows Terminal** and a font with box-drawing
  and block glyphs (Cascadia Mono, Consolas, JetBrains Mono). Sweep respects
  `NO_COLOR`.
- The web interface is the better choice on a touch screen or a high-DPI
  display: every control is reachable by Tab, and the page honours
  `prefers-reduced-motion`.

## USB drives

Sweep works from a USB stick, which makes it a useful repair kit for a PC that
is low on space or has no Python.

- Use a normal writable stick (NTFS or exFAT is fine). If the stick has a
  physical write-protect switch, turn it off — otherwise updates are refused
  with "Sweep cannot replace its own files".
- Updates download to `%LOCALAPPDATA%` on the PC, not to the stick, and are then
  copied onto the stick. The stick needs free space for the new files during the
  swap; the backup itself stays on the PC.
- Quarantine still lives on the PC's own drive. Removing the stick does not
  remove quarantined files, and restoring them later needs the stick only to run
  Sweep.

## OneDrive and synced folders

Sweep runs from a OneDrive folder, but syncing and updating can race:

- **Pause OneDrive while installing an update.** The helper replaces many files
  in a few seconds; if OneDrive is uploading them at the same time, it can lock a
  file and force a rollback.
- If the folder is set to "Free up space" (online-only files), the first launch
  has to download the program again. Let it finish, or mark the folder "Always
  keep on this device".
- Your data is in `%LOCALAPPDATA%`, which OneDrive does not sync. Two PCs running
  the same synced Sweep folder still have separate settings and quarantine.

If updates in OneDrive fail repeatedly, move the app to a local folder such as
`Documents\Sweep` outside OneDrive. The app works the same; only the sync is
lost.

## Upgrading

**Automatically.** Leave the update check on (the default) and use
**Settings → Updates → Download & install** when a new version is offered. Sweep verifies
the download, backs up the old files, replaces them and restarts. See
[UPDATES.md](UPDATES.md).

**By hand.** Download the new `Sweep-<version>.zip`, extract it, and either:

- copy the new files over the old folder, replacing what it asks about; or
- extract to a new folder and delete the old one.

Either way, `%LOCALAPPDATA%\Sweep` is untouched, so your settings, logs and
quarantine survive. Close Sweep before replacing files by hand.

**If a new version misbehaves,** restore the backup:

```bat
py -3 sweep_app\updater.py --list
py -3 sweep_app\updater.py --restore "<backup folder>" --relaunch
```

Those two commands need Python 3.10+ because the helper is a script. Without
Python, extract the previous release zip and copy its contents over the folder
again. Your data is unaffected.

## Uninstalling

There is no uninstaller because there was no installer. To remove Sweep:

1. **Deal with quarantine first.** Open **Quarantine** and restore or purge what
   you want to keep. Deleting the folder in step 3 destroys anything still in
   quarantine — permanently.
2. **Delete the Sweep folder** you extracted (and any shortcut you made).
3. **Delete `%LOCALAPPDATA%\Sweep`.** That removes settings, logs, update
   downloads and backups. If you might reinstall later, keep it: a new copy will
   pick up your settings and quarantine where they left off.

Nothing else is left behind: no service, no scheduled task, no startup entry, no
registry key, no Add/remove programs entry.

## Windows SmartScreen and unsigned builds

Sweep is not code-signed (a signing certificate costs money and identifies a
publisher). Windows therefore treats a downloaded `Sweep.exe` or a launcher as
"unknown", and SmartScreen may show **"Windows protected your PC"** or a
"Windows cannot verify the publisher" prompt. This is expected for an unsigned
portable app; it is not a sign that the file is malicious.

If you trust the source:

1. Click **More info** (the small link in the dialog).
2. Click **Run anyway**.

To avoid the prompt entirely, remove the Mark-of-the-Web from the zip before
extracting it:

```powershell
Unblock-File .\Sweep-1.1.0.zip
```

`Unblock-File` tells Windows you vetted the file. It is the same trust decision
as **Run anyway**, made once for the zip instead of once per extracted file.

If you want to verify the download before running it, compare its SHA-256 with
the value published with the release:

```powershell
Get-FileHash .\Sweep-1.1.0.zip -Algorithm SHA256
```

The manifest published with the release carries the same digest. If they differ,
do not run it. If your organisation forbids unsigned binaries, build Sweep from
source — see below.

## Running from source

Use this if you want to read or change the code, or if you cannot run an
unsigned build. Python 3.10+ is required; the bundled dependencies in `vendor\`
mean there is nothing to `pip install` for normal use.

```bat
py -3 main.py
```

`run.bat` finds `py -3`, `python` or `python3`, then a runtime bundled next to
the app (`python\`, `runtime\` or `vendor\python\`), and prints a clear message
if none is usable. Set `SWEEP_PYTHON` to a full interpreter path to force a
specific one. The web interface is:

```bat
py -3 main.py web
```

Every copy checks the official release feed by default, including a source
checkout, so **Settings → Updates** works with no setup. To point a fork or a
test build somewhere else, set `updates.manifest_url` in `config.json`, use the
`SWEEP_UPDATE_URL` environment variable, or paste the URL into Settings. The
opt-out is the **Check for updates automatically** toggle (or
`updates.enabled = false`); a missing address is never treated as an opt-out.

## Installation troubleshooting

| What you see | What it means | What to do |
| --- | --- | --- |
| "Sweep needs Python 3.10 or newer" | You are running the source-style zip or a checkout, not a build with the bundled runtime. | Install Python 3.10+ from python.org and tick "Add python.exe to PATH", or download the release that bundles the runtime. |
| The browser does not open | The server may have failed to start, or the default browser is blocked. | Open `http://127.0.0.1:8765` yourself. If the port is busy, run `Sweep Web.bat --port 9000` (or `py -3 main.py web --port 9000` from a checkout). |
| "Port 8765 is already in use" | Another copy of Sweep, or another app, owns the port. | Close the other copy, or pass `--port` with a free port. |
| Antivirus quarantines `Sweep.exe` | Unsigned binaries and packers are common false positives. | Restore it and add an exclusion, or run from source. Do not disable antivirus globally. |
| Console text looks like boxes or question marks | The terminal font lacks box-drawing glyphs, or the code page is wrong. | Use Windows Terminal with Cascadia Mono/Consolas; the launchers set UTF-8 with `chcp 65001`. |
| Files can't be deleted, "in use by another process" | The owning app has them open. | Close that app and rescan. Sweep reports each locked file with its reason instead of failing silently. |
| Sweep cannot save settings or update itself | The folder is read-only for your user, typically `Program Files` or a write-protected USB stick. | Move the folder under your user profile (or unlock the stick). Categories that need Administrator are separate and labelled `needs admin`. |

## See also

- [UPDATES.md](UPDATES.md) — the update checker, channels, rollback and logs.
- [RELEASING.md](RELEASING.md) — building and publishing a release.
- [../README.md](../README.md) — what Sweep does and how it classifies files.
