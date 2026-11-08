"""Where the speed date keeps what outlives a session: graded verdicts (for the share
page), learner profiles (for the next date and the class report), costs, and cached
voice lines.

The stores sit next to the dates directory unless their own environment variable says
otherwise, and are created on first use, so the app factory needs no new wiring.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .costs import CostStore
from .date_models import DateVerdict
from .learner_profile import LearnerProfileStore
from .voice_cache import VoiceCache

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class VerdictStore:
    """The last verdict graded for each run, so a share link never re-grades."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id):
            raise ValueError("Invalid run_id")
        return self.directory / f"{run_id}.json"

    def save(self, verdict: DateVerdict):
        path = self._path(verdict.run_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(verdict.model_dump_json(), encoding="utf-8")
        temp.replace(path)

    def get(self, run_id: str) -> DateVerdict:
        path = self._path(run_id)
        if not path.is_file():
            raise FileNotFoundError(run_id)
        return DateVerdict.model_validate(json.loads(path.read_text(encoding="utf-8")))


@dataclass
class Records:
    verdicts: VerdictStore
    learners: LearnerProfileStore
    costs: CostStore
    voice_cache: VoiceCache


def records(state) -> Records:
    """The app's record stores, made on first use from the dates directory's parent."""
    existing = getattr(state, "records", None)
    if existing is not None:
        return existing
    date_store = getattr(state, "date_store", None)
    base = date_store.directory.parent if date_store is not None else Path("runs")

    def place(variable: str, name: str) -> Path:
        return Path(os.getenv(variable) or base / name)

    made = Records(verdicts=VerdictStore(place("VERDICT_DIR", "verdicts")),
                   learners=LearnerProfileStore(place("LEARNER_DIR", "learners")),
                   costs=CostStore(place("COST_DIR", "costs")),
                   voice_cache=VoiceCache(place("VOICE_CACHE_DIR", "voice_cache")))
    state.records = made
    return made
