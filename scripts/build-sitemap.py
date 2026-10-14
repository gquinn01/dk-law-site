#!/usr/bin/env python3
"""
Sitemap builder.

WHY THIS EXISTS. docs/sitemap.xml is the list of pages worth crawling, and
scripts/audit.py fails any page that is missing from it. That check turns a
forgotten <url> block into a build failure rather than a page Google never
finds, which is the right way round, but it still left somebody hand-editing
XML for every page and typing a date each time. Hand-maintained lists
drift, and a date typed by hand is a date that is wrong.

So the file is GENERATED from the pages themselves, the same shape as
scripts/stamp-assets.py: a command that rewrites, and a --check that fails if
what is on disk is stale.

WHAT GOES IN IT, and what does not:

  - Every page under docs/ that a reader should land on.
  - NOT a redirect stub, and NOT the 404 page. Both declare themselves with
    <meta name="dky-page" content="..."> and the audit already scores
    them as a critical if they appear here.
  - NOT a noindexed utility page. One declares itself with
    content="utility". Whether this site has any is pagemap.md's to say;
    the kind stays, because the rule costs nothing and the first utility
    page needs it.

  The site-wide staging noindex is deliberately NOT a reason to leave a page
  out. Every page carries that tag today and none of them will after cutover;
  a sitemap built from it would empty itself for the wrong reason and refill
  itself later without anyone deciding anything.

WHERE lastmod COMES FROM. The page's own WebPage node, its "dateModified".
Not the file's mtime, which changes on every checkout, and not today's date,
which would claim every page changed whenever anyone ran this. A page with no
dateModified is an error, because "when did this last change" is a fact about
the page and the page should carry it.

USAGE:
    python3 scripts/build-sitemap.py            # write docs/sitemap.xml
    python3 scripts/build-sitemap.py --check    # exit 1 if it is stale

No external packages needed, pure Python standard library.
"""

import argparse
import glob
import json
import os
import re
import sys

SITE_DIR = "docs"
SITEMAP_PATH = os.path.join(SITE_DIR, "sitemap.xml")
SITE_BASE = "https://dklawllc.com/"

# Kinds that declare themselves out of the sitemap, and why.
EXCLUDED_KINDS = {
    "redirect-stub": "a stub whose only job is to point at another page",
    "error-404": "the error page",
    "utility": "a noindexed utility page",
}

CANONICAL_RE = re.compile(
    r"""<link[^>]+rel=["']canonical["'][^>]*href=["']([^"']+)["']""", re.I)
KIND_RE = re.compile(
    r"""<meta[^>]+name=["']dky-page["'][^>]*content=["']([^"']+)["']""", re.I)
JSONLD_RE = re.compile(
    r"""<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.I | re.S)


# The page node's type. ContactPage is a schema.org subtype of WebPage, the
# type a contact page carries because that is what the page is, and a blog
# index carries a CollectionPage (house precedent from the founding client
# build). A page that declares another
# subtype adds it here; until then its lastmod is missing and the build
# says so, which is the right way round.
PAGE_NODE_TYPES = ("WebPage", "ContactPage", "CollectionPage")


def date_modified(html: str):
    """The dateModified from the page's WebPage node, or the node of a
    WebPage subtype in PAGE_NODE_TYPES. None if it has none."""
    for block in JSONLD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        nodes = []
        for item in items:
            graph = item.get("@graph") if isinstance(item, dict) else None
            nodes.extend(graph if isinstance(graph, list) else [item])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") in PAGE_NODE_TYPES and node.get("dateModified"):
                return str(node["dateModified"]).strip()[:10]
    return None


def collect():
    """Every page that belongs in the sitemap, with its canonical and date.
    Returns (entries, problems)."""
    entries, problems = [], []
    for path in sorted(glob.glob(os.path.join(SITE_DIR, "**", "*.html"),
                                 recursive=True)):
        with open(path, encoding="utf-8") as f:
            html = f.read()
        kind = (KIND_RE.search(html).group(1).strip().lower()
                if KIND_RE.search(html) else "page")
        if kind in EXCLUDED_KINDS:
            continue
        m = CANONICAL_RE.search(html)
        if not m:
            problems.append(f"{path}: no rel=canonical, so it has no address to list")
            continue
        loc = m.group(1).strip()
        if not loc.startswith(SITE_BASE):
            problems.append(f"{path}: canonical {loc} is not absolute to {SITE_BASE}")
            continue
        date = date_modified(html)
        if not date:
            problems.append(f"{path}: no dateModified in its WebPage node, so lastmod "
                            f"would have to be invented")
            continue
        entries.append((loc, date))
    return entries, problems


def render(entries) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<!-- GENERATED by scripts/build-sitemap.py. Do not hand-edit: run the',
             '     script. Each lastmod is the page\'s own schema dateModified. -->',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, date in entries:
        lines += ["  <url>", f"    <loc>{loc}</loc>",
                  f"    <lastmod>{date}</lastmod>", "  </url>"]
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--check", action="store_true",
                    help="Exit 1 if docs/sitemap.xml is missing or stale.")
    opts = ap.parse_args()

    entries, problems = collect()
    if problems:
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(f"{len(problems)} page(s) cannot be listed. Fix them, then re-run.",
              file=sys.stderr)
        return 1

    # No pages yet, no sitemap yet: the build has not started, and an empty
    # sitemap.xml would be a file claiming to list a site that does not
    # exist. Once a page lands, this writes the file and --check holds it.
    if not entries and not os.path.exists(SITEMAP_PATH):
        print(f"No pages under {SITE_DIR}/ yet, so no {SITEMAP_PATH} to build or check.")
        return 0

    want = render(entries)
    try:
        with open(SITEMAP_PATH, encoding="utf-8") as f:
            have = f.read()
    except OSError:
        have = None

    if opts.check:
        if have == want:
            print(f"{SITEMAP_PATH} is current ({len(entries)} page(s)).")
            return 0
        print(f"{SITEMAP_PATH} is stale. Run: python3 scripts/build-sitemap.py",
              file=sys.stderr)
        return 1

    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(want)
    print(f"Wrote {SITEMAP_PATH} with {len(entries)} page(s)"
          + ("." if have == want else ", changed."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
