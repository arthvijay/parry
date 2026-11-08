"""What the date can see: the learner's face and gaze, turned into human signals.

Raw numbers (blendshape weights, head angles, whether the camera is pointed at the
date's face) become the things a person across the table would notice: a smile, a
laugh, a nod, a shake of the head, a puzzled look, a surprised one, looking away and
looking back. Each signal is debounced so a flicker is not a smile, and timed so it
counts only once per occurrence.

Signals go three places: to the vision panel's live feed (so the demo shows what the
date is picking up), to the chemistry director (a smile at a joke, looking away while
they talk), and to the date's own prompt as a [NONVERBAL] note, so they react the way a
person would.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .face_tracker import FaceReading


@dataclass
class Signal:
    # smile | laugh | nod | shake | wobble | puzzled | surprised | frown | look_away | look_back
    kind: str
    label: str       # for the vision panel, e.g. "Smiling"
    note: str        # for the date's prompt
    during_npc: bool


NOTES = {
    "smile": "they smiled",
    "laugh": "they laughed",
    "nod": "they nodded along",
    "shake": "they shook their head",
    "wobble": "they did the head wobble (here that means yes, go on)",
    "puzzled": "they looked puzzled, maybe lost",
    "surprised": "they looked surprised",
    "frown": "they frowned",
    "look_away": "they looked away from you",
    "look_back": "they looked back at you",
}
LABELS = {
    "smile": "Smiling 😊", "laugh": "Laughing 😂", "nod": "Nodding 👍", "shake": "Head shake 🙅",
    "wobble": "Head wobble 👌", "puzzled": "Puzzled 🤔", "surprised": "Surprised 😮", "frown": "Frowning 😕",
    "look_away": "Looking away 👀", "look_back": "Eye contact restored 👁️",
}


class _Hold:
    """A condition that must hold for ``on`` seconds to start and fail for ``off``
    seconds to end, so the edge fires once per real occurrence."""

    def __init__(self, on: float, off: float = 0.4):
        self.on, self.off = on, off
        self.active = False
        self.since: float | None = None
        self.lost: float | None = None

    def update(self, condition: bool, now: float) -> bool:
        """True exactly when the condition becomes active."""
        if condition:
            self.lost = None
            if self.since is None:
                self.since = now
            if not self.active and now - self.since >= self.on:
                self.active = True
                return True
        else:
            self.since = None
            if self.active:
                self.lost = self.lost or now
                if now - self.lost >= self.off:
                    self.active = False
        return False


class NonverbalTracker:
    def __init__(self, head_wobble: bool = False):
        self.smile = _Hold(0.35)
        self.laugh = _Hold(0.25, 0.8)
        self.puzzled = _Hold(0.8, 0.6)
        self.surprised = _Hold(0.3, 0.6)
        self.frown = _Hold(0.7, 0.6)
        # Where a side-to-side wobble means "yes, go on" (hi-IN), it is read as such
        # instead of being ignored; elsewhere a rolling head is not a signal.
        self.head_wobble = head_wobble
        self.head: deque[tuple[float, float, float, float]] = deque(maxlen=40)  # (t, pitch, yaw, roll)
        self.last_gesture = -10.0
        self.pending: list[str] = []
        self.levels: dict[str, float] = {}
        self.looking = True
        self.away_since: float | None = None
        self.called_out = False
        self.smiling_now = False
        self.face_seen = False

    # ---- face -----------------------------------------------------------------

    def face(self, reading: FaceReading, now: float, npc_speaking: bool) -> list[Signal]:
        if not reading.found:
            self.smiling_now = False
            return []
        self.face_seen = True
        s = reading.shape
        smile = (s("mouthSmileLeft") + s("mouthSmileRight")) / 2
        jaw = s("jawOpen")
        brow_down = (s("browDownLeft") + s("browDownRight")) / 2
        brow_up = s("browInnerUp")
        wide = (s("eyeWideLeft") + s("eyeWideRight")) / 2
        frown = (s("mouthFrownLeft") + s("mouthFrownRight")) / 2
        squint = (s("eyeSquintLeft") + s("eyeSquintRight")) / 2
        self.levels = {"smile": smile, "jaw": jaw, "brow_down": brow_down, "brow_up": brow_up,
                       "eye_wide": wide, "frown": frown,
                       "blink": (s("eyeBlinkLeft") + s("eyeBlinkRight")) / 2}
        self.smiling_now = smile > 0.4
        out = []
        if self.laugh.update(smile > 0.5 and jaw > 0.3, now):
            out.append(self._signal("laugh", npc_speaking))
        elif self.smile.update(smile > 0.45, now):
            out.append(self._signal("smile", npc_speaking))
        if self.puzzled.update(smile < 0.2 and (brow_down > 0.35 or (brow_up > 0.35 and squint > 0.3)), now):
            out.append(self._signal("puzzled", npc_speaking))
        if self.surprised.update(brow_up > 0.5 and wide > 0.3 and jaw > 0.2, now):
            out.append(self._signal("surprised", npc_speaking))
        if self.frown.update(frown > 0.35 and smile < 0.15, now):
            out.append(self._signal("frown", npc_speaking))
        gesture = self._head_gesture(now, reading.pitch, reading.yaw, reading.roll)
        if gesture:
            out.append(self._signal(gesture, npc_speaking))
        return out

    def _head_gesture(self, now: float, pitch: float, yaw: float,
                      roll: float = 0.0) -> str | None:
        """A nod is pitch going down and up at least twice within ~1.5 s while yaw stays
        put; a shake is the same on yaw; a wobble (only where it means yes) is the same
        on roll while pitch and yaw stay put."""
        self.head.append((now, pitch, yaw, roll))
        recent = [h for h in self.head if now - h[0] <= 1.5]
        if len(recent) < 5 or now - self.last_gesture < 1.5:
            return None

        def swings(values: list[float], threshold: float) -> int:
            count, direction, anchor = 0, 0, values[0]
            for v in values[1:]:
                if direction >= 0 and v < anchor - threshold:
                    count, direction, anchor = count + (direction > 0), -1, v
                elif direction <= 0 and v > anchor + threshold:
                    count, direction, anchor = count + (direction < 0), 1, v
                elif (direction > 0 and v > anchor) or (direction < 0 and v < anchor):
                    anchor = v
            return count

        pitches, yaws = [h[1] for h in recent], [h[2] for h in recent]
        rolls = [h[3] for h in recent]
        pitch_range, yaw_range = max(pitches) - min(pitches), max(yaws) - min(yaws)
        roll_range = max(rolls) - min(rolls)
        if (self.head_wobble and swings(rolls, 4.0) >= 2
                and max(pitch_range, yaw_range) < roll_range * 0.7):
            self.last_gesture = now
            return "wobble"
        if swings(pitches, 4.0) >= 2 and yaw_range < pitch_range * 0.7:
            self.last_gesture = now
            return "nod"
        if swings(yaws, 6.0) >= 2 and pitch_range < yaw_range * 0.7:
            self.last_gesture = now
            return "shake"
        return None

    # ---- gaze -----------------------------------------------------------------

    def gaze(self, looking: bool, away_seconds: float, now: float,
             npc_speaking: bool) -> list[Signal]:
        out = []
        if looking and not self.looking:
            out.append(self._signal("look_back", npc_speaking))
            self.away_since, self.called_out = None, False
        elif not looking:
            # The client measures the episode continuously; trust the longer account.
            began = now - max(0.0, away_seconds)
            self.away_since = began if self.away_since is None else min(self.away_since, began)
        self.looking = looking
        return out

    def looked_away_for(self, now: float) -> float:
        return 0.0 if self.looking or self.away_since is None else now - self.away_since

    def look_away_episode(self, now: float, threshold: float, npc_speaking: bool) -> bool:
        """True once per episode of looking away too long while the date is talking."""
        if npc_speaking and not self.called_out and self.looked_away_for(now) > threshold:
            self.called_out = True
            self.pending.append(f"{NOTES['look_away']} for {self.looked_away_for(now):.0f} s "
                                "while you were talking")
            return True
        return False

    # ---- notes ----------------------------------------------------------------

    def _signal(self, kind: str, npc_speaking: bool) -> Signal:
        note = NOTES[kind] + (" while you were talking" if npc_speaking else "")
        if kind != "look_back":
            self.pending.append(note)
            del self.pending[:-6]
        return Signal(kind, LABELS[kind], note, npc_speaking)

    def take_notes(self) -> list[str]:
        """What the date noticed since their last line, once each, then forgotten."""
        seen, notes = set(), []
        for note in self.pending:
            if note not in seen:
                seen.add(note)
                notes.append(note)
        self.pending = []
        return notes

    def snapshot(self) -> dict:
        return {"levels": {k: round(v, 3) for k, v in self.levels.items()},
                "smiling": self.smiling_now, "looking": self.looking,
                "face_seen": self.face_seen}
