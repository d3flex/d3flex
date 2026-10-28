"""Rewrite the CB-PROJECTS and CB-STATS blocks in a Codeberg .profile checkout
and regenerate its contribution calendar SVG.

Usage: update_codeberg.py <path-to-.profile-checkout>
"""

import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

USER = "fleax"
API = "https://codeberg.org/api/v1"
DAYS = 90
TOP = 3
EXCLUDE = {f"{USER}/.profile"}
SVG_NAME = "contributions.svg"
SVG_URL = f"https://codeberg.org/{USER}/.profile/raw/branch/main/{SVG_NAME}"

# Calendar colors: an empty cell that reads on light and dark themes, then 4 levels.
EMPTY = "#8b949e33"
LEVELS = ["#9be9a8", "#40c463", "#30a14e", "#216e39"]
MUTED = "#8b949e"


def get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def fetch_activity(since):
    events = []
    for page in range(1, 21):
        batch = get_json(
            f"{API}/users/{USER}/activities/feeds"
            f"?only-performed-by=true&limit=50&page={page}"
        )
        events.extend(e for e in batch if datetime.fromisoformat(e["created"]) >= since)
        if len(batch) < 50 or datetime.fromisoformat(batch[-1]["created"]) < since:
            break
    return [e for e in events if e["repo"]["full_name"] not in EXCLUDE]


def commit_count(event):
    content = json.loads(event["content"] or "{}")
    # Commits is capped to the last few; Len holds the real push size.
    return content.get("Len") or len(content.get("Commits") or [])


def summarize(events, static):
    repos, stats = Counter(), Counter()
    for e in events:
        repos[e["repo"]["full_name"]] += 1
        match e["op_type"]:
            case "commit_repo":
                stats["commits"] += commit_count(e)
            case "create_pull_request":
                stats["PRs"] += 1
            case "publish_release":
                stats["releases"] += 1
    stats["repos"] = len(repos)
    top = [repo for repo, _ in repos.most_common() if repo not in static][:TOP]
    return top, stats


def shield(text):
    return text.replace("-", "--").replace("_", "__").replace(" ", "%20")


def project_badge(repo):
    name = shield(repo.split("/", 1)[1])
    return (
        f"  [![{repo}](https://img.shields.io/badge/{name}-active-green?style=for-the-badge)]"
        f"(https://codeberg.org/{repo})"
    )


def stats_badges(stats):
    labels = [
        ("commits", "commits"),
        ("PRs", "PRs"),
        ("releases", "releases"),
        ("repos", "active repos"),
    ]
    return "  " + "\n  ".join(
        f"![{label}](https://img.shields.io/badge/{shield(label)}-{stats[key]}-2185d0?style=flat-square)"
        for key, label in labels
    )


def calendar_svg(today):
    per_day = Counter()
    for bucket in get_json(f"{API}/users/{USER}/heatmap"):
        day = datetime.fromtimestamp(bucket["timestamp"], UTC).date()
        per_day[day] += bucket["contributions"]

    # 53 week columns ending this week; rows run Sunday to Saturday.
    start = today - timedelta(days=(today.weekday() + 1) % 7 + 52 * 7)
    peak = max(per_day.values(), default=0)
    cell, gap, top = 10, 3, 16
    parts = []
    for i in range((today - start).days + 1):
        day = start + timedelta(days=i)
        week, row = divmod(i, 7)
        n = per_day.get(day, 0)
        color = EMPTY if not n else LEVELS[min(3, (4 * n - 1) // peak)]
        x, y = week * (cell + gap), top + row * (cell + gap)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}">'
            f"<title>{day}: {n}</title></rect>"
        )
        if day.day == 1:
            parts.append(f'<text x="{x}" y="10" fill="{MUTED}">{day:%b}</text>')

    width = 53 * (cell + gap)
    height = top + 7 * (cell + gap)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="9">\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )


def replace_block(text, name, body):
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    pattern = re.compile(re.escape(start) + ".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        sys.exit(f"Markers {start} / {end} not found")
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", text)


def main(profile):
    now = datetime.now(UTC)
    readme = profile / "README.md"
    text = readme.read_text()
    # Repos already linked outside the block are pinned by hand; don't repeat them.
    outside = re.sub(
        r"<!-- CB-PROJECTS:START -->.*?<!-- CB-PROJECTS:END -->",
        "",
        text,
        flags=re.DOTALL,
    )
    static = set(re.findall(rf"codeberg\.org/({USER}/[\w.-]+)", outside))
    repos, stats = summarize(fetch_activity(now - timedelta(days=DAYS)), static)

    if repos:
        text = replace_block(text, "CB-PROJECTS", "\n".join(map(project_badge, repos)))
    stats_body = (
        f"  **Last {DAYS} days on Codeberg**\n\n{stats_badges(stats)}\n\n"
        f"  ![Codeberg contributions]({SVG_URL})"
    )
    text = replace_block(text, "CB-STATS", stats_body)
    readme.write_text(text)
    (profile / SVG_NAME).write_text(calendar_svg(now.date()))
    print("Projects:", ", ".join(repos) or "none", "| Stats:", dict(stats))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
