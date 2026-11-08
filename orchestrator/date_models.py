"""Wire contracts for the speed date: the matchmaker's request and the date it builds,
the live events the stream sends, and the verdict the receipt prints.

Kept apart from ``models.py`` so the café's contracts stay exactly as they were.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config
from .models import LetterGrade

Short = Annotated[str, Field(min_length=1, max_length=200)]
Line = Annotated[str, Field(min_length=1, max_length=1200)]
DateId = Annotated[str, Field(pattern=r"^date_[a-z0-9_]{1,80}$")]
RunId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
MilestoneId = Literal["break_ice", "find_common_ground", "cultural_vibe", "close_the_date"]
VerdictKind = Literal["match", "friendzone", "ghosted"]
Posture = Literal["lean_forward_smile", "neutral", "lean_back_glance_away"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- matchmaker

class MatchmakerRequest(Model):
    learner_name: Annotated[str, Field(max_length=60)] = ""
    language: str = "es-MX"
    proficiency: Literal["A1", "A2", "B1", "B2", "C1", "C2"] = "B1"
    # A venue id, or "auto" to let the scene prompt choose.
    venue_style: str = "auto"
    date_gender: Literal["female", "male", "nonbinary"] = "female"
    # Appearance only: drives the 3D model's skin and hair, never the personality.
    date_ethnicity: str = "mixed"
    personality_archetype: str = "playful_sarcastic"
    custom_notes: Annotated[str, Field(max_length=600)] = ""
    # Free text describing the world: "a rooftop bar at sunset after the rain".
    scene_prompt: Annotated[str, Field(max_length=600)] = ""
    city: Annotated[str, Field(max_length=60)] | None = None

    @field_validator("language")
    @classmethod
    def _language(cls, value: str) -> str:
        config.dialect(value)
        return value

    @field_validator("venue_style")
    @classmethod
    def _venue(cls, value: str) -> str:
        if value != "auto":
            config.venue(value)
        return value

    @field_validator("date_ethnicity")
    @classmethod
    def _appearance(cls, value: str) -> str:
        if value not in config.APPEARANCES:
            raise ValueError(f"Unknown appearance {value!r}")
        return value

    @field_validator("personality_archetype")
    @classmethod
    def _archetype(cls, value: str) -> str:
        config.archetype(value)
        return value


class AvatarConfig(Model):
    base_model: str
    skin_tint: str
    hair_tint: str
    outfit_style: str
    resting_smile_weight: Annotated[float, Field(ge=0, le=1)]


class VoiceConfig(Model):
    provider: Literal["fish", "sample"]
    # Fish Audio voice model (reference_id); empty means Fish's default voice.
    voice_id: str
    speaking_rate: Annotated[float, Field(ge=0.5, le=2.0)]
    temperature: Annotated[float, Field(ge=0, le=1)]
    latency: Literal["low", "normal", "balanced"]


class Milestone(Model):
    id: MilestoneId
    text: Short
    core: bool
    # What the learner has to say for it to count; the director quotes against this.
    evidence_required: Line


class DateCharacter(Model):
    id: Literal["date_npc"] = "date_npc"
    display_name: Short
    gender: Literal["female", "male", "nonbinary"]
    age: Annotated[int, Field(ge=21, le=45)]
    occupation: Short
    interests: Annotated[list[Short], Field(min_length=2, max_length=6)]
    backstory: Line
    avatar_config: AvatarConfig
    voice_config: VoiceConfig
    opening_line: Line
    system_prompt: Annotated[str, Field(min_length=1, max_length=8000)]
    green_flags: Annotated[list[Short], Field(min_length=2, max_length=6)]
    red_flags: Annotated[list[Short], Field(min_length=2, max_length=6)]


class HostCharacter(Model):
    id: Literal["host"] = "host"
    display_name: Short
    gender: Literal["female", "male", "nonbinary"]
    greeting: Line
    chat_lines: list[Line]
    avatar_config: AvatarConfig
    voice_config: VoiceConfig


class VenueInfo(Model):
    id: str
    label: Short
    setting: Line
    ambience: list[str]
    lighting_preset: str


class CulturalMoment(Model):
    """One local custom the date brings up mid-date (mate in Buenos Aires, a tsukkomi in
    Osaka), authored in the dialect's data. It sharpens the cultural_vibe milestone."""

    id: Short
    milestone: Short
    cue: Line                 # the stage direction the date gets, in English
    keywords: list[str] = []  # words the offline judge listens for


class PracticeTarget(Model):
    """A phrasing the learner got wrong on an earlier date, carried into this one so
    the date gives them a natural chance to say it right."""

    heard: Line
    better: Line
    why_en: Line


class DateScenario(Model):
    scenario_id: DateId
    city: Short
    language_code: str
    dialect: str
    dialect_label: Short
    proficiency: str
    learner_name: str
    venue_scene: str
    lighting_preset: str
    venue: VenueInfo
    scene_description: Line
    personality_archetype: str
    date_character: DateCharacter
    host_character: HostCharacter
    milestones: Annotated[list[Milestone], Field(min_length=1, max_length=6)]
    date_seconds: int
    wingman_seconds: float
    chemistry_start: int
    generated_by: Literal["model", "template"]
    cultural_moment: CulturalMoment | None = None
    practice: Annotated[list[PracticeTarget], Field(max_length=3)] = []


# --------------------------------------------------------------------------- live events

class ChemistryUpdate(Model):
    type: Literal["chemistry_update"] = "chemistry_update"
    chemistry_score: Annotated[int, Field(ge=0, le=100)]
    delta: int
    mood_label: str
    reason: str
    npc_posture: Posture
    completed_milestones: list[str]
    evidence_quotes: dict[str, str]
    green_flags_hit: list[str] = []
    red_flags_hit: list[str] = []
    source: Literal["turn", "nonverbal", "wingman", "timer"] = "turn"


class WingmanOption(Model):
    tone: str
    target: Line
    gloss: Line


class WingmanHint(Model):
    type: Literal["wingman_hint"] = "wingman_hint"
    whisper_context: Line
    options: Annotated[list[WingmanOption], Field(min_length=3, max_length=3)]


# --------------------------------------------------------------------------- verdict

class DateGradeRequest(Model):
    run_id: RunId
    scenario_id: DateId


class Pillar(Model):
    id: Literal["icebreaker", "dialect_authenticity", "active_listening", "agility_pacing"]
    label: str
    grade: LetterGrade | None
    comment: Line
    evidence_quote: Line | None


class MilestoneResult(Model):
    id: str
    text: str
    achieved: bool
    evidence_quote: str | None


class Correction(Model):
    heard: Line
    better: Line
    why_en: Line


class FollowUp(Model):
    sender: Short
    text: Line
    translation_en: Line
    correction: Correction | None


class DateMetrics(Model):
    turns: int
    learner_words: int
    avg_response_latency_ms: int | None
    pronunciation_confidence_pct: int | None
    wingman_hints_used: int
    wingman_lines_used: int
    unassisted_fluency_pct: int
    eye_contact_pct: int | None
    smiles: int
    look_away_callouts: int
    barge_ins: int
    # How the learner hesitated and addressed the date, measured from their own lines.
    local_fillers: int = 0
    foreign_fillers: int = 0
    register_used: Literal["casual", "formal", "mixed"] | None = None
    # Words the recogniser was unsure of: an impression of what to practise, not a score.
    words_to_practise: list[str] = []
    # Slang from another region the learner used ("güey" in Buenos Aires).
    other_region_words: list[str] = []


class ProgressItem(Model):
    """A phrasing missed on an earlier date and said right on this one, quoted."""

    better: Line
    quote: Line


class CostLine(Model):
    provider: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    audio_seconds: float = 0.0
    characters: int = 0
    characters_cached: int = 0
    usd: float | None = None


class DateCost(Model):
    """What one date cost to run, by provider. ``usd`` is None for a provider with no
    configured price, and ``total_usd`` then covers only the priced lines."""

    lines: list[CostLine]
    total_usd: float | None
    complete: bool


class DateVerdict(Model):
    scenario_id: str
    run_id: str
    verdict: VerdictKind
    stamp: str
    stamp_en: str
    final_chemistry: int
    venue: str
    city: str
    date_name: str
    persona: str
    dialect: str
    pillars: list[Pillar]
    milestones: list[MilestoneResult]
    metrics: DateMetrics
    followup: FollowUp
    overall: LetterGrade
    summary: Line
    chemistry_timeline: list[int]
    graded_by: Literal["model", "rules"]
    progress: list[ProgressItem] = []
    cost: DateCost | None = None
