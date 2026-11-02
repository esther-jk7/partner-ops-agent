"""Fetch recent news for each company on the watchlist and save a dated snapshot.

The brief is built from the snapshot, not the live feed, so a demo or a rerun uses exactly
the same inputs, and every item keeps its source, date, and link.
"""

import csv
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

WATCHLIST_PATH = "data/watchlist.csv"
SNAPSHOT_DIR = Path("data/intel")
LOOKBACK_DAYS = 14
MAX_ITEMS_PER_COMPANY = 6
FEED_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
HEADERS = {"User-Agent": "Mozilla/5.0 (partner-ops-agent)"}


def load_watchlist(path: str = WATCHLIST_PATH) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def clean_title(title: str, source: str) -> str:
    """Google News adds ' - Source' to each headline; drop it, since the source is stored separately."""
    suffix = f" - {source}"
    return title[: -len(suffix)] if source and title.endswith(suffix) else title


def normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def parse_items(xml_bytes: bytes, company: str, relationship: str, since: datetime) -> list[dict]:
    """Turn a feed into items, skipping anything older than `since` or missing a headline or link."""
    items = []
    for node in ET.fromstring(xml_bytes).findall("./channel/item"):
        source = (node.findtext("source") or "").strip()
        title = clean_title((node.findtext("title") or "").strip(), source)
        link = (node.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime(node.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if not title or not link or published < since:
            continue
        items.append({"company": company, "relationship": relationship, "title": title,
                      "source": source, "published": published.date().isoformat(), "link": link})
    return items


def select(items: list[dict]) -> list[dict]:
    """Newest first, one copy of each headline, capped per company."""
    seen, kept = set(), []
    for item in sorted(items, key=lambda i: i["published"], reverse=True):
        key = normalize(item["title"])
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return kept[:MAX_ITEMS_PER_COMPANY]


def fetch_company(entry: dict, since: datetime) -> list[dict]:
    query = urllib.parse.quote(f"{entry['query']} when:{LOOKBACK_DAYS}d")
    request = urllib.request.Request(FEED_URL.format(query=query), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        return select(parse_items(response.read(), entry["company"], entry["relationship"], since))


def fetch_all(watchlist_path: str = WATCHLIST_PATH) -> Path:
    """Fetch every company; one failed feed is recorded, not fatal."""
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    snapshot = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "lookback_days": LOOKBACK_DAYS, "items": [], "errors": []}
    for entry in load_watchlist(watchlist_path):
        try:
            items = fetch_company(entry, since)
            snapshot["items"] += items
            print(f"{entry['company']:<22} {len(items)} items")
        except Exception as err:  # network errors vary; record and move on
            snapshot["errors"].append({"company": entry["company"], "error": f"{type(err).__name__}: {err}"})
            print(f"{entry['company']:<22} FAILED ({type(err).__name__})")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"snapshot_{date.today().isoformat()}.json"
    path.write_text(json.dumps(snapshot, indent=2))
    print(f"Saved {len(snapshot['items'])} items to {path}")
    return path


if __name__ == "__main__":
    fetch_all()
