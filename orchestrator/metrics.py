"""Latency, measured rather than claimed.

Every speech turn reports where its time went. This keeps the recent figures per
character so `GET /v1/metrics` can answer "how fast is it, really" with a median and a
90th percentile, which is what the demo shows instead of an adjective.
"""

from __future__ import annotations

from collections import defaultdict, deque

STAGES = ("stt", "session_open", "first_audio", "first_sound", "complete", "total")
WINDOW = 200


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * q), len(ordered) - 1)]


class Metrics:
    def __init__(self):
        self.turns: dict[str, deque] = defaultdict(lambda: deque(maxlen=WINDOW))

    def record(self, npc_id: str, timings_ms: dict[str, int]):
        self.turns[npc_id].append(dict(timings_ms))

    def summary(self) -> dict:
        out = {}
        everything = [t for turns in self.turns.values() for t in turns]
        for name, turns in [("all", everything), *self.turns.items()]:
            if not turns:
                continue
            # A warm turn is the steady state; a cold one also opened the conversation.
            warm = [t for t in turns if not t.get("session_open")]
            out[name] = {"turns": len(turns), "warm_turns": len(warm), "stages_ms": {
                stage: {"p50": _percentile(values, 0.5), "p90": _percentile(values, 0.9)}
                for stage in STAGES
                if (values := [t[stage] for t in (warm or turns) if stage in t])}}
        return out
