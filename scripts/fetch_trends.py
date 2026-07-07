"""
Weekly data collector for the vibecoding trends dashboard.

Pulls three signals:
  1. GitHub  - repo count for a topic (e.g. "vibe-coding")
  2. PyPI    - weekly download totals for chosen packages
  3. Google Trends - search interest for a term, via pytrends (unofficial)

Appends one row per source per run to data/vibecoding_trends.csv, so that
history accumulates across scheduled runs instead of being overwritten.

Configuration lives in the CONFIG block below - edit these lists to track
different GitHub topics, PyPI packages, or Trends search terms.
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

GITHUB_TOPICS = ["vibe-coding", "claude-code", "github-copilot"] # add "-" instead of a space between words
PYPI_PACKAGES = ["vibe-coding", "claude-code", "github copilot"]  # add more pip-installable package names here
TRENDS_TERMS = ["vibe coding", "claude code", "github copilot"]

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "vibecoding_trends.csv")
CSV_HEADERS = ["date", "source", "metric", "value"]

# GitHub API auth is optional but strongly recommended (60/hr unauth vs 5000/hr auth)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


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
# 2. PyPI - weekly downloads per package
# ---------------------------------------------------------------------------

def fetch_pypi_downloads():
    print("Fetching PyPI download stats...")
    for package in PYPI_PACKAGES:
        url = f"https://pypistats.org/api/packages/{package}/overall"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  WARNING: pypistats returned {resp.status_code} for '{package}': {resp.text[:200]}")
            continue
        data = resp.json().get("data", [])
        # Sum the last 7 days of "without_mirrors" downloads as a weekly figure
        recent = sorted(data, key=lambda d: d["date"])[-7:]
        weekly_total = sum(d["downloads"] for d in recent if d.get("category") == "without_mirrors") or \
            sum(d["downloads"] for d in recent)
        append_row("pypi", f"weekly_downloads_{package}", weekly_total)


# ---------------------------------------------------------------------------
# 3. Google Trends - search interest per term (unofficial API via pytrends)
# ---------------------------------------------------------------------------

def fetch_google_trends():
    print("Fetching Google Trends data...")
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  WARNING: pytrends not installed, skipping Google Trends fetch.")
        return

    try:
        pytrends = TrendReq(hl="en-US", tz=0)
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
    fetch_pypi_downloads()
    fetch_google_trends()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
