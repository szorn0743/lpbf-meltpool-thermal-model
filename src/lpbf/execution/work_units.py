"""Serializable simulation work units for the active execution API.

The work-unit layer is deliberately smaller than the numerical evaluator. A
SimulationJob contains only immutable identifiers and frozen values. A worker
receives one job and returns a payload; the parent owns ordering and artifact
publication. This keeps the serial path explicit now and gives the next patch
a Windows-spawn-safe boundary without moving HDF5 handles or live solver
state across processes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


FrozenValue = (
    str
    | int
    | float
    | bool
    | None
    | tuple["FrozenValue", ...]
    | tuple[tuple[str, "FrozenValue"], ...]
)
FrozenPairs = tuple[tuple[str, FrozenValue], ...]
CoordinatePairs = tuple[tuple[str, float], ...]


def _freeze_value(value: Any) -> FrozenValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _freeze_value(item))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    raise TypeError(
        "simulation job context must contain only JSON-like immutable values; "
        f"got {type(value).__name__}"
    )


def _freeze_pairs(value: Mapping[str, Any] | Sequence[tuple[str, Any]]) -> FrozenPairs:
    pairs = value.items() if isinstance(value, Mapping) else value
    frozen = tuple(
        (str(key), _freeze_value(item))
        for key, item in sorted(pairs, key=lambda item: str(item[0]))
    )
    if len({key for key, _ in frozen}) != len(frozen):
        raise ValueError("simulation job mappings must not contain duplicate keys")
    return frozen


def _freeze_coordinates(
    value: Mapping[str, Any] | Sequence[tuple[str, Any]],
) -> CoordinatePairs:
    pairs = value.items() if isinstance(value, Mapping) else value
    frozen = tuple(
        (str(key), float(item))
        for key, item in sorted(pairs, key=lambda item: str(item[0]))
    )
    if len({key for key, _ in frozen}) != len(frozen):
        raise ValueError("candidate coordinates must not contain duplicate keys")
    return frozen


def _thaw_value(value: FrozenValue) -> Any:
    if isinstance(value, tuple):
        if all(isinstance(item, tuple) and len(item) == 2 for item in value):
            return {str(key): _thaw_value(item) for key, item in value}
        return [_thaw_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SimulationJob:
    """One case-level simulation work unit.

    window_cells is an ordered window sequence. The initial schedule groups
    one representative case's 79/99/117 evaluations in one job so a worker
    can open its dataset once and evaluate those windows sequentially. The
    field accepts either one integer or an immutable tuple, while
    window_sequence provides the normalized iteration form. Both forms are
    safe to pickle under Windows spawn.
    """

    case_index: int
    member_identity: str
    frame_index: int
    window_cells: int | tuple[int, ...]
    candidate_coordinates: CoordinatePairs
    experiment_context: FrozenPairs = ()
    work_unit_id: str | None = None
    identity_provenance: FrozenPairs = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_index", int(self.case_index))
        object.__setattr__(self, "frame_index", int(self.frame_index))
        if self.case_index < 0:
            raise ValueError("case_index must be non-negative")
        if self.frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        identity = str(self.member_identity)
        if not identity:
            raise ValueError("member_identity must be non-empty")
        object.__setattr__(self, "member_identity", identity)
        raw_windows = self.window_cells
        if isinstance(raw_windows, int):
            windows = (int(raw_windows),)
        else:
            windows = tuple(int(window) for window in raw_windows)
        if not windows or any(window <= 0 for window in windows):
            raise ValueError("window_cells must contain positive values")
        if tuple(sorted(set(windows))) != windows:
            raise ValueError("window_cells must be unique and strictly increasing")
        object.__setattr__(
            self,
            "window_cells",
            int(windows[0]) if isinstance(raw_windows, int) else windows,
        )
        object.__setattr__(
            self,
            "candidate_coordinates",
            _freeze_coordinates(self.candidate_coordinates),
        )
        object.__setattr__(
            self,
            "experiment_context",
            _freeze_pairs(self.experiment_context),
        )
        raw_work_unit_id = self.work_unit_id
        if raw_work_unit_id is not None:
            raw_work_unit_id = str(raw_work_unit_id).strip()
            if not raw_work_unit_id:
                raise ValueError("work_unit_id must be non-empty when provided")
        object.__setattr__(self, "work_unit_id", raw_work_unit_id)
        object.__setattr__(
            self,
            "identity_provenance",
            _freeze_pairs(self.identity_provenance),
        )

    @property
    def window_sequence(self) -> tuple[int, ...]:
        return (
            (int(self.window_cells),)
            if isinstance(self.window_cells, int)
            else tuple(int(window) for window in self.window_cells)
        )

    @property
    def sort_key(self) -> tuple[int, str, int, tuple[int, ...]]:
        return (
            int(self.case_index),
            str(self.member_identity),
            int(self.frame_index),
            self.window_sequence,
        )

    @property
    def identity_key(self) -> tuple[Any, ...]:
        if self.work_unit_id is not None:
            return ("work_unit", self.work_unit_id)
        return (
            "legacy",
            int(self.case_index),
            str(self.member_identity),
            int(self.frame_index),
            self.window_sequence,
            self.candidate_coordinates,
            self.experiment_context,
        )

    @property
    def candidate_coordinates_dict(self) -> dict[str, float]:
        return {key: float(value) for key, value in self.candidate_coordinates}

    @property
    def experiment_context_dict(self) -> dict[str, Any]:
        return {key: _thaw_value(value) for key, value in self.experiment_context}

    @property
    def identity_provenance_dict(self) -> dict[str, Any]:
        return {key: _thaw_value(value) for key, value in self.identity_provenance}


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Parent-owned result envelope for one completed simulation job."""

    job: SimulationJob
    payload: Any
    attempts: int = 1

    def __post_init__(self) -> None:
        if int(self.attempts) < 1:
            raise ValueError("attempts must be positive")
        object.__setattr__(self, "attempts", int(self.attempts))

    @property
    def sort_key(self) -> tuple[int, str, int, tuple[int, ...]]:
        return self.job.sort_key


class SimulationExecutionError(RuntimeError):
    """A worker failure annotated with the exact immutable job identity."""

    def __init__(
        self,
        job: SimulationJob,
        *,
        attempts: int,
        cause_type: str,
        cause_message: str,
    ) -> None:
        self.job = job
        self.attempts = int(attempts)
        self.cause_type = str(cause_type)
        self.cause_message = str(cause_message)
        super().__init__(
            f"simulation job failed after {self.attempts} attempt(s): "
            f"case_index={job.case_index}, member_identity={job.member_identity!r}, "
            f"frame_index={job.frame_index}, window_cells={job.window_cells}; "
            f"{self.cause_type}: {self.cause_message}"
        )

    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        return (
            _rebuild_simulation_execution_error,
            (self.job, self.attempts, self.cause_type, self.cause_message),
        )


def _rebuild_simulation_execution_error(
    job: SimulationJob,
    attempts: int,
    cause_type: str,
    cause_message: str,
) -> SimulationExecutionError:
    return SimulationExecutionError(
        job,
        attempts=attempts,
        cause_type=cause_type,
        cause_message=cause_message,
    )


SimulationWorker = Callable[[SimulationJob], Any]
ResultCallback = Callable[[SimulationResult], None]


def execute_serial_jobs(
    jobs: Sequence[SimulationJob],
    worker: SimulationWorker,
    *,
    max_retries: int = 0,
    on_result: ResultCallback | None = None,
) -> tuple[SimulationResult, ...]:
    """Execute jobs serially and return deterministic parent-side ordering.

    Retries are explicit and default to zero so a scientific failure is never
    silently retried. The returned envelopes contain the worker payload only;
    workers do not write final artifacts or mutate shared result state.
    ``on_result`` (optional) is called once per completed job, for progress
    reporting only; it does not affect the returned ordering.
    """

    if not callable(worker):
        raise TypeError("worker must be callable")
    if on_result is not None and not callable(on_result):
        raise TypeError("on_result must be callable or None")
    max_retries = int(max_retries)
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    normalized_jobs = tuple(jobs)
    if any(not isinstance(job, SimulationJob) for job in normalized_jobs):
        raise TypeError("jobs must contain only SimulationJob instances")
    keys = [job.identity_key for job in normalized_jobs]
    if len(set(keys)) != len(keys):
        raise ValueError("simulation job identities must be unique")

    completed: list[SimulationResult] = []
    for job in normalized_jobs:
        attempts = 0
        while True:
            attempts += 1
            try:
                payload = worker(job)
                completed.append(
                    SimulationResult(job=job, payload=payload, attempts=attempts)
                )
                if on_result is not None:
                    on_result(completed[-1])
                break
            except Exception as exc:
                if attempts > max_retries:
                    raise SimulationExecutionError(
                        job,
                        attempts=attempts,
                        cause_type=type(exc).__name__,
                        cause_message=str(exc),
                    ) from exc
    return tuple(sorted(completed, key=lambda result: result.sort_key))


__all__ = [
    "CoordinatePairs",
    "FrozenPairs",
    "ResultCallback",
    "SimulationExecutionError",
    "SimulationJob",
    "SimulationResult",
    "execute_serial_jobs",
]
