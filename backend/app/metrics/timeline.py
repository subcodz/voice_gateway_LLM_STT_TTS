"""Single-clock turn timeline.

Why this module exists:
Every duration in a turn is measured on one monotonic clock (time.perf_counter)
against one shared t0, so stage spans can be checked against the total.
`unattributed_ms` is the part of the total that no span covers. A test asserts it
stays small, which is how a multi-second hole in a waterfall gets caught.

Definitions used by the session demo (identical for both arms):
  t0               the moment the reply text is final (after LLM or LLM cache)
  first_byte       t0 -> first audio byte handed to the sender
  first_playable   t0 -> end of clause 1 (a complete, playable WAV)
  total            t0 -> last byte of the last clause
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Span:
    name: str
    start_ms: float
    end_ms: Optional[float] = None

    @property
    def duration_ms(self) -> float:
        return 0.0 if self.end_ms is None else self.end_ms - self.start_ms


class Timeline:
    def __init__(self, t0: Optional[float] = None):
        self.t0 = time.perf_counter() if t0 is None else t0
        self.spans: List[Span] = []
        self.marks: Dict[str, float] = {}
        self._end_ms: Optional[float] = None

    def now_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000.0

    def begin(self, name: str) -> Span:
        span = Span(name, self.now_ms())
        self.spans.append(span)
        return span

    def end(self, span: Span) -> None:
        if span.end_ms is None:
            span.end_ms = self.now_ms()

    def mark(self, name: str) -> float:
        """Records a named instant. The first mark wins, so 'first_byte' never
        moves when later chunks arrive."""
        return self.marks.setdefault(name, self.now_ms())

    def finish(self) -> float:
        """Closes the timeline, ending any span still open (e.g. after an error)."""
        if self._end_ms is None:
            self._end_ms = self.now_ms()
            for s in self.spans:
                if s.end_ms is None:
                    s.end_ms = self._end_ms
        return self._end_ms

    @property
    def total_ms(self) -> float:
        return self._end_ms if self._end_ms is not None else self.now_ms()

    def covered_ms(self) -> float:
        """Length of the union of closed spans (overlaps are not double counted)."""
        intervals = sorted((s.start_ms, s.end_ms) for s in self.spans if s.end_ms is not None)
        covered = 0.0
        cur_s: Optional[float] = None
        cur_e: Optional[float] = None
        for s, e in intervals:
            if cur_e is None or s > cur_e:
                if cur_e is not None:
                    covered += cur_e - cur_s
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        if cur_e is not None:
            covered += cur_e - cur_s
        return covered

    def by_name(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for s in self.spans:
            out[s.name] = out.get(s.name, 0.0) + s.duration_ms
        return out

    def unattributed_ms(self) -> float:
        return max(0.0, self.total_ms - self.covered_ms())
