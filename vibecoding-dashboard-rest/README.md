# Vibecoding trends dashboard - data pipeline

Weekly, automated collection of vibecoding-adoption signals across GitHub,
Reddit, and Google Trends, feeding a Power BI dashboard.

## Two output files, not one

Data is split into two CSVs because GitHub/Reddit produce **raw counts**
while Google Trends produces a **0-100 relative index** - different units
that shouldn't be plotted on the same axis without normalization.

- `data/counts_trends.csv` - GitHub repo counts + Reddit post mentions
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

**GitHub** - for each configured topic tag, how many repos are labeled with
that exact topic. Official API, no auth required (though a token raises the
rate limit substantially).

**Reddit** - for each configured search term, how many posts (titles/bodies,
not comments - no public comment-search endpoint exists) mentioned that term
in the last 7 days. Capped at 100 per term per run, since Reddit's API has
no "total matches" figure - only actual paginated results can be counted.
If a term hits the cap, the script logs a `NOTE:` - the real number could be
higher than what's recorded.

**Google Trends** - relative search interest (0-100, where 100 = that term's
own peak over the last 3 months). Not a count of anything - an index. Uses
`pytrends-modern`, a maintained fork; the original `pytrends` library was
archived by its maintainers in April 2025 and is no longer reliable.

## Step-by-step setup

### 1. Push the project into your repo
Copy in `.github/workflows/update-data.yml`, `data/counts_trends.csv`,
`data/interest_trends.csv`, `scripts/fetch_trends.py`,
`scripts/requirements.txt`, this README - into your repo root (not as a
subfolder).

### 2. Register a Reddit app for API credentials
Go to https://www.reddit.com/prefs/apps -> **Create App** -> choose
**script** type -> fill in any name/description/redirect URI (redirect URI
isn't used for this flow, any placeholder like `http://localhost` works.
Note: self-service registration has reportedly required manual approval for
some new accounts recently - if you hit that, budget extra time before this
step is usable).

After creating the app, you'll see:
- **client ID** - the string under the app name, directly below "personal use script"
- **client secret** - labeled "secret"

### 3. Add repo secrets
Settings -> Secrets and variables -> Actions -> New repository secret:
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`

(`GITHUB_TOKEN` needs no setup - Actions provides it automatically.)

### 4. Test the workflow manually
Actions tab -> "Update vibecoding trends data" -> Run workflow. Check the
logs for each of the three fetch steps, and confirm both CSVs got new rows.

### 5. Let it run weekly
Cron is set to Monday 06:00 UTC - no further action needed.

### 6. Connect Power BI - TWO separate Web API connections
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

### 7. Shape both in Power Query
Set `date` to Date type, `value` to Whole Number, on both queries
independently.

### 8. Build visuals
Keep the two queries as separate tables (don't merge/append them - the
units don't match). Build one visual set for counts, one for the interest
index, using `source`/`metric` slicers on each as before.

### 9. Publish and schedule refresh
Shared workspace, weekly scheduled refresh (Pro license required).

## Configuration

Edit the top of `scripts/fetch_trends.py`:
- `GITHUB_TOPICS` - GitHub topic tags to count repos for
- `REDDIT_TERMS` - search phrases to count Reddit posts for
- `TRENDS_TERMS` - search phrases to pull Google Trends interest for

## Handoff notes (for whoever inherits this)

- **GitHub Actions write side**: uses the auto-provided `GITHUB_TOKEN`, no
  rotation ever needed.
- **Reddit credentials**: tied to whoever registered the app. If that
  account loses access, a new app needs registering and the two repo
  secrets updated.
- **Power BI read side (PAT)**: tied to whoever generated it - same
  rotation note as before, except now there are two Power Query connections
  both using it, so update both if it's rotated.
- Transferring the repo to an org: Settings -> Transfer ownership. Both
  workflow secrets need re-adding under the new org repo (secrets don't
  transfer automatically with repo ownership).
