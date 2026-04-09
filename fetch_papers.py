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
    # Dedicated EP journals — take everything
    {"name": "Heart Rhythm",          "url": "https://rss.sciencedirect.com/publication/science/15475271",  "ep_only": False},
    {"name": "Heart Rhythm O2",       "url": "https://rss.sciencedirect.com/publication/science/26665018",  "ep_only": False},
    {"name": "JACC: Clinical EP",     "url": "https://rss.sciencedirect.com/publication/science/2405500X",  "ep_only": False},
    {"name": "PACE",                  "url": "https://onlinelibrary.wiley.com/feed/15408159/most-recent",   "ep_only": False},
    {"name": "J Cardiovasc EP",       "url": "https://onlinelibrary.wiley.com/feed/15408167/most-recent",   "ep_only": False},
    # General cardiology journals — filter to EP-relevant papers only
    {"name": "NEJM",                  "url": "https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss",                         "ep_only": True},
    {"name": "JACC",                  "url": "https://rss.sciencedirect.com/publication/science/07351097",                               "ep_only": True},
    {"name": "Lancet",                "url": "https://www.thelancet.com/rssfeed/lancet_current.xml",                                     "ep_only": True},
    {"name": "Nature Cardiovasc Res", "url": "https://www.nature.com/natcardiovascres.rss",                                              "ep_only": True},
    {"name": "Nature Medicine",       "url": "https://www.nature.com/nm.rss",                                                             "ep_only": True},
]

# Keywords used to filter general journals (ep_only: True)
# A paper must match at least one of these in its title to be included
EP_FILTER_KEYWORDS = [
    "atrial fibrillation", "atrial flutter", "atrial tachycardia",
    "ventricular tachycardia", "ventricular arrhythmia", "ventricular fibrillation",
    "sudden cardiac death", "sudden cardiac arrest", "cardiac arrest",
    "electrophysiology", "catheter ablation", "cardiac ablation",
    "pacemaker", "implantable cardioverter", " icd", "icd ",
    "leadless", "cardiac resynchronization", "crt ", "defibrillator",
    "arrhythmia", "arrhythmias", "brugada", "long qt", "channelopathy",
    "left bundle branch pacing", "his bundle pacing", "lbbap",
    "pulmonary vein", "cardioversion", "antiarrhythmic",
    "cardiac electrophysiology", "sinus node", "av node", "accessory pathway",
    "wolff-parkinson", "wpw", "svt ", " svt", "supraventricular",
]

# Journals to fetch via CrossRef API (ISSN → display name)
# Used for journals whose RSS feeds are broken or inaccessible (e.g. Oxford Academic)
CROSSREF_JOURNALS = [
    {"name": "EP Europace",            "issn": "1099-5129", "ep_only": False},
    {"name": "Circ: Arrhythmia & EP",  "issn": "1941-3084", "ep_only": False},
    {"name": "Heart Rhythm Case Rep",  "issn": "2214-0271", "ep_only": False},
    {"name": "European Heart Journal", "issn": "0195-668X", "ep_only": True},
    {"name": "Circulation",           "issn": "0009-7322", "ep_only": True},
    {"name": "JAMA Cardiology",       "issn": "2380-6583", "ep_only": True},
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
        "cardiac ct", "computed tomography", "scar mapping",
    ],
    "SVT": [
        "supraventricular tachycardia", "svt ", " svt", "avnrt", "avrt",
        "atrial tachycardia", "atrioventricular nodal", "atrioventricular reentrant",
        "accessory pathway", "wolff-parkinson", "wpw", "delta wave",
        "junctional tachycardia", "focal atrial tachycardia", "sinus tachycardia",
        "inappropriate sinus", "sinoatrial reentrant",
    ],
    "AI": [
        "artificial intelligence", "machine learning", "deep learning",
        "neural network", "ecg ai", "electrocardiogram ai", "natural language processing",
        "large language model", "llm", "foundation model", "digital twin",
        "computer vision", "convolutional", "transformer model",
        "risk prediction model", "predictive model", "algorithm",
    ],
}

TAG_COLORS = {
    "AFib":     "#2563eb",
    "VT":       "#dc2626",
    "SCD":      "#7c3aed",
    "Devices":  "#0891b2",
    "Genetics": "#059669",
    "Imaging":  "#d97706",
    "SVT":      "#c2410c",
    "AI":       "#0d9488",
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
                # For general journals, filter to EP-relevant papers only
                if feed_meta.get("ep_only"):
                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in EP_FILTER_KEYWORDS):
                        continue
                date = parse_date(entry)
                # Try to extract DOI from RSS entry metadata fields
                doi = None
                for field in ("prism_doi", "dc_identifier"):
                    val = getattr(entry, field, None)
                    if val and val.strip().startswith("10."):
                        doi = val.strip()
                        break
                if not doi:
                    # Some feeds put DOI in tags/links
                    for tag in getattr(entry, "tags", []):
                        term = getattr(tag, "term", "") or ""
                        if term.startswith("10."):
                            doi = term.strip()
                            break
                if not doi:
                    doi = extract_doi(link)
                papers.append({
                    "title":   title,
                    "link":    link,
                    "doi":     doi,
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
                # For general journals, filter to EP-relevant papers only
                if journal.get("ep_only"):
                    if not any(kw in title.lower() for kw in EP_FILTER_KEYWORDS):
                        continue
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
                    "doi":     doi,
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
                "doi":     doi if doi else extract_doi(link),
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
# ALTMETRIC (hot papers)
# ─────────────────────────────────────────────

HOT_CITATION_THRESHOLD = 3  # cited-by count above this = 🔥

def extract_doi(link: str) -> str | None:
    """Extract DOI from a journal article URL, handling publisher-specific formats."""
    if not link:
        return None

    # Standard doi.org resolver
    if "doi.org/" in link:
        doi = link.split("doi.org/")[-1].strip().rstrip("/")
        return doi if doi else None

    # Query param: ?doi=10.xxxx/...
    if "doi=" in link:
        doi = link.split("doi=")[-1].split("&")[0].strip()
        return doi if doi.startswith("10.") else None

    # /doi/full/10.xxxx or /doi/abs/10.xxxx or /doi/10.xxxx
    m = re.search(r"/doi/(10\.\d{4,}/[^\s?#]+)", link)
    if m:
        return m.group(1).split("?")[0].rstrip("/")

    return None


def resolve_doi_via_crossref(title: str) -> str | None:
    """Look up a paper's DOI via CrossRef title search. Used as fallback
    when the DOI isn't available from the RSS feed or URL (e.g. Elsevier)."""
    try:
        resp = requests.get(
            "https://api.crossref.org/works",
            params={"query.title": title, "rows": 1, "mailto": "ep-feed@example.com"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("message", {}).get("items", [])
        if not items:
            return None
        candidate = items[0]
        candidate_title = (candidate.get("title", [""])[0] or "").lower().strip()
        query_title = title.lower().strip()
        # Verify first 60 chars match to avoid false positives
        if candidate_title[:60] != query_title[:60]:
            return None
        doi = candidate.get("DOI", "").strip()
        return doi if doi else None
    except Exception:
        return None


def fetch_hot_scores(papers: list[dict]) -> list[dict]:
    """Check citation counts via OpenAlex (free, no API key needed).
    Falls back to CrossRef title lookup for papers without a DOI.
    """
    import time
    found_doi = 0
    crossref_resolved = 0

    # Step 1: Resolve missing DOIs via CrossRef
    for paper in papers:
        doi = paper.get("doi") or extract_doi(paper.get("link", ""))
        if not doi:
            doi = resolve_doi_via_crossref(paper["title"])
            if doi:
                paper["doi"] = doi
                crossref_resolved += 1
                time.sleep(0.3)
        if doi:
            paper["doi"] = doi
            found_doi += 1

    print(f"[info] DOI extracted for {found_doi}/{len(papers)} papers ({crossref_resolved} resolved via CrossRef)")

    # Step 2: Batch query OpenAlex for citation counts (up to 50 DOIs per request)
    papers_with_doi = [p for p in papers if p.get("doi")]
    for i in range(0, len(papers_with_doi), 50):
        batch = papers_with_doi[i:i + 50]
        doi_filter = "|".join(f"https://doi.org/{p['doi']}" for p in batch)
        try:
            resp = requests.get(
                "https://api.openalex.org/works",
                params={
                    "filter": f"doi:{doi_filter}",
                    "select": "doi,cited_by_count",
                    "per_page": 50,
                    "mailto": "ep-feed@example.com",
                },
                timeout=15,
                headers={"User-Agent": "EPFeed/1.0 (personal research tool)"},
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                cite_map = {}
                for r in results:
                    rdoi = (r.get("doi") or "").replace("https://doi.org/", "").lower()
                    cite_map[rdoi] = r.get("cited_by_count", 0)
                for p in batch:
                    count = cite_map.get(p["doi"].lower(), 0)
                    p["hot"] = count >= HOT_CITATION_THRESHOLD
                    if p["hot"]:
                        print(f"[info] 🔥 cited_by={count} — {p['title'][:60]}")
            else:
                for p in batch:
                    p["hot"] = False
            time.sleep(0.5)
        except Exception:
            for p in batch:
                p["hot"] = False

    # Papers without DOI can't be checked
    for p in papers:
        p.setdefault("hot", False)

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
    hot_badge = '<span class="hot-badge" title="High attention score">🔥</span>' if paper.get("hot") else ""
    link_id = paper["link"].replace("https://", "").replace("http://", "").replace("/", "_").replace(".", "_")
    journal_safe = paper["journal"].replace('"', '&quot;')
    return f'''
    <div class="paper {tag_classes}" data-id="{link_id}" data-date="{paper["date_ts"]}" data-journal="{journal_safe}">
      <div class="paper-tags">{tags_html}</div>
      <div class="paper-title-wrap">
        <span class="unread-dot" title="Unread"></span>
        <span class="bookmark-btn" title="Bookmark" onclick="toggleBookmark('{link_id}')">&#9734;</span>
        {hot_badge}
        <a class="paper-title" href="{paper["link"]}" target="_blank" rel="noopener"
           onclick="markRead('{link_id}')">{paper["title"]}</a>
      </div>
      <div class="paper-meta">{paper["journal"]} · {paper["date"]}</div>
    </div>'''


def render_html(papers: list[dict]) -> str:
    updated = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")

    tag_order = ["AFib", "SVT", "VT", "SCD", "Devices", "Genetics", "Imaging", "AI", "Other"]
    filter_buttons = '<button class="filter-btn active" onclick="filterTag(\'all\')">All</button>'
    for tag in tag_order:
        color = TAG_COLORS[tag]
        filter_buttons += f'<button class="filter-btn" onclick="filterTag(\'{tag.lower()}\''
        filter_buttons += f')" style="--accent:{color}">{tag}</button>'

    # Build journal dropdown options
    journals = sorted(set(p["journal"] for p in papers))
    journal_options = '<option value="all">All journals</option>'
    for j in journals:
        journal_options += f'<option value="{j}">{j}</option>'

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
      --bg:       #111318;
      --surface:  #1a1d24;
      --border:   #252932;
      --text:     #edf2f7;
      --muted:    #8b95a5;
      --accent:   #5b9cf6;
      --unread:   #5b9cf6;
      --hot:      #f97316;
      --mono:     'IBM Plex Mono', monospace;
      --sans:     'DM Sans', sans-serif;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 15px;
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
      backdrop-filter: blur(8px);
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

    .last-updated {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      display: none;
    }}

    .header-right {{
      margin-left: auto;
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      display: flex;
      align-items: center;
      gap: 10px;
    }}

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
      opacity: 0.25;
    }}

    /* ── filters ── */
    .filters {{
      padding: 14px 32px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }}

    .filter-btn {{
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.07em;
      padding: 5px 11px;
      border-radius: 4px;
      border: 1px solid var(--border);
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      transition: all 0.12s;
    }}

    .filter-btn:hover {{
      color: var(--text);
      border-color: var(--accent);
      background: color-mix(in srgb, var(--accent) 8%, transparent);
    }}

    .filter-btn.active {{
      background: var(--accent);
      color: #0e1118;
      border-color: var(--accent);
    }}

    /* ── paper rows ── */
    .feed {{
      max-width: 980px;
      margin: 0 auto;
      padding: 0 32px 80px;
    }}

    .paper {{
      display: grid;
      grid-template-columns: 150px 1fr auto;
      align-items: center;
      gap: 14px;
      padding: 12px 0;
      border-bottom: 1px solid var(--border);
      transition: background 0.1s;
    }}

    .paper:hover {{
      background: var(--surface);
      margin: 0 -32px;
      padding: 12px 32px;
      border-radius: 4px;
    }}

    .paper.hidden {{ display: none; }}

    /* unread state */
    .paper.unread .paper-title {{ font-weight: 500; color: #eaf0f9; }}
    .paper.unread .unread-dot {{
      display: inline-block;
      width: 6px; height: 6px;
      border-radius: 50%;
      background: var(--unread);
      margin-right: 6px;
      flex-shrink: 0;
      vertical-align: middle;
      position: relative;
      top: -1px;
    }}
    .paper.read .unread-dot {{ display: none; }}

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
      letter-spacing: 0.05em;
      padding: 2px 6px;
      border-radius: 3px;
      border: 1px solid;
      white-space: nowrap;
    }}

    .paper-title-wrap {{
      display: flex;
      align-items: center;
      gap: 0;
    }}

    .paper-title {{
      color: var(--text);
      text-decoration: none;
      font-weight: 400;
      font-size: 14.5px;
      line-height: 1.5;
      transition: color 0.1s;
    }}

    .paper-title:hover {{ color: var(--accent); }}

    .hot-badge {{
      font-size: 14px;
      margin-right: 5px;
      flex-shrink: 0;
      filter: drop-shadow(0 0 4px rgba(249,115,22,0.5));
    }}

    .paper-meta {{
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
      flex-shrink: 0;
      text-align: right;
    }}

    /* ── toolbar (search + sort + journal filter) ── */
    .toolbar {{
      padding: 12px 32px;
      background: var(--bg);
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}

    .search-input {{
      flex: 1;
      min-width: 180px;
      max-width: 400px;
      padding: 7px 12px;
      font-family: var(--sans);
      font-size: 14px;
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 5px;
      outline: none;
      transition: border-color 0.15s;
    }}
    .search-input::placeholder {{ color: var(--muted); }}
    .search-input:focus {{ border-color: var(--accent); }}

    .toolbar-select {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 6px 8px;
      cursor: pointer;
      outline: none;
    }}
    .toolbar-select:focus {{ border-color: var(--accent); }}

    .theme-toggle {{
      font-size: 16px;
      background: none;
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 4px 8px;
      cursor: pointer;
      color: var(--muted);
      transition: all 0.12s;
    }}
    .theme-toggle:hover {{ color: var(--text); border-color: var(--muted); }}

    /* ── scroll to top ── */
    .scroll-top {{
      position: fixed;
      bottom: 28px;
      right: 28px;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: var(--accent);
      color: var(--bg);
      border: none;
      font-size: 20px;
      cursor: pointer;
      display: none;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      z-index: 20;
      transition: opacity 0.2s;
    }}
    .scroll-top.visible {{ display: flex; }}

    /* ── bookmark ── */
    .bookmark-btn {{
      cursor: pointer;
      font-size: 14px;
      color: var(--muted);
      margin-right: 5px;
      flex-shrink: 0;
      transition: color 0.1s;
      user-select: none;
    }}
    .bookmark-btn:hover {{ color: var(--accent); }}
    .bookmark-btn.bookmarked {{ color: #f5c518; }}

    /* ── new-since-last-visit divider ── */
    .new-divider {{
      padding: 8px 0;
      text-align: center;
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.08em;
      position: relative;
    }}
    .new-divider::before, .new-divider::after {{
      content: '';
      position: absolute;
      top: 50%;
      width: 30%;
      height: 1px;
      background: var(--border);
    }}
    .new-divider::before {{ left: 0; }}
    .new-divider::after {{ right: 0; }}

    .empty {{
      padding: 64px 0;
      text-align: center;
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);
      letter-spacing: 0.1em;
    }}

    /* ── footer ── */
    footer {{
      border-top: 1px solid var(--border);
      padding: 24px 32px;
      text-align: center;
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.04em;
    }}

    /* ── light theme ── */
    body.light {{
      --bg:       #f5f6f8;
      --surface:  #ffffff;
      --border:   #dde1e8;
      --text:     #1a1d24;
      --muted:    #6b7280;
      --accent:   #2563eb;
      --unread:   #2563eb;
    }}
    body.light .paper.unread .paper-title {{ color: #111318; }}

    /* ── responsive ── */
    @media (max-width: 640px) {{
      header {{
        padding: 10px 16px;
        flex-wrap: nowrap;
        gap: 8px;
        align-items: center;
      }}
      .logo-sub {{ font-size: 11px; white-space: nowrap; }}
      .last-updated {{ display: block; font-size: 9px; }}
      .header-right span {{ display: none; }}
      .header-right {{ gap: 0; }}
      .filters {{ padding: 10px 16px; gap: 5px; }}
      .toolbar {{ padding: 10px 16px; flex-wrap: nowrap; }}
      .search-input {{ min-width: 0; flex: 1; font-size: 13px; padding: 6px 10px; }}
      .feed {{ padding: 0 16px 48px; }}
      .paper {{ grid-template-columns: 1fr; gap: 5px; }}
      .paper:hover {{ margin: 0 -16px; padding: 12px 16px; }}
      .paper-meta {{ font-size: 10px; text-align: left; }}
      footer {{ padding: 16px; }}
    }}
  </style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="logo">EP Feed</div>
    <div class="logo-sub">Your daily EP reading list</div>
    <div class="last-updated">Last updated {updated}</div>
  </div>
  <div class="header-right">
    <span>Last updated {updated}</span>
    <button class="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark mode" id="theme-btn">&#9790;</button>
  </div>
</header>

<div class="ecg-bar"></div>

<div class="filters">
  {filter_buttons}
</div>

<div class="toolbar">
  <input type="text" class="search-input" placeholder="Search papers..." oninput="searchPapers(this.value)"/>
  <select class="toolbar-select" id="journal-filter" onchange="filterJournal(this.value)">
    {journal_options}
  </select>
</div>

<div class="feed">
  {rows}
</div>

<footer>
  &copy; {datetime.now().year} Yotam Kolben. All rights reserved.
</footer>

<button class="scroll-top" id="scroll-top-btn" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">&#8593;</button>

<script>
  const READ_KEY = 'ep_read_v1';
  const BOOKMARK_KEY = 'ep_bookmarks_v1';
  const VISIT_KEY = 'ep_last_visit';
  const THEME_KEY = 'ep_theme';

  // ── localStorage helpers ──
  function getSet(key) {{
    try {{ return new Set(JSON.parse(localStorage.getItem(key) || '[]')); }}
    catch {{ return new Set(); }}
  }}
  function saveSet(key, s) {{ localStorage.setItem(key, JSON.stringify([...s])); }}

  // ── Read state ──
  function applyReadState() {{
    const read = getSet(READ_KEY);
    document.querySelectorAll('.paper').forEach(p => {{
      if (read.has(p.dataset.id)) {{
        p.classList.add('read'); p.classList.remove('unread');
      }} else {{
        p.classList.add('unread'); p.classList.remove('read');
      }}
    }});
  }}

  function markRead(id) {{
    const read = getSet(READ_KEY);
    read.add(id);
    saveSet(READ_KEY, read);
    const paper = document.querySelector(`.paper[data-id="${{id}}"]`);
    if (paper) {{ paper.classList.add('read'); paper.classList.remove('unread'); }}
  }}

  // ── Bookmarks ──
  function applyBookmarks() {{
    const bm = getSet(BOOKMARK_KEY);
    document.querySelectorAll('.paper').forEach(p => {{
      const btn = p.querySelector('.bookmark-btn');
      if (bm.has(p.dataset.id)) {{
        btn.innerHTML = '&#9733;';
        btn.classList.add('bookmarked');
      }} else {{
        btn.innerHTML = '&#9734;';
        btn.classList.remove('bookmarked');
      }}
    }});
  }}

  function toggleBookmark(id) {{
    const bm = getSet(BOOKMARK_KEY);
    if (bm.has(id)) {{ bm.delete(id); }} else {{ bm.add(id); }}
    saveSet(BOOKMARK_KEY, bm);
    applyBookmarks();
  }}

  // ── Tag filter ──
  let activeTag = 'all';
  function filterTag(tag) {{
    activeTag = tag;
    document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    applyVisibility();
  }}

  // ── Journal filter ──
  let activeJournal = 'all';
  function filterJournal(journal) {{
    activeJournal = journal;
    applyVisibility();
  }}

  // ── Search ──
  let searchQuery = '';
  function searchPapers(query) {{
    searchQuery = query.toLowerCase().trim();
    applyVisibility();
  }}

  // ── Combined visibility (tag + journal + search) ──
  function applyVisibility() {{
    document.querySelectorAll('.paper').forEach(p => {{
      let show = true;
      if (activeTag !== 'all' && !p.classList.contains('tag-' + activeTag)) show = false;
      if (activeJournal !== 'all' && p.dataset.journal !== activeJournal) show = false;
      if (searchQuery) {{
        const title = (p.querySelector('.paper-title')?.textContent || '').toLowerCase();
        const meta = (p.querySelector('.paper-meta')?.textContent || '').toLowerCase();
        if (!title.includes(searchQuery) && !meta.includes(searchQuery)) show = false;
      }}
      p.style.display = show ? '' : 'none';
    }});
  }}

  // ── Sort ──
  function sortPapers(mode) {{
    const feed = document.querySelector('.feed');
    const papers = [...feed.querySelectorAll('.paper')];
    const read = getSet(READ_KEY);
    const bm = getSet(BOOKMARK_KEY);
    papers.sort((a, b) => {{
      if (mode === 'date') return parseFloat(b.dataset.date) - parseFloat(a.dataset.date);
      if (mode === 'journal') return a.dataset.journal.localeCompare(b.dataset.journal) || parseFloat(b.dataset.date) - parseFloat(a.dataset.date);
      if (mode === 'unread') {{
        const au = read.has(a.dataset.id) ? 1 : 0;
        const bu = read.has(b.dataset.id) ? 1 : 0;
        return au - bu || parseFloat(b.dataset.date) - parseFloat(a.dataset.date);
      }}
      if (mode === 'bookmarked') {{
        const ab = bm.has(a.dataset.id) ? 0 : 1;
        const bb = bm.has(b.dataset.id) ? 0 : 1;
        return ab - bb || parseFloat(b.dataset.date) - parseFloat(a.dataset.date);
      }}
      return 0;
    }});
    papers.forEach(p => feed.appendChild(p));
  }}

  // ── Theme ──
  function applyTheme() {{
    const theme = localStorage.getItem(THEME_KEY) || 'dark';
    document.body.classList.toggle('light', theme === 'light');
    document.getElementById('theme-btn').innerHTML = theme === 'light' ? '&#9728;' : '&#9790;';
  }}
  function toggleTheme() {{
    const current = localStorage.getItem(THEME_KEY) || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem(THEME_KEY, next);
    applyTheme();
  }}

  // ── New since last visit ──
  function markNewPapers() {{
    const lastVisit = parseFloat(localStorage.getItem(VISIT_KEY) || '0');
    if (lastVisit === 0) {{
      localStorage.setItem(VISIT_KEY, String(Date.now() / 1000));
      return;
    }}
    let dividerInserted = false;
    const papers = document.querySelectorAll('.paper');
    for (const p of papers) {{
      const ts = parseFloat(p.dataset.date);
      if (!dividerInserted && ts <= lastVisit) {{
        const divider = document.createElement('div');
        divider.className = 'new-divider';
        divider.textContent = 'previously seen';
        p.parentNode.insertBefore(divider, p);
        dividerInserted = true;
        break;
      }}
    }}
    localStorage.setItem(VISIT_KEY, String(Date.now() / 1000));
  }}

  // ── Scroll to top ──
  window.addEventListener('scroll', () => {{
    const btn = document.getElementById('scroll-top-btn');
    btn.classList.toggle('visible', window.scrollY > 400);
  }});

  // ── Init ──
  document.addEventListener('DOMContentLoaded', () => {{
    applyTheme();
    applyReadState();
    applyBookmarks();
    markNewPapers();
  }});
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
        "to":   [e.strip() for e in EMAIL_TO.split(",") if e.strip()],
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

    # Hot paper detection disabled for now
    # if new_papers:
    #     print(f"[info] Checking hot scores for {len(new_papers)} new papers...")
    #     new_papers = fetch_hot_scores(new_papers)
    #     hot_count = sum(1 for p in new_papers if p.get("hot"))
    #     print(f"[info] {hot_count} hot papers found")
    
    # Carry over hot flag from existing papers (already stored)
    for p in new_papers:
        p.setdefault("hot", False)

    print(f"[info] {len(new_papers)} new papers found (seen grew from {seen_before} → {len(seen)})")

    # Load all previously stored papers to show in HTML (not just today's)
    # We persist a rolling papers.json alongside seen.json
    papers_file = Path("papers.json")
    all_papers = []
    if papers_file.exists():
        all_papers = json.loads(papers_file.read_text())
        for p in all_papers:
            p.setdefault("hot", False)

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
