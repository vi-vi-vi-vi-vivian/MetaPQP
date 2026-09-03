"""Human-readable terminal progress for local audit runs.

Progress is deliberately written to stderr so the CLI's final JSON result on
stdout remains safe for scripts and IDE integrations to consume.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TextIO


@dataclass
class ProgressReporter:
    """Print compact, phase-oriented progress messages for one local run."""

    enabled: bool = True
    stream: TextIO | None = None

    def __post_init__(self) -> None:
        if self.stream is None:
            self.stream = sys.stderr

    def task_start(self, title: str, details: Iterable[str] = ()) -> float:
        self._line("")
        self._line("═" * 30)
        self._line(f"  {title}")
        self._line("═" * 30)
        for detail in details:
            self._line(detail)
        return time.monotonic()

    def task_complete(self, title: str, started_at: float, details: Iterable[str] = ()) -> None:
        for detail in details:
            self._line(detail)
        self._line("═" * 30)
        self._line(f"  {title} · 耗时 {self._duration(started_at)}")
        self._line("═" * 30)

    def stage_start(self, title: str, description: str | None = None) -> float:
        self._line("")
        self._line(f"──────────── {title} ────────────")
        if description:
            self._line(description)
        return time.monotonic()

    def stage_complete(self, started_at: float, details: Iterable[str] = ()) -> None:
        self._line(f"完成：{self._duration(started_at)}")
        for detail in details:
            self._line(f"  - {detail}")

    def warning(self, message: str, details: Iterable[str] = ()) -> None:
        self._line(f"警告：{message}")
        for detail in details:
            self._line(f"  - {detail}")

    def _line(self, content: str) -> None:
        if self.enabled:
            print(content, file=self.stream, flush=True)

    @staticmethod
    def _duration(started_at: float) -> str:
        return f"{time.monotonic() - started_at:.1f} 秒"
