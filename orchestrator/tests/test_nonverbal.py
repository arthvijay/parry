"""The face reader's calibration and attention: readings are relative to the learner's
own resting face, and the face can overrule the game camera's gaze."""

from orchestrator.face_tracker import FaceReading
from orchestrator.nonverbal import NonverbalTracker

FPS = 8


def reading(found=True, pitch=0.0, yaw=0.0, **shapes) -> FaceReading:
    return FaceReading(found=found, blendshapes=dict(shapes), pitch=pitch, yaw=yaw)


def feed(t: NonverbalTracker, start: float, seconds: float, make, talking=False):
    """Feed ``make(i)`` readings at 8 fps; return the signal kinds and the end time."""
    kinds, n = [], int(seconds * FPS)
    for i in range(n):
        kinds += [s.kind for s in t.face(make(i), start + i / FPS, talking)]
    return kinds, start + n / FPS


def test_a_resting_brow_is_not_read_as_puzzled():
    t = NonverbalTracker()
    rest = {"browDownLeft": 0.4, "browDownRight": 0.4}
    kinds, now = feed(t, 0.0, 20.0, lambda i: reading(**rest))
    # A flicker of "puzzled" while the baseline warms up, then nothing for the rest.
    assert kinds.count("puzzled") <= 1
    later, now = feed(t, now, 10.0, lambda i: reading(**rest))
    assert "puzzled" not in later
    # A real furrow on top of that resting brow still reads.
    furrow = {"browDownLeft": 0.85, "browDownRight": 0.85}
    kinds, _ = feed(t, now + 2.0, 2.0, lambda i: reading(**furrow))
    assert "puzzled" in kinds


def test_a_long_real_smile_is_not_absorbed_by_the_baseline():
    t = NonverbalTracker()
    _, now = feed(t, 0.0, 25.0, lambda i: reading(mouthSmileLeft=0.8, mouthSmileRight=0.8))
    assert t.smiling_now


def test_a_camera_off_to_the_side_is_the_centre_not_looking_away():
    t = NonverbalTracker()
    _, now = feed(t, 0.0, 5.0, lambda i: reading(yaw=35.0, pitch=-22.0))
    assert t.attentive(now)
    assert t.snapshot()["calibrated"]
    # Turning from that centre is looking away.
    _, now = feed(t, now, 1.0, lambda i: reading(yaw=-5.0, pitch=-22.0))
    assert not t.attentive(now) and t.away_reason == "head_turned"


def test_looking_down_and_eyes_aside_and_leaving_the_frame_are_away():
    for make, reason in [
        (lambda i: reading(pitch=-30.0), "head_tilted"),
        (lambda i: reading(pitch=30.0), "head_tilted"),
        (lambda i: reading(eyeLookOutLeft=0.8, eyeLookInRight=0.8), "eyes_aside"),
        (lambda i: reading(found=False), "out_of_frame"),
    ]:
        t = NonverbalTracker()
        _, now = feed(t, 0.0, 3.0, lambda i: reading())
        assert t.attentive(now)
        _, now = feed(t, now, 2.0, make)
        assert not t.attentive(now), reason
        assert t.snapshot()["away_reason"] == reason


def test_a_blink_or_a_glance_is_not_looking_away():
    t = NonverbalTracker()
    _, now = feed(t, 0.0, 3.0, lambda i: reading())
    _, now = feed(t, now, 0.25, lambda i: reading(yaw=60.0))
    assert t.attentive(now)
    _, now = feed(t, now, 1.0, lambda i: reading(eyeLookDownLeft=0.9, eyeLookDownRight=0.9,
                                                 eyeBlinkLeft=0.9, eyeBlinkRight=0.9))
    assert t.attentive(now)


def test_the_face_overrules_the_camera_gaze_and_stops_when_frames_stop():
    t = NonverbalTracker()
    _, now = feed(t, 0.0, 3.0, lambda i: reading())
    _, now = feed(t, now, 2.0, lambda i: reading(yaw=50.0))
    t.gaze(True, 0.0, now, True)
    assert t.looking is False
    # No frames for a while: the face has no say, the camera's gaze stands.
    kinds = [s.kind for s in t.gaze(True, 0.0, now + 3.0, True)]
    assert t.looking is True and kinds == ["look_back"]


def test_the_look_away_callout_counts_time_the_face_was_away():
    t = NonverbalTracker()
    _, now = feed(t, 0.0, 3.0, lambda i: reading())
    called = False
    for i in range(int(6 * FPS)):
        at = now + i / FPS
        t.face(reading(yaw=50.0), at, True)
        t.gaze(True, 0.0, at, True)
        called = t.look_away_episode(at, 4.5, True) or called
    assert called


def test_stats_summarise_the_date():
    t = NonverbalTracker()
    _, now = feed(t, 0.0, 4.0, lambda i: reading())
    feed(t, now, 2.0, lambda i: reading(mouthSmileLeft=0.9, mouthSmileRight=0.9), talking=True)
    stats = t.stats()
    assert stats["frames"] == 48 and stats["face_visible_pct"] == 100
    assert stats["attentive_pct"] == 100
    assert stats["signals"].get("smile") == 1
    assert stats["signals_while_date_talked"].get("smile") == 1
    assert NonverbalTracker().stats()["face_visible_pct"] is None
