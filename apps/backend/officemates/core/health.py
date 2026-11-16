"""Readiness checks.

Dependencies (MySQL, Redis, Pinecone, ...) register a check here as they are added in later
phases. ``/readyz`` runs them all concurrently with a timeout and reports each result.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

CheckFn = Callable[[], Awaitable[None]]  # raises on failure
Status = Literal["ok", "fail"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    duration_ms: float
    error: str | None = None


@dataclass
class ReadinessRegistry:
    timeout_s: float = 2.0
    _checks: dict[str, CheckFn] = field(default_factory=dict)

    def register(self, name: str, check: CheckFn) -> None:
        if name in self._checks:
            raise ValueError(f"readiness check {name!r} already registered")
        self._checks[name] = check

    @property
    def names(self) -> list[str]:
        return sorted(self._checks)

    async def run(self) -> list[CheckResult]:
        results = await asyncio.gather(
            *(self._run_one(name, fn) for name, fn in sorted(self._checks.items()))
        )
        return list(results)

    async def _run_one(self, name: str, fn: CheckFn) -> CheckResult:
        started = time.perf_counter()
        try:
            await asyncio.wait_for(fn(), timeout=self.timeout_s)
        except TimeoutError:
            return CheckResult(name, "fail", _elapsed(started), "timeout")
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
            # Only the exception type is reported: messages can contain hosts or credentials.
            return CheckResult(name, "fail", _elapsed(started), type(exc).__name__)
        return CheckResult(name, "ok", _elapsed(started))


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
