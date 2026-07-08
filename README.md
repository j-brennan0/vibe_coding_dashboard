# Vibecoding trends dashboard - data pipeline

Weekly, automated collection of three vibecoding-adoption signals (GitHub topic
activity, Stack Overflow tag question volume, Google Trends search interest),
feeding a Power BI dashboard.

## How it works

```
GitHub Actions (weekly, cron)
  -> runs scripts/fetch_trends.py
  -> appends new rows to data/vibecoding_trends.csv
  -> commits + pushes the file back to this repo
                    |
                    v
Power BI Service (weekly scheduled refresh)
  -> reads the CSV via the GitHub Contents API
  -> dashboard updates automatically
```

## Step-by-step setup

### 1. Create the repo
Create a new GitHub repo (public or private - this project assumes **private**,
per your earlier decision). Clone it locally, then copy in everything from this
project: `.github/workflows/update-data.yml`, `data/vibecoding_trends.csv`,
`scripts/fetch_trends.py`, `scripts/requirements.txt`, this README.

### 2. Push the initial commit
```bash
git add .
git commit -m "Initial vibecoding trends pipeline"
git push
```
No secrets need configuring yet - the workflow uses GitHub's own built-in
`GITHUB_TOKEN`, which Actions provides automatically and scopes to this repo
only. You don't need to create anything for the write side to work.

### 3. Test the workflow manually
Go to the repo's **Actions** tab -> "Update vibecoding trends data" ->
**Run workflow** (this works because of the `workflow_dispatch` trigger in the
YAML). Watch the run logs. You should see three fetch steps run and a new
commit appear adding a row per source to `data/vibecoding_trends.csv`.

If the Stack Overflow or Trends steps warn or fail on first run, check the log output -
`fetch_trends.py` prints a `WARNING:` line with the actual HTTP status or
error rather than failing silently.

### 4. Let it run weekly on its own
The cron schedule (`0 6 * * 1` = every Monday 06:00 UTC) needs no further
action - GitHub runs it automatically from here. Adjust the cron expression
in the YAML if you want a different day/time.

### 5. Generate a fine-grained PAT for Power BI to read the private repo
Power BI needs read access to pull the CSV out of a private repo:
- GitHub -> Settings -> Developer settings -> Personal access tokens ->
  Fine-grained tokens -> Generate new token
- Repository access: **only this repository**
- Permissions: **Contents - Read-only** (nothing else)
- Copy the token now - GitHub only shows it once

### 6. Connect Power BI to the private CSV
In Power BI Desktop:
- Get Data -> Web -> Advanced
- URL: `https://api.github.com/repos/<owner>/<repo>/contents/data/vibecoding_trends.csv`
- Add header: `Authorization` = `Bearer <your fine-grained PAT>`
- Add header: `Accept` = `application/vnd.github.raw`
- Load - Power Query will parse the CSV content directly

### 7. Shape the data in Power Query
Split `metric` if you want separate visuals per source, or pivot `source` +
`metric` into columns depending on how you want the report laid out. Set
`date` to Date type and `value` to a numeric type explicitly - Power Query
sometimes infers these as text from a raw API response.

### 8. Publish and schedule refresh
- Publish to a **shared Power BI workspace** (not "My Workspace") so it isn't
  tied to one person's account
- In Power BI Service: dataset settings -> Scheduled refresh -> weekly,
  matching (or trailing a few hours after) the GitHub Actions cron time

## Configuration

Edit the top of `scripts/fetch_trends.py` to change what's tracked:
- `GITHUB_TOPICS` - GitHub topic tags to count repos for
- `STACKOVERFLOW_TAGS` - Stack Overflow tags to pull weekly new-question counts
  and all-time totals for. If a tag doesn't exist yet on Stack Overflow (too new
  or too low-volume to have been created), the script logs a `NOTE:` and writes
  0 rather than failing.
- `TRENDS_TERMS` - search terms to pull Google Trends interest for

### Optional: Stack Exchange API key
Requests work without any key, but share a low IP-based quota (~300/day) with
everyone else hitting the API from the same runner IP - can be tight on shared
GitHub-hosted runners. To raise this, register a free key at
[stackapps.com](https://stackapps.com/apps/oauth/register) and add it as a
repository secret named `STACK_APPS_KEY` (Settings -> Secrets and variables ->
Actions -> New repository secret). The workflow already references this secret
and will simply run without a key if the secret is left unset.

## Handoff notes (for whoever inherits this)

- The **write side** (Actions -> commit) needs no secret rotation ever - it
  uses GitHub's auto-provided token.
- The **read side** (Power BI's PAT) is tied to whoever generated it. If that
  person loses repo access, Power BI refresh will start failing with an auth
  error. Generate a fresh token under the inheriting account's login and swap
  it into the Power Query step above.
- If migrating the repo to an org, use Settings -> Transfer ownership. Both
  the workflow and its built-in token continue working immediately after
  transfer with no changes needed.
