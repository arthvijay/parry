"""What the app remembers about a learner from one date to the next.

After every graded date the learner's profile (keyed by the name they gave the
matchmaker) gains a line: the dialect, the verdict, the grades, the milestones met. The
corrections from that date join a short practice list for that dialect, but only ones
the learner certainly said: quoted from their own lines and not built on a word the
recogniser doubted.

The next date in that dialect carries the two most recent open items. The date is told,
silently, to give the learner a natural reason to say them (never to teach them), and
the director listens: an item is marked fixed only when the learner's own line contains
the better phrasing word for word. Same rule as everywhere else: no quote, no tick.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .chemistry_director import ChemistryState, plain
from .date_grader import asr_suspect
from .date_models import DateScenario, DateVerdict, PracticeTarget
from .director import said_by_learner
from .models import TranscriptTurn

KEY = re.compile(r"^[a-z0-9_]{1,48}$")
MAX_DATES = 200
MAX_OPEN_PER_DIALECT = 12


def learner_key(name: str) -> str | None:
    """A file-safe key for a learner's name: ASCII where the name allows, else a hash."""
    name = (name or "").strip()
    if not name:
        return None
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "_", ascii_name.casefold()).strip("_")[:40]
    return key or "u_" + hashlib.sha256(name.casefold().encode()).hexdigest()[:16]


class LearnerProfileStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, key: str) -> Path:
        if not KEY.match(key):
            raise ValueError("Invalid learner key")
        return self.directory / f"{key}.json"

    def get(self, name: str) -> dict | None:
        key = learner_key(name)
        if key is None:
            return None
        path = self._path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def all(self) -> list[dict]:
        if not self.directory.is_dir():
            return []
        profiles = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                profiles.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return profiles

    def _save(self, profile: dict):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(profile["key"])
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(path)

    # ---- reading ----------------------------------------------------------------

    def practice_targets(self, name: str, dialect: str, limit: int = 2) -> list[PracticeTarget]:
        """The most recent open items for this dialect, for the next date to carry."""
        profile = self.get(name) or {}
        open_items = [p for p in profile.get("practice", [])
                      if p.get("dialect") == dialect and p.get("status") == "open"]
        return [PracticeTarget(heard=p["heard"], better=p["better"], why_en=p["why_en"])
                for p in reversed(open_items[-limit:])]

    # ---- writing ----------------------------------------------------------------

    def record(self, scenario: DateScenario, state: ChemistryState,
               transcript: Sequence[TranscriptTurn], verdict: DateVerdict) -> dict | None:
        """Add this date to the learner's profile; idempotent per run."""
        key = learner_key(scenario.learner_name)
        if key is None:
            return None
        profile = self.get(scenario.learner_name) or {
            "learner": scenario.learner_name.strip(), "key": key, "dates": [], "practice": []}
        entry = {
            "run_id": verdict.run_id, "scenario_id": verdict.scenario_id,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "dialect": scenario.dialect, "dialect_label": scenario.dialect_label,
            "city": scenario.city, "date_name": verdict.date_name, "verdict": verdict.verdict,
            "overall": verdict.overall, "chemistry": verdict.final_chemistry,
            "pillars": {p.id: p.grade for p in verdict.pillars},
            "milestones": [m.id for m in verdict.milestones if m.achieved],
            "fixed": [p.better for p in verdict.progress],
            "words_to_practise": list(verdict.metrics.words_to_practise),
        }
        profile["dates"] = [d for d in profile["dates"] if d.get("run_id") != verdict.run_id]
        profile["dates"] = (profile["dates"] + [entry])[-MAX_DATES:]

        practice = profile["practice"]
        known = {(p["dialect"], plain(p["better"])) for p in practice}
        fresh = []
        if verdict.followup.correction is not None:
            fresh.append(verdict.followup.correction.model_dump())
        fresh += list(state.mistakes)
        for item in fresh:
            heard, better = (item.get("heard") or "").strip(), (item.get("better") or "").strip()
            if not heard or not better or plain(heard) == plain(better):
                continue
            if not said_by_learner(heard, transcript) or asr_suspect(heard, transcript):
                continue
            if (scenario.dialect, plain(better)) in known:
                continue
            known.add((scenario.dialect, plain(better)))
            practice.append({"dialect": scenario.dialect, "heard": heard[:300],
                             "better": better[:300],
                             "why_en": (item.get("why_en") or "More natural.").strip()[:300],
                             "from_run": verdict.run_id, "status": "open"})
        for item in verdict.progress:
            for p in practice:
                if (p["dialect"] == scenario.dialect and p["status"] == "open"
                        and plain(p["better"]) == plain(item.better)):
                    p.update(status="fixed", fixed_quote=item.quote, fixed_run=verdict.run_id)
        open_here = [p for p in practice if p["dialect"] == scenario.dialect and p["status"] == "open"]
        for stale in open_here[:-MAX_OPEN_PER_DIALECT]:
            stale["status"] = "retired"
        self._save(profile)
        return profile


def summary(profile: dict) -> dict:
    """One row of the class report."""
    dates = profile.get("dates", [])
    verdicts = [d.get("verdict") for d in dates]
    practice = profile.get("practice", [])
    return {
        "learner": profile.get("learner", ""), "key": profile.get("key", ""),
        "dates": len(dates), "matches": verdicts.count("match"),
        "friendzones": verdicts.count("friendzone"), "ghosted": verdicts.count("ghosted"),
        "dialects": sorted({d.get("dialect", "") for d in dates}),
        "last_overall": dates[-1].get("overall") if dates else None,
        "last_at": dates[-1].get("at") if dates else None,
        "open_practice": [p["better"] for p in practice if p.get("status") == "open"][-3:],
        "fixed": sum(p.get("status") == "fixed" for p in practice),
    }
