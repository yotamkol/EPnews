#!/usr/bin/env python3
"""
EP Feed - Cardiac Electrophysiology Paper Aggregator
Fetches RSS feeds from key EP journals, tags papers by topic,
generates a static HTML page, and sends a daily email digest.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

FEEDS = [
    {"name": "Heart Rhythm",          "url": "https://rss.sciencedirect.com/publication/science/15475271"},
    {"name": "Heart Rhythm O2",       "url": "https://rss.sciencedirect.com/publication/science/26665018"},
    {"name": "JACC: Clinical EP",     "url": "https://rss.sciencedirect.com/publication/science/2405500X"},
    {"name": "Circ: Arrhythmia & EP", "url": "https://www.ahajournals.org/action/showFeed?type=ahead&feed=rss&jc=circep"},
    {"name": "PACE",                  "url": "https://onlinelibrary.wiley.com/feed/15408159/most-recent"},
    {"name": "J Cardiovasc EP",       "url": "https://onlinelibrary.wiley.com/feed/15408167/most-recent"},
    {"name": "Heart Rhythm Case Rep", "url": "https://rss.sciencedirect.com/publication/science/24054966"},
]

# Journals to fetch via CrossRef API (ISSN → display name)
# Used for journals whose RSS feeds are broken or inaccessible
CROSSREF_JOURNALS = [
    {"name": "EP Europace", "issn": "1099-5129"},
]

MEDRXIV_URL = (
    "https://api.biorxiv.org/details/medrxiv/2020-01-01/"
    "{today}/0/json"
)

MEDRXIV_KEYWORDS = [
    "electrophysiology", "atrial fibrillation", "ventricular tachycardia",
    "ventricular arrhythmia", "sudden cardiac death", "cardiac ablation",
    "catheter ablation", "pacemaker", "defibrillator", "arrhythmia",
    "brugada", "long qt", "channelopathy",
]

TAGS = {
    "AFib": [
        "atrial fibrillation", "af ablation", "pulmonary vein isolation",
        "pulmonary vein", "cardioversion", "atrial flutter", "atrial tachycardia",
        "left atrial", "paroxysmal af", "persistent af",
    ],
    "VT": [
        "ventricular tachycardia", "ventricular arrhythmia", "ventricular fibrillation",
        "vt ablation", "vt storm", "catheter ablation ventricular",
        "anti-tachycardia pacing", "atp therapy",
    ],
    "SCD": [
        "sudden cardiac death", "sudden cardiac arrest", "cardiac arrest",
        "resuscitation", "out-of-hospital cardiac", "scd risk",
        "primary prevention", "risk stratification",
    ],
    "Devices": [
        "implantable cardioverter", "icd ", " icd", "pacemaker", "crt ",
        "leadless", "subcutaneous icd", "s-icd", "extravascular",
        "his bundle pacing", "left bundle branch pacing", "lbbap",
        "cardiac resynchronization", "lead extraction", "cardiac device",
    ],
    "Genetics": [
        "channelopathy", "brugada", "long qt", "lqts", "short qt",
        "arrhythmogenic", "arvc", "hypertrophic cardiomyopathy", "hcm",
        "genetic", "inherited", "mutation", "cardiomyopathy",
        "catecholaminergic", "cpvt",
    ],
    "Imaging": [
        "cardiac mri", "cardiac magnetic resonance", "late gadolinium",
        "electroanatomic mapping", "intracardiac echocardiography", "ice guided",
        "cardiac ct", "computed tomography", "ecg ai", "electrocardiogram ai",
        "digital twin", "scar mapping",
    ],
}

TAG_COLORS = {
    "AFib":     "#2563eb",
    "VT":       "#dc2626",
    "SCD":      "#7c3aed",
    "Devices":  "#0891b2",
    "Genetics": "#059669",
    "Imaging":  "#d97706",
    "Other":    "#4b5563",
}

SEEN_FILE = Path("seen.json")
OUTPUT_FILE = Path("index.html")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "ep-feed@yourdomain.com")
EMAIL_TO   = os.environ.get("EMAIL_TO", "")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def tag_paper(title: str) -> list[str]:
    title_lower = title.lower()
    matched = [tag for tag, kws in TAGS.items() if any(kw in title_lower for kw in kws)]
    return matched if matched else ["Other"]


def parse_date(entry) -> datetime:
    """Best-effort date extraction from a feedparser entry."""
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────

def fetch_rss_papers(seen: set) -> list[dict]:
    papers = []
    for feed_meta in FEEDS:
        try:
            feed = feedparser.parse(feed_meta["url"])
            for entry in feed.entries:
                link = entry.get("link", "").strip()
                if not link or link in seen:
                    continue
                title = entry.get("title", "").strip()
                if not title:
                    continue
                date = parse_date(entry)
                papers.append({
                    "title":   title,
                    "link":    link,
                    "journal": feed_meta["name"],
                    "date":    date.strftime("%b %d, %Y"),
                    "date_ts": date.timestamp(),
                    "tags":    tag_paper(title),
                })
                seen.add(link)
        except Exception as e:
            print(f"[warn] Failed to fetch {feed_meta['name']}: {e}", file=sys.stderr)
    return papers


def fetch_crossref_papers(seen: set) -> list[dict]:
    """Fetch recent papers from CrossRef API by journal ISSN.
    Used for journals whose RSS feeds are unavailable (e.g. Europace).
    """
    papers = []
    for journal in CROSSREF_JOURNALS:
        try:
            url = (
                f"https://api.crossref.org/journals/{journal['issn']}/works"
                f"?sort=published&order=desc&rows=50"
                f"&select=DOI,title,author,published,container-title"
                f"&mailto=ep-feed@example.com"
            )
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            items = resp.json().get("message", {}).get("items", [])
            for item in items:
                doi = item.get("DOI", "").strip()
                if not doi:
                    continue
                link = f"https://doi.org/{doi}"
                if link in seen:
                    continue
                titles = item.get("title", [])
                if not titles:
                    continue
                title = titles[0].strip()
                # Parse date from published date-parts
                date_parts = item.get("published", {}).get("date-parts", [[]])
                parts = date_parts[0] if date_parts else []
                try:
                    if len(parts) >= 3:
                        date = datetime(*parts[:3], tzinfo=timezone.utc)
                    elif len(parts) == 2:
                        date = datetime(parts[0], parts[1], 1, tzinfo=timezone.utc)
                    else:
                        date = datetime.now(timezone.utc)
                except Exception:
                    date = datetime.now(timezone.utc)
                papers.append({
                    "title":   title,
                    "link":    link,
                    "journal": journal["name"],
                    "date":    date.strftime("%b %d, %Y"),
                    "date_ts": date.timestamp(),
                    "tags":    tag_paper(title),
                })
                seen.add(link)
        except Exception as e:
            print(f"[warn] CrossRef fetch failed for {journal['name']}: {e}", file=sys.stderr)
    return papers


def fetch_medrxiv_papers(seen: set) -> list[dict]:
    papers = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        url = MEDRXIV_URL.format(today=today)
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("collection", []):
            title = item.get("title", "").strip()
            doi   = item.get("doi", "").strip()
            if not doi or not title:
                continue
            link = f"https://www.medrxiv.org/content/{doi}"
            if link in seen:
                continue
            title_lower = title.lower()
            abstract_lower = item.get("abstract", "").lower()
            if not any(kw in title_lower or kw in abstract_lower for kw in MEDRXIV_KEYWORDS):
                continue
            date_str = item.get("date", today)
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                date = datetime.now(timezone.utc)
            papers.append({
                "title":   title,
                "link":    link,
                "journal": "medRxiv (preprint)",
                "date":    date.strftime("%b %d, %Y"),
                "date_ts": date.timestamp(),
                "tags":    tag_paper(title),
            })
            seen.add(link)
    except Exception as e:
        print(f"[warn] Failed to fetch medRxiv: {e}", file=sys.stderr)
    return papers


# ─────────────────────────────────────────────
# RENDER HTML
# ─────────────────────────────────────────────

def build_tag_pill(tag: str) -> str:
    color = TAG_COLORS.get(tag, TAG_COLORS["Other"])
    return f'<span class="tag" style="background:{color}22;color:{color};border-color:{color}33">{tag}</span>'


def build_paper_row(paper: dict) -> str:
    tags_html = "".join(build_tag_pill(t) for t in paper["tags"])
    tag_classes = " ".join(f"tag-{t.lower()}" for t in paper["tags"])
    return f'''
    <div class="paper {tag_classes}">
      <div class="paper-tags">{tags_html}</div>
      <a class="paper-title" href="{paper["link"]}" target="_blank" rel="noopener">{paper["title"]}</a>
      <div class="paper-meta">{paper["journal"]} · {paper["date"]}</div>
    </div>'''


def render_html(papers: list[dict]) -> str:
    updated = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    count = len(papers)

    all_tags = sorted(TAG_COLORS.keys())
    filter_buttons = '<button class="filter-btn active" onclick="filter(\'all\')">All</button>'
    for tag in all_tags:
        color = TAG_COLORS[tag]
        filter_buttons += f'<button class="filter-btn" onclick="filter(\'{tag.lower()}\''
        filter_buttons += f')" style="--accent:{color}">{tag}</button>'

    rows = "\n".join(build_paper_row(p) for p in papers) if papers else \
        '<div class="empty">No new papers today.</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>EP Feed</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --bg:       #080c0e;
      --surface:  #0d1317;
      --border:   #1a2228;
      --text:     #d4dde3;
      --muted:    #4a5a63;
      --accent:   #00d4aa;
      --mono:     'IBM Plex Mono', monospace;
      --sans:     'DM Sans', sans-serif;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
    }}

    /* ── header ── */
    header {{
      border-bottom: 1px solid var(--border);
      padding: 20px 32px;
      display: flex;
      align-items: baseline;
      gap: 20px;
      position: sticky;
      top: 0;
      background: var(--bg);
      z-index: 10;
    }}

    .logo {{
      font-family: var(--mono);
      font-size: 13px;
      font-weight: 500;
      letter-spacing: 0.15em;
      color: var(--accent);
      text-transform: uppercase;
    }}

    .logo-sub {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.08em;
    }}

    .header-right {{
      margin-left: auto;
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      text-align: right;
      line-height: 1.7;
    }}

    .count {{ color: var(--accent); }}

    /* ── ecg line decoration ── */
    .ecg-bar {{
      height: 2px;
      background: linear-gradient(90deg,
        var(--bg) 0%,
        var(--accent) 20%, var(--accent) 22%,
        var(--bg) 30%,
        var(--accent) 35%, var(--accent) 38%,
        var(--bg) 40%,
        var(--bg) 100%);
      opacity: 0.3;
    }}

    /* ── filters ── */
    .filters {{
      padding: 16px 32px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }}

    .filter-btn {{
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.08em;
      padding: 5px 12px;
      border-radius: 3px;
      border: 1px solid var(--border);
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      transition: all 0.15s;
    }}

    .filter-btn:hover {{
      color: var(--text);
      border-color: var(--accent);
    }}

    .filter-btn.active {{
      background: var(--accent);
      color: var(--bg);
      border-color: var(--accent);
    }}

    /* ── paper rows ── */
    .feed {{
      max-width: 960px;
      margin: 0 auto;
      padding: 0 32px 64px;
    }}

    .paper {{
      display: grid;
      grid-template-columns: 140px 1fr auto;
      align-items: baseline;
      gap: 12px;
      padding: 13px 0;
      border-bottom: 1px solid var(--border);
      transition: background 0.1s;
    }}

    .paper:hover {{
      background: var(--surface);
      margin: 0 -32px;
      padding: 13px 32px;
    }}

    .paper.hidden {{ display: none; }}

    .paper-tags {{
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
      flex-shrink: 0;
    }}

    .tag {{
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 500;
      letter-spacing: 0.06em;
      padding: 2px 6px;
      border-radius: 2px;
      border: 1px solid;
      white-space: nowrap;
    }}

    .paper-title {{
      color: var(--text);
      text-decoration: none;
      font-weight: 400;
      font-size: 13.5px;
      line-height: 1.45;
      transition: color 0.1s;
    }}

    .paper-title:hover {{
      color: var(--accent);
    }}

    .paper-meta {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      white-space: nowrap;
      flex-shrink: 0;
    }}

    .empty {{
      padding: 64px 0;
      text-align: center;
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);
      letter-spacing: 0.1em;
    }}

    /* ── responsive ── */
    @media (max-width: 640px) {{
      header {{ padding: 16px 20px; flex-wrap: wrap; gap: 8px; }}
      .filters {{ padding: 12px 20px; }}
      .feed {{ padding: 0 20px 40px; }}
      .paper {{ grid-template-columns: 1fr; gap: 4px; }}
      .paper:hover {{ margin: 0 -20px; padding: 13px 20px; }}
      .paper-meta {{ font-size: 10px; }}
    }}
  </style>
</head>
<body>

<header>
  <div>
    <div class="logo">EP Feed</div>
    <div class="logo-sub">Cardiac Electrophysiology</div>
  </div>
  <div class="header-right">
    <div><span class="count">{count}</span> papers</div>
    <div>updated {updated}</div>
  </div>
</header>

<div class="ecg-bar"></div>

<div class="filters">
  {filter_buttons}
</div>

<div class="feed">
  {rows}
</div>

<script>
  function filter(tag) {{
    document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    document.querySelectorAll('.paper').forEach(p => {{
      if (tag === 'all') {{
        p.classList.remove('hidden');
      }} else {{
        p.classList.toggle('hidden', !p.classList.contains('tag-' + tag));
      }}
    }});
  }}
</script>

</body>
</html>
"""


# ─────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────

def build_email_html(papers: list[dict]) -> str:
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    rows = ""
    for p in papers:
        tags_str = " · ".join(p["tags"])
        rows += f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #1a2228;vertical-align:top">
            <div style="font-size:11px;color:#00d4aa;font-family:monospace;margin-bottom:4px">{tags_str}</div>
            <a href="{p['link']}" style="color:#d4dde3;text-decoration:none;font-size:13px;line-height:1.4">{p['title']}</a>
            <div style="font-size:11px;color:#4a5a63;font-family:monospace;margin-top:3px">{p['journal']} · {p['date']}</div>
          </td>
        </tr>"""

    return f"""
    <html><body style="background:#080c0e;margin:0;padding:0;font-family:'DM Sans',sans-serif">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;margin:0 auto;padding:32px 24px">
      <tr><td>
        <div style="font-family:monospace;font-size:13px;color:#00d4aa;letter-spacing:0.15em;margin-bottom:4px">EP FEED</div>
        <div style="font-family:monospace;font-size:11px;color:#4a5a63;margin-bottom:32px">{date_str} · {len(papers)} new papers</div>
        <table width="100%" cellpadding="0" cellspacing="0">
          {rows}
        </table>
      </td></tr>
    </table>
    </body></html>
    """


def send_email(papers: list[dict]):
    if not RESEND_API_KEY or not EMAIL_TO:
        print("[info] No RESEND_API_KEY or EMAIL_TO set, skipping email.", file=sys.stderr)
        return
    date_str = datetime.now(timezone.utc).strftime("%b %d")
    payload = {
        "from": EMAIL_FROM,
        "to":   [EMAIL_TO],
        "subject": f"EP Feed — {len(papers)} new papers ({date_str})",
        "html": build_email_html(papers),
    }
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    if resp.status_code == 200:
        print(f"[info] Email sent to {EMAIL_TO}")
    else:
        print(f"[warn] Email failed: {resp.status_code} {resp.text}", file=sys.stderr)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("[info] Loading seen papers...")
    seen = load_seen()
    seen_before = len(seen)

    print("[info] Fetching RSS feeds...")
    rss_papers = fetch_rss_papers(seen)

    print("[info] Fetching CrossRef journals (Europace)...")
    crossref_papers = fetch_crossref_papers(seen)

    print("[info] Fetching medRxiv...")
    medrxiv_papers = fetch_medrxiv_papers(seen)

    new_papers = rss_papers + crossref_papers + medrxiv_papers
    new_papers.sort(key=lambda p: p["date_ts"], reverse=True)

    print(f"[info] {len(new_papers)} new papers found (seen grew from {seen_before} → {len(seen)})")

    # Load all previously stored papers to show in HTML (not just today's)
    # We persist a rolling papers.json alongside seen.json
    papers_file = Path("papers.json")
    all_papers = []
    if papers_file.exists():
        all_papers = json.loads(papers_file.read_text())

    # Prepend new papers
    all_papers = new_papers + all_papers

    # Keep last 500 papers in the feed
    all_papers = all_papers[:500]
    papers_file.write_text(json.dumps(all_papers, indent=2))

    print("[info] Rendering HTML...")
    html = render_html(all_papers)
    OUTPUT_FILE.write_text(html)
    print(f"[info] Wrote {OUTPUT_FILE} ({len(all_papers)} total papers)")

    save_seen(seen)

    if new_papers:
        print("[info] Sending email digest...")
        send_email(new_papers)
    else:
        print("[info] No new papers, skipping email.")

    print("[info] Done.")


if __name__ == "__main__":
    main()
