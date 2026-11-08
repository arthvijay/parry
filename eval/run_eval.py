"""The director's gate: a goal ticked that the learner did not earn fails the build.

A tick is the one piece of grading the learner sees live, in the middle of a
conversation, so a wrong one teaches the wrong thing at the worst moment. A late tick
costs nothing (every open goal is looked at again next turn); a false one cannot be
taken back. So this measures recall but gates on precision: any false award exits 1.

It runs the path that ships: `OpenAIDirector.review` with its real instructions, input
layout, timeout and schema, followed by the same in-code quote rule `Director` applies.
A call that times out counts as a miss, never as a pass, because that is what the
learner would experience.

The rubric is the live pack's goals plus the harder goals of the full visit (price,
follow-up, small talk, repair), so the adversarial cases have something to tempt the
model with even while the demo pack is kept to three easy quests.

    uv run python eval/run_eval.py --model gpt-5.6-luna --effort none --repeats 3
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "orchestrator" / ".env", override=False)

from orchestrator.director import OpenAIDirector, said_by_learner  # noqa: E402
from orchestrator.models import RubricGoal, TranscriptTurn  # noqa: E402

CONCURRENCY = 6

# The full visit's goals that the three-quest demo pack leaves out.
EXTRA_GOALS = [
    RubricGoal(id="ask_price", npc_id="maria", core=True,
               label="Ask what something costs, before being told",
               evidence_required="The learner asks a price question in Spanish (¿cuánto cuesta…?, "
               "¿cuánto es?, ¿cuánto le debo?, ¿a cómo está…?) before Maria volunteers the price "
               "or the total. Asking after Maria has already said the price does not count."),
    RubricGoal(id="small_talk", npc_id="luis", core=True, label="Hold a personal conversation",
               evidence_required="At least two full-clause statements about themselves in Spanish "
               "across at least three back-and-forth exchanges with Luis. One-word answers do "
               "not count."),
    RubricGoal(id="follow_up", npc_id="luis", core=True,
               label="Ask a follow-up about something Luis said",
               evidence_required="The learner asks Luis a question in Spanish that refers to "
               "content from one of Luis's previous two turns. A bare '¿y tú?' or an unrelated "
               "question does not count."),
    RubricGoal(id="repair", npc_id="any", core=False, label="Recover in Spanish when lost",
               evidence_required="The learner uses a Spanish repair phrase at least once (¿cómo?, "
               "¿mande?, ¿puedes repetir?, más despacio por favor, no entendí). Switching to "
               "English does not count."),
]


def load_rubric() -> list[RubricGoal]:
    pack = json.loads((ROOT / "scenarios/cafe_cancun/scenario.json").read_text(encoding="utf-8"))
    goals = [RubricGoal(id=g["id"], npc_id=g["npc_id"], core=g["core"], label=g["label"],
                        evidence_required=g["evidence_required"]) for g in pack["goals"]]
    return goals + [g for g in EXTRA_GOALS if g.id not in {x.id for x in goals}]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))] if ordered else 0.0


async def run(args) -> int:
    rubric = load_rubric()
    known = {goal.id for goal in rubric}
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    for case in cases:
        if not set(case["expected"]) <= known:
            sys.exit(f"{case['id']}: expected {case['expected']} is not in the rubric {sorted(known)}")

    director = OpenAIDirector(os.environ["OPENAI_API_KEY"], args.model, effort=args.effort)
    try:
        await director.warm_up()
    except Exception as error:  # noqa: BLE001
        print(f"warm-up failed ({type(error).__name__}); first calls may be slow")

    gate = asyncio.Semaphore(CONCURRENCY)
    latencies, tokens, errors = [], [0, 0], []
    false_awards, missed, dropped = [], [], []
    stats = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    async def one(case, repeat):
        transcript = [TranscriptTurn.model_validate(turn) for turn in case["transcript"]]
        async with gate:
            started = time.perf_counter()
            try:
                verdict = await director.review(rubric, transcript, rubric=rubric)
                used = director.last_usage
            except Exception as error:  # noqa: BLE001 — a failed call is a miss for the learner
                errors.append(f"{case['id']}#{repeat}: {type(error).__name__}")
                verdict, used = None, (0, 0)
            latencies.append(time.perf_counter() - started)
        tokens[0] += used[0]
        tokens[1] += used[1]
        awarded = {}
        for tick in verdict.achieved if verdict else []:
            if tick.id in known and said_by_learner(tick.evidence_quote, transcript):
                awarded[tick.id] = tick.evidence_quote
            else:
                dropped.append(f"{case['id']}#{repeat}: {tick.id} ← {tick.evidence_quote!r}")
        expected = set(case["expected"])
        for goal in known:
            if goal in awarded and goal in expected:
                stats[goal]["tp"] += 1
            elif goal in awarded:
                stats[goal]["fp"] += 1
                false_awards.append(f"{case['id']}#{repeat}: {goal} ← {awarded[goal]!r}  "
                                    f"({case['note']})")
            elif goal in expected:
                stats[goal]["fn"] += 1
                missed.append(f"{case['id']}#{repeat}: {goal}")

    await asyncio.gather(*(one(case, r) for r in range(args.repeats) for case in cases))
    await director.aclose()

    print(f"\n{args.model}  effort={args.effort}  {len(cases)} cases x {args.repeats}\n")
    print(f"{'goal':<12}{'precision':>10}{'recall':>8}{'tp':>5}{'fp':>5}{'fn':>5}")
    total = {"tp": 0, "fp": 0, "fn": 0}
    for goal in rubric:
        s = stats[goal.id]
        for key in total:
            total[key] += s[key]
        print(f"{goal.id:<12}{ratio(s['tp'], s['fp']):>10}{ratio(s['tp'], s['fn']):>8}"
              f"{s['tp']:>5}{s['fp']:>5}{s['fn']:>5}")
    print(f"{'ALL':<12}{ratio(total['tp'], total['fp']):>10}{ratio(total['tp'], total['fn']):>8}"
          f"{total['tp']:>5}{total['fp']:>5}{total['fn']:>5}")
    print(f"\nlatency p50 {statistics.median(latencies):.2f}s  p95 {percentile(latencies, .95):.2f}s"
          f"   cached tokens {tokens[1] / tokens[0]:.0%} of {tokens[0]}" if tokens[0] else "")
    print(f"errors/timeouts: {len(errors)}" + "".join(f"\n  {e}" for e in errors[:10]))
    print(f"ticks dropped by the quote rule: {len(dropped)}" + "".join(f"\n  {d}" for d in dropped))
    print(f"missed (looked at again next turn in a real run): {len(missed)}"
          + "".join(f"\n  {m}" for m in missed))
    print(f"\nFALSE AWARDS: {len(false_awards)}" + "".join(f"\n  {f}" for f in false_awards))
    return 1 if false_awards else 0


def ratio(hit: int, miss: int) -> str:
    return f"{hit / (hit + miss):.2f}" if hit + miss else "-"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--effort", default="none")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", default=str(Path(__file__).with_name("director_cases.jsonl")))
    sys.exit(asyncio.run(run(parser.parse_args())))
