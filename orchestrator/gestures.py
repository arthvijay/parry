"""Body language chosen from what a character said, not asked of its language model.

Gestures used to be a tool the agent called. Every tool call costs a second model
round trip, so a nod added about a second to the reply it accompanied, on most turns.
Latency is the thing a learner feels first, and a nod does not need a language model:
the words already say which gesture fits. This picks one from the reply text in
microseconds, so the body still moves and the voice arrives a second sooner.

Pure function, no I/O. At most one gesture per reply, and often none: a character
that gestures on every line looks like a puppet.
"""

from __future__ import annotations

import re
import unicodedata

# Checked in order; the first match wins. Patterns are matched on lower-cased text
# with accents removed, so "¿qué?" and "que" are the same.
_RULES: tuple[tuple[str, re.Pattern], ...] = tuple((name, re.compile(pattern)) for name, pattern in (
    ("laugh", r"\bja(ja)+\b|\bjeje|no manches|que chistoso|me da risa"),
    ("wave", r"\b(hola|buenas tardes|buenos dias|buenas noches|bienvenid[oa]|adios|hasta luego|"
             r"nos vemos|que te vaya bien|pasale)\b"),
    ("shake_head", r"\b(no hay|se me acabo|se acabo|no tenemos|no tengo|lo siento|uy)\b"),
    ("point_menu", r"\b(tenemos|en el menu|la carta|te recomiendo|hay de|ofrezco)\b"),
    ("think", r"\b(a ver|dejame ver|dejame pensar|mmm+|pues)\b"),
    ("shrug", r"\b(no se|quien sabe|ni idea|mas o menos|depende)\b"),
    ("lean_in", r"\b(neta|en serio|de verdad|cuentame|y tu que|a poco|fijate que|que padre)\b"),
    ("nod", r"\b(claro|perfecto|con gusto|por supuesto|ahorita|muy bien|exacto|asi es|"
            r"de acuerdo|va|sale|orale|si)\b"),
))


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")


def infer(text: str, allowed: list[str] | tuple[str, ...] | None = None,
          last: str | None = None) -> str | None:
    """The gesture that fits this reply, or None.

    `allowed` is the scenario's gesture list. `last` is the previous gesture for this
    character: repeating it back to back is skipped, which is what stops the endless
    nodding a rule like this would otherwise produce.
    """
    plain = _plain(text or "")
    for name, pattern in _RULES:
        if allowed and name not in allowed:
            continue
        if pattern.search(plain):
            return None if name == last else name
    return None
