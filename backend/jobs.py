"""In-process async job queue.

Handoff Section 2, rule 1: "stages are jobs, not request handlers." Stage B
(scVI integration, 10-40 min/lineage) and Stage F (A100, ~17 min) cannot run
inside a request. The API submits a job, returns a ``job_id``, and the frontend
polls ``GET /jobs/{job_id}``.

Here jobs run on background threads. A job's runner either (a) returns a cached
artifact quickly, or (b) raises ``ComputeUnavailable`` when the requested
combination has no cached result and the real recompute needs resources not
present in this bundle (a GPU host, multi-GB atlases, PertFormer weights). It
never invents a result — a failed job reports honestly what compute is missing.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional


class ComputeUnavailable(Exception):
    """Raised when a stage cannot produce a real result in this environment."""


class Job:
    def __init__(self, stage: str, params: Dict[str, Any]) -> None:
        self.job_id = "job_" + uuid.uuid4().hex[:16]
        self.stage = stage
        self.params = params
        self.status = "queued"  # queued | running | done | failed
        self.progress: Optional[str] = None
        self.result: Any = None
        self.result_uri: Optional[str] = None
        self.error: Optional[str] = None
        self.created = time.time()
        self.updated = self.created

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "stage": self.stage,
            "params": self.params,
            "status": self.status,
            "progress": self.progress,
            "result_uri": self.result_uri,
            "error": self.error,
        }


_JOBS: Dict[str, Job] = {}
_LOCK = threading.Lock()


def _run(job: Job, runner: Callable[["Job"], Any]) -> None:
    job.status = "running"
    job.progress = "started"
    job.updated = time.time()
    try:
        result = runner(job)
        job.result = result
        job.result_uri = result.get("artifact_uri") if isinstance(result, dict) else None
        job.status = "done"
        job.progress = "complete"
    except ComputeUnavailable as exc:
        job.status = "failed"
        job.error = str(exc)
    except Exception as exc:  # noqa: BLE001 — surface any runner failure honestly
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.updated = time.time()


def submit(stage: str, params: Dict[str, Any], runner: Callable[["Job"], Any]) -> Job:
    """Create a job and start its runner on a background thread."""
    job = Job(stage, params)
    with _LOCK:
        _JOBS[job.job_id] = job
    thread = threading.Thread(target=_run, args=(job, runner), daemon=True)
    thread.start()
    return job


def get(job_id: str) -> Optional[Job]:
    with _LOCK:
        return _JOBS.get(job_id)


def find_running(stage: str, params_predicate: Callable[[Dict[str, Any]], bool]) -> Optional[Job]:
    """Return an in-flight job for a stage whose params match (for the run index)."""
    with _LOCK:
        for job in _JOBS.values():
            if job.stage == stage and job.status in ("queued", "running") and params_predicate(job.params):
                return job
    return None
