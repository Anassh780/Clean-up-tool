"""Quarantine round-trip check for the web API.

Moves the *user temp* junk category into quarantine, verifies the batch, then
restores it. Refuses to run in permanent-delete mode.

Usage:  python tools/test_web_clean.py [base_url]
"""
from __future__ import annotations

import json

from test_web import BASE, FAILURES, call, check, wait_job


def main() -> int:
    status, payload = call("/api/meta")
    if status != 200:
        print("server is not answering")
        return 1
    if payload["data"]["mode"] != "quarantine":
        print("refusing to run: mode is permanent")
        return 2

    print(f"server: {BASE}")

    status, payload = call("/api/junk/scan", method="POST", body={})
    job = wait_job(payload["data"]["id"], timeout=240)
    check("scan", job.get("status") == "done")
    rows = {row["key"]: row for row in job["result"]["results"]}
    temp = rows.get("user_temp", {})
    before = temp.get("size", 0)
    print(f"  user_temp before: {before:,} bytes in {temp.get('files', 0):,} files")
    check("user_temp has content", before > 0, str(temp)[:200])
    if before <= 0:
        return 1

    status, payload = call("/api/junk/clean", method="POST", body={"keys": ["user_temp"], "permanent": False})
    check("clean accepted", status == 200 and payload["ok"], json.dumps(payload)[:300])
    if status != 200:
        return 1
    job = wait_job(payload["data"]["id"], timeout=300)
    check("clean finished", job.get("status") == "done", json.dumps(job.get("error"))[:300])
    result = job.get("result") or {}
    print(
        f"  moved={result.get('moved')} skipped={result.get('skipped')} "
        f"failed={result.get('failed')} bytes={result.get('bytes'):,} batch={result.get('batch_id')}"
    )
    check("something moved", result.get("moved", 0) > 0)
    check("bytes accounted", result.get("bytes", 0) > 0)
    check("batch created", bool(result.get("batch_id")))
    check("failures explained", all(e.get("reason") for e in result.get("errors", [])))

    batch = result.get("batch_id")
    status, payload = call("/api/quarantine")
    ids = [b["id"] for b in payload["data"]["batches"]]
    check("batch listed", batch in ids, str(ids)[:200])

    status, payload = call("/api/quarantine/restore", method="POST", body={"ids": [batch]})
    check("restore accepted", status == 200 and payload["ok"], json.dumps(payload)[:300])
    job = wait_job(payload["data"]["id"], timeout=300)
    check("restore finished", job.get("status") == "done", json.dumps(job.get("error"))[:300])
    restored = sum(item.get("restored", 0) for item in (job.get("result") or {}).get("results", []))
    print(f"  restored={restored}")
    check("files came back", restored > 0)

    status, payload = call("/api/quarantine")
    ids = [b["id"] for b in payload["data"]["batches"]]
    check("batch retired", batch not in ids, str(ids)[:200])

    status, payload = call("/api/junk")
    check("restore marks junk stale", payload["data"].get("stale") is True, str(payload["data"].get("stale")))

    status, payload = call("/api/junk/scan", method="POST", body={})
    job = wait_job(payload["data"]["id"], timeout=240)
    check("rescan after restore", job.get("status") == "done")

    status, payload = call("/api/junk")
    after = {row["key"]: row for row in payload["data"]["results"]}.get("user_temp", {})
    print(f"  user_temp after: {after.get('size', 0):,} bytes in {after.get('files', 0):,} files")
    check("temp folder has files again", after.get("size", 0) > 0)
    check("stale flag cleared", payload["data"].get("stale") is False)
    check("table still has 18 rows", len(payload["data"]["results"]) == 18, str(len(payload["data"]["results"])))

    print()
    print(f"round-trip complete · failures: {len(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
