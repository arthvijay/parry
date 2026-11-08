"""What the date can see: the learner's face and gaze, turned into human signals.

Raw numbers (blendshape weights, head angles, whether the camera is pointed at the
date's face) become the things a person across the table would notice: a smile, a
laugh, a nod, a shake of the head, a puzzled look, a surprised one, looking away and
looking back. Each signal is debounced so a flicker is not a smile, and timed so it
counts only once per occurrence.

Faces differ and webcams sit in odd places, so every reading is taken relative to the
learner's own resting face. Each expression has a baseline (a low quantile of the last
~20 s), and the head pose has a centre (the median of on-screen poses, i.e. where the
screen is; looking away never moves it). A resting brow or a laptop camera below the
chin is not mistaken for a frown or for looking away. Until a few frames have
arrived, the baseline is zero.

Attention comes from the face as well as the game camera. The head turned well away
from the screen's centre, tilted well up or down (a phone in the lap), the eyes held off to
one side, or the face leaving the frame all count as looking away. When no face frames
are arriving at all, the face has no say and the game camera's gaze stands alone.

Signals go three places: to the vision panel's live feed (so the demo shows what the
date is picking up), to the chemistry director (a smile at a joke, looking away while
they talk), and to the date's own prompt as a [NONVERBAL] note, so they react the way a
person would.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

from .face_tracker import FaceReading


@dataclass
class Signal:
    kind: str        # smile | laugh | nod | shake | puzzled | surprised | frown | look_away | look_back
    label: str       # for the vision panel, e.g. "Smiling"
    note: str        # for the date's prompt
    during_npc: bool


NOTES = {
    "smile": "they smiled",
    "laugh": "they laughed",
    "nod": "they nodded along",
    "shake": "they shook their head",
    "puzzled": "they looked puzzled, maybe lost",
    "surprised": "they looked surprised",
    "frown": "they frowned",
    "look_away": "they looked away from you",
    "look_back": "they looked back at you",
}
LABELS = {
    "smile": "Smiling 😊", "laugh": "Laughing 😂", "nod": "Nodding 👍", "shake": "Head shake 🙅",
    "puzzled": "Puzzled 🤔", "surprised": "Surprised 😮", "frown": "Frowning 😕",
    "look_away": "Looking away 👀", "look_back": "Eye contact restored 👁️",
}

# Attention, relative to the learner's own centre pose. Degrees and blendshape weights.
SCREEN_YAW = 28.0        # head turned this far from centre is looking off-screen
SCREEN_PITCH = 20.0     # head tilted this far up or down from centre is off-screen
EYES_ASIDE = 0.65        # eyeLookIn/Out held this high is looking off to the side
FACE_LOST_SECONDS = 1.0  # face missing from frames for this long is out of frame
FRAMES_STALE_SECONDS = 1.5  # no frames for this long: the face has no say

# Per-channel baselines: the quantile that stands for "resting", and how much of a
# reading the baseline may ever absorb, so a long real expression is not erased.
_CHANNELS = {
    "smile": (0.2, 0.25), "jaw": (0.2, 0.15), "brow_down": (0.2, 0.3),
    "brow_up": (0.2, 0.3), "eye_wide": (0.2, 0.2), "frown": (0.2, 0.25),
    "squint": (0.2, 0.3),
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


class _Baseline:
    """One channel's resting level: a quantile of the last ``window`` readings, zero
    until ``warmup`` readings have arrived, never more than ``cap``."""

    def __init__(self, quantile: float, cap: float, window: int = 160, warmup: int = 12):
        self.quantile, self.cap, self.warmup = quantile, cap, warmup
        self.values: deque[float] = deque(maxlen=window)

    def add(self, value: float) -> float:
        """Record a reading and return the baseline it is measured against."""
        self.values.append(value)
        return self.level

    @property
    def level(self) -> float:
        if len(self.values) < self.warmup:
            return 0.0
        ordered = sorted(self.values)
        level = ordered[min(len(ordered) - 1, int(self.quantile * len(ordered)))]
        return max(-self.cap, min(self.cap, level))

    @property
    def ready(self) -> bool:
        return len(self.values) >= self.warmup


def _relative(raw: float, base: float) -> float:
    """A blendshape reading above its resting level, rescaled so the full 0 to 1 range
    is still reachable from a non-zero rest."""
    if base <= 0:
        return max(0.0, raw)
    return max(0.0, (raw - base) / (1.0 - base))


class NonverbalTracker:
    def __init__(self):
        self.smile = _Hold(0.35)
        self.laugh = _Hold(0.25, 0.8)
        self.puzzled = _Hold(0.8, 0.6)
        self.surprised = _Hold(0.3, 0.6)
        self.frown = _Hold(0.7, 0.6)
        self.away_hold = _Hold(0.5, 0.25)   # the face says "away" for a moment, not a blip
        self.head: deque[tuple[float, float, float]] = deque(maxlen=40)  # (t, pitch, yaw)
        self.baselines = {k: _Baseline(q, cap) for k, (q, cap) in _CHANNELS.items()}
        self.pose_pitch = _Baseline(0.5, 30.0)
        self.pose_yaw = _Baseline(0.5, 30.0)
        self.last_gesture = -10.0
        self.pending: list[str] = []
        self.levels: dict[str, float] = {}
        self.looking = True
        self.away_since: float | None = None
        self.called_out = False
        self.smiling_now = False
        self.face_seen = False
        # Attention from the face alone.
        self.last_frame_at: float | None = None
        self.last_face_at: float | None = None
        self.face_away = False
        self.away_reason: str | None = None
        self.relative_pose = (0.0, 0.0)
        # What the face showed over the whole date, for the report.
        self.frames = 0
        self.frames_with_face = 0
        self.frames_attentive = 0
        self.counts: Counter[str] = Counter()
        self.counts_during_npc: Counter[str] = Counter()

    # ---- face -----------------------------------------------------------------

    def face(self, reading: FaceReading, now: float, npc_speaking: bool) -> list[Signal]:
        self.frames += 1
        self.last_frame_at = now
        if not reading.found:
            self.smiling_now = False
            self._attention(now, found=False)
            return []
        self.face_seen = True
        self.frames_with_face += 1
        self.last_face_at = now
        s = reading.shape
        raw = {
            "smile": (s("mouthSmileLeft") + s("mouthSmileRight")) / 2,
            "jaw": s("jawOpen"),
            "brow_down": (s("browDownLeft") + s("browDownRight")) / 2,
            "brow_up": s("browInnerUp"),
            "eye_wide": (s("eyeWideLeft") + s("eyeWideRight")) / 2,
            "frown": (s("mouthFrownLeft") + s("mouthFrownRight")) / 2,
            "squint": (s("eyeSquintLeft") + s("eyeSquintRight")) / 2,
        }
        lv = {k: _relative(v, self.baselines[k].add(v)) for k, v in raw.items()}
        smile, jaw, brow_down, brow_up = lv["smile"], lv["jaw"], lv["brow_down"], lv["brow_up"]
        wide, frown, squint = lv["eye_wide"], lv["frown"], lv["squint"]
        blink = (s("eyeBlinkLeft") + s("eyeBlinkRight")) / 2
        # Eyes to one side: looking out with one eye is looking in with the other.
        eyes_aside = max((s("eyeLookOutLeft") + s("eyeLookInRight")) / 2,
                         (s("eyeLookInLeft") + s("eyeLookOutRight")) / 2)
        self.levels = {"smile": smile, "jaw": jaw, "brow_down": brow_down, "brow_up": brow_up,
                       "eye_wide": wide, "frown": frown, "blink": blink,
                       "eyes_aside": eyes_aside}
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
        gesture = self._head_gesture(now, reading.pitch, reading.yaw)
        if gesture:
            out.append(self._signal(gesture, npc_speaking))
        pitch = reading.pitch - self.pose_pitch.level
        yaw = reading.yaw - self.pose_yaw.level
        # The centre learns only from poses on the screen (or while it first warms up),
        # so holding the head turned away never drags the centre after it.
        if not self.pose_yaw.ready or (abs(yaw) <= SCREEN_YAW and abs(pitch) <= SCREEN_PITCH):
            self.pose_pitch.add(reading.pitch)
            self.pose_yaw.add(reading.yaw)
        self.relative_pose = (pitch, yaw)
        self._attention(now, found=True, pitch=pitch, yaw=yaw, eyes_aside=eyes_aside,
                        blink=blink)
        return out

    def _attention(self, now: float, found: bool, pitch: float = 0.0, yaw: float = 0.0,
                   eyes_aside: float = 0.0, blink: float = 0.0):
        """Whether the face says the learner is looking somewhere other than the screen."""
        reason = None
        if not found:
            if self.last_face_at is not None and now - self.last_face_at >= FACE_LOST_SECONDS:
                reason = "out_of_frame"
        elif abs(yaw) > SCREEN_YAW:
            reason = "head_turned"
        elif abs(pitch) > SCREEN_PITCH:
            # Either sign: dropped to a phone or tipped back, the screen is not in view.
            reason = "head_tilted"
        elif eyes_aside > EYES_ASIDE and blink < 0.5:
            reason = "eyes_aside"
        if reason is not None:
            self.away_reason = reason
        self.away_hold.update(reason is not None, now)
        self.face_away = self.away_hold.active
        if not self.face_away:
            self.away_reason = None
        if found and not self.face_away:
            self.frames_attentive += 1

    def attentive(self, now: float) -> bool:
        """The face's view: True unless recent frames show the learner looking away."""
        if self.last_frame_at is None or now - self.last_frame_at > FRAMES_STALE_SECONDS:
            return True
        return not self.face_away

    def _head_gesture(self, now: float, pitch: float, yaw: float) -> str | None:
        """A nod is pitch going down and up at least twice within ~1.5 s while yaw stays
        put; a shake is the same on yaw."""
        self.head.append((now, pitch, yaw))
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
        pitch_range, yaw_range = max(pitches) - min(pitches), max(yaws) - min(yaws)
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
        """The game camera's gaze, overruled by the face when it shows the learner
        looking away from the screen. ``self.looking`` holds the combined answer."""
        looking = looking and self.attentive(now)
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
            self.counts["look_away"] += 1
            self.counts_during_npc["look_away"] += 1
            self.pending.append(f"{NOTES['look_away']} for {self.looked_away_for(now):.0f} s "
                                "while you were talking")
            return True
        return False

    # ---- notes ----------------------------------------------------------------

    def _signal(self, kind: str, npc_speaking: bool) -> Signal:
        note = NOTES[kind] + (" while you were talking" if npc_speaking else "")
        self.counts[kind] += 1
        if npc_speaking:
            self.counts_during_npc[kind] += 1
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
        pitch, yaw = self.relative_pose
        return {"levels": {k: round(v, 3) for k, v in self.levels.items()},
                "smiling": self.smiling_now, "looking": self.looking,
                "face_seen": self.face_seen,
                "calibrated": self.pose_yaw.ready,
                "attentive": not self.face_away, "away_reason": self.away_reason,
                "relative_head": {"pitch": round(pitch, 1), "yaw": round(yaw, 1)}}

    def stats(self) -> dict:
        """What the face showed over the whole date: how often it was visible and on the
        screen, and how many of each signal (and how many while the date was talking)."""
        def pct(part: int, whole: int) -> int | None:
            return round(100 * part / whole) if whole >= 8 else None

        return {"frames": self.frames,
                "face_visible_pct": pct(self.frames_with_face, self.frames),
                "attentive_pct": pct(self.frames_attentive, self.frames_with_face),
                "signals": dict(self.counts),
                "signals_while_date_talked": dict(self.counts_during_npc)}
