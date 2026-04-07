# EP Feed

A personal Hacker News-style feed for cardiac electrophysiology research.
Aggregates new papers from 8 journals + medRxiv preprints, tags them by topic,
renders a static page on Vercel, and sends a daily email digest.

## Sources

| Journal | Publisher |
|---|---|
| Heart Rhythm | Elsevier |
| Heart Rhythm O2 | Elsevier |
| JACC: Clinical Electrophysiology | Elsevier |
| EP Europace | Oxford Academic |
| Circulation: Arrhythmia & EP | AHA / Wolters Kluwer |
| PACE | Wiley |
| Journal of Cardiovascular EP | Wiley |
| Heart Rhythm Case Reports | Elsevier |
| medRxiv (EP preprints) | Cold Spring Harbor |

## Setup (one-time, ~15 minutes)

### 1. Fork / clone this repo

```bash
git clone https://github.com/yourname/ep-feed.git
cd ep-feed
```

### 2. Connect to Vercel

1. Go to [vercel.com](https://vercel.com) → New Project → Import this repo
2. Framework preset: **Other** (it's a static site)
3. Output directory: `.` (the root)
4. Deploy — you'll get a URL like `ep-feed.vercel.app`

Vercel will auto-redeploy every time the GitHub Actions bot pushes new HTML.

### 3. Set up Resend (email)

1. Sign up at [resend.com](https://resend.com) (free tier: 3,000 emails/month)
2. Add your sending domain, or use `onboarding@resend.dev` for testing
3. Copy your API key

### 4. Add GitHub Actions secrets

In your repo → **Settings → Secrets → Actions**, add:

| Secret | Value |
|---|---|
| `RESEND_API_KEY` | Your Resend API key |
| `EMAIL_FROM` | e.g. `ep-feed@yourdomain.com` |
| `EMAIL_TO` | Your email address |

### 5. Run it manually to populate the feed

Go to **Actions → Daily EP Feed Update → Run workflow**.

This will fetch all current papers, build `index.html`, and push it to the repo,
which triggers a Vercel deployment. Your feed is live.

After that, the cron job runs every day at 06:00 UTC automatically.

## Customizing

### Adding/removing journals

Edit `FEEDS` in `fetch_papers.py`. Each entry needs a `name` and RSS `url`.

### Adjusting topic tags

Edit `TAGS` in `fetch_papers.py`. Each tag maps to a list of title keywords.
Matching is case-insensitive substring matching on the paper title.

### Changing the schedule

Edit the cron expression in `.github/workflows/daily.yml`.
`"0 6 * * *"` = 06:00 UTC = 09:00 Israel time.

### RSS URL notes

- **Elsevier** (Heart Rhythm, JACC:EP): `https://rss.sciencedirect.com/publication/science/{ISSN}`
- **Oxford** (Europace): fetched via **CrossRef API** by ISSN instead of RSS (Oxford's RSS URLs are dynamically generated and not reliably accessible). Add to `CROSSREF_JOURNALS` in the script.
- **AHA** (Circ AE): `https://www.ahajournals.org/action/showFeed?type=ahead&feed=rss&jc=circep`
- **Wiley** (PACE, JCE): `https://onlinelibrary.wiley.com/feed/{eISSN}/most-recent`

If a feed stops working, test it by pasting the URL into your browser —
it should return XML. Wiley occasionally changes feed formats.

## Local development

```bash
pip install -r requirements.txt
python fetch_papers.py
open index.html
```

The script will print warnings for any feeds it can't reach. The email step
is skipped if `RESEND_API_KEY` is not set.
