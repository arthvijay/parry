"""Mouth shapes from the timing data ElevenLabs already sends with every audio frame.

Each agent audio frame carries ``alignment``: the characters being spoken, with a start
time and duration for each, in milliseconds from the start of that frame. Spanish
spelling is nearly phonemic, so a small table turns those characters into visemes
accurately enough to drive a face, with no audio analysis and no extra API call.

The same timeline answers a second question: when a learner cuts a character off,
which words had actually been said? That is what lets a character react to being
interrupted instead of believing it finished its sentence.

Pure functions, no I/O.
"""

from __future__ import annotations

import re

# A deliberately small set a game rig can map to blendshapes: five vowels, and the
# consonant groups that are visibly different on a face.
VISEMES = ("sil", "A", "E", "I", "O", "U", "PBM", "FV", "L", "S", "TD", "KG", "R", "CH")

_VOWELS = {"a": "A", "á": "A", "e": "E", "é": "E", "i": "I", "í": "I", "y": "I",
           "o": "O", "ó": "O", "u": "U", "ú": "U", "ü": "U"}
_CONSONANTS = {"p": "PBM", "b": "PBM", "m": "PBM", "v": "PBM",  # b and v are one sound in Spanish
               "f": "FV", "l": "L", "s": "S", "z": "S", "x": "S",
               "t": "TD", "d": "TD", "n": "TD", "ñ": "TD",
               "k": "KG", "g": "KG", "j": "KG", "q": "KG", "w": "U", "r": "R"}
_TAG = re.compile(r"<[^>]*>|\[[^\]]*\]")


def _shape(chars: list[str], i: int) -> str | None:
    """The viseme for ``chars[i]``, or None when the letter makes no mouth shape."""
    ch = chars[i].lower()
    nxt = chars[i + 1].lower() if i + 1 < len(chars) else ""
    prev = chars[i - 1].lower() if i else ""
    if ch in _VOWELS:
        # The u in "que", "qui", "gue", "gui" is silent.
        if ch == "u" and prev in {"q", "g"} and nxt in {"e", "i", "é", "í"}:
            return None
        return _VOWELS[ch]
    if ch == "h":
        return None  # silent, and the h of "ch" is covered by the c
    if ch == "c":
        if nxt == "h":
            return "CH"
        return "S" if nxt in {"e", "i", "é", "í"} else "KG"
    if ch == "l" and nxt == "l":
        return "I"  # "ll" is a y sound
    if ch == "l" and prev == "l":
        return None
    return _CONSONANTS.get(ch)


def timeline(chars: list[str], starts_ms: list[int], durations_ms: list[int],
             offset_ms: int = 0) -> list[dict]:
    """Turn one frame's alignment into ``[{"t", "d", "v"}]`` on the reply's clock.

    Spaces and punctuation become ``sil`` so the mouth closes between words. Markup
    such as ``<despacio>`` or ``[laughs]`` is skipped: it is direction, not speech.
    Neighbouring identical shapes are merged so the client gets fewer, longer keys.
    """
    n = min(len(chars), len(starts_ms), len(durations_ms))
    chars = list(chars[:n])
    skip = set()
    for match in _TAG.finditer("".join(c if len(c) == 1 else " " for c in chars)):
        skip.update(range(match.start(), match.end()))
    keys: list[dict] = []
    for i in range(n):
        if i in skip:
            continue
        shape = _shape(chars, i) if chars[i].isalpha() else "sil"
        if shape is None:
            continue
        start, duration = offset_ms + int(starts_ms[i]), max(int(durations_ms[i]), 0)
        if keys and keys[-1]["v"] == shape:
            keys[-1]["d"] = max(keys[-1]["d"], start + duration - keys[-1]["t"])
        else:
            keys.append({"t": start, "d": duration, "v": shape})
    return keys


def heard_prefix(chars: list[str], starts_ms: list[int], heard_ms: int) -> str:
    """The part of a reply that had been spoken ``heard_ms`` into it, cut at a word.

    Used when the learner interrupts. Cutting mid-word would hand the character a
    fragment it never said, so the prefix is trimmed back to the last whole word.
    """
    spoken = "".join(c for c, start in zip(chars, starts_ms, strict=False) if start <= heard_ms)
    spoken = _TAG.sub("", spoken)
    if len(spoken) < len(_TAG.sub("", "".join(chars))):
        cut = max(spoken.rfind(" "), 0)
        spoken = spoken[:cut]
    return " ".join(spoken.split())
