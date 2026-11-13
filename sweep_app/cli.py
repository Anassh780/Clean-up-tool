"""Headless entry points (``sweep scan``, ``sweep procs``, …).

The TUI is the main event, but a scriptable mode is handy for automation and
for verifying the engine without a terminal.
"""
from __future__ import annotations

import argparse
import sys
import threading

from . import __version__, admin, appfiles, cli_update, junk, leftovers, procs, safety, util


def _banner(text: str) -> None:
    print(f"\n\033[1;36m{text}\033[0m")
    print("\033[2m" + "─" * min(78, max(20, len(text))) + "\033[0m")


def cmd_web(args: argparse.Namespace) -> int:
    from .web.server import serve

    return serve(port=args.port, open_browser=not args.no_browser, host=args.host)


def cmd_scan(args: argparse.Namespace) -> int:
    _banner("Junk scan")
    total_size = 0
    total_files = 0
    results = junk.scan_all(
        on_result=lambda scan: print(
            f"  {junk.CATEGORY_MAP[scan.key].title:<34} "
            f"{util.human_size(scan.size):>10}  {scan.files:>7,} files  "
            f"{'[' + scan.status + ']' if scan.status != 'ok' else ''}"
        )
    )
    for scan in results.values():
        total_size += scan.size
        total_files += scan.files
    print(f"\n  Reclaimable: {util.human_size(total_size)} across {total_files:,} files")
    if not admin.is_admin():
        print("  \033[33mNote: some categories need Administrator to delete.\033[0m")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    if args.categories:
        keys = [k.strip() for k in args.categories.split(",") if k.strip()]
        unknown = [k for k in keys if k not in junk.CATEGORY_MAP]
        if unknown:
            print(f"Unknown categories: {', '.join(unknown)}")
            return 2
        categories = [junk.CATEGORY_MAP[k] for k in keys]
    else:
        categories = [c for c in junk.CATEGORIES if c.default]

    mode = "permanent" if args.permanent else "quarantine"
    print(f"Mode: {mode}")
    for category in categories:
        print(f"  · {category.title} ({category.risk})")

    if not args.yes:
        print("\nNothing deleted. Re-run with --yes to execute.")
        return 1

    deleter = safety.Deleter(mode=mode, note="cli clean")
    cancel = threading.Event()
    done = 0
    for category in categories:
        if category.kind == "recycle":
            ok, message = safety.empty_recycle_bin()
            print(f"  {category.title}: {message}")
            continue
        roots, items = category.spec()
        if not roots:
            continue
        print(f"  {category.title}: {len(items)} targets", end="", flush=True)
        for item in items:
            deleter.delete(item, allowed_roots=roots, category=category.key, cancel=cancel)
            done += 1
            if done % 100 == 0:
                print(".", end="", flush=True)
        print(" done")
    stats = deleter.finish()
    print(
        f"\n  Freed {util.human_size(stats.bytes)} — "
        f"{stats.moved} quarantined, {stats.deleted} deleted, "
        f"{stats.failed} locked/skipped"
    )
    if stats.failures:
        print(f"  Could not move {len(stats.failures)} file(s):")
        for failure in stats.failures[:20]:
            print(
                f"    - {failure.get('path')} — "
                f"{util.short_reason(failure.get('reason', ''))}"
            )
        if len(stats.failures) > 20:
            print(f"    … and {len(stats.failures) - 20} more (see the log)")
    elif stats.errors:
        print("  First problems:")
        for error in stats.errors:
            print(f"    - {error}")
    if mode == "quarantine" and stats.moved:
        print(f"  Restore with: sweep quarantine --restore {deleter.batch_id}")
    return 0


def cmd_procs(args: argparse.Namespace) -> int:
    _banner("Processes")
    infos = procs.collect()
    counts = procs.summary(infos)
    for group in ("active", "tray", "idle", "service", "system", "locked"):
        if counts.get(group):
            print(f"  {procs.STATE_LABELS[group]:<8} {counts[group]:>4}")
    print()
    print(f"  {'PID':>7}  {'STATE':<8} {'RAM':>8}  {'NAME':<32} REASON")
    for info in infos:
        if args.idle_only and info.group != "idle":
            continue
        print(
            f"  {info.pid:>7}  {info.state:<8} {util.human_size(info.rss):>8}  "
            f"{util.truncate(info.name, 32):<32} {info.reason}"
        )
    idle = [p for p in infos if p.group == "idle"]
    print(f"\n  {len(idle)} idle processes could be terminated.")
    if args.kill_idle:
        if not args.yes:
            print("  Re-run with --yes to actually terminate them.")
            return 1
        results = procs.kill_processes(idle, progress=lambda i, n, name: print(f"    killing {name}"))
        ok = sum(1 for r in results if r.ok)
        print(f"  Terminated {ok}/{len(results)}")
    return 0


def cmd_leftovers(args: argparse.Namespace) -> int:
    _banner("Uninstall leftovers")
    index = leftovers.build_index()
    print(f"  Indexed {index.size:,} installed names / {len(index.name_words):,} words")
    orphans = leftovers.scan_orphans(progress=lambda msg, frac: None, index=index)
    if not orphans:
        print("  No orphan folders found.")
        return 0
    total = 0
    for orphan in orphans:
        total += orphan.size
        print(
            f"  {orphan.confidence:<7} {util.human_size(orphan.size):>9}  "
            f"{orphan.root_label:<18} {util.truncate(orphan.path, 64)}"
        )
    print(f"\n  {len(orphans)} candidates, {util.human_size(total)} total")
    print("  Review them in the TUI before removing anything.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    _banner(f"Search: {args.name}")
    outcome = appfiles.search_files(args.name)
    print(f"  Scanned {outcome.scanned:,} folders in {outcome.elapsed:.1f}s")
    for hit in outcome.hits:
        print(
            f"  {hit.kind_label:<8} {util.human_size(hit.size):>9}  "
            f"{util.truncate(hit.path, 90)}"
        )
    if args.registry:
        for hit in appfiles.registry_hits(args.name):
            print(f"  Registry {util.truncate(hit.name, 40):<40} {hit.path}")
    if args.services:
        for hit in appfiles.service_hits(args.name):
            print(f"  Service  {util.truncate(hit.name, 40):<40} {hit.path} ({hit.extra})")
    print(f"\n  {len(outcome.hits)} file hits")
    return 0


def cmd_quarantine(args: argparse.Namespace) -> int:
    if args.restore:
        restored, failed = safety.restore_batch(args.restore)
        print(f"Restored {restored}, failed {failed}")
        return 0
    if args.purge:
        print("Purged" if safety.purge_batch(args.purge) else "Purge failed")
        return 0
    if args.purge_all:
        ok, bad = safety.purge_all()
        print(f"Purged {ok} batches, {bad} failed")
        return 0
    batches = safety.quarantine_batches()
    if not batches:
        print("Quarantine is empty.")
        return 0
    total, items = safety.quarantine_usage()
    _banner(f"Quarantine — {util.human_size(total)} in {items:,} items")
    for batch in batches:
        print(
            f"  {batch['id']:<16} {batch.get('created', '')[:19]:<20} "
            f"{len(batch.get('items', [])):>5} items  {batch.get('note', '')}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sweep",
        description="Sweep — Windows cleanup console. Run without arguments for the TUI.",
    )
    parser.add_argument("--version", action="version", version=f"Sweep {__version__}")
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="measure reclaimable junk")
    scan.set_defaults(func=cmd_scan)

    clean = sub.add_parser("clean", help="remove junk (quarantine by default)")
    clean.add_argument("--categories", help="comma separated category keys")
    clean.add_argument("--permanent", action="store_true", help="delete instead of quarantine")
    clean.add_argument("--yes", action="store_true", help="actually execute")
    clean.set_defaults(func=cmd_clean)

    proc = sub.add_parser("procs", help="list processes and verdicts")
    proc.add_argument("--idle-only", action="store_true")
    proc.add_argument("--kill-idle", action="store_true")
    proc.add_argument("--yes", action="store_true")
    proc.set_defaults(func=cmd_procs)

    left = sub.add_parser("leftovers", help="find orphaned app folders")
    left.set_defaults(func=cmd_leftovers)

    search = sub.add_parser("search", help="find every trace of a program name")
    search.add_argument("name")
    search.add_argument("--registry", action="store_true")
    search.add_argument("--services", action="store_true")
    search.set_defaults(func=cmd_search)

    quar = sub.add_parser("quarantine", help="inspect / restore the holding area")
    quar.add_argument("--restore", metavar="BATCH")
    quar.add_argument("--purge", metavar="BATCH")
    quar.add_argument("--purge-all", action="store_true")
    quar.set_defaults(func=cmd_quarantine)

    # "update" is the only command that touches the network; its flags, report
    # and exit codes live in cli_update so this file stays readable.
    cli_update.add_parser(sub)

    web = sub.add_parser("web", help="serve the local web interface")
    web.add_argument("--port", type=int, default=8765, help="port to try first (default 8765)")
    web.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    web.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    web.set_defaults(func=cmd_web)

    sub.add_parser("tui", help="open the interface")
    return parser


def main(argv: list[str] | None = None) -> int:
    # The launchers already do this, but `cli.main()` is also called directly
    # (tests, embedders); keep box-drawing and arrows safe on a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["tui"]
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "tui"):
        from .ui.app import run

        return run()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
