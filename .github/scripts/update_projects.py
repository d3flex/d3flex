"""Rewrite the GH-PROJECTS block in README.md with the top public repos
the user contributed to on GitHub in the last N days."""

import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

USER = os.environ.get("GH_USER", "d3flex")
DAYS = 90
TOP = 3
# Commits pushed, PRs opened, reviews given.
EVENT_TYPES = {"PushEvent", "PullRequestEvent", "PullRequestReviewEvent"}
EXCLUDE = {f"{USER}/{USER}"}

README = Path(__file__).resolve().parents[2] / "README.md"
START = "<!-- GH-PROJECTS:START -->"
END = "<!-- GH-PROJECTS:END -->"


def get_json(url):
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as resp:
        return json.load(resp)


def fetch_events():
    events = []
    # The events API returns at most 300 events (3 pages of 100).
    for page in range(1, 4):
        batch = get_json(
            f"https://api.github.com/users/{USER}/events/public?per_page=100&page={page}"
        )
        events.extend(batch)
        if len(batch) < 100:
            break
    return events


@cache
def upstream(repo):
    """Credit work done in forks to the root repo they were forked from."""
    info = get_json(f"https://api.github.com/repos/{repo}")
    return info["source"]["full_name"] if info.get("fork") else repo


def top_repos(events):
    since = datetime.now(UTC) - timedelta(days=DAYS)
    counts = Counter()
    for event in events:
        created = datetime.fromisoformat(event["created_at"])
        if created < since or event["type"] not in EVENT_TYPES:
            continue
        if (
            event["type"] == "PullRequestEvent"
            and event["payload"].get("action") != "opened"
        ):
            continue
        repo = upstream(event["repo"]["name"])
        if repo not in EXCLUDE:
            counts[repo] += 1
    return [repo for repo, _ in counts.most_common(TOP)]


def badge(repo):
    # shields.io static badges need "-" and "_" doubled.
    name = repo.split("/", 1)[1].replace("-", "--").replace("_", "__")
    return (
        f"  [![{repo}](https://img.shields.io/badge/{name}-active-blue?style=for-the-badge)]"
        f"(https://github.com/{repo})"
    )


def main():
    repos = top_repos(fetch_events())
    if not repos:
        print("No recent contributions found; leaving README unchanged.")
        return 0
    block = "\n".join([START, *map(badge, repos), END])
    text = README.read_text()
    pattern = re.compile(re.escape(START) + ".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(text):
        sys.exit(f"Markers {START} / {END} not found in {README}")
    README.write_text(pattern.sub(lambda _: block, text))
    print("Updated with:", ", ".join(repos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
