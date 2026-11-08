"""Parry's registry: the brand, the dialects, the venues, the personas, the models and
the voices, in one place.

Everything the matchmaker, the live date and the grader need to agree on lives here,
so adding a dialect or a venue is one entry, not a hunt across modules. The brand is
read from the same ``BrandConfig.json`` the Unity client ships with, so the product
name exists in exactly one file.

Model ids, provider keys and voice ids come from the environment at call time (never
at import), so tests and a running server can change them without a restart.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache, cache
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BRAND_FILE = REPO / "My project" / "Assets" / "Resources" / "BrandConfig.json"
DIALECT_DIR = REPO / "scenarios" / "speed_dating" / "dialects"
PRESET_DIR = REPO / "scenarios" / "speed_dating" / "presets"

DATE_SECONDS = 180
START_CHEMISTRY = 50
WINGMAN_STALL_SECONDS = 4.0
LOOK_AWAY_CALLOUT_SECONDS = 4.5
MATCH_AT, FRIENDZONE_AT = 65, 45


# --------------------------------------------------------------------------- brand

@dataclass(frozen=True)
class Brand:
    name: str
    tagline: str
    description: str
    verdicts: dict[str, str]


_DEFAULT_BRAND = {
    "name": "Parry",
    "tagline": "Keep up. Flirt back. Speak like a local.",
    "description": "A cultural speed-dating simulator.",
    "verdicts": {"match": "SECOND DATE UNLOCKED", "friendzone": "FRIENDZONED",
                 "ghosted": "GHOSTED"},
}


@lru_cache(maxsize=1)
def brand() -> Brand:
    """The product name and copy, from the file the Unity client also reads."""
    data = dict(_DEFAULT_BRAND)
    try:
        data.update(json.loads(BRAND_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return Brand(name=str(data["name"]), tagline=str(data["tagline"]),
                 description=str(data["description"]),
                 verdicts={**_DEFAULT_BRAND["verdicts"], **dict(data.get("verdicts") or {})})


# --------------------------------------------------------------------------- dialects

@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    # Where in the city the date happens, for the persona's sense of place.
    neighbourhood: str


@dataclass(frozen=True)
class Dialect:
    code: str               # what the client sends and the response echoes, e.g. es-AR
    label: str              # "Argentine Spanish (Buenos Aires)"
    language: str           # ISO 639-1 for TTS/STT: es, zh, hi, ja, fr
    locale: str             # BCP 47 for the response's language_code
    cities: tuple[City, ...]
    register: str           # how the date speaks, for the persona prompt
    slang: tuple[str, ...]  # markers of local speech the director listens for
    # Nemotron ASR locale (Riva language_code): es-US for Latin American Spanish,
    # es-ES for Spain, "auto" where the model has no tuned locale.
    asr_language: str
    # Light, rough check that a learner line is in the target language at all.
    script: str = "latin"   # latin | han | devanagari | kana
    # What stiff, textbook register sounds like on a date in this dialect (a regex), or
    # empty where formal address is normal and warm.
    formal_marker: str = ""
    # How the receipt names it: "NEXT DATE UNLOCKED · KANSAI-BEN, OSAKA".
    nickname: str = ""

    @property
    def city(self) -> City:
        return self.cities[0]

    def city_named(self, name: str | None) -> City:
        for city in self.cities:
            if name and city.name.casefold() == name.casefold():
                return city
        return self.city


DIALECTS: dict[str, Dialect] = {d.code: d for d in (
    Dialect("es-MX", "Mexican Spanish (CDMX / Cancún)", "es", "es-MX",
            (City("Ciudad de México", 19.43, -99.13, "la Roma"),
             City("Cancún", 21.16, -86.85, "el centro, cerca de la playa")),
            "Informal Mexican Spanish with tú. Natural chilango warmth: güey between friends, "
            "qué onda, neta, padrísimo, ¿mande?, ahorita, órale, no manches.",
            ("güey", "wey", "qué onda", "neta", "padre", "padrísimo", "chido", "órale",
             "ahorita", "no manches", "mande", "chamba", "qué padre"),
            asr_language="es-US", formal_marker=r"\busted(es)?\b", nickname="Mexican Spanish"),
    Dialect("es-AR", "Argentine Spanish (Buenos Aires)", "es", "es-AR",
            (City("Buenos Aires", -34.60, -58.38, "Palermo"),),
            "Rioplatense Spanish with voseo (vos sos, tenés, decime, mirá), sh-sounding ll/y, "
            "and porteño colour: che, re copado, boludo only between close friends, posta, "
            "dale, qué sé yo, bárbaro, buenísimo.",
            ("che", "vos", "sos", "tenés", "decime", "re", "copado", "posta", "dale", "bárbaro",
             "boludo", "laburo", "mirá", "qué sé yo", "buenísimo"),
            asr_language="es-US", formal_marker=r"\busted(es)?\b", nickname="Porteño Spanish"),
    Dialect("es-ES", "Castilian Spanish (Madrid)", "es", "es-ES",
            (City("Madrid", 40.42, -3.70, "Malasaña"),),
            "Peninsular Spanish from Madrid with vosotros, a quick cadence and castizo colour: "
            "tío/tía, guay, vale, mola, flipar, qué fuerte, en plan, currar, a tope.",
            ("tío", "tía", "guay", "vale", "mola", "flipo", "flipar", "qué fuerte", "en plan",
             "currar", "curro", "a tope", "vosotros", "majo", "maja"),
            asr_language="es-ES", formal_marker=r"\busted(es)?\b", nickname="Madrileño Spanish"),
    Dialect("zh-CN", "Mandarin Chinese (Shanghai / Beijing)", "zh", "zh-CN",
            (City("Shanghai", 31.23, 121.47, "法租界 (the Former French Concession)"),
             City("Beijing", 39.90, 116.40, "三里屯 (Sanlitun)")),
            "Standard Mandarin as young urban professionals speak it: relaxed, warm, light "
            "particles (呀, 嘛, 吧, 哈), modern dating talk (加个微信, 有趣, 靠谱), and "
            "polite curiosity before personal questions.",
            ("呀", "嘛", "吧", "哈哈", "挺", "超", "靠谱", "有意思", "微信", "真的假的",
             "厉害", "好玩", "随便"),
            asr_language="auto", script="han", formal_marker="您", nickname="Mandarin"),
    Dialect("hi-IN", "Hinglish / Hindi (Mumbai / Delhi)", "hi", "hi-IN",
            (City("Mumbai", 19.08, 72.88, "Bandra"),
             City("Delhi", 28.61, 77.21, "Hauz Khas Village")),
            "Natural urban Hinglish: Hindi and English mixed mid-sentence the way young people "
            "in Mumbai and Delhi actually talk, with yaar, arre, scene kya hai, achha, bas, "
            "matlab, sahi hai, ekdum, chal.",
            ("yaar", "arre", "achha", "acha", "scene", "bas", "matlab", "sahi", "ekdum",
             "chal", "kya", "hai", "nahi", "bhai", "mast", "bilkul"),
            asr_language="hi-IN", script="devanagari", nickname="Hinglish"),
    Dialect("ja-JP", "Japanese (Tokyo standard)", "ja", "ja-JP",
            (City("Tokyo", 35.68, 139.69, "下北沢 (Shimokitazawa)"),),
            "Tokyo standard Japanese: polite です/ます at first, sliding into casual speech as "
            "the date warms up; soft aizuchi (へえ, そうなんだ, なるほど), never blunt.",
            ("へえ", "そうなんだ", "なるほど", "すごい", "めっちゃ", "やばい", "マジ",
             "ね", "よね", "かな"),
            asr_language="ja-JP", script="kana", nickname="Tokyo Japanese"),
    Dialect("ja-JP-kansai", "Japanese (Osaka Kansai-ben)", "ja", "ja-JP",
            (City("Osaka", 34.69, 135.50, "道頓堀 (Dōtonbori)"),),
            "Osaka Kansai-ben: quick banter and teasing, なんでやねん, めっちゃ, ほんま, "
            "あかん, ～へん, ～や instead of ～だ; jokes are expected and a straight man (tsukkomi) "
            "is appreciated.",
            ("なんでやねん", "ほんま", "めっちゃ", "あかん", "せや", "ちゃう", "おおきに",
             "へん", "やん", "ええやん"),
            asr_language="ja-JP", script="kana", nickname="Kansai-ben"),
    Dialect("fr-FR", "French (Parisian)", "fr", "fr-FR",
            (City("Paris", 48.86, 2.35, "le Marais"),),
            "Parisian French: rapid, with liaison and dropped ne (j'sais pas), dry wit and "
            "understatement, tu once the date is friendly, and everyday slang: grave, trop "
            "bien, ouf, kiffer, genre, bref, carrément, du coup.",
            ("grave", "trop", "ouf", "kiffe", "kiffer", "genre", "bref", "carrément", "du coup",
             "chelou", "sympa", "mec", "meuf", "bah", "ouais"),
            asr_language="fr-FR", formal_marker=r"\bvous\b", nickname="Parisian French"),
)}


# What a match unlocks next: a trip around the dialects, each a little further from home.
NEXT_DIALECT = {"es-MX": "es-AR", "es-AR": "ja-JP-kansai", "ja-JP-kansai": "fr-FR",
                "fr-FR": "zh-CN", "zh-CN": "es-ES", "es-ES": "hi-IN", "hi-IN": "ja-JP",
                "ja-JP": "es-MX"}


def dialect(code: str) -> Dialect:
    try:
        return DIALECTS[code]
    except KeyError:
        raise ValueError(f"Unknown language {code!r}") from None


@cache
def dialect_content(code: str) -> dict:
    """Authored lines for one dialect: offline personas, callouts, wingman fallbacks,
    closing lines and stamps. Data, not code, so a writer can tune it."""
    path = DIALECT_DIR / f"{code}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- culture

@dataclass(frozen=True)
class Norms:
    """How people in this place tend to read body language on a date. Tendencies the
    date and the judge take into account, not rules about people; authored per dialect
    in its data file so a native speaker can tune them."""

    look_away_seconds: float   # looking away longer than this while the date talks is noticed
    look_away_penalty: int     # what that costs, in chemistry points
    eye_contact: str           # steady | moderate | soft
    head_wobble: bool          # a side-to-side head wobble means "yes, go on" here
    note: str                  # one line for the persona prompt and the judge


def norms(code: str) -> Norms:
    raw = (dialect_content(code).get("nonverbal") or {}) if code in DIALECTS else {}
    return Norms(look_away_seconds=float(raw.get("look_away_seconds", LOOK_AWAY_CALLOUT_SECONDS)),
                 look_away_penalty=int(raw.get("look_away_penalty", 6)),
                 eye_contact=str(raw.get("eye_contact", "steady")),
                 head_wobble=bool(raw.get("head_wobble", False)),
                 note=str(raw.get("norms", "")))


def other_region_slang(code: str) -> dict[str, str]:
    """Words a local would place in another region ("güey" in Buenos Aires), mapped to
    that region, minus anything that is also local slang here."""
    own = {s.casefold() for s in dialect(code).slang}
    raw = dialect_content(code).get("other_region_slang") or {}
    return {word: region for word, region in raw.items() if word.casefold() not in own}


# --------------------------------------------------------------------------- plan and prices

def plan() -> str:
    """``PLAN=free`` moves the per-turn chemistry judge and the wingman to the rules,
    which removes most of a date's model calls; anything else is the full date."""
    return "free" if (os.getenv("PLAN") or "").strip().casefold() == "free" else "pro"


# Anthropic first-party list prices, USD per million tokens: input, output, cache read,
# cache write (5-minute TTL, 1.25x input). Override every Claude model at once with
# CLAUDE_PRICE_INPUT / _OUTPUT / _CACHE_READ / _CACHE_WRITE. The other providers have no
# built-in price: set theirs from their pricing pages, or a date reports usage only.
CLAUDE_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


@dataclass(frozen=True)
class Prices:
    claude: dict[str, tuple[float, float, float, float]]
    gemini: tuple[float, float] | None       # input, output per million tokens
    asr_per_minute: float | None            # NVIDIA speech recognition, per audio minute
    tts_per_million_chars: float | None     # ElevenLabs, per million characters


def _price(name: str) -> float | None:
    value = (os.getenv(name) or "").strip()
    try:
        return float(value) if value else None
    except ValueError:
        return None


def prices() -> Prices:
    claude = dict(CLAUDE_PRICES)
    override = [_price(f"CLAUDE_PRICE_{part}") for part in
                ("INPUT", "OUTPUT", "CACHE_READ", "CACHE_WRITE")]
    if all(value is not None for value in override):
        claude = {model: tuple(override) for model in [*claude, "*"]}
    g_in, g_out = _price("GEMINI_PRICE_INPUT"), _price("GEMINI_PRICE_OUTPUT")
    return Prices(claude=claude,
                  gemini=(g_in, g_out) if g_in is not None and g_out is not None else None,
                  asr_per_minute=_price("NVIDIA_ASR_PRICE_PER_MINUTE"),
                  tts_per_million_chars=_price("ELEVENLABS_PRICE_PER_MILLION_CHARS"))


# --------------------------------------------------------------------------- venues

@dataclass(frozen=True)
class Venue:
    id: str
    label: str
    scene: str               # Unity scene the venue is staged in
    lighting: str            # preset the client applies (colour temperature, fog, ambient)
    ambience: tuple[str, ...]
    keywords: tuple[str, ...]
    # One line the persona can use to know where they are.
    setting: str


VENUES: dict[str, Venue] = {v.id: v for v in (
    Venue("seaside_sunset_lounge", "Seaside Sunset Lounge", "CancunCafe", "warm_sunset_lounge",
          ("ocean_loop", "cafe_murmur_loop"),
          ("beach", "sea", "ocean", "seaside", "sunset", "coast", "playa", "lounge", "tropical"),
          "an open-air lounge by the sea at sunset, waves audible, warm light"),
    Venue("cozy_rain_cafe", "Cozy Rain-Streaked Café", "CancunCafe", "cool_rainy_evening",
          ("rain_loop", "cafe_murmur_loop"),
          ("rain", "rainy", "cozy", "café", "cafe", "coffee", "books", "storm", "lluvia"),
          "a small cosy café on a rainy evening, rain streaking the windows, coffee smell"),
    Venue("candlelit_modern_terrace", "Candlelit Modern Terrace", "SampleScene", "candlelit_night",
          ("garden_night_loop", "soft_jazz_loop"),
          ("candle", "candlelit", "terrace", "garden", "modern", "romantic", "dinner", "night"),
          "a candlelit terrace of a modern house, garden at night, quiet and intimate"),
    Venue("rooftop_bar", "Rooftop Bar", "SampleScene", "city_night_neon",
          ("city_night_loop", "cafe_murmur_loop"),
          ("rooftop", "bar", "cocktail", "skyline", "city", "drinks", "neon", "club"),
          "a rooftop bar above the city at night, skyline lights, low music"),
)}


def venue(venue_id: str) -> Venue:
    try:
        return VENUES[venue_id]
    except KeyError:
        raise ValueError(f"Unknown venue {venue_id!r}") from None


def venue_from_prompt(text: str, default: str = "seaside_sunset_lounge") -> str:
    """The venue whose keywords a free-text scene prompt mentions most."""
    words = (text or "").casefold()
    scored = sorted(((sum(k in words for k in v.keywords), v.id) for v in VENUES.values()),
                    reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else default


# --------------------------------------------------------------------------- personas

@dataclass(frozen=True)
class Archetype:
    id: str
    label: str
    traits: str              # how they behave, for the persona prompt
    resting_smile: float     # resting mouthSmile blendshape weight, 0-1
    speaking_rate: float
    voice_stability: float   # ElevenLabs stability: lower is more expressive
    # How much each turn can move chemistry; a reserved date is harder to win.
    volatility: float


ARCHETYPES: dict[str, Archetype] = {a.id: a for a in (
    Archetype("playful_sarcastic", "Playful & Sarcastic",
              "Teases textbook answers, loves banter and quick comebacks, tests you with a "
              "cheeky challenge early, rewards wit and a bit of attitude, gets bored by "
              "politeness alone.", 0.15, 1.05, 0.40, 1.15),
    Archetype("warm_romantic", "Warm & Romantic",
              "Attentive and expressive, smiles easily, asks about feelings, family and what "
              "makes you happy, remembers details and brings them back.", 0.30, 0.98, 0.50, 0.9),
    Archetype("reserved_intellectual", "Reserved Intellectual",
              "Speaks deliberately, dislikes small talk, lights up for ideas, books, science "
              "and real opinions, values active listening and follow-up questions.",
              0.05, 0.92, 0.60, 0.8),
    Archetype("high_energy_creative", "High-Energy Creative",
              "Fast talker, expressive and passionate about art, music and food, jumps "
              "between topics, loves enthusiasm and stories, hates flat answers.",
              0.25, 1.12, 0.35, 1.1),
)}


def archetype(archetype_id: str) -> Archetype:
    try:
        return ARCHETYPES[archetype_id]
    except KeyError:
        raise ValueError(f"Unknown personality archetype {archetype_id!r}") from None


@dataclass(frozen=True)
class Appearance:
    id: str
    label: str
    skin: str                # tint the client multiplies onto the skin materials
    hair: str


# Appearance only drives the 3D model. It never reaches the persona prompt: who someone
# is comes from the archetype and the learner's notes, not from how they look.
APPEARANCES: dict[str, Appearance] = {a.id: a for a in (
    Appearance("latina", "Latina / Latino", "#C99A78", "#2B1D16"),
    Appearance("east_asian", "East Asian", "#E3C3A3", "#151213"),
    Appearance("south_asian", "South Asian", "#A97856", "#16100D"),
    Appearance("southeast_asian", "Southeast Asian", "#C19272", "#18120F"),
    Appearance("black", "Black", "#6E4A35", "#110D0B"),
    Appearance("white", "White", "#EBCBB2", "#6B4A2E"),
    Appearance("middle_eastern", "Middle Eastern / North African", "#C09070", "#1C1411"),
    Appearance("mixed", "Mixed", "#B98A69", "#3A2619"),
)}

GENDERS = ("female", "male", "nonbinary")
BASE_MODELS = {"female": "Female_Adult_08", "male": "Male_Adult_08", "nonbinary": "Female_Adult_08"}


@dataclass(frozen=True)
class Level:
    cefr: str
    band: str                # beginner | intermediate | native
    tts_speed: float
    # Scales penalties: a beginner's stumble costs less chemistry than a fluent speaker's.
    forgiveness: float
    ambient_volume: float
    wingman_seconds: float


LEVELS: dict[str, Level] = {lv.cefr: lv for lv in (
    Level("A1", "beginner", 0.82, 0.5, 0.15, 4.0),
    Level("A2", "beginner", 0.88, 0.6, 0.2, 4.0),
    Level("B1", "intermediate", 0.95, 0.8, 0.3, 4.0),
    Level("B2", "intermediate", 1.0, 0.9, 0.35, 4.0),
    Level("C1", "native", 1.06, 1.0, 0.45, 4.5),
    Level("C2", "native", 1.1, 1.1, 0.5, 5.0),
)}


def level(cefr: str) -> Level:
    try:
        return LEVELS[cefr]
    except KeyError:
        raise ValueError(f"Unknown proficiency {cefr!r}") from None


# --------------------------------------------------------------------------- models

@dataclass(frozen=True)
class Models:
    """Who does which job. Claude does the thinking between rounds (building the date,
    judging chemistry, writing the receipt); Gemini Flash speaks during the date, where
    time to first token is what the learner feels."""

    anthropic_ready: bool
    matchmaker: str
    chemistry: str
    grader: str
    matchmaker_effort: str
    chemistry_effort: str
    grader_effort: str
    claude_fallbacks: bool
    gemini_ready: bool
    gemini_vertex: bool
    gemini_key: str | None
    gemini_project: str | None
    gemini_location: str
    date_brain: str
    date_brain_thinking: str


def models() -> Models:
    env = os.getenv
    sonnet = env("CLAUDE_MODEL") or "claude-sonnet-5-5"
    key = env("GEMINI_API_KEY") or env("GOOGLE_API_KEY") or None
    project = env("GOOGLE_CLOUD_PROJECT") or None
    return Models(
        anthropic_ready=bool(env("ANTHROPIC_API_KEY") or env("ANTHROPIC_AUTH_TOKEN")),
        matchmaker=env("MATCHMAKER_MODEL") or sonnet,
        chemistry=env("CHEMISTRY_MODEL") or sonnet,
        grader=env("DATE_GRADER_MODEL") or sonnet,
        matchmaker_effort=env("MATCHMAKER_EFFORT") or "medium",
        # Per turn and off the reply path, but a meter that lags a whole turn feels dead.
        chemistry_effort=env("CHEMISTRY_EFFORT") or "low",
        grader_effort=env("DATE_GRADER_EFFORT") or "medium",
        claude_fallbacks=(env("CLAUDE_FALLBACKS") or "1") != "0",
        gemini_ready=bool(key or project),
        gemini_vertex=key is None and project is not None,
        gemini_key=key, gemini_project=project,
        gemini_location=env("GOOGLE_CLOUD_LOCATION") or "global",
        date_brain=env("DATE_MODEL") or "gemini-3.8-flash",
        date_brain_thinking=env("DATE_THINKING_LEVEL") or "MINIMAL",
    )


# --------------------------------------------------------------------------- voices

# NVIDIA's hosted Nemotron ASR streaming function on build.nvidia.com. It is the English
# model; for Spanish point NEMOTRON_ASR_FUNCTION_ID at the multilingual (Nemotron 3.5)
# deployment, or NEMOTRON_ASR_SERVER at a self-hosted NIM ("type=multi", port 50051).
NEMOTRON_HOSTED_SERVER = "grpc.nvcf.nvidia.com:443"
NEMOTRON_HOSTED_FUNCTION = "bb0837de-8c7b-481f-9ec8-ef5663e9c1fa"
# NVIDIA's multilingual Nemotron has no hosted endpoint (self-hosted NIM only, which needs
# an NVIDIA GPU). Its hosted multilingual sibling on the same platform, key and protocol is
# Parakeet 1.1B RNNT Multilingual; non-English dates use it unless told otherwise.
NVIDIA_MULTILINGUAL_FUNCTION = "71203149-d3b7-4460-8231-1be2543a1fca"


@dataclass(frozen=True)
class Providers:
    nvidia_key: str | None
    asr_server: str
    asr_function_id: str
    asr_ssl: bool
    asr_language: str | None   # overrides every dialect's locale when set
    asr_multilingual_function_id: str
    elevenlabs_key: str | None
    elevenlabs_model: str


def providers() -> Providers:
    env = os.getenv
    server = env("NEMOTRON_ASR_SERVER") or NEMOTRON_HOSTED_SERVER
    return Providers(
        nvidia_key=env("NVIDIA_API_KEY") or None,
        asr_server=server,
        asr_function_id=env("NEMOTRON_ASR_FUNCTION_ID") or (
            NEMOTRON_HOSTED_FUNCTION if server == NEMOTRON_HOSTED_SERVER else ""),
        asr_ssl=(env("NEMOTRON_ASR_SSL") or ("1" if server.endswith(":443") else "0")) != "0",
        asr_language=env("NEMOTRON_ASR_LANGUAGE") or None,
        asr_multilingual_function_id=env("NVIDIA_ASR_MULTILINGUAL_FUNCTION_ID") or (
            NVIDIA_MULTILINGUAL_FUNCTION if server == NEMOTRON_HOSTED_SERVER else ""),
        elevenlabs_key=env("ELEVENLABS_API_KEY") or None,
        # Flash v2.5: ElevenLabs' lowest-latency multilingual model, and it streams over
        # the text-to-speech WebSocket.
        elevenlabs_model=env("ELEVENLABS_TTS_MODEL") or "eleven_flash_v2_5",
    )


@dataclass(frozen=True)
class VoiceChoice:
    provider: str
    voice_id: str


def _env_key(*parts: str) -> str:
    return "_".join(p.upper().replace("-", "_") for p in parts)


# ElevenLabs' premade voices, in every account; multilingual, but with a neutral accent.
# Set dialect voices (e.g. an Argentine voice from the Voice Library, added to My Voices)
# for a date that sounds local.
ELEVENLABS_DEFAULT_VOICES = {"female": "EXAVITQu4vr4xnSDxMaL", "male": "JBFqnCBsd6RMkjVDRZzb",
                             "nonbinary": "EXAVITQu4vr4xnSDxMaL"}


def voice_for(code: str, gender: str) -> VoiceChoice:
    """An ElevenLabs voice for this dialect and gender, configured as
    ELEVENLABS_VOICE_<DIALECT>_<GENDER> (e.g. ELEVENLABS_VOICE_ES_AR_FEMALE), else
    ELEVENLABS_VOICE_<GENDER>, else a premade voice. Without a key, the bundled sample."""
    if not providers().elevenlabs_key:
        return VoiceChoice("sample", "sample")
    voice = (os.getenv(_env_key("ELEVENLABS_VOICE", code, gender))
             or os.getenv(_env_key("ELEVENLABS_VOICE", gender))
             or ELEVENLABS_DEFAULT_VOICES.get(gender, ELEVENLABS_DEFAULT_VOICES["female"]))
    return VoiceChoice("elevenlabs", voice)


def preset(preset_id: str) -> dict:
    """An authored date (a demo scenario) by id."""
    path = PRESET_DIR / f"{preset_id}.json"
    if not preset_id.replace("_", "").isalnum() or not path.is_file():
        raise ValueError(f"Unknown preset {preset_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def presets() -> list[dict]:
    found = []
    for path in sorted(PRESET_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        variants = data.get("variants", {})
        dialect = DIALECTS.get(data["dialect"])
        found.append({"id": data["id"], "label": data["label"], "summary": data.get("summary", ""),
                      "dialect": data["dialect"], "city": data["city"]["name"],
                      # For the start screen's cards: who you'd meet, and in what language.
                      "venue": data.get("venue", {}).get("label", ""),
                      "language": (dialect.nickname or dialect.label) if dialect else data["dialect"],
                      "dates": {g: v.get("display_name", "") for g, v in variants.items()},
                      "lat": data["city"]["lat"], "lon": data["city"]["lon"],
                      "default_proficiency": data.get("default_proficiency", "B1")})
    return found


def catalog() -> dict:
    """What the matchmaker UI offers, so the client never hardcodes an option list."""
    return {
        "presets": presets(),
        "brand": {"name": brand().name, "tagline": brand().tagline},
        "date_seconds": DATE_SECONDS,
        "dialects": [{"code": d.code, "label": d.label, "language": d.language,
                      "cities": [{"name": c.name, "lat": c.lat, "lon": c.lon} for c in d.cities]}
                     for d in DIALECTS.values()],
        "venues": [{"id": v.id, "label": v.label, "scene": v.scene, "lighting": v.lighting}
                   for v in VENUES.values()],
        "archetypes": [{"id": a.id, "label": a.label} for a in ARCHETYPES.values()],
        "appearances": [{"id": a.id, "label": a.label, "skin": a.skin, "hair": a.hair}
                        for a in APPEARANCES.values()],
        "levels": [{"cefr": lv.cefr, "band": lv.band} for lv in LEVELS.values()],
        "genders": list(GENDERS),
    }
