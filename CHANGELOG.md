# Changelog

All notable changes to Sweep are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
`MAJOR.MINOR.PATCH` versions with `-beta.N` / `-rc.N` prereleases.

## 1.1.1 — 2026-11-13

### Changed

- **Updates are on for every copy.** A source checkout, an older zip, or any
  build without a baked `_build_info.py` now falls back to the official release
  feed instead of reporting "No update source is configured". The only opt-out
  is the existing **Check for updates automatically** setting, so a missing
  address can no longer leave a user without updates.

## 1.1.0 — 2026-11-13

### Added

- **Update checker.** One HTTPS `GET` for a small JSON manifest, at launch and
  at most every six hours (configurable 0–720 hours), with the answer cached in
  `config.json`. Can be turned off completely; Sweep then makes no outbound
  request. `stable` and `beta` channels; a release can be skipped ("Skip this
  version") without being promoted again.
- **Verified install.** The release zip is downloaded over HTTPS, checked
  against the manifest's size and SHA-256, extracted with path traversal and
  symlink entries refused, and checked again against its own `__version__`
  before anything is replaced. A release without a checksum is refused.
- **Backup, overlay and rollback.** A detached helper waits for Sweep to exit,
  copies every file it will replace into
  `%LOCALAPPDATA%\Sweep\updates\backup-<old-version>-<stamp>`, overlays the
  staged files, removes stale modules and `__pycache__`, writes
  `update-status.json`, and restarts Sweep. Any failure restores the backup and
  starts the old version. Manual rollback via `update --rollback` or
  `sweep_app\updater.py --restore <folder>`.
- **Update UI.** Settings → Updates in the web interface (check, download,
  install with typed confirmation, skip, channel, on/off, cleanup of old
  downloads and backups) and in the terminal console (`s`, plus `u` for a
  check). Every failure keeps the what/reason/hint shape used elsewhere in
  Sweep.
- **`sweep update` command.** `--check`, `--install --yes`, `--dry-run`,
  `--rollback`, `--skip`, `--cleanup`, `--channel`, `--source`,
  `--enable`/`--disable` and `--json`, with exit code `10` for "an update is
  available" so a script can branch without parsing text.
- **One settings store.** `sweep_app/config.py` owns `config.json` for both
  interfaces: atomic writes, validation before save, and unknown keys preserved
  so an older build cannot erase a newer setting.
- **Portable release tooling.** `tools/build_release.py` builds
  `Sweep-<version>.zip` and `latest.json` together, injects the manifest URL
  into the shipped copy only, refuses to overwrite a version without `--force`,
  and `--verify` extracts the result and runs it. Launchers now also look for a
  runtime in `python\`, `runtime\` or `vendor\python\` next to the app, and
  `sweep.cmd` provides a `sweep` command shim.
- **Project metadata.** `pyproject.toml` with the `sweep` console script,
  Python 3.10+ requirement, package data for the web assets and theme, and the
  version read from `sweep_app/__init__.py`.
- **Tests.** `tests/test_updates.py` covers version comparison, manifest
  parsing, the throttled check, checksum and archive failures, staging, the
  apply plan, backup/overlay/restore, and the state shape, all against temporary
  folders.
- **Documentation.** `docs/INSTALL.md` (portable install, permissions, USB,
  OneDrive, SmartScreen, uninstall), `docs/UPDATES.md` (user guide, rollback,
  troubleshooting), `docs/RELEASING.md` (maintainer runbook and manifest
  schema), and a README section on what the update check sends.

### Changed

- README no longer claims Sweep makes no network calls. The accurate claim is
  that the update manifest is the only optional outbound request, it is one
  `GET`, it carries no identifiers, and it can be turned off. The local-only
  security properties (127.0.0.1 bind, per-session token, Origin/Host checks,
  CSP, no CDN, no telemetry) are unchanged.
- Install instructions are written for a non-technical Windows user: extract
  anywhere, double-click a launcher, no installer and no Administrator rights.
- The version now has a single source of truth (`sweep_app/__init__.py`);
  release notes come from `CHANGELOG.md`, and `latest.json` is generated from
  the zip it describes instead of being maintained by hand.

### Fixed

- Both interfaces previously wrote `config.json` independently; the last writer
  won. Settings now go through one validated, atomic store.
- The update helper removes `__pycache__` and modules the new release dropped,
  so an upgrade cannot leave stale bytecode or a deleted module importable.

## 1.0.0 — 2026-11-12

### Added

- Initial release: a Windows cleanup console with a Textual terminal interface
  and a local web interface over the same engine.
- **Junk files:** 18 categories (user and Windows temp, Prefetch, Windows Update
  cache, Delivery Optimization, `Windows.old`, crash dumps, WER, thumbnails,
  WinINet, browser and GPU shader caches, Windows logs, developer caches,
  installer patches, `ProgramData` package cache, Recycle Bin), each measured
  before anything is touched, with risky categories never pre-selected.
- **Processes:** classification into active, tray, service, Windows and idle,
  with idle-only termination and explicit refusals for anything with a window,
  a service, a Windows image, or a kept ancestor.
- **Leftovers:** orphan-folder detection built from the Uninstall registry
  hives, Program Files names, Start Menu shortcuts and executable metadata, with
  a three-week age floor.
- **Program remover:** search every fixed drive for a name, with opt-in registry
  keys and services, all backed up before removal.
- **Quarantine:** removals are moves into a per-volume holding area with a JSON
  manifest; restore puts every file back, purge is typed-confirmation only.
- **Safety model:** hard refusals for drive roots, system folders, user data
  folders and credential stores; category-scoped deletes; typed confirmation for
  permanent and large operations; everything logged under
  `%LOCALAPPDATA%\Sweep\logs`.
- **Local web interface:** `127.0.0.1` bind, per-session token, Origin/Host
  validation, strict CSP, no external assets, responsive layout, background jobs
  with progress and cancellation, and errors with what/reason/hint.
- **CLI:** `scan`, `clean`, `procs`, `leftovers`, `search`, `quarantine`, `web`
  and `tui`.
