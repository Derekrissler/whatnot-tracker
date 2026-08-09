# Setup

`README.md` is **generated** — every run overwrites it. Edit this file instead.

## What this does

Every 2 hours a GitHub Action samples what's live on Whatnot, appends it to
`data/history.jsonl`, rebuilds `README.md` from the whole history, and pushes.
Your repo homepage becomes a self-updating dashboard. No Pages, no hosting,
nothing to deploy.

The metric it's built around is **viewers per competing show**. Everyone knows
8–10pm has the most viewers, which is exactly why it's crowded. A slot with 400
viewers and 6 streams beats one with 900 viewers and 30 streams.

## Get it running — 3 minutes

```bash
python3 run.py --seed 21     # fill it with demo data so there's something to see
git init
git add -A
git commit -m "whatnot tracker"
gh repo create whatnot-tracker --public --source=. --push
```

No `gh` CLI? Create an empty public repo on github.com and follow the push
instructions it shows you.

Then **one required setting**:

> Settings → Actions → General → Workflow permissions → **Read and write permissions**

Without it the job runs fine and then fails on `git push`. This is the single
most common way this breaks.

Finally, open the **Actions** tab and hit *Run workflow* once to confirm. After
that it runs itself.

Public repo matters: Actions minutes are unlimited on public repos, capped at
2,000/month on private free plans. This uses about 350/month.

## Real data

Out of the box this generates **synthetic** data — the streamer names are made
up. It exists so you can confirm the pipeline works before spending anything.

Whatnot has no public API. Options:

- **Apify** (supported here). Third-party actors scrape Whatnot and expose it as
  a paid API, which puts that surface on them rather than you. Add two repo
  secrets under *Settings → Secrets and variables → Actions*: `APIFY_TOKEN` and
  `APIFY_ACTOR` (e.g. `getascraper~whatnot-scraper`). Then wipe the demo history
  so it doesn't pollute your real data:

  ```bash
  rm data/history.jsonl && python3 run.py
  ```

  Expect to adjust the field mapping in `fetch_shows()` — every actor names its
  fields differently. Print the first result before trusting it.

- **Manual sampling.** Open the app a few times a night and type in what you
  see. About 30 well-spread samples is enough to find your slot. Costs nothing.

- **Your own scraper.** Read Whatnot's Terms first. Automated access is very
  likely prohibited, and building your marketplace on a competitor's ToS
  violation is a bad opening move.

## Files

```
run.py                       collect + aggregate + write README
README.md                    GENERATED — do not edit
data/history.jsonl           append-only raw samples — never overwrite this
data/summary.json            aggregated numbers
index.html                   optional prettier dashboard, if you ever want it
.github/workflows/track.yml  the job
```

`index.html` is a nicer interactive version with a colour heatmap and tooltips.
You don't need it, but if you want it: `python3 -m http.server 8000` and open
localhost:8000. (Double-clicking the file won't work — browsers block `fetch()`
on `file://`.)

## Commands

```bash
python3 run.py               # take a sample, rebuild everything
python3 run.py --rebuild     # rebuild README + summary without sampling
python3 run.py --seed 21     # replace history with 21 days of demo data
```

## Settings

Top of `run.py`:

| Setting | Default | Does what |
|---|---|---|
| `LOCAL_TZ` | `America/New_York` | Timezone all analysis is done in |
| `WINDOW_DAYS` | `28` | How much history the dashboard covers |
| `MIN_SAMPLES_PER_SLOT` | `2` | Won't recommend a slot it's seen once |

## Gotchas

- **`data/history.jsonl` is the asset.** One sample is worth little; the time
  series is the point, and you can't backfill it. Never let anything overwrite it.
- GitHub cron is **UTC only** and drifts an hour twice a year with DST.
- Scheduled workflows are **auto-disabled after 60 days** of repo inactivity.
  The commits this makes prevent that on their own.
- Schedules only fire from the **default branch**. Test with *Run workflow*, not
  by pushing to a feature branch.
- Give it a week before trusting the heatmap. Under ~2 samples per slot you're
  looking at noise — that's what `MIN_SAMPLES_PER_SLOT` guards against.
