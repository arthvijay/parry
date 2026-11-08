"""What a date costs to run, measured from the providers' own usage figures.

Every paid call reports what it used: Claude and Gemini their token counts (including
Claude's cache reads and writes), NVIDIA speech recognition the seconds of audio it
heard, ElevenLabs the characters it spoke, plus the characters a cached line saved. The figures go to the
ledger of whatever is running (the live date, the matchmaker, the grader), found through
a context variable so no call site has to carry it, and to a process-wide ledger that
``GET /v1/metrics`` reports.

Dollars come from ``config.prices()``: Claude has list prices built in; the other
providers are priced only when their prices are configured. An unpriced line keeps its
usage and shows no dollars, so the report never invents a number.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from . import config
from .date_models import CostLine, DateCost

UNITS = ("calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
         "audio_seconds", "characters", "characters_cached")
KEY = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class Ledger:
    def __init__(self):
        self.lines: dict[tuple[str, str], dict[str, float]] = {}

    def add(self, provider: str, model: str, **units: float):
        line = self.lines.setdefault((provider, model or "default"), dict.fromkeys(UNITS, 0))
        for name, value in units.items():
            if name in line and value:
                line[name] += value

    def merge(self, other: Ledger) -> Ledger:
        for (provider, model), units in other.lines.items():
            self.add(provider, model, **units)
        return self

    def to_json(self) -> list[dict]:
        return [{"provider": p, "model": m, **u} for (p, m), u in sorted(self.lines.items())]

    @classmethod
    def from_json(cls, data: list[dict]) -> Ledger:
        ledger = cls()
        for row in data or []:
            ledger.add(str(row.get("provider", "")), str(row.get("model", "")),
                       **{k: float(row.get(k) or 0) for k in UNITS})
        return ledger

    def report(self) -> DateCost:
        lines = [_priced(p, m, u) for (p, m), u in sorted(self.lines.items())]
        priced = [line.usd for line in lines if line.usd is not None]
        return DateCost(lines=lines, total_usd=round(sum(priced), 6) if priced else None,
                        complete=all(line.usd is not None for line in lines))


def _priced(provider: str, model: str, u: dict[str, float]) -> CostLine:
    p = config.prices()
    usd = None
    if provider == "claude":
        rates = p.claude.get(model) or p.claude.get("*")
        if rates:
            usd = (u["input_tokens"] * rates[0] + u["output_tokens"] * rates[1]
                   + u["cache_read_tokens"] * rates[2] + u["cache_write_tokens"] * rates[3]) / 1e6
    elif provider == "gemini" and p.gemini:
        usd = (u["input_tokens"] * p.gemini[0] + u["output_tokens"] * p.gemini[1]) / 1e6
    elif provider == "nemotron" and p.asr_per_minute is not None:
        usd = u["audio_seconds"] / 60 * p.asr_per_minute
    elif provider == "elevenlabs" and p.tts_per_million_chars is not None:
        usd = u["characters"] * p.tts_per_million_chars / 1e6
    return CostLine(provider=provider, model=model, calls=int(u["calls"]),
                    input_tokens=int(u["input_tokens"]), output_tokens=int(u["output_tokens"]),
                    cache_read_tokens=int(u["cache_read_tokens"]),
                    cache_write_tokens=int(u["cache_write_tokens"]),
                    audio_seconds=round(u["audio_seconds"], 1), characters=int(u["characters"]),
                    characters_cached=int(u["characters_cached"]),
                    usd=round(usd, 6) if usd is not None else None)


# --------------------------------------------------------------------------- recording

_current: ContextVar[Ledger | None] = ContextVar("parry_ledger", default=None)
TOTAL = Ledger()


def record(provider: str, model: str, **units: float):
    """Charge the running job's ledger (if any) and the process-wide one."""
    units.setdefault("calls", 1)
    ledger = _current.get()
    if ledger is not None:
        ledger.add(provider, model, **units)
    TOTAL.add(provider, model, **units)


@contextmanager
def charging(ledger: Ledger) -> Iterator[Ledger]:
    """Everything awaited inside, and every task created inside, charges ``ledger``."""
    token = _current.set(ledger)
    try:
        yield ledger
    finally:
        _current.reset(token)


def claude_usage(model: str, usage) -> None:
    """Claude's usage object, however much of it the response carried."""
    if usage is None:
        return
    record("claude", model,
           input_tokens=getattr(usage, "input_tokens", 0) or 0,
           output_tokens=getattr(usage, "output_tokens", 0) or 0,
           cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
           cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0)


# --------------------------------------------------------------------------- storage

class CostStore:
    """One file per date and per run: ``date_…`` holds the matchmaker's call, the run id
    holds the live date and the grade. A date's cost is the two together."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, key: str) -> Path:
        if not KEY.match(key):
            raise ValueError("Invalid cost key")
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Ledger:
        path = self._path(key)
        if not path.is_file():
            return Ledger()
        return Ledger.from_json(json.loads(path.read_text(encoding="utf-8")))

    def add(self, key: str, ledger: Ledger):
        if not ledger.lines:
            return
        merged = self.get(key).merge(ledger)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(merged.to_json()), encoding="utf-8")
        temp.replace(path)

    def date_cost(self, run_id: str, scenario_id: str | None) -> DateCost:
        ledger = self.get(run_id)
        if scenario_id:
            ledger.merge(self.get(scenario_id))
        return ledger.report()
