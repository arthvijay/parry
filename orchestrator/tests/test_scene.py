"""Scene logic: pricing, tool dispatch and the endpoints that describe the cast.

No credentials, no network. Everything here is the part of the demo that must never
be wrong: a character must not invent a price, and a tool call must always be
answered even when the parameters are nonsense.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.app import create_app
from orchestrator.scene import RunState, ScenePack, spanish_number

PACK_DIR = Path(__file__).resolve().parent.parent.parent / "scenarios" / "cafe_cancun"


@pytest.fixture(scope="module")
def pack():
    return ScenePack.load(PACK_DIR)


# ---------------------------------------------------------------- numbers

@pytest.mark.parametrize("value,expected", [
    (0, "cero"), (15, "quince"), (21, "veintiuno"), (30, "treinta"),
    (45, "cuarenta y cinco"), (80, "ochenta"), (100, "cien"), (101, "ciento uno"),
    (120, "ciento veinte"), (195, "ciento noventa y cinco"), (200, "doscientos"),
    (999, "novecientos noventa y nueve"), (1000, "mil"), (1500, "mil quinientos"),
])
def test_spanish_number(value, expected):
    assert spanish_number(value) == expected


def test_spanish_number_out_of_range_falls_back_to_digits():
    assert spanish_number(-1) == "-1"
    assert spanish_number(10_000) == "10000"


# ---------------------------------------------------------------- the pack

def test_pack_loads_and_injects_the_menu(pack):
    assert pack.scenario.scenario_id == "cafe_cancun_v1"
    assert set(pack.npcs) == {"maria", "luis"}
    # The menu placeholder must be resolved, or the character sees a literal token.
    assert "[[MENU]]" not in pack.prompts["maria"]
    assert "cincuenta pesos" in pack.prompts["maria"]
    # Every dynamic variable the prompts use must be one the adapter always sends.
    for text in pack.prompts.values():
        for token in ("{{learner_name}}", "{{user_order}}", "{{learner_level}}"):
            text = text.replace(token, "")  # presence is optional, unknown ones are not
        assert "{{" not in text


def test_only_maria_can_take_an_order(pack):
    # No play_gesture: a tool call is a second LLM generation, and a nod on every
    # reply cost about a second of first-audio. Gestures are inferred server-side.
    assert set(pack.npcs["maria"].tools) == {"serve_order", "show_bill"}
    assert pack.npcs["luis"].tools == []


def test_voices_match_each_character_gender(pack):
    assert pack.npcs["maria"].gender == "female"
    assert pack.npcs["luis"].gender == "male"
    assert pack.npcs["maria"].voice_id != pack.npcs["luis"].voice_id


# ---------------------------------------------------------------- pricing

def test_order_is_priced_from_the_menu_not_the_model(pack):
    state = RunState()
    outcome = pack.dispatch("maria", "serve_order",
                            {"items": ["cafe_olla", "concha"]}, state)
    assert not outcome.is_error
    assert state.total_mxn == 80                      # 50 + 30
    assert "ochenta pesos" in outcome.result
    assert outcome.action["total_mxn"] == 80
    assert outcome.action["action"] == "serve_order"


def test_serve_order_declares_the_whole_order_and_replaces(pack):
    """The call carries the complete order, so a later call supersedes the earlier."""
    state = RunState()
    pack.dispatch("maria", "serve_order", {"items": ["americano"]}, state)
    pack.dispatch("maria", "serve_order", {"items": ["americano", "concha"]}, state)
    assert state.items == ["americano", "concha"]
    assert state.total_mxn == 75


def test_repeated_identical_order_does_not_double_charge(pack):
    """Regression: the model re-called serve_order while confirming, billing twice."""
    state = RunState()
    first = pack.dispatch("maria", "serve_order",
                          {"items": ["cafe_olla", "concha"]}, state)
    second = pack.dispatch("maria", "serve_order",
                           {"items": ["cafe_olla", "concha"]}, state)
    assert state.total_mxn == 80                 # not 160
    assert state.items == ["cafe_olla", "concha"]
    assert first.action is not None              # one cup appears...
    assert second.action is None                 # ...and not a second one
    assert not second.is_error
    assert "already placed" in second.result


def test_repeat_detection_ignores_item_order(pack):
    state = RunState()
    pack.dispatch("maria", "serve_order", {"items": ["cafe_olla", "concha"]}, state)
    again = pack.dispatch("maria", "serve_order", {"items": ["concha", "cafe_olla"]}, state)
    assert again.action is None
    assert state.total_mxn == 80


def test_bill_reports_the_running_total(pack):
    state = RunState()
    pack.dispatch("maria", "serve_order", {"items": ["latte"]}, state)
    outcome = pack.dispatch("maria", "show_bill", {}, state)
    assert "sesenta y cinco pesos" in outcome.result
    assert outcome.action["total_mxn"] == 65
    assert state.bill_shown


def test_bill_before_ordering_is_a_readable_error(pack):
    outcome = pack.dispatch("maria", "show_bill", {}, RunState())
    assert outcome.is_error
    assert outcome.action is None
    assert "Nothing has been ordered" in outcome.result


# ---------------------------------------------------------------- bad input

def test_sold_out_item_is_refused_with_a_recoverable_message(pack):
    state = RunState()
    outcome = pack.dispatch("maria", "serve_order", {"items": ["pay_limon"]}, state)
    assert outcome.is_error
    assert "sold out" in outcome.result
    assert state.items == []          # nothing was charged for


def test_unknown_item_lists_the_valid_ones(pack):
    outcome = pack.dispatch("maria", "serve_order", {"items": ["pizza"]}, RunState())
    assert outcome.is_error
    assert "cafe_olla" in outcome.result
    assert "pay_limon" not in outcome.result     # never offer the sold-out item


def test_comma_separated_string_is_accepted(pack):
    """Models sometimes send "concha,concha" instead of a JSON array."""
    state = RunState()
    outcome = pack.dispatch("maria", "serve_order", {"items": "concha, concha"}, state)
    assert not outcome.is_error
    assert state.total_mxn == 60


@pytest.mark.parametrize("params", [{}, {"items": []}, {"items": None}, None, "nonsense"])
def test_malformed_order_never_raises(pack, params):
    outcome = pack.dispatch("maria", "serve_order", params, RunState())
    assert outcome.is_error and outcome.result   # always something to say


def test_order_is_capped(pack):
    state = RunState()
    pack.dispatch("maria", "serve_order", {"items": ["concha"] * 500}, state)
    assert len(state.items) <= 12


def test_unknown_tool_is_answered_not_raised(pack):
    outcome = pack.dispatch("luis", "launch_rocket", {}, RunState())
    assert outcome.is_error and "Unknown tool" in outcome.result


def test_gesture_produces_an_action_and_rejects_invented_ones(pack):
    good = pack.dispatch("luis", "play_gesture", {"gesture": "wave"}, RunState())
    assert good.action == {"action": "play_gesture", "npc_id": "luis", "gesture": "wave"}
    bad = pack.dispatch("luis", "play_gesture", {"gesture": "backflip"}, RunState())
    assert bad.action is None      # non-blocking, so silently dropped


# ---------------------------------------------------------------- order handoff

def test_order_summary_is_spanish_for_the_other_character(pack):
    state = RunState()
    assert state.order_summary_es(pack.menu) == "nada"
    pack.dispatch("maria", "serve_order",
                  {"items": ["cafe_olla", "concha", "concha"]}, state)
    summary = state.order_summary_es(pack.menu)
    assert "Café de olla" in summary and "dos Concha" in summary


# ---------------------------------------------------------------- endpoints

def test_npcs_endpoint_describes_the_cast():
    with TestClient(create_app(pack=ScenePack.load(PACK_DIR))) as client:
        body = client.get("/v1/npcs").json()
    assert body["scenario_id"] == "cafe_cancun_v1"
    by_id = {n["npc_id"]: n for n in body["npcs"]}
    assert set(by_id) == {"maria", "luis"}
    assert by_id["maria"]["greeting"].startswith("¡Buenas tardes!")
    assert "serve_order" in by_id["maria"]["actions"]
    assert "serve_order" not in by_id["luis"]["actions"]   # only the waitress serves
    assert by_id["maria"]["ready"] is False        # no agent configured in tests
    assert len(body["menu"]) == 10
    assert [g["id"] for g in body["goals"]] == ["introduce", "hometown", "order"]


def test_health_reports_the_loaded_pack():
    with TestClient(create_app(pack=ScenePack.load(PACK_DIR))) as client:
        assert client.get("/health").json()["scenario_pack"] == "cafe_cancun_v1"


def test_alias_lets_an_older_client_id_keep_working(pack):
    """Unity still calls the waitress 'mariana'; the scenario declares that alias."""
    assert pack.resolve("mariana") == "maria"
    assert pack.resolve("maria") == "maria"
    assert pack.resolve("luis") == "luis"
    assert pack.resolve("nobody") == "nobody"   # unknown ids pass through untouched


def test_npcs_endpoint_exposes_aliases():
    with TestClient(create_app(pack=ScenePack.load(PACK_DIR))) as client:
        body = client.get("/v1/npcs").json()
    maria = next(n for n in body["npcs"] if n["npc_id"] == "maria")
    assert "mariana" in maria["aliases"]


# ---------------------------------------------------------------- sound and voice data

def test_scene_actions_carry_their_sound_effect(pack):
    state = RunState()
    served = pack.dispatch("maria", "serve_order", {"items": ["cafe_olla"]}, state)
    assert served.action["sfx"] == "/v1/ambience/cup_on_table"
    billed = pack.dispatch("maria", "show_bill", {}, state)
    assert billed.action["sfx"] == "/v1/ambience/receipt"


def test_repeat_order_and_unmapped_tools_make_no_sound(pack):
    """The cup is set down once. A repeat has no action, so it has nothing to carry."""
    state = RunState()
    pack.dispatch("maria", "serve_order", {"items": ["concha"]}, state)
    again = pack.dispatch("maria", "serve_order", {"items": ["concha"]}, state)
    assert again.action is None
    gesture = pack.dispatch("luis", "play_gesture", {"gesture": "nod"}, state)
    assert "sfx" not in gesture.action


def test_action_sfx_must_name_a_declared_sound(pack):
    from orchestrator.scene import ScenarioFile
    data = pack.scenario.model_dump()
    data["action_sfx"] = {"serve_order": "foghorn"}
    with pytest.raises(ValueError, match="unknown ambience id"):
        ScenarioFile.model_validate(data)


def test_ambience_path_only_resolves_declared_ids(pack):
    assert pack.ambience_path("ocean_loop").name == "ocean_loop.mp3"
    assert pack.ambience_path("../menu.json") is None
    assert pack.ambience_path("ocean_loop.mp3") is None


def test_every_character_can_slow_down_in_its_own_voice(pack):
    """<despacio> is a multi-voice label; it must exist or the tag is read aloud."""
    for npc in pack.npcs.values():
        labels = {v.label: v for v in npc.supported_voices}
        assert "despacio" in labels and labels["despacio"].speed < npc.tts.speed
        assert "<despacio>" in pack.prompts[npc.npc_id]

