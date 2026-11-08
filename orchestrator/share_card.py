"""The shareable receipt: a 1080×1920 (9:16) card for TikTok, Reels and Shorts.

Drawn as plain SVG, so it needs no imaging library and the browser can turn it into a
PNG: the verdict printed on receipt paper (chemistry, the four pillars with the learner's
own words, what it unlocks), the rubber stamp across it, and the roast underneath. The
share page around it downloads the image, opens the system share sheet where the browser
has one (on a phone that is where TikTok, Instagram and YouTube live), and otherwise saves
the image, copies a caption and opens the platform's upload page.

Everything on the card comes from the saved verdict; nothing is invented here.
"""

from __future__ import annotations

import html
import json
import unicodedata

from . import config
from .date_models import DateVerdict

W, H = 1080, 1920
PAPER_X, PAPER_W = 140, 800
CREAM, INK, MUTED = "#f7ecdf", "#2a1820", "#7a6370"
COLORS = {"match": "#ff3d6e", "friendzone": "#ffb454", "ghosted": "#7fa6ff"}
MONO = "'JetBrains Mono', Menlo, Consolas, 'DejaVu Sans Mono', 'Noto Sans Mono', monospace"
SANS = "'Bricolage Grotesque', 'Segoe UI', 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
SCRIPT = "Yellowtail, 'Brush Script MT', 'Segoe Script', cursive"


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _width(ch: str) -> float:
    return 1.0 if unicodedata.east_asian_width(ch) in "WF" else 0.6


def wrap(text: str, size: int, width: float, max_lines: int) -> list[str]:
    """Greedy wrap by estimated glyph width (wide CJK glyphs count double), with an
    ellipsis when it runs past ``max_lines``."""
    text = " ".join((text or "").split())
    limit = width / size
    lines, line, used = [], "", 0.0
    tokens = []
    for word in text.split(" "):
        # CJK has no spaces: let it break anywhere.
        tokens.extend(list(word) if any(_width(c) == 1.0 for c in word) else [word])
    for token in tokens:
        cjk = len(token) == 1 and _width(token) == 1.0
        piece = token if (cjk or not line) else " " + token
        need = sum(_width(c) for c in piece)
        if used + need > limit and line:
            lines.append(line)
            line, used = token, sum(_width(c) for c in token)
        else:
            line, used = line + piece, used + need
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip()[: max(1, int(limit) - 1)] + "…"
    return lines


def _text(x: float, y: float, s: str, size: int, fill: str, *, family: str = MONO,
          weight: int = 400, anchor: str = "start", italic: bool = False) -> str:
    style = " font-style=\"italic\"" if italic else ""
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{style}>{esc(s)}</text>')


def _dashes(y: float) -> str:
    return (f'<line x1="{PAPER_X + 40}" y1="{y:.0f}" x2="{PAPER_X + PAPER_W - 40}" y2="{y:.0f}" '
            f'stroke="{MUTED}" stroke-opacity=".55" stroke-width="3" stroke-dasharray="12 8"/>')


def render_svg(v: DateVerdict) -> str:
    brand = config.brand().name
    color = COLORS.get(v.verdict, COLORS["ghosted"])
    left, right = PAPER_X + 40, PAPER_X + PAPER_W - 40
    inner = right - left
    body: list[str] = []
    y = 330.0

    def line(s: str, size: int, fill: str = INK, **kw):
        nonlocal y
        body.append(_text(PAPER_W / 2 + PAPER_X if kw.get("anchor") == "middle" else left, y, s, size, fill, **kw))
        y += size * 1.35

    line(f"{brand.upper()} · DATE VERDICT", 34, weight=800, anchor="middle")
    y += 4
    line(f"{v.venue} · {v.city}", 24, MUTED, anchor="middle")
    for part in wrap(f"{v.dialect} · {v.date_name} ({v.persona})", 24, inner, 2):
        line(part, 24, MUTED, anchor="middle")
    y += 6
    body.append(_dashes(y))
    y += 52

    # Chemistry, and a dotted bar.
    body.append(_text(left, y, "CHEMISTRY", 28, INK, weight=800))
    body.append(_text(right, y + 6, f"{v.final_chemistry}%", 64, INK, weight=800, anchor="end"))
    y += 34
    filled = inner * max(0, min(100, v.final_chemistry)) / 100
    x = 0.0
    while x + 12 <= filled:
        body.append(f'<rect x="{left + x:.0f}" y="{y:.0f}" width="12" height="20" fill="{INK}"/>')
        x += 18
    for mark in (config.FRIENDZONE_AT, config.MATCH_AT):
        mx = left + inner * mark / 100
        body.append(f'<rect x="{mx - 2:.0f}" y="{y - 6:.0f}" width="4" height="32" fill="{MUTED}" opacity=".7"/>')
    y += 56
    body.append(_dashes(y))
    y += 50

    # The four pillars, with the learner's own words.
    for i, p in enumerate(v.pillars[:4], 1):
        body.append(_text(left, y, f"{i:02d} {p.label.upper()}"[:34], 25, INK, weight=800))
        body.append(_text(right, y, p.grade or "—", 30, INK, weight=800, anchor="end"))
        y += 36
        if p.evidence_quote:
            for part in wrap(f"“{p.evidence_quote}”", 24, inner - 40, 2):
                body.append(_text(left + 40, y, part, 24, INK, italic=True))
                y += 32
        y += 14
    body.append(_dashes(y))
    y += 50
    if v.next_date is not None:
        for part in wrap(v.next_date.headline, 26, inner, 2):
            line(part, 26, color, weight=800, anchor="middle")
    paper_bottom = y + 10

    # Paper, a scalloped tear, then the stamp across the pillars.
    paper = [f'<rect x="{PAPER_X + 14}" y="{270}" width="{PAPER_W}" height="{paper_bottom - 250:.0f}" '
             f'fill="#000" opacity=".35" rx="6"/>',
             f'<rect x="{PAPER_X}" y="{250}" width="{PAPER_W}" height="{paper_bottom - 250:.0f}" fill="{CREAM}" rx="4"/>']
    paper += [f'<circle cx="{PAPER_X + 10 + k * 20}" cy="{paper_bottom:.0f}" r="11" fill="{CREAM}"/>'
              for k in range(PAPER_W // 20)]
    stamp_text = v.stamp or config.brand().verdicts.get(v.verdict, "")
    sw = max(460, int(sum(_width(c) for c in stamp_text) * 66 * 0.95) + 90)
    cy = 250 + (paper_bottom - 250) * 0.56
    cx = PAPER_X + PAPER_W / 2
    stamp = [f'<g transform="rotate(-13 {cx:.0f} {cy:.0f})" opacity=".9">',
             f'<rect x="{cx - sw / 2:.0f}" y="{cy - 78:.0f}" width="{sw}" height="156" rx="16" '
             f'fill="{color}" fill-opacity=".07" stroke="{color}" stroke-width="9"/>',
             f'<rect x="{cx - sw / 2 + 16:.0f}" y="{cy - 62:.0f}" width="{sw - 32}" height="124" rx="10" '
             f'fill="none" stroke="{color}" stroke-width="3"/>',
             _text(cx, cy + 14, stamp_text, 66, color, family=SANS, weight=900, anchor="middle")]
    if v.stamp_en and v.stamp_en != stamp_text:
        stamp.append(_text(cx, cy + 50, v.stamp_en.upper(), 24, color, family=SANS, weight=800, anchor="middle"))
    stamp.append("</g>")

    # The roast, in a bubble under the receipt.
    roast_lines = wrap(v.roast, 38, 820, 4) if v.roast else []
    ry = paper_bottom + 60
    roast: list[str] = []
    if roast_lines:
        rh = 96 + len(roast_lines) * 50
        roast += [f'<rect x="110" y="{ry:.0f}" width="860" height="{rh}" rx="34" fill="#2b0d1f" '
                  f'stroke="{COLORS["match"]}" stroke-opacity=".7" stroke-width="3"/>',
                  _text(150, ry + 58, "THE ROAST", 26, "#ffb454", weight=800)]
        for k, part in enumerate(roast_lines):
            roast.append(_text(150, ry + 112 + k * 50, part, 38, CREAM, family=SANS, weight=700))
        ry += rh

    # Then the date texts: their follow-up, as a notification, when there is room.
    f = v.followup
    if f is not None and f.text:
        text_lines = wrap(f.text, 32, 700, 3)
        gloss = wrap(f.translation_en, 24, 700, 2)
        fh = 136 + len(text_lines) * 44 + len(gloss) * 32
        fy = ry + 44
        if fy + fh < H - 120:
            initial = (v.date_name or "?")[0].upper()
            roast += [f'<rect x="110" y="{fy:.0f}" width="860" height="{fh}" rx="30" fill="#1d0a16" '
                      f'stroke="#f7ecdf" stroke-opacity=".14" stroke-width="2"/>',
                      f'<circle cx="170" cy="{fy + 62:.0f}" r="34" fill="{color}"/>',
                      _text(170, fy + 74, initial, 34, "#120710", family=SANS, weight=900, anchor="middle"),
                      _text(222, fy + 58, f"{v.date_name} texted you", 28, CREAM, family=SANS, weight=800),
                      _text(222, fy + 90, "now", 22, "#8d7381", family=SANS)]
            ty = fy + 140
            for part in text_lines:
                roast.append(_text(150, ty, part, 32, CREAM, family=SANS))
                ty += 44
            for part in gloss:
                roast.append(_text(150, ty, part, 24, "#c9b1bd", family=SANS, italic=True))
                ty += 32

    head = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
            "<defs><radialGradient id='g1' cx='.2' cy='.05' r='.7'><stop offset='0' stop-color='#ff3d6e' "
            "stop-opacity='.35'/><stop offset='1' stop-color='#ff3d6e' stop-opacity='0'/></radialGradient>"
            "<radialGradient id='g2' cx='.9' cy='.95' r='.7'><stop offset='0' stop-color='#ffb454' "
            "stop-opacity='.25'/><stop offset='1' stop-color='#ffb454' stop-opacity='0'/></radialGradient></defs>",
            f'<rect width="{W}" height="{H}" fill="#120710"/>',
            f'<rect width="{W}" height="{H}" fill="url(#g1)"/><rect width="{W}" height="{H}" fill="url(#g2)"/>',
            _text(W / 2, 150, brand, 110, COLORS["match"], family=SCRIPT, anchor="middle"),
            _text(W / 2, 205, config.brand().tagline, 28, "#c9b1bd", family=SANS, anchor="middle")]
    foot = [_text(W / 2, H - 70, f"3-minute speed date · {v.city}", 28, "#8d7381", family=SANS, anchor="middle"),
            "</svg>"]
    return "\n".join(head + paper + body + stamp + roast + foot)


def caption(v: DateVerdict) -> str:
    brand = config.brand().name
    tag = "".join(ch for ch in brand if ch.isalnum())
    roast = f" 🔥 “{v.roast}”" if v.roast else ""
    return (f"{v.stamp_en} on a 3-minute speed date with {v.date_name} in {v.city}: "
            f"{v.final_chemistry}% chemistry.{roast} #{tag} #languagelearning #speeddating")


PLATFORMS = (("TikTok", "https://www.tiktok.com/upload"),
             ("Reels", "https://www.instagram.com/"),
             ("Shorts", "https://www.youtube.com/upload"))


def render_page(v: DateVerdict) -> str:
    brand = esc(config.brand().name)
    run = esc(v.run_id)
    text = caption(v)
    data = json.dumps({"caption": text, "file": f"{config.brand().name.lower()}-{v.run_id}.png"},
                      ensure_ascii=False).replace("</", "<\\/")
    buttons = "".join(f'<button data-go="{esc(url)}">{esc(name)}</button>' for name, url in PLATFORMS)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{brand} · {esc(v.stamp_en)}</title>
<meta property="og:title" content="{brand} · {esc(v.stamp_en)} at {v.final_chemistry}%">
<meta property="og:description" content="{esc(v.roast)}">
<style>
body{{margin:0;min-height:100vh;background:#120710;color:#f7ecdf;font-family:{SANS};display:flex;justify-content:center}}
main{{display:flex;gap:40px;align-items:center;padding:32px;flex-wrap:wrap;justify-content:center}}
img{{height:min(86vh,1100px);aspect-ratio:9/16;border-radius:18px;box-shadow:0 30px 80px #000a}}
.side{{max-width:380px}} h1{{font-size:28px;margin:0 0 6px}} p{{color:#c9b1bd;line-height:1.45}}
.row{{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}}
button{{font:inherit;font-weight:700;padding:12px 20px;border-radius:999px;border:1px solid #f7ecdf33;background:#2b0d1f;color:#f7ecdf;cursor:pointer}}
button.primary{{background:#ff3d6e;border-color:#ff3d6e}} button:hover{{filter:brightness(1.15)}}
#caption{{font-size:14px;background:#ffffff0d;padding:12px;border-radius:12px}} #status{{color:#7cf5e4;min-height:1.4em}}
</style></head><body><main>
<img id="card" src="/v1/date/receipt/{run}.svg" alt="{esc(v.stamp_en)} receipt">
<div class="side"><h1>Share your receipt</h1>
<p>9:16, sized for TikTok, Reels and Shorts.</p>
<div class="row"><button class="primary" id="share">Share…</button><button id="dl">Download image</button></div>
<div class="row">{buttons}</div>
<p id="caption"></p><div class="row"><button id="copy">Copy caption</button></div>
<p id="status"></p></div></main>
<script>
const DATA = {data};
const $ = id => document.getElementById(id);
$("caption").textContent = DATA.caption;
async function png() {{
  const img = new Image(); img.src = $("card").src; await img.decode();
  const c = document.createElement("canvas"); c.width = {W}; c.height = {H};
  c.getContext("2d").drawImage(img, 0, 0, {W}, {H});
  return await new Promise(r => c.toBlob(r, "image/png"));
}}
function save(blob) {{
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = DATA.file; a.click();
}}
async function copy() {{ try {{ await navigator.clipboard.writeText(DATA.caption); return true; }} catch (e) {{ return false; }} }}
$("dl").onclick = async () => {{ save(await png()); $("status").textContent = "Saved."; }};
$("copy").onclick = async () => {{ $("status").textContent = (await copy()) ? "Caption copied." : "Select the caption to copy it."; }};
$("share").onclick = async () => {{
  const blob = await png(); const file = new File([blob], DATA.file, {{type: "image/png"}});
  if (navigator.canShare && navigator.canShare({{files: [file]}})) {{
    try {{ await navigator.share({{files: [file], text: DATA.caption}}); return; }} catch (e) {{ if (e.name === "AbortError") return; }}
  }}
  save(blob); await copy();
  $("status").textContent = "Image saved and caption copied: post it from TikTok, Instagram or YouTube.";
}};
for (const b of document.querySelectorAll("[data-go]")) b.onclick = async () => {{
  const w = window.open("about:blank", "_blank");
  save(await png()); const copied = await copy();
  $("status").textContent = "Image saved" + (copied ? " and caption copied" : "") + ": upload it on " + b.textContent + ".";
  if (w) w.location = b.dataset.go;
}};
</script></body></html>"""
