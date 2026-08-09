#!/usr/bin/env python3
"""
Whatnot show tracker.

Samples what's live right now, appends the sample to data/history.jsonl,
then rebuilds data/summary.json for the dashboard.

    python run.py              # collect one sample + rebuild
    python run.py --rebuild    # rebuild summary only (no fetch)
    python run.py --seed 21    # generate 21 days of demo history to try it out

Two collectors ship here:
  DEMO   - synthetic but realistic. Default. Works with zero setup.
  APIFY  - real data via an Apify Whatnot actor. Set APIFY_TOKEN + APIFY_ACTOR.

See the note in fetch_shows() before pointing this at real data.
"""

import argparse
import json
import os
import random
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ----------------------------------------------------------------------------
# CONFIG - the only things you should need to change
# ----------------------------------------------------------------------------
LOCAL_TZ = ZoneInfo("America/New_York")   # your timezone; all analysis is in it
WINDOW_DAYS = 28                          # how much history the dashboard shows
MIN_SAMPLES_PER_SLOT = 2                  # don't recommend a slot seen once

DATA = Path(__file__).parent / "data"
HISTORY = DATA / "history.jsonl"
SUMMARY = DATA / "summary.json"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ----------------------------------------------------------------------------
# COLLECT
# ----------------------------------------------------------------------------
def fetch_shows():
    """Return a list of dicts: {streamer, category, viewers, title}.

    Whatnot has no public API. Options, in order of how defensible they are:

      1. APIFY (what this supports) - a third-party service that runs the
         scraping and carries that surface. Set APIFY_TOKEN and APIFY_ACTOR.
      2. Manual sampling - open the app a few times a night and type in what
         you see. Tedious, but 30 samples is enough to find your time slot.
      3. Rolling your own scraper - check Whatnot's Terms first. Automated
         access is very likely prohibited, and you would be building a
         business on top of a competitor's ToS violation.

    With no token set, this returns synthetic data so you can see the
    dashboard work end to end today.
    """
    token = os.environ.get("APIFY_TOKEN")
    actor = os.environ.get("APIFY_ACTOR")

    if token and actor:
        url = (f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
               f"?token={token}&timeout=120")
        req = urllib.request.Request(
            url,
            data=json.dumps({"maxItems": 200}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            rows = json.load(r)
        return [
            {
                "streamer": row.get("username") or row.get("seller") or "unknown",
                "category": row.get("category") or "Other",
                "viewers": int(row.get("viewers") or row.get("viewerCount") or 0),
                "title": (row.get("title") or "")[:120],
            }
            for row in rows
        ]

    return _demo_shows(datetime.now(timezone.utc))


# --- synthetic data so the dashboard works before you wire up a real source ---
_STREAMERS = [
    ("cardvaultbreaks", "Trading Cards"), ("thehobbyhouse", "Trading Cards"),
    ("slabsanddabs", "Trading Cards"),    ("buckeyebreaks", "Sports Cards"),
    ("pristinepulls", "Sports Cards"),    ("vintagevault614", "Sports Cards"),
    ("pokeprospector", "Pokemon"),        ("charizardcorner", "Pokemon"),
    ("gradedgoods", "Pokemon"),           ("sneakerstacks", "Sneakers"),
    ("funkofinds", "Pop Culture"),        ("comiccryptllc", "Comics"),
    ("coinsbykyle", "Coins"),             ("midwestmemorabilia", "Sports Cards"),
    ("ripcityrips", "Trading Cards"),     ("thecardcave", "Trading Cards"),
]


def _demo_shows(when_utc):
    """Realistic-ish snapshot: evening peak, weekend bump, long tail of viewers."""
    local = when_utc.astimezone(LOCAL_TZ)
    hour, weekday = local.hour, local.weekday()

    # how busy the platform is at this hour (0-1)
    curve = {0: .35, 1: .18, 2: .08, 3: .04, 4: .03, 5: .03, 6: .05, 7: .08,
             8: .12, 9: .16, 10: .20, 11: .24, 12: .30, 13: .32, 14: .34,
             15: .38, 16: .44, 17: .52, 18: .64, 19: .82, 20: .95, 21: 1.0,
             22: .88, 23: .62}[hour]
    if weekday >= 5:
        curve *= 1.25

    rng = random.Random(f"{local:%Y%m%d%H}")
    n = max(0, int(round(len(_STREAMERS) * curve * rng.uniform(.75, 1.15))))

    shows = []
    for name, cat in rng.sample(_STREAMERS, min(n, len(_STREAMERS))):
        # viewer demand peaks slightly EARLIER than show supply -> the gap
        # this dashboard is built to find
        demand = curve ** 0.65
        base = 40 * demand * rng.lognormvariate(0, 0.7)
        shows.append({
            "streamer": name,
            "category": cat,
            "viewers": max(1, int(base)),
            "title": f"{cat} show",
        })
    return shows


def collect(now=None):
    now = now or datetime.now(timezone.utc)
    shows = fetch_shows()
    sample = {
        "t": now.replace(microsecond=0).isoformat(),
        "shows": len(shows),
        "viewers": sum(s["viewers"] for s in shows),
        "detail": [
            {"s": s["streamer"], "c": s["category"], "v": s["viewers"]}
            for s in shows
        ],
    }
    DATA.mkdir(exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(json.dumps(sample) + "\n")
    return sample


# ----------------------------------------------------------------------------
# AGGREGATE
# ----------------------------------------------------------------------------
def load_history():
    if not HISTORY.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    out = []
    for line in HISTORY.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        t = datetime.fromisoformat(row["t"])
        if t >= cutoff:
            row["_local"] = t.astimezone(LOCAL_TZ)
            out.append(row)
    return out


def aggregate():
    rows = load_history()
    if not rows:
        return {"error": "no data yet - run `python run.py --seed 21` to try it out"}

    slots = defaultdict(lambda: {"shows": [], "viewers": []})
    hours = defaultdict(lambda: {"shows": [], "viewers": []})
    streamers = defaultdict(lambda: {"peak": 0, "views": [], "appearances": 0,
                                     "category": "Other"})
    cats = defaultdict(int)

    for r in rows:
        d, h = r["_local"].weekday(), r["_local"].hour
        slots[(d, h)]["shows"].append(r["shows"])
        slots[(d, h)]["viewers"].append(r["viewers"])
        hours[h]["shows"].append(r["shows"])
        hours[h]["viewers"].append(r["viewers"])
        for s in r.get("detail", []):
            st = streamers[s["s"]]
            st["peak"] = max(st["peak"], s["v"])
            st["views"].append(s["v"])
            st["appearances"] += 1
            st["category"] = s["c"]
            cats[s["c"]] += s["v"]

    def mean(xs):
        return round(sum(xs) / len(xs), 1) if xs else 0

    # day x hour grid
    grid = []
    for d in range(7):
        for h in range(24):
            cell = slots.get((d, h))
            if not cell:
                grid.append({"d": d, "h": h, "n": 0, "shows": 0,
                             "viewers": 0, "vps": 0})
                continue
            sh, vw = mean(cell["shows"]), mean(cell["viewers"])
            grid.append({
                "d": d, "h": h, "n": len(cell["shows"]),
                "shows": sh, "viewers": vw,
                "vps": round(vw / sh, 1) if sh else 0,
            })

    by_hour = []
    for h in range(24):
        cell = hours.get(h)
        sh = mean(cell["shows"]) if cell else 0
        vw = mean(cell["viewers"]) if cell else 0
        by_hour.append({
            "h": h, "n": len(cell["shows"]) if cell else 0,
            "shows": sh, "viewers": vw,
            "vps": round(vw / sh, 1) if sh else 0,
        })

    top = sorted(
        (
            {
                "name": k,
                "category": v["category"],
                "peak": v["peak"],
                "avg": mean(v["views"]),
                "shows": v["appearances"],
            }
            for k, v in streamers.items()
        ),
        key=lambda x: -x["peak"],
    )[:15]

    # best slots = most viewers per competing show, with enough samples to trust
    ranked = sorted(
        [c for c in grid if c["n"] >= MIN_SAMPLES_PER_SLOT and c["shows"] > 0],
        key=lambda c: -c["vps"],
    )[:5]

    busiest = max(by_hour, key=lambda x: x["viewers"])

    return {
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tz": str(LOCAL_TZ),
        "samples": len(rows),
        "days_covered": round((rows[-1]["_local"] - rows[0]["_local"]).total_seconds()
                              / 86400, 1),
        "grid": grid,
        "by_hour": by_hour,
        "top_streamers": top,
        "categories": sorted(
            ({"name": k, "viewers": v} for k, v in cats.items()),
            key=lambda x: -x["viewers"],
        )[:8],
        "best_slots": [
            {"label": f"{DAYS[c['d']]} {fmt_hour(c['h'])}", **c} for c in ranked
        ],
        "busiest_hour": {"label": fmt_hour(busiest["h"]), **busiest},
    }


def fmt_hour(h):
    ampm = "am" if h < 12 else "pm"
    hh = h % 12 or 12
    return f"{hh}{ampm}"


# ----------------------------------------------------------------------------
# RENDER  ->  README.md  (this is the dashboard; GitHub renders it for free)
# ----------------------------------------------------------------------------
RAMP = ["·", "░", "▒", "▓", "█"]   # 5 steps, low -> high


def bar(value, maximum, width=22):
    n = 0 if not maximum else max(1, round(value / maximum * width))
    return "█" * n


def write_readme(d):
    out = ["# Whatnot Show Tracker", ""]

    if d.get("error"):
        out += [d["error"], ""]
        Path(__file__).with_name("README.md").write_text("\n".join(out))
        return

    live = bool(os.environ.get("APIFY_TOKEN"))
    best = d["best_slots"][0]
    crowded = max(d["by_hour"], key=lambda x: x["shows"])

    out += [
        f"## Go live: **{best['label']}**",
        "",
        f"`{best['vps']}` viewers for every show that's competing with you — "
        f"the best ratio all week.",
        "",
        "| | |",
        "|---|---|",
        f"| Biggest audience | **{d['busiest_hour']['label']}** "
        f"({round(d['busiest_hour']['viewers'])} viewers platform-wide) |",
        f"| Most competition | **{fmt_hour(crowded['h'])}** "
        f"({crowded['shows']} shows live at once) |",
        f"| Samples collected | **{d['samples']}** over {d['days_covered']} days |",
        "",
    ]

    # --- heatmap -------------------------------------------------------
    mx = max((c["vps"] for c in d["grid"]), default=0) or 1
    ruler = " " * 5
    for h in range(24):
        ruler += (fmt_hour(h).replace("am", "a").replace("pm", "p")
                  .ljust(6) if h % 3 == 0 else "")
    lines = [ruler.rstrip()]
    for di, day in enumerate(DAYS):
        row = day.ljust(5)
        for h in range(24):
            c = next((g for g in d["grid"] if g["d"] == di and g["h"] == h), None)
            if not c or c["n"] == 0 or c["vps"] == 0:
                row += "  "
            else:
                row += RAMP[min(4, int(c["vps"] / mx * 4.99))] * 2
        lines.append(row)

    out += [
        "## When to stream",
        "",
        "Viewers per competing show, by day and hour. Denser blocks are better "
        "slots — that's audience going spare.",
        "",
        "```",
        *lines,
        "",
        f"     low  {' '.join(RAMP)}  high",
        "```",
        "",
        "| Best slot | Viewers/show | Shows live | Total viewers |",
        "|---|--:|--:|--:|",
    ]
    for s in d["best_slots"]:
        out.append(f"| {s['label']} | {s['vps']} | {s['shows']} | "
                   f"{round(s['viewers'])} |")

    # --- by hour -------------------------------------------------------
    hmx = max(x["vps"] for x in d["by_hour"]) or 1
    out += ["", "## Viewers per show, by hour", "", "```"]
    for x in d["by_hour"]:
        out.append(f"{fmt_hour(x['h']):>4}  {bar(x['vps'], hmx):<22} {x['vps']}")
    out += ["```", ""]

    # --- streamers -----------------------------------------------------
    smx = d["top_streamers"][0]["peak"] if d["top_streamers"] else 1
    out += ["## Top streamers", "",
            "| # | Streamer | Category | Peak | Avg | |",
            "|--:|---|---|--:|--:|---|"]
    for i, s in enumerate(d["top_streamers"], 1):
        out.append(f"| {i} | `{s['name']}` | {s['category']} | {s['peak']} | "
                   f"{s['avg']} | `{bar(s['peak'], smx, 16)}` |")

    # --- categories ----------------------------------------------------
    cmx = d["categories"][0]["viewers"] if d["categories"] else 1
    out += ["", "## Where the audience is", "",
            "| Category | Viewer-samples | |", "|---|--:|---|"]
    for c in d["categories"]:
        out.append(f"| {c['name']} | {c['viewers']:,} | "
                   f"`{bar(c['viewers'], cmx, 18)}` |")

    out += [
        "", "---", "",
        f"<sub>Updated {d['generated'].replace('T', ' ')[:16]} UTC · "
        f"times shown in {d['tz']} · "
        f"{'live data' if live else 'demo data'}</sub>", "",
    ]

    Path(__file__).with_name("README.md").write_text("\n".join(out))


# ----------------------------------------------------------------------------
def seed(days):
    """Backfill synthetic history so you can look at a full dashboard now."""
    DATA.mkdir(exist_ok=True)
    HISTORY.write_text("")
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    with HISTORY.open("a") as f:
        for i in range(days * 24, 0, -1):
            t = now - timedelta(hours=i)
            shows = _demo_shows(t)
            f.write(json.dumps({
                "t": t.isoformat(),
                "shows": len(shows),
                "viewers": sum(s["viewers"] for s in shows),
                "detail": [{"s": s["streamer"], "c": s["category"],
                            "v": s["viewers"]} for s in shows],
            }) + "\n")
    print(f"seeded {days} days of demo history")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rebuild", action="store_true", help="rebuild summary only")
    p.add_argument("--seed", type=int, metavar="DAYS", help="generate demo history")
    a = p.parse_args()

    if a.seed:
        seed(a.seed)
    elif not a.rebuild:
        s = collect()
        print(f"sampled {s['shows']} shows / {s['viewers']} viewers")

    DATA.mkdir(exist_ok=True)
    summary = aggregate()
    SUMMARY.write_text(json.dumps(summary, indent=1))
    write_readme(summary)
    print("wrote data/summary.json and README.md")


if __name__ == "__main__":
    main()
