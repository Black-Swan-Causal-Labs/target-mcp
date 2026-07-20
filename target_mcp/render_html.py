"""HTML writer for the completed TARGET checklist.

A self-contained, single-file HTML page (all CSS inline, no external assets) so
it renders identically in any browser on any host — Claude, an OpenAI client, or
a plain file open. Committed to a single light "canvas" theme (matching the
Black Swan Causal Labs registry) so it never flips to a dark background in a
dark-mode viewer.

Pure serializer of a `render.render_checklist` report: no scoring, no spec
access. Carries the same provenance stamp as the Markdown and .docx renderers.
"""

from __future__ import annotations

import html
from typing import Any

from . import render as _render
from .spec import SECTIONS

_VERDICT = {
    "reported": ("Reported", "p-rep"),
    "partial": ("Partial", "p-par"),
    "not_reported": ("Not reported", "p-not"),
    "not_applicable": ("N/A", "p-na"),
    "not_assessed": ("Not assessed", "p-na"),
}

_CSS = """
  *, *::before, *::after { box-sizing: border-box; }
  :root {
    --paper:#F4F1E8; --surface:#FAF8F1; --ink:#111412; --ink-soft:#4B4E47; --ink-faint:#8A8C81;
    --line:#111412; --line-soft:rgba(17,20,18,.15); --accent:#15655A; --oxblood:#9B3A2E;
    --rep:#2E6B34; --rep-bg:rgba(46,107,52,.12); --par:#9A6714; --par-bg:rgba(154,103,20,.13);
    --not:#9B3A2E; --not-bg:rgba(155,58,46,.11); --na:#6E6D62; --na-bg:rgba(110,109,98,.12);
    --font:"Times New Roman", Times, Georgia, serif; --maxw:1120px;
  }
  body { margin:0; background:var(--paper); color:var(--ink); font-family:var(--font); font-size:16px; line-height:1.5; }
  .wrap { max-width:var(--maxw); margin:0 auto; padding:clamp(20px,4vw,52px) clamp(16px,4vw,40px) 72px; }
  .eyebrow { font-size:13px; letter-spacing:.2em; text-transform:uppercase; font-weight:700; margin:0 0 14px; }
  h1 { font-weight:700; font-size:clamp(1.7rem,3.4vw,2.5rem); line-height:1.12; margin:0 0 8px; width:100%; letter-spacing:-.01em; }
  .subtitle { font-weight:700; font-style:italic; font-size:1.3rem; color:var(--accent); margin:0 0 16px; width:100%; }
  .citation { font-style:italic; font-size:.95rem; color:var(--ink-soft); width:100%; margin:0 0 18px; line-height:1.45; }
  .meta { display:flex; flex-direction:column; gap:4px; padding:12px 15px; background:var(--surface); border:1.5px solid var(--line); }
  .meta .ms { font-weight:700; font-size:1.02rem; }
  .meta .instr { font-size:.95rem; color:var(--ink-soft); line-height:1.4; }
  .rule-bar { height:11px; background:var(--line); margin:22px 0 0; }
  .rule-bar.foot { margin:0 0 14px; }
  .summary { margin:26px 0 8px; }
  .summary h2 { font-size:13px; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-faint); font-weight:700; margin:0 0 11px; }
  .meter { display:flex; height:16px; overflow:hidden; border:1.5px solid var(--line); }
  .meter span { display:block; }
  .seg-rep { background:var(--rep); } .seg-par { background:var(--par); } .seg-not { background:var(--not); } .seg-na { background:var(--na); }
  .legend { display:flex; flex-wrap:wrap; gap:8px 24px; margin-top:13px; }
  .legend div { display:flex; align-items:center; gap:8px; font-size:.95rem; color:var(--ink-soft); }
  .legend b { color:var(--ink); font-variant-numeric:tabular-nums; font-weight:700; }
  .dot { width:11px; height:11px; flex:none; border:1px solid var(--line); }
  .table-wrap { margin-top:26px; overflow-x:auto; border:2px solid var(--line); background:var(--surface); }
  table { border-collapse:collapse; width:100%; min-width:900px; table-layout:fixed; }
  th { text-align:left; font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink); font-weight:700; padding:12px 14px; border-bottom:2px solid var(--line); background:var(--paper); }
  td { padding:12px 14px; border-bottom:1px solid var(--line-soft); vertical-align:top; font-size:1rem; word-wrap:break-word; }
  .section-row td { border-top:2px solid var(--line); border-bottom:2px solid var(--line); font-weight:700; font-size:1.08rem; letter-spacing:.05em; text-transform:uppercase; padding:10px 14px; background:var(--paper); }
  .group-row td { border-bottom:1px solid var(--line-soft); font-weight:700; font-size:.78rem; letter-spacing:.07em; text-transform:uppercase; color:var(--accent); padding:7px 14px; }
  .col-id { font-weight:700; color:var(--ink); white-space:nowrap; font-variant-numeric:tabular-nums; }
  .grp { display:block; font-size:10.5px; letter-spacing:.08em; text-transform:uppercase; color:var(--accent); font-weight:700; margin-bottom:2px; }
  .pill { display:inline-block; font-size:13px; font-weight:700; padding:2px 10px; border:1.5px solid; white-space:nowrap; }
  .p-rep { color:var(--rep); background:var(--rep-bg); border-color:var(--rep); }
  .p-par { color:var(--par); background:var(--par-bg); border-color:var(--par); }
  .p-not { color:var(--not); background:var(--not-bg); border-color:var(--not); }
  .p-na  { color:var(--na);  background:var(--na-bg);  border-color:var(--na); }
  .loc { font-size:1rem; color:var(--ink-soft); }
  .loc.supp { color:var(--accent); font-weight:700; }
  .loc.none { color:var(--ink-faint); font-style:italic; }
  .quote { display:block; border-left:2px solid var(--line); padding-left:10px; color:var(--ink); font-size:1rem; line-height:1.42; }
  .quote.none { border-left-color:var(--line-soft); color:var(--ink-faint); font-style:italic; }
  .rationale { display:block; margin-top:5px; color:var(--ink-soft); font-size:1rem; line-height:1.42; }
  footer { margin-top:30px; }
  footer p { font-style:italic; font-size:.9rem; color:var(--ink-faint); margin:0 0 6px; width:100%; }
  .stamp { font-style:normal; font-weight:700; color:var(--ink-soft); }
"""


def _esc(text: str) -> str:
    return html.escape(text or "")


def _evidence_html(row: dict[str, Any]) -> str:
    verdict = row["verdict"]
    quotes = [ev for ev in row.get("evidence", []) if ev.get("quote", "").strip()]
    if quotes:
        parts = []
        for ev in quotes:
            mark = "" if ev.get("resolved", True) else " <em>(unresolved)</em>"
            parts.append(f'<span class="quote">“{_esc(ev["quote"].strip())}”{mark}</span>')
        rationale = (row.get("rationale") or "").strip()
        if rationale:
            parts.append(f'<span class="rationale">{_esc(rationale)}</span>')
        return "".join(parts)
    # not_reported / not_assessed / N/A: show the rationale as a muted note
    note = (row.get("rationale") or "").strip()
    return f'<span class="quote none">{_esc(note)}</span>' if note else ""


def _location_html(row: dict[str, Any]) -> str:
    loc = row["location"]
    if row["verdict"] in ("not_reported", "not_assessed"):
        cls = "loc none"
    elif loc.startswith("Supplement"):
        cls = "loc supp"
    else:
        cls = "loc"
    return f'<span class="{cls}">{_esc(loc)}</span>'


def _item_html(row: dict[str, Any]) -> str:
    text = _esc(row["official_text"])
    if row.get("group"):
        role = "specification" if row["role"] == "specification" else "emulation"
        return f'<span class="grp">{role}</span>{text}'
    return text


def _rows_html(rows: list[dict[str, Any]]) -> str:
    out: list[str] = []
    prev_section = None
    prev_group = None
    for row in rows:
        if row["section"] != prev_section:
            out.append(f'<tr class="section-row"><td colspan="5">'
                       f'{_esc(_render.SECTION_TITLE.get(row["section"], row["section"].title()))}</td></tr>')
            prev_section = row["section"]
            prev_group = None
        grp = row.get("group")
        if grp and grp != prev_group:
            out.append(f'<tr class="group-row"><td colspan="5">{_esc(grp)}</td></tr>')
            prev_group = grp
        elif not grp:
            prev_group = None
        label, pill = _VERDICT[row["verdict"]]
        out.append(
            "<tr>"
            f'<td class="col-id">{_esc(row["id"])}</td>'
            f"<td>{_item_html(row)}</td>"
            f'<td><span class="pill {pill}">{label}</span></td>'
            f"<td>{_location_html(row)}</td>"
            f"<td>{_evidence_html(row)}</td>"
            "</tr>"
        )
    return "\n".join(out)


def render_html(report: dict[str, Any]) -> str:
    """Serialize a render_checklist report to a self-contained HTML string."""
    c = report["completeness"]
    total = max(c.get("scored", 0) or c["total_leaves"], 1)
    prov = report.get("provenance", {})
    attrib = report.get("attribution", {})
    mid = report.get("manuscript_id") or "(unnamed)"

    seg = ""
    for key, cls in (("reported", "seg-rep"), ("partial", "seg-par"),
                     ("not_reported", "seg-not"), ("not_applicable", "seg-na")):
        pct = round(100 * c.get(key, 0) / total, 1)
        if pct > 0:
            seg += f'<span class="{cls}" style="width:{pct}%"></span>'

    legend = ""
    for key, cls, lbl in (("reported", "--rep", "Reported"), ("partial", "--par", "Partial"),
                          ("not_reported", "--not", "Not reported"), ("not_applicable", "--na", "N/A")):
        legend += (f'<div><span class="dot" style="background:var({cls})"></span>'
                   f'<b>{c.get(key, 0)}</b> {lbl}</div>')
    if c.get("not_assessed"):
        legend += (f'<div><span class="dot" style="background:var(--na)"></span>'
                   f'<b>{c["not_assessed"]}</b> Not assessed</div>')

    meta_tags = "".join(
        f'<meta name="target-mcp:{k}" content="{_esc(str(v))}">'
        for k, v in prov.items()
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(_render.TITLE)} — {_esc(mid)}</title>
{meta_tags}
<style>{_CSS}</style></head>
<body><div class="wrap">
  <header>
    <p class="eyebrow">Completed reporting checklist</p>
    <h1>{_esc(_render.TITLE)}</h1>
    <p class="subtitle">{_esc(_render.SUBTITLE)}</p>
    <p class="citation">{_esc(attrib.get("citation", _render.CITATION))}</p>
    <div class="meta">
      <span class="ms">Manuscript: {_esc(mid)}</span>
      <span class="instr">{_esc(_render.instrument_line(report))}</span>
    </div>
  </header>
  <div class="rule-bar"></div>
  <div class="summary">
    <h2>Completeness · {c['total_leaves']} leaves</h2>
    <div class="meter" role="img" aria-label="completeness">{seg}</div>
    <div class="legend">{legend}</div>
  </div>
  <div class="table-wrap"><table>
    <colgroup><col style="width:58px"><col style="width:25%"><col style="width:112px"><col style="width:150px"><col></colgroup>
    <thead><tr><th>Item</th><th>Checklist item</th><th>Verdict</th><th>Location reported</th><th>Evidence &amp; rationale</th></tr></thead>
    <tbody>
{_rows_html(report["rows"])}
    </tbody>
  </table></div>
  <footer>
    <div class="rule-bar foot"></div>
    <p><span class="stamp">{_esc(_render.provenance_line(prov))}</span></p>
    <p>{_esc(attrib.get("license", _render.LICENSE))}</p>
  </footer>
</div></body></html>"""
