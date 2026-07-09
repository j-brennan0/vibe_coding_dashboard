"""
Weekly data collector for the vibecoding trends dashboard.

Writes to TWO separate CSVs, since GitHub/Reddit produce raw counts while
Google Trends produces a 0-100 relative index - different units that
shouldn't be plotted on the same axis without normalization:

  data/counts_trends.csv   <- GitHub repo counts + Reddit post mentions (raw counts)
  data/interest_trends.csv <- Google Trends search interest (0-100 index)

Sources:
  1. GitHub  - repo count per topic tag (official API)
  2. Hacker News - story + comment mention counts per search term, last 7
     days, via the official Algolia HN Search API. No auth, no approval
     process, and returns a true total match count (nbHits).
  3. Google Trends - search interest via Trends MCP (api.trendsmcp.ai), a
     third-party managed proxy. Switched to this after both pytrends and
     pytrends-modern were confirmed, in real GitHub Actions runs, to get
     blocked with 429 errors from Google - GitHub's shared runner IPs are
     apparently already flagged. Trends MCP's free tier is capped at 100
     requests/month and 20/day, so TRENDS_TERMS is intentionally kept short.
     IMPORTANT CAVEAT: this is an unverified, heavily content-marketed
     third-party vendor, not a Google-official source. See the README for
     the full reliability caveat - this is the least stable link in the
     pipeline and may need replacing again if the vendor changes terms or
     shuts down.

Configuration lives in the CONFIG block below.
"""

import csv
import datetime
import os
import sys
import time

import requests

# ---------------------------------------------------------------------------
# CONFIG - edit these to change what gets tracked
# ---------------------------------------------------------------------------

GITHUB_TOPICS = ["vibe-coding", "github-copilot", "claude-code", "codex", "cursor-ide"]
HN_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex", "cursor ai"]
TRENDS_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex"]  # kept short - Trends MCP free tier caps at 20 requests/day, 100/month

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
COUNTS_CSV_PATH = os.path.join(DATA_DIR, "counts_trends.csv")
INTEREST_CSV_PATH = os.path.join(DATA_DIR, "interest_trends.csv")
CSV_HEADERS = ["date", "source", "metric", "value"]

# GitHub API auth is optional but strongly recommended (60/hr unauth vs 5000/hr auth)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Hacker News (Algolia Search API) needs no credentials at all - no key,
# no approval process, no rate limit officially published (the script
# still paces itself out of courtesy).

# Trends MCP (api.trendsmcp.ai) - free tier requires an API key. Register at
# trendsmcp.ai, add as a repo secret named TRENDS_MCP_API_KEY.
TRENDS_MCP_API_KEY = os.environ.get("TRENDS_MCP_API_KEY", "")


def today_str():
    return datetime.date.today().isoformat()


def ensure_csv_exists(path):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def append_row(path, source, metric, value):
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([today_str(), source, metric, value])
    print(f"  wrote: {source} | {metric} | {value}")


# ---------------------------------------------------------------------------
# 1. GitHub - repo count per topic  -> counts_trends.csv
# ---------------------------------------------------------------------------

def fetch_github_topic_counts():
    print("Fetching GitHub topic counts...")
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    for topic in GITHUB_TOPICS:
        url = "https://api.github.com/search/repositories"
        params = {"q": f"topic:{topic}", "per_page": 1}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  WARNING: GitHub API returned {resp.status_code} for topic '{topic}': {resp.text[:200]}")
            continue
        total_count = resp.json().get("total_count", 0)
        append_row(COUNTS_CSV_PATH, "github", f"repo_count_{topic}", total_count)


# ---------------------------------------------------------------------------
# 2. Hacker News - story + comment mentions per term, last 7 days
#    (docs: https://hn.algolia.com/api) -> counts_trends.csv
# ---------------------------------------------------------------------------

def fetch_hn_mentions():
    print("Fetching Hacker News mention counts...")
    now = datetime.datetime.now(datetime.timezone.utc)
    one_week_ago = now - datetime.timedelta(days=7)
    now_ts = int(now.timestamp())
    week_ago_ts = int(one_week_ago.timestamp())

    for term in HN_TERMS:
        metric_name = term.replace(" ", "_")

        # Stories and comments are tracked separately - posting vs. discussing
        # are different behaviors and shouldn't be silently summed together.
        for tag, label in [("story", "stories"), ("comment", "comments")]:
            url = "https://hn.algolia.com/api/v1/search_by_date"
            params = {
                "query": term,
                "tags": tag,
                "numericFilters": f"created_at_i>{week_ago_ts},created_at_i<{now_ts}",
                "hitsPerPage": 1,  # we only need nbHits, not the actual hits
            }
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"  WARNING: HN Algolia API returned {resp.status_code} for '{term}' ({label}): {resp.text[:200]}")
                time.sleep(1)
                continue
            total_hits = resp.json().get("nbHits", 0)
            append_row(COUNTS_CSV_PATH, "hackernews", f"weekly_{label}_{metric_name}", total_hits)
            time.sleep(1)  # polite pacing, no official rate limit but good practice


# ---------------------------------------------------------------------------
# 3. Google Trends (via Trends MCP) - search interest per term -> interest_trends.csv
#    (docs: https://www.trendsmcp.ai/docs)
# ---------------------------------------------------------------------------

def fetch_google_trends():
    print("Fetching Google Trends data (via Trends MCP)...")
    if not TRENDS_MCP_API_KEY:
        print("  WARNING: TRENDS_MCP_API_KEY not set, skipping Google Trends fetch.")
        return

    headers = {"Authorization": f"Bearer {TRENDS_MCP_API_KEY}"}

    for term in TRENDS_TERMS:
        body = {
            "mode": "get_time_series",
            "source": "google search",
            "keyword": term,
            "data_mode": "weekly",
        }
        try:
            resp = requests.post("https://api.trendsmcp.ai/api", headers=headers, json=body, timeout=30)
        except Exception as e:
            print(f"  WARNING: Trends MCP request failed for '{term}': {e}")
            time.sleep(2)
            continue

        if resp.status_code != 200:
            print(f"  WARNING: Trends MCP returned {resp.status_code} for '{term}': {resp.text[:200]}")
            time.sleep(2)
            continue

        # Response shape is inferred from partial vendor documentation (this
        # is a third-party service, not an Anthropic or Google product) - if
        # this breaks, check trendsmcp.ai/docs for the current exact schema
        # and adjust the parsing below accordingly.
        payload = resp.json()
        series = payload.get("data") or payload.get("results") or payload.get("series") or payload
        if not series or not isinstance(series, list):
            print(f"  WARNING: unexpected Trends MCP response shape for '{term}': {str(payload)[:200]}")
            time.sleep(2)
            continue

        latest_point = series[-1]  # most recent week
        latest_value = latest_point.get("value")
        if latest_value is None:
            print(f"  WARNING: no 'value' field in latest Trends MCP data point for '{term}': {latest_point}")
            time.sleep(2)
            continue

        append_row(INTEREST_CSV_PATH, "google_trends", f"interest_{term.replace(' ', '_')}", int(latest_value))
        time.sleep(2)  # stay well under the 20/day cap


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ensure_csv_exists(COUNTS_CSV_PATH)
    ensure_csv_exists(INTEREST_CSV_PATH)
    fetch_github_topic_counts()
    fetch_hn_mentions()
    fetch_google_trends()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
