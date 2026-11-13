"""Background jobs for the web interface.

Scans take seconds to minutes, so every long call runs in a worker thread and
the browser polls ``/api/jobs/<id>``. A job carries progress, a partial payload
(for live tables), the final result and a structured error.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import ApiError, explain

log = logging.getLogger("sweep.web.jobs")


@dataclass
class Job:
    kind: str
    title: str
    id: str = field(default_factory=lambda: secrets.token_hex(6))
    status: str = "queued"  # queued | running | done | error | cancelled
    phase: str = "Queued"
    message: str = "Waiting to start"
    current: float = 0.0
    total: float = 0.0
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    result: Any = None
    error: dict[str, Any] | None = None
    partial: dict[str, Any] = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- progress ------------------------------------------------------- #
    def progress(
        self,
        current: float | None = None,
        total: float | None = None,
        phase: str | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            if current is not None:
                self.current = float(current)
            if total is not None:
                self.total = float(total)
            if phase is not None:
                self.phase = phase
            if message is not None:
                self.message = message

    def bump(self, amount: float = 1.0, message: str | None = None) -> None:
        with self._lock:
            self.current += amount
            if message is not None:
                self.message = message

    def publish(self, **values: Any) -> None:
        """Put a partial payload in the job so the table can fill in live."""
        with self._lock:
            self.partial.update(values)

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0 if self.status in ("queued", "running") else 100.0
        return max(0.0, min(100.0, self.current / self.total * 100.0))

    def to_dict(self, include_result: bool = True) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "id": self.id,
                "kind": self.kind,
                "title": self.title,
                "status": self.status,
                "phase": self.phase,
                "message": self.message,
                "current": round(self.current, 2),
                "total": round(self.total, 2),
                "percent": round(self.percent, 1),
                "created": self.created,
                "started": self.started,
                "finished": self.finished,
                "elapsed": round((self.finished or time.time()) - (self.started or self.created), 2),
                "partial": dict(self.partial),
                "error": self.error,
                "has_result": self.result is not None,
            }
            if include_result and self.status in ("done", "cancelled"):
                payload["result"] = self.result
            return payload


class JobManager:
    """Thread-per-job runner with cancellation and a bounded history."""

    def __init__(self, history: int = 40) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._history = history
        self._lock = threading.Lock()
        # Destructive operations are serialised so two cleanups cannot race.
        self.operation_lock = threading.Lock()

    # -- public --------------------------------------------------------- #
    def submit(
        self,
        kind: str,
        title: str,
        target: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Job:
        job = Job(kind=kind, title=title)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._trim()
        thread = threading.Thread(
            target=self._run,
            args=(job, target, args, kwargs),
            name=f"sweep-job-{job.id}",
            daemon=True,
        )
        thread.start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel.set()
        job.progress(message="Cancelling — finishing the current item")
        return job

    def active(self) -> list[Job]:
        with self._lock:
            jobs = [self._jobs[i] for i in self._order if i in self._jobs]
        return [j for j in jobs if j.status in ("queued", "running")]

    def recent(self, limit: int = 12) -> list[Job]:
        with self._lock:
            jobs = [self._jobs[i] for i in reversed(self._order) if i in self._jobs]
        return jobs[:limit]

    # -- internals ------------------------------------------------------ #
    def _trim(self) -> None:
        while len(self._order) > self._history:
            oldest = self._order.pop(0)
            self._jobs.pop(oldest, None)

    def _run(
        self,
        job: Job,
        target: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        job.status = "running"
        job.started = time.time()
        job.progress(phase="Starting", message="Preparing…")
        try:
            result = target(job, *args, **kwargs)
            if job.cancel.is_set() and job.status != "error":
                job.status = "cancelled"
                job.result = result
                job.progress(phase="Cancelled", message="Stopped at your request")
            else:
                job.status = "done"
                job.result = result
                job.progress(current=job.total or 1, phase="Done", message="Finished")
        except ApiError as exc:
            job.status = "error"
            job.error = exc.to_dict()
            job.progress(phase="Failed", message=exc.message)
        except BaseException as exc:  # noqa: BLE001 - report everything
            job.status = "error"
            job.error = explain(exc).to_dict()
            job.progress(phase="Failed", message=job.error["message"])
            log.error("job %s (%s) crashed:\n%s", job.id, job.kind, traceback.format_exc())
        finally:
            job.finished = time.time()
            if job.status == "running":
                job.status = "done"
