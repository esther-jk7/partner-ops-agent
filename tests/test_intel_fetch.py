"""Fetcher tests on a fixed feed, so they need no network."""

from datetime import datetime, timezone

from src.intel_fetch import parse_items, select

FEED = b"""<?xml version="1.0"?><rss><channel>
<item><title>Partner launches AI tool - Reuters</title><link>https://example.com/a</link>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Partner launches AI tool - CNBC</title><link>https://example.com/b</link>
<pubDate>Sun, 01 Nov 2026 10:00:00 GMT</pubDate><source url="https://cnbc.com">CNBC</source></item>
<item><title>Old news - Axios</title><link>https://example.com/c</link>
<pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate><source url="https://axios.com">Axios</source></item>
<item><title></title><link>https://example.com/d</link>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate><source url="https://x.com">X</source></item>
</channel></rss>"""
SINCE = datetime(2026, 10, 19, tzinfo=timezone.utc)


def test_parse_drops_old_and_blank_items_and_cleans_titles():
    items = parse_items(FEED, "Partner", "Partner", SINCE)
    assert len(items) == 2
    assert all(i["title"] == "Partner launches AI tool" for i in items)


def test_select_keeps_newest_copy_of_duplicate_headline():
    kept = select(parse_items(FEED, "Partner", "Partner", SINCE))
    assert len(kept) == 1
    assert kept[0]["source"] == "Reuters"
