"""
Weekly data collector for the vibecoding trends dashboard.

Writes to TWO separate CSVs, since GitHub/Reddit produce raw counts while
Google Trends produces a 0-100 relative index - different units that
shouldn't be plotted on the same axis without normalization:

  data/counts_trends.csv   <- GitHub repo counts + Reddit post mentions (raw counts)
  data/interest_trends.csv <- Google Trends search interest (0-100 index)

Sources:
  1. GitHub  - repo count per topic tag (official API)
  2. Reddit  - post count per search term, last 7 days, capped at 100 per
     term since Reddit's API has no true "total matches" figure - you can
     only page through actual results and count them. A term hitting the
     cap gets flagged with a NOTE, since the real number could be higher.
     Only searches post titles/bodies, not comments (no public comment
     search endpoint exists).
  3. Google Trends - search interest via pytrends-modern (maintained fork;
     the original pytrends was archived in April 2025 and is unreliable)

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
REDDIT_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex", "cursor ai"]
TRENDS_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex", "cursor ai"]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
COUNTS_CSV_PATH = os.path.join(DATA_DIR, "counts_trends.csv")
INTEREST_CSV_PATH = os.path.join(DATA_DIR, "interest_trends.csv")
CSV_HEADERS = ["date", "source", "metric", "value"]

# GitHub API auth is optional but strongly recommended (60/hr unauth vs 5000/hr auth)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Reddit requires app credentials - register a "script" type app at
# https://www.reddit.com/prefs/apps to get these.
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "vibecoding-trends-dashboard/1.0")


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
# 2. Reddit - post mentions per search term, last 7 days -> counts_trends.csv
#    (docs: https://www.reddit.com/dev/api/)
# ---------------------------------------------------------------------------

def get_reddit_token():
    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": REDDIT_USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_reddit_mentions():
    print("Fetching Reddit mention counts...")
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        print("  WARNING: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set, skipping Reddit fetch.")
        return

    try:
        token = get_reddit_token()
    except Exception as e:
        print(f"  WARNING: Reddit authentication failed: {e}")
        return

    headers = {"Authorization": f"Bearer {token}", "User-Agent": REDDIT_USER_AGENT}

    for term in REDDIT_TERMS:
        params = {"q": term, "t": "week", "limit": 100, "sort": "new"}
        resp = requests.get("https://oauth.reddit.com/search", headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  WARNING: Reddit API returned {resp.status_code} for term '{term}': {resp.text[:200]}")
            time.sleep(2)
            continue
        posts = resp.json().get("data", {}).get("children", [])
        count = len(posts)
        if count >= 100:
            print(f"  NOTE: '{term}' hit the 100-post cap - actual weekly mentions may be higher. "
                  f"This script only counts a single page of results, not true pagination.")
        append_row(COUNTS_CSV_PATH, "reddit", f"weekly_mentions_{term.replace(' ', '_')}", count)
        time.sleep(2)  # respect Reddit's rate limits


# ---------------------------------------------------------------------------
# 3. Google Trends - search interest per term -> interest_trends.csv
# ---------------------------------------------------------------------------

def fetch_google_trends():
    print("Fetching Google Trends data...")
    try:
        from pytrends_modern import TrendReq
    except ImportError:
        print("  WARNING: pytrends-modern not installed, skipping Google Trends fetch.")
        return

    try:
        pytrends = TrendReq(
            hl="en-US",
            tz=0,
            retries=3,
            backoff_factor=0.5,
            rotate_user_agent=True,
        )
        for term in TRENDS_TERMS:
            pytrends.build_payload([term], timeframe="today 3-m")
            df = pytrends.interest_over_time()
            if df.empty:
                print(f"  WARNING: no Trends data returned for '{term}'")
                continue
            latest_value = int(df[term].iloc[-1])
            append_row(INTEREST_CSV_PATH, "google_trends", f"interest_{term.replace(' ', '_')}", latest_value)
            time.sleep(2)  # be polite between requests
    except Exception as e:
        print(f"  WARNING: Google Trends fetch failed: {e}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ensure_csv_exists(COUNTS_CSV_PATH)
    ensure_csv_exists(INTEREST_CSV_PATH)
    fetch_github_topic_counts()
    fetch_reddit_mentions()
    fetch_google_trends()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
