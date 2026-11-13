"""End-to-end checks for the local web API.

Usage:  python tools/test_web.py [base_url]

Starts nothing: point it at a running ``main.py web --no-browser`` server.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILURES.append(name)


def raw(path: str, method: str = "GET", body: dict | None = None, token: str = ""):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-Sweep-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def token_from_index() -> str:
    with urllib.request.urlopen(BASE + "/", timeout=10) as response:
        html = response.read().decode()
    match = re.search(r'name="sweep-token" content="([^"]+)"', html)
    return match.group(1) if match else ""


TOKEN = token_from_index()


def call(path: str, method: str = "GET", body: dict | None = None, token: str | None = None):
    return raw(path, method, body, TOKEN if token is None else token)


def wait_job(job_id: str, timeout: float = 180.0) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        status, payload = call(f"/api/jobs/{job_id}")
        if status != 200:
            return payload
        job = payload["data"]
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.4)
    return {"status": "timeout"}


def main() -> int:
    print(f"server: {BASE}")

    status, payload = call("/api/meta")
    check("meta", status == 200 and payload["ok"], str(payload)[:200])
    meta = payload.get("data", {})
    check("meta has drives", bool(meta.get("drives")), str(meta.get("drives"))[:120])
    check("meta has mode", meta.get("mode") in ("quarantine", "permanent"))

    status, payload = call("/api/meta", token="wrong-token")
    check("bad token rejected", status == 401 and payload["error"]["code"] == "unauthorized", str(status))
    check("bad token explains why", "token" in payload["error"]["reason"].lower())

    status, payload = raw("/api/junk", method="POST")
    check("missing token rejected", status == 401, str(status))

    status, payload = call("/api/junk/scan", method="POST", body={})
    check("scan accepted", status == 200 and payload["ok"], str(payload)[:200])
    job = wait_job(payload["data"]["id"], timeout=240)
    check("scan finished", job.get("status") == "done", json.dumps(job.get("error"))[:300])
    if job.get("status") == "done":
        totals = job["result"]["totals"]
        check("scan measured bytes", totals["bytes"] > 0, str(totals))
        check("scan has 18 categories", len(job["result"]["results"]) == 18, str(len(job["result"]["results"])))

    status, payload = call("/api/junk")
    check("junk state cached", status == 200 and payload["data"]["scanned_at"] > 0)

    status, payload = call("/api/junk/clean", method="POST", body={"keys": ["nope"], "permanent": False})
    check("unknown category rejected", status == 400 and payload["error"]["code"] == "invalid_request", str(status))

    status, payload = call("/api/junk/clean", method="POST", body={"keys": ["user_temp"], "permanent": True})
    check("permanent clean needs word", status == 400 and payload["error"]["code"] == "confirmation_required", str(payload)[:200])
    check("confirmation word is delete", payload["error"]["details"]["word"] == "delete")

    status, payload = call("/api/procs/refresh", method="POST", body={})
    job = wait_job(payload["data"]["id"], timeout=120)
    check("procs finished", job.get("status") == "done", json.dumps(job.get("error"))[:300])
    if job.get("status") == "done":
        check("procs classified", job["result"]["summary"]["total"] > 50, str(job["result"]["summary"]))
        check("procs have states", all(p["state"] for p in job["result"]["items"][:10]))

    status, payload = call("/api/procs/kill", method="POST", body={"pids": [99999999]})
    check("kill unknown pid refused", status == 409 and payload["error"]["code"] == "nothing_to_kill", str(status))

    status, payload = call("/api/leftovers/scan", method="POST", body={})
    job = wait_job(payload["data"]["id"], timeout=240)
    check("leftovers finished", job.get("status") == "done", json.dumps(job.get("error"))[:300])

    status, payload = call("/api/search", method="POST", body={"query": "x"})
    check("short query rejected", status == 400 and payload["error"]["code"] == "invalid_request", str(status))

    status, payload = call("/api/search", method="POST", body={"query": "openclaw"})
    check("search accepted", status == 200 and payload["ok"], str(payload)[:200])
    job = wait_job(payload["data"]["id"], timeout=240)
    check("search finished", job.get("status") == "done", json.dumps(job.get("error"))[:300])
    if job.get("status") == "done":
        hits = job["result"]["hits"]
        check("search found something", len(hits) > 0, str(len(hits)))
        check("hits have ids", all(h["id"].startswith("h") for h in hits[:5]))

    status, payload = call("/api/quarantine")
    check("quarantine state", status == 200 and isinstance(payload["data"]["batches"], list))

    status, payload = call("/api/quarantine/restore", method="POST", body={"ids": ["does-not-exist"]})
    check("restore unknown batch refused", status == 404 and payload["error"]["code"] == "not_found", str(status))

    status, payload = call("/api/open", method="POST", body={"path": r"C:\definitely\not\here"})
    check("open missing path refused", status == 404 and payload["error"]["code"] == "path_missing", str(status))

    status, payload = call("/api/activity?limit=5")
    check("activity parsed", status == 200 and isinstance(payload["data"], list))

    status, payload = call("/api/nope")
    check("unknown endpoint 404", status == 404 and payload["error"]["code"] == "not_found", str(status))

    status, payload = raw("/api/meta", method="POST")
    check("wrong method rejected", status in (401, 405), str(status))

    print()
    print(f"failures: {len(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
