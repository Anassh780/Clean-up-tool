# Sweep tests

Run everything from the `sweep` folder:

```powershell
$py = 'C:\Users\IRON MAN\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD;$PWD\vendor"
& $py -m unittest discover -s tests -v
```

PowerShell may print a `NativeCommandError` banner while unittest still reports
`OK`; judge the run by the final `OK` / `FAILED` line and the exit code.

## Files

| File | Covers |
| --- | --- |
| `test_updates.py` | Core engine: versions, config, manifest parsing, check, download, stage, apply plan, helper, state. Treated as the verified baseline. |
| `test_web_update.py` | Real in-process web server: `/api/update` shape, check available/up-to-date/HTTP 404, settings validation, token/origin rejection, download job staging, apply refusals. |
| `test_cli_update.py` | `sweep update` via `cli.main`: `--version`, unconfigured `--json`, bad `--source`, local `--check` (exit 10), `--disable`/`--enable`, `--skip`. |
| `test_updater_rollback.py` | A simulated disk failure in the middle of the overlay: the old tree is restored and `update-status.json` records `rolled_back`. |
| `update_support.py` | Shared helpers (not collected as tests): temporary home, loopback HTTP server, fake release zip. |

## Hermetic design

- `update_support.temp_home()` redirects `paths.SWEEP_HOME`, `QUARANTINE`,
  `LOGS`, `CONFIG_FILE` and `UPDATES` into a `TemporaryDirectory`, points
  `LOCALAPPDATA` at it (the standalone updater reads that itself), removes
  `SWEEP_UPDATE_URL`, and swaps `updates.DEFAULT_MANIFEST_URL` for the
  source-checkout placeholder. The developer's real settings are never read.
- Manifest and archive hosts are `http.server` instances on `127.0.0.1:0`;
  no test reaches the internet.
- `test_web_update` points `updates.app_root` at a fake install tree so
  `state()` / `writable_install()` never probe the checkout. It also disables
  the one-shot startup check, whose daemon thread could outlive the temporary
  folder.
- Every server, file handler and environment value is restored in
  `addCleanup` / `tearDown`, and temporary folders are removed.
