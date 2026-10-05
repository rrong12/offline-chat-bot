"""Build bot/content/higherlower.json: each term's English Wikipedia page views for the last full month.

Run from the repo root: .venv/bin/python scripts/fetch_pageviews.py
Terms come from scripts/higherlower_terms.txt (display name|article title|category). Titles are
resolved through redirects first, since page views are counted per exact title. Re-run it any
time to refresh the numbers.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bot  # noqa: E402, F401  (points Python at certifi's certificates when the system has none)

TERMS = ROOT / "scripts" / "higherlower_terms.txt"
OUT = ROOT / "bot" / "content" / "higherlower.json"
USER_AGENT = "offline-chat-bot/0.1 (https://github.com/rrong12/offline-chat-bot)"
ACTION_API = "https://en.wikipedia.org/w/api.php"
VIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
REVIEW_BELOW = 3000  # monthly views this low usually mean the wrong article
MIN_TERMS = 100


def get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 5:
                raise
            retry_after = exc.headers.get("Retry-After") or ""
            wait = int(retry_after) if retry_after.isdigit() else 5 * 2**attempt  # rate limited: back off
            time.sleep(min(wait, 120))
        except (urllib.error.URLError, TimeoutError):  # dropped connection: try again
            if attempt == 5:
                raise
            time.sleep(5 * 2**attempt)
    raise AssertionError("unreachable")


def last_full_month(today: date) -> tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def resolve(titles: list[str]) -> dict[str, str | None]:
    """Title -> canonical title after normalization and redirects, or None if the page doesn't exist."""
    result: dict[str, str | None] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "redirects": 1, "titles": "|".join(batch),
            "prop": "pageprops", "ppprop": "disambiguation",  # a disambiguation page is the wrong article
        })
        data = get(f"{ACTION_API}?{query}")["query"]
        step = {n["from"]: n["to"] for n in data.get("normalized", [])}
        step.update({r["from"]: r["to"] for r in data.get("redirects", [])})
        missing = {
            p["title"] for p in data["pages"].values()
            if "missing" in p or "invalid" in p or "disambiguation" in p.get("pageprops", {})
        }
        for title in batch:
            current = title
            for _ in range(3):  # normalized, then redirected
                current = step.get(current, current)
            result[title] = None if current in missing else current
        time.sleep(0.5)
    return result


def monthly_views(title: str, start: date, end: date) -> int:
    article = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"{VIEWS_API}/{article}/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00"
    return sum(item["views"] for item in get(url)["items"])


def main() -> None:
    rows = []
    for line in TERMS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, title, category = (part.strip() for part in line.split("|"))
            rows.append((name, title, category))
    start, end = last_full_month(date.today())
    canonical = resolve([title for _, title, _ in rows])
    terms, problems = [], []
    for name, title, category in rows:
        real = canonical.get(title)
        if real is None:
            problems.append(f"missing or disambiguation page: {title}")
            continue
        try:
            views = monthly_views(real, start, end)
        except urllib.error.HTTPError as exc:
            problems.append(f"no views ({exc.code}): {real}")
            continue
        terms.append({"name": name, "article": real, "category": category, "views": views})
        if real != title or views < REVIEW_BELOW:
            problems.append(f"check by hand: {name} -> {real} ({views} views)")
        time.sleep(1.0)  # stay well under Wikimedia's rate limit
    for problem in problems:
        print("  " + problem)
    if len(terms) < MIN_TERMS:  # don't overwrite good data with a failed run
        sys.exit(f"only {len(terms)} terms found; {OUT} left unchanged")
    payload = {
        "source": "English Wikipedia page views (Wikimedia REST API), user agents only",
        "month": f"{start:%Y-%m}",
        "terms": terms,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {len(terms)} terms for {start:%Y-%m} to {OUT}")


if __name__ == "__main__":
    main()
