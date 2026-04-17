from __future__ import annotations

from time import perf_counter


class TimingRecorder:
    def __init__(self) -> None:
        self.timings: dict[str, float] = {}

    def start(self) -> float:
        return perf_counter()

    def stop(self, stage: str, started_at: float) -> float:
        duration_ms = (perf_counter() - started_at) * 1000
        self.timings[stage] = duration_ms
        return duration_ms
