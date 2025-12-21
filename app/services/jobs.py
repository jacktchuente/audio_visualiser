"""
Job management utilities for asynchronous video rendering tasks.

Jobs are identified by a UUID string and track their status and
results in an in‑memory store. Each job record contains:
 - status: one of 'queued', 'running', 'done', or 'error'
 - output: path to the generated MP4 file relative to the outputs folder
 - error: error message if status is 'error'

The `create_job` function registers a new job and spawns a background
task that performs the rendering using the provided coroutine. Status
transitions are managed internally. When the task completes or fails,
the job record is updated accordingly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict

from uuid import uuid4

# In‑memory job store
_jobs: Dict[str, Dict[str, Any]] = {}


def create_job(task_func: Callable[[str], Awaitable[Path]]) -> str:
    """Create a new job and schedule its task to run.

    Parameters
    ----------
    task_func: coroutine function that takes the job_id and returns the
        path to the generated output file. It must handle all exceptions
        internally and update the job record via `update_job`.

    Returns
    -------
    job_id: string
        Unique identifier for the created job.
    """
    job_id = uuid4().hex
    # Initialize job state
    _jobs[job_id] = {"status": "queued", "output": None, "error": None}

    async def wrapper():
        # Mark job as running
        update_job(job_id, status="running")
        try:
            output_path = await task_func(job_id)
        except Exception as exc:
            update_job(job_id, status="error", error=str(exc))
            return
        update_job(job_id, status="done", output=str(output_path))

    # Schedule the task in the background without awaiting it
    asyncio.create_task(wrapper())
    return job_id


def get_job(job_id: str) -> Dict[str, Any]:
    """Retrieve job information for the given job ID.

    Returns a dictionary with keys 'status', 'output', and 'error'. If
    the job ID does not exist, an empty dict is returned.
    """
    return _jobs.get(job_id, {})


def update_job(job_id: str, *, status: str, output: str | None = None, error: str | None = None) -> None:
    """Update fields of a job entry.

    This helper centralises the mutation of job state. When updating
    status to 'done' you may optionally specify an output path. When
    updating status to 'error', an error message can be included.
    """
    job = _jobs.get(job_id)
    if not job:
        return
    job["status"] = status
    if output is not None:
        job["output"] = output
    if error is not None:
        job["error"] = error
