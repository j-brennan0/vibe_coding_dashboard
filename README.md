# Vibecoding trends dashboard - data pipeline

Weekly, automated collection of vibecoding-adoption signals across GitHub,
Hacker News, and Google Trends, feeding a Power BI dashboard.

## Two output files, not one

Data is split into two CSVs because GitHub/Hacker News produce **raw
counts** while Google Trends produces a **0-100 relative index** -
different units that shouldn't be plotted on the same axis without
normalization.

- `data/counts_trends.csv` - GitHub repo counts + Hacker News mentions
- `data/interest_trends.csv` - Google Trends search interest index

Both share the same shape: `date, source, metric, value`.

## How it works

```
GitHub Actions (weekly, cron)
  -> runs scripts/fetch_trends.py
  -> appends new rows to BOTH csv files
  -> commits + pushes both back to this repo
                    |
                    v
Power BI Service (weekly scheduled refresh)
  -> reads BOTH csvs via the GitHub Contents API (two separate queries)
  -> dashboard updates automatically
```

## What each source actually measures

**GitHub** - for each configured topic tag, how many repos are labeled
with that exact topic. Official API, no auth required (though a token
raises the rate limit substantially).

**Hacker News** - for each configured search term, how many stories and
how many comments mentioned that term in the last 7 days, tracked as
separate metrics (posting vs. discussing are different behaviors). Uses
the official Algolia HN Search API - no auth, no approval process, and
unlike some other sources, it returns a true total match count (`nbHits`)
rather than being artificially capped by pagination.

**Google Trends** - relative search interest (0-100, where 100 = that
term's own peak over the last 3 months). Not a count of anything - an
index. Uses `pytrends-modern`, a maintained fork; the original `pytrends`
library was archived by its maintainers in April 2025 and is no longer
reliable.

## Why Hacker News instead of Reddit or Stack Overflow

Reddit's official API now requires manual approval under its Responsible
Builder Policy, with no published timeline and reported rejections for
small personal projects - not workable for a dependable weekly pipeline.
Stack Overflow's overall question volume has collapsed since ChatGPT's
2022 launch (a well-documented ~90%+ drop), making it a shrinking, less
representative signal over time. Hacker News needs no approval, has an
active and specifically developer-focused audience, and its search API
gives exact counts with no artificial cap.

## Step-by-step setup

### 1. Push the project into your repo
Copy in `.github/workflows/update-data.yml`, `data/counts_trends.csv`,
`data/interest_trends.csv`, `scripts/fetch_trends.py`,
`scripts/requirements.txt`, this README - into your repo root (not as a
subfolder).

No API credentials or secrets are required for GitHub or Hacker News -
`GITHUB_TOKEN` is provided automatically by Actions.

### 2. Test the workflow manually
Actions tab -> "Update vibecoding trends data" -> Run workflow. Check the
logs for each of the three fetch steps, and confirm both CSVs got new rows.

### 3. Let it run weekly
Cron is set to Monday 06:00 UTC - no further action needed.

### 4. Connect Power BI - TWO separate Web API connections
Repeat the connection process once per file:

- Get Data -> **Web API**
- URL (base only): `https://api.github.com`
- Authentication kind: Anonymous
- Click Next, then open **Advanced Editor** and use:

```m
let
    Source = Web.Contents("https://api.github.com", [
        RelativePath = "repos/<owner>/<repo>/contents/data/counts_trends.csv",
        Headers = [
            Authorization = "Bearer <your fine-grained PAT>",
            Accept = "application/vnd.github.raw"
        ]
    ]),
    #"Imported CSV" = Csv.Document(Source, [Delimiter=",", Columns=4, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    #"Promoted Headers" = Table.PromoteHeaders(#"Imported CSV", [PromoteAllScalars=true])
in
    #"Promoted Headers"
```

Repeat with `RelativePath` pointing at `data/interest_trends.csv` for the
second query. Name the two queries something clear (e.g. `CountsTrends` and
`InterestTrends`) in the Queries pane.

### 5. Shape both in Power Query
Set `date` to Date type, `value` to Whole Number, on both queries
independently.

### 6. Build visuals
Keep the two queries as separate tables (don't merge/append them - the
units don't match). Build one visual set for counts, one for the interest
index, using `source`/`metric` slicers on each.

### 7. Publish and schedule refresh
Shared workspace, weekly scheduled refresh (Pro license required).

## Configuration

Edit the top of `scripts/fetch_trends.py`:
- `GITHUB_TOPICS` - GitHub topic tags to count repos for
- `HN_TERMS` - search phrases to count HN story/comment mentions for
- `TRENDS_TERMS` - search phrases to pull Google Trends interest for

## Handoff notes (for whoever inherits this)

- **GitHub Actions write side**: uses the auto-provided `GITHUB_TOKEN`, no
  rotation ever needed. Hacker News needs no credentials at all, so nothing
  to rotate there either.
- **Power BI read side (PAT)**: tied to whoever generated it. If that
  person loses repo access, both Power Query connections (counts + interest)
  need their token swapped for a freshly generated one.
- Transferring the repo to an org: Settings -> Transfer ownership. No
  secrets need re-adding for the write side, since GITHUB_TOKEN is
  auto-provided per-repo regardless of ownership.
