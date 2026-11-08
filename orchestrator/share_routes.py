"""Pages and reports built from what the date already recorded.

    GET /v1/date/runs/{run_id}/card     the verdict as a shareable page (stamp, best line, grades)
    GET /v1/date/runs/{run_id}/verdict  the stored verdict, as JSON, without re-grading
    GET /v1/learners/{name}             one learner's profile: dates and practice list
    GET /v1/reports/class               every learner at a glance (?format=json for data)
    GET /v1/costs                       what the running server has spent, by provider

Everything here reads stored records; nothing calls a model. Text from the transcript
is escaped before it reaches a page.
"""

from __future__ import annotations

import asyncio
from html import escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import config, costs
from .date_models import DateVerdict
from .learner_profile import summary
from .run_records import records

STYLE = """
:root { --bg:#faf7f2; --card:#ffffff; --ink:#1f1d1a; --soft:#6b665e; --line:#e7e1d7;
        --match:#1f7a4d; --friend:#9a6b12; --ghost:#a3303a; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151412; --card:#1f1d1a; --ink:#f2eee7; --soft:#a9a397; --line:#36322c;
          --match:#5fd39a; --friend:#e7b75a; --ghost:#f07c86; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:640px; margin:0 auto; padding:24px 16px 48px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:24px; }
.brand { color:var(--soft); font-size:13px; letter-spacing:.08em; text-transform:uppercase; }
.stamp { font-size:clamp(28px,7vw,44px); font-weight:800; line-height:1.1; margin:12px 0 4px; }
.match { color:var(--match); } .friendzone { color:var(--friend); } .ghosted { color:var(--ghost); }
.meta, .soft { color:var(--soft); }
blockquote { margin:20px 0; padding:12px 16px; border-left:4px solid var(--line); font-size:18px; }
.grades { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px; margin:16px 0; }
.grade { border:1px solid var(--line); border-radius:10px; padding:8px 12px; }
.grade b { display:block; font-size:22px; }
h2 { font-size:15px; margin:24px 0 8px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--line); vertical-align:top; }
.wrap { overflow-x:auto; }
"""


def _page(title: str, description: str, body: str) -> HTMLResponse:
    name = escape(config.brand().name)
    html = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)} · {name}</title>"
            f"<meta property='og:title' content='{escape(title)} · {name}'>"
            f"<meta property='og:description' content='{escape(description)}'>"
            f"<meta name='description' content='{escape(description)}'>"
            f"<style>{STYLE}</style></head><body><main>{body}</main></body></html>")
    return HTMLResponse(html)


def best_line(verdict: DateVerdict) -> str | None:
    """The learner's own line worth sharing: a milestone's quote, else a pillar's."""
    for m in verdict.milestones:
        if m.achieved and m.evidence_quote:
            return m.evidence_quote
    return next((p.evidence_quote for p in verdict.pillars if p.evidence_quote), None)


def card_html(verdict: DateVerdict) -> HTMLResponse:
    brand = config.brand()
    quote = best_line(verdict)
    grades = "".join(f"<div class='grade'><span class='soft'>{escape(p.label)}</span>"
                     f"<b>{escape(p.grade or '—')}</b></div>" for p in verdict.pillars)
    follow = verdict.followup
    correction = ""
    if follow.correction is not None:
        correction = (f"<h2>Next time</h2><p>«{escape(follow.correction.better)}» instead of "
                      f"«{escape(follow.correction.heard)}». <span class='soft'>"
                      f"{escape(follow.correction.why_en)}</span></p>")
    progress = "".join(f"<li>«{escape(p.better)}» <span class='soft'>(you said: "
                       f"{escape(p.quote)})</span></li>" for p in verdict.progress)
    body = (f"<div class='card'><div class='brand'>{escape(brand.name)} · "
            f"{escape(brand.tagline)}</div>"
            f"<div class='stamp {escape(verdict.verdict)}'>{escape(verdict.stamp)}</div>"
            f"<div class='meta'>{escape(verdict.stamp_en)} · {escape(verdict.date_name)} · "
            f"{escape(verdict.city)} · {escape(verdict.dialect)}</div>"
            + (f"<blockquote>“{escape(quote)}”</blockquote>" if quote else "")
            + f"<div class='grades'><div class='grade'><span class='soft'>Overall</span>"
              f"<b>{escape(verdict.overall)}</b></div><div class='grade'><span class='soft'>"
              f"Chemistry</span><b>{verdict.final_chemistry}</b></div>{grades}</div>"
            + f"<h2>A text from {escape(follow.sender)}</h2><p>{escape(follow.text)}<br>"
              f"<span class='soft'>{escape(follow.translation_en)}</span></p>"
            + correction
            + (f"<h2>Said right this time</h2><ul>{progress}</ul>" if progress else "")
            + f"<p class='soft'>{escape(verdict.summary)}</p></div>")
    description = f"{verdict.stamp_en} with {verdict.date_name} in {verdict.city}" + (
        f": “{quote}”" if quote else "")
    return _page(f"{verdict.stamp_en} · {verdict.date_name}", description[:200], body)


def class_html(rows: list[dict]) -> HTMLResponse:
    cells = "".join(
        f"<tr><td>{escape(r['learner'])}</td><td>{r['dates']}</td>"
        f"<td>{r['matches']} / {r['friendzones']} / {r['ghosted']}</td>"
        f"<td>{escape(', '.join(r['dialects']))}</td><td>{escape(r['last_overall'] or '—')}</td>"
        f"<td>{r['fixed']}</td><td>{escape('; '.join(r['open_practice'])) or '—'}</td></tr>"
        for r in rows)
    total = sum(r["dates"] for r in rows)
    body = (f"<div class='card'><div class='brand'>{escape(config.brand().name)} · class report"
            f"</div><h1 class='stamp' style='font-size:28px'>{len(rows)} learners, {total} dates"
            f"</h1><div class='wrap'><table><thead><tr><th>Learner</th><th>Dates</th>"
            f"<th>Match / friend / ghosted</th><th>Dialects</th><th>Last grade</th>"
            f"<th>Fixed</th><th>Practising</th></tr></thead><tbody>"
            f"{cells or '<tr><td colspan=7 class=soft>No graded dates yet.</td></tr>'}"
            f"</tbody></table></div><p class='soft'>Practice items come only from lines the "
            f"learner certainly said; “fixed” means they later said the better version, "
            f"word for word.</p></div>")
    return _page("Class report", f"{len(rows)} learners, {total} dates", body)


def build_share_router() -> APIRouter:
    router = APIRouter(tags=["speed date records"])

    async def stored(request: Request, run_id: str) -> DateVerdict:
        try:
            return await asyncio.to_thread(records(request.app.state).verdicts.get, run_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "No graded date under this run_id yet") from None

    @router.get("/v1/date/runs/{run_id}/card", response_class=HTMLResponse)
    async def card(request: Request, run_id: str):
        return card_html(await stored(request, run_id))

    @router.get("/v1/date/runs/{run_id}/verdict", response_model=DateVerdict)
    async def verdict(request: Request, run_id: str):
        return await stored(request, run_id)

    @router.get("/v1/learners/{name}")
    async def learner(request: Request, name: str):
        try:
            profile = await asyncio.to_thread(records(request.app.state).learners.get, name)
        except ValueError:
            profile = None
        if profile is None:
            raise HTTPException(404, "No graded dates for this learner yet")
        return profile

    @router.get("/v1/reports/class")
    async def class_report(request: Request, format: str = "html", learners: str = ""):
        wanted = {n.strip().casefold() for n in learners.split(",") if n.strip()}
        profiles = await asyncio.to_thread(records(request.app.state).learners.all)
        rows = [summary(p) for p in profiles
                if not wanted or p.get("learner", "").casefold() in wanted]
        return {"learners": rows} if format == "json" else class_html(rows)

    @router.get("/v1/costs")
    async def spend():
        """Since this server started: usage and dollars by provider and model."""
        return {"plan": config.plan(), **costs.TOTAL.report().model_dump()}

    return router
