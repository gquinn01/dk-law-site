#!/usr/bin/env python3
"""
SEO News Fetcher: the "eyes" of your Google Watch Agent.

Nobody can literally "scan Google's algorithm" (it's secret). What the
pros actually do: monitor the places where algorithm changes are
announced or first detected, then react fast. This script pulls the
latest headlines from those sources into one file. The AI agent then
reads that file, decides what actually matters for YOUR sites, and
reports through a GitHub Issue.

Usage:
    python3 scripts/fetch_seo_news.py

Output: seo-news.md (headlines from the last 10 days)
Pure Python standard library, no packages to install.
"""

import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

# Where algorithm changes are announced or first spotted.
FEEDS = [
    # Google's own announcements (official)
    ("Google Search Central Blog", "https://developers.google.com/search/blog/rss.xml"),
    # Google's live status dashboard for ranking system updates (official)
    ("Google Search Status", "https://status.search.google.com/en/feed.atom"),
    # The industry's fastest watchdog for suspected/confirmed updates
    ("Search Engine Roundtable", "https://www.seroundtable.com/index.rdf"),
    # Broad industry coverage
    ("Search Engine Land", "https://searchengineland.com/feed"),
]

CUTOFF_DAYS = 10


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SEO-News-Agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def parse_feed(raw: bytes):
    """Handle RSS 2.0, RSS 1.0 (RDF), and Atom with one forgiving parser."""
    items = []
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return items

    def text(el, *names):
        for name in names:
            for child in el.iter():
                tag = child.tag.split("}")[-1]
                if tag == name and (child.text or "").strip():
                    return child.text.strip()
        return ""

    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("item", "entry"):
            title = text(el, "title")
            link = text(el, "link") or ""
            if not link:  # Atom links live in an attribute
                for child in el.iter():
                    if child.tag.split("}")[-1] == "link" and child.get("href"):
                        link = child.get("href")
                        break
            date_raw = text(el, "pubDate", "date", "updated", "published")
            items.append({"title": title, "link": link, "date": date_raw})
    return items


def recent(date_raw: str) -> bool:
    """Keep items from the last CUTOFF_DAYS. If we can't parse the date, keep it."""
    if not date_raw:
        return True
    fmts = ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"]
    cleaned = re.sub(r"(\.\d+)?Z$", "+0000", date_raw.strip())
    for fmt in fmts:
        try:
            dt = datetime.strptime(cleaned[:31], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
        except ValueError:
            continue
    return True


def main():
    lines = ["# SEO News Sweep", "",
             f"Headlines from the last {CUTOFF_DAYS} days, gathered for the Google Watch Agent.", ""]
    total = 0
    for name, url in FEEDS:
        lines.append(f"## {name}")
        lines.append("")
        try:
            items = [i for i in parse_feed(fetch(url)) if i["title"] and recent(i["date"])]
            if not items:
                lines.append("_No recent items._")
            for item in items[:15]:
                date = f" ({item['date'][:16]})" if item["date"] else ""
                lines.append(f"- [{item['title']}]({item['link']}){date}")
                total += 1
        except Exception as e:  # a dead feed should never kill the run
            lines.append(f"_Could not fetch this source ({type(e).__name__}). The agent should note this and move on._")
        lines.append("")

    out = "\n".join(lines)
    with open("seo-news.md", "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    print(f"\n({total} headlines saved to seo-news.md)", file=sys.stderr)


if __name__ == "__main__":
    main()
