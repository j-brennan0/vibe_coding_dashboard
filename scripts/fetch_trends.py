"""
Weekly data collector for the vibecoding trends dashboard.

Pulls three signals:
  1. GitHub  - repo count for a topic (e.g. "vibe-coding")
  2. Stack Overflow - weekly new question counts + all-time total for chosen tags,
     via the official Stack Exchange API
  3. Google Trends - search interest for a term, via pytrends-modern (an
     actively maintained fork; the original pytrends library was archived
     by its maintainers in April 2025 and is no longer reliable)

Appends one row per source per run to data/vibecoding_trends.csv, so that
history accumulates across scheduled runs instead of being overwritten.

Configuration lives in the CONFIG block below - edit these lists to track
different GitHub topics, Stack Overflow tags, or Trends search terms.
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

GITHUB_TOPICS = ["vibe-coding"]
STACKOVERFLOW_TAGS = ["vibe-coding"]  # add more Stack Overflow tags here
TRENDS_TERMS = ["vibe coding"]

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "vibecoding_trends.csv")
CSV_HEADERS = ["date", "source", "metric", "value"]

# GitHub API auth is optional but strongly recommended (60/hr unauth vs 5000/hr auth)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Stack Exchange API key is optional. Without one, requests share a low IP-based
# quota (roughly 300/day) across everyone on the same runner IP, which can be
# tight on shared GitHub-hosted runners. With a free key (from stackapps.com),
# the quota rises substantially. Set as a repo secret named STACK_APPS_KEY if used.
STACK_APPS_KEY = os.environ.get("STACK_APPS_KEY", "")


def today_str():
    return datetime.date.today().isoformat()


def ensure_csv_exists():
    if not os.path.exists(CSV_PATH):
        os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def append_row(source, metric, value):
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([today_str(), source, metric, value])
    print(f"  wrote: {source} | {metric} | {value}")


# ---------------------------------------------------------------------------
# 1. GitHub - repo count per topic
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
        append_row("github", f"repo_count_{topic}", total_count)


# ---------------------------------------------------------------------------
# 2. Stack Overflow - question volume per tag, via the official Stack Exchange API
#    (docs: https://api.stackexchange.com/docs)
# ---------------------------------------------------------------------------

def fetch_stackoverflow_tags():
    print("Fetching Stack Overflow tag stats...")
    now = datetime.datetime.now(datetime.timezone.utc)
    one_week_ago = now - datetime.timedelta(days=7)

    for tag in STACKOVERFLOW_TAGS:
        # (a) All-time total questions for this tag - a snapshot, not a weekly figure,
        # but useful context alongside the weekly number below.
        info_url = f"https://api.stackexchange.com/2.3/tags/{tag}/info"
        info_params = {"site": "stackoverflow"}
        if STACK_APPS_KEY:
            info_params["key"] = STACK_APPS_KEY
        info_resp = requests.get(info_url, params=info_params, timeout=30)
        if info_resp.status_code != 200:
            print(f"  WARNING: Stack Exchange API returned {info_resp.status_code} for tag info '{tag}': {info_resp.text[:200]}")
        else:
            items = info_resp.json().get("items", [])
            if not items:
                # This means the tag doesn't exist (yet) on Stack Overflow, or has
                # too little volume to have been created as an official tag.
                print(f"  NOTE: tag '{tag}' not found on Stack Overflow - writing 0. "
                      f"Consider checking https://stackoverflow.com/questions/tagged/{tag} directly.")
                append_row("stackoverflow", f"total_questions_{tag}", 0)
            else:
                append_row("stackoverflow", f"total_questions_{tag}", items[0].get("count", 0))
        time.sleep(1)

        # (b) New questions with this tag in the last 7 days - the actual weekly signal.
        search_url = "https://api.stackexchange.com/2.3/questions"
        search_params = {
            "site": "stackoverflow",
            "tagged": tag,
            "fromdate": int(one_week_ago.timestamp()),
            "todate": int(now.timestamp()),
            "filter": "total",  # built-in filter that returns just {"total": N}, saves quota
        }
        if STACK_APPS_KEY:
            search_params["key"] = STACK_APPS_KEY
        search_resp = requests.get(search_url, params=search_params, timeout=30)
        if search_resp.status_code != 200:
            print(f"  WARNING: Stack Exchange API returned {search_resp.status_code} for weekly count '{tag}': {search_resp.text[:200]}")
            time.sleep(1)
            continue
        weekly_total = search_resp.json().get("total", 0)
        append_row("stackoverflow", f"weekly_new_questions_{tag}", weekly_total)
        time.sleep(1)  # be polite between requests, respects Stack Exchange's throttle guidance


# ---------------------------------------------------------------------------
# 3. Google Trends - search interest per term (unofficial API via pytrends)
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
            append_row("google_trends", f"interest_{term.replace(' ', '_')}", latest_value)
            time.sleep(2)  # be polite between requests
    except Exception as e:
        print(f"  WARNING: Google Trends fetch failed: {e}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ensure_csv_exists()
    fetch_github_topic_counts()
    fetch_stackoverflow_tags()
    fetch_google_trends()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
