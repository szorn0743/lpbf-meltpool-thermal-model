"""Windows-spawn process-pool execution for serializable simulation jobs."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from typing import Sequence

from .work_units import (
    ResultCallback,
    SimulationExecutionError,
    SimulationJob,
    SimulationResult,
    SimulationWorker,
)


def execute_parallel_jobs(
    jobs: Sequence[SimulationJob],
    worker: SimulationWorker,
    *,
    workers: int,
    max_retries: int = 0,
    on_result: ResultCallback | None = None,
) -> tuple[SimulationResult, ...]:
    """Execute jobs in a Windows-compatible process pool.

    The explicit spawn context makes the process-start contract testable on
    every platform. Workers receive only picklable jobs and return payloads;
    the parent performs deterministic ordering and owns all final artifacts.
    ``on_result`` (optional) is called in the parent as each job completes, in
    completion order, for progress reporting only; the returned tuple is still
    sorted by job identity.
    """

    if not callable(worker):
        raise TypeError("worker must be callable")
    if on_result is not None and not callable(on_result):
        raise TypeError("on_result must be callable or None")
    if isinstance(workers, bool):
        raise ValueError("workers must be a positive integer")
    try:
        worker_count = int(workers)
    except (TypeError, ValueError) as exc:
        raise ValueError("workers must be a positive integer") from exc
    if worker_count != workers or worker_count < 1:
        raise ValueError("workers must be a positive integer")
    if isinstance(max_retries, bool):
        raise ValueError("max_retries must be a non-negative integer")
    try:
        retry_count = int(max_retries)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_retries must be a non-negative integer") from exc
    if retry_count != max_retries or retry_count < 0:
        raise ValueError("max_retries must be a non-negative integer")
    max_retries = retry_count

    normalized_jobs = tuple(jobs)
    if any(not isinstance(job, SimulationJob) for job in normalized_jobs):
        raise TypeError("jobs must contain only SimulationJob instances")
    keys = [job.identity_key for job in normalized_jobs]
    if len(set(keys)) != len(keys):
        raise ValueError("simulation job identities must be unique")
    if not normalized_jobs:
        return ()

    executor = ProcessPoolExecutor(
        max_workers=worker_count,
        mp_context=get_context("spawn"),
    )
    pending = {}
    completed: list[SimulationResult] = []
    try:
        for job in normalized_jobs:
            pending[executor.submit(worker, job)] = (job, 1)
        while pending:
            for future in as_completed(tuple(pending)):
                job, attempts = pending.pop(future)
                try:
                    payload = future.result()
                except Exception as exc:
                    if attempts <= max_retries:
                        pending[executor.submit(worker, job)] = (job, attempts + 1)
                        continue
                    raise SimulationExecutionError(
                        job,
                        attempts=attempts,
                        cause_type=type(exc).__name__,
                        cause_message=str(exc),
                    ) from exc
                completed.append(
                    SimulationResult(job=job, payload=payload, attempts=attempts)
                )
                if on_result is not None:
                    on_result(completed[-1])
    except Exception:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    return tuple(sorted(completed, key=lambda result: result.sort_key))


__all__ = ["execute_parallel_jobs"]
