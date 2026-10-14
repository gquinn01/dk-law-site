#!/usr/bin/env python3
"""
Tests for the sitemap expansion in audit.py.

WHY THIS FILE EXISTS. A live run gets its page list from the site's own
sitemap, and that file is written by somebody else's CMS. The first
prospect scan, against a WordPress site with a Yoast sitemap index,
came back reporting three "pages": category-sitemap.xml,
page-sitemap.xml and post-sitemap.xml. A <urlset> lists pages and a
<sitemapindex> lists other sitemaps, both using the same <loc> tag, so
reading one as the other silently turns a scan of a client's site into
a scan of three XML files.

That bug is invisible in a well-behaved site's numbers. A plain urlset
scores the same either way, so nothing in a local audit would ever have
caught it. Only a strange sitemap shows it, and we cannot count on a
client to have one handy. It matters twice over here: the firm's live
site at dklawllc.com IS WordPress, so until cutover every weekly run
is pointed at exactly the sitemap shape that caused the bug. So the
strange sitemaps live here, fabricated.

No network and no external packages: audit.load is swapped for a
dictionary lookup, so this runs offline in a second and cannot be
broken by a third party changing their site.

Usage:
    python3 scripts/test-sitemap-expansion.py     # exits 1 if anything fails
"""

import os
import sys

# Import audit.py as a module from the folder this file sits in, so the
# test runs from any working directory, not just the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit  # noqa: E402


# --- The fabricated sitemaps ------------------------------------------
# Each key is a URL the code under test may try to fetch. A URL that is
# NOT a key here raises, which is how the dead-sitemap and no-sitemap
# cases below get their failure.
FAKE = {
    # A plain urlset. This is the shape a hand-built site ships, and the
    # case that has to stay bit for bit unchanged.
    "https://plain.test/sitemap.xml": """<?xml version="1.0"?>
      <urlset><url><loc>https://plain.test/</loc></url>
      <url><loc>https://plain.test/about/</loc></url></urlset>""",

    # The Yoast index that started all this, with one child that 404s.
    "https://wp.test/sitemap.xml": """<?xml version="1.0"?>
      <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://wp.test/page-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://wp.test/post-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://wp.test/dead-sitemap.xml</loc></sitemap>
      </sitemapindex>""",
    "https://wp.test/page-sitemap.xml": """<urlset>
        <url><loc>https://wp.test/</loc></url>
        <url><loc>https://wp.test/services/</loc></url></urlset>""",
    "https://wp.test/post-sitemap.xml": """<urlset>
        <url><loc>https://wp.test/blog/hello/</loc></url></urlset>""",

    # An index inside an index. Rare, but legal, and a one-level
    # expansion would return level3.xml as a page.
    "https://nest.test/sitemap.xml": """<sitemapindex>
        <sitemap><loc>https://nest.test/level2.xml</loc></sitemap></sitemapindex>""",
    "https://nest.test/level2.xml": """<sitemapindex>
        <sitemap><loc>https://nest.test/level3.xml</loc></sitemap></sitemapindex>""",
    "https://nest.test/level3.xml": """<urlset>
        <url><loc>https://nest.test/deep/</loc></url></urlset>""",

    # An index that lists itself. Without the seen set this recurses
    # until the file cap stops it, wasting 50 fetches on one file.
    "https://loop.test/sitemap.xml": """<sitemapindex>
        <sitemap><loc>https://loop.test/sitemap.xml</loc></sitemap>
        <sitemap><loc>https://loop.test/real.xml</loc></sitemap></sitemapindex>""",
    "https://loop.test/real.xml": """<urlset>
        <url><loc>https://loop.test/page/</loc></url></urlset>""",

    # A urlset that lies: it wraps a sitemap in <url> tags, so the
    # wrapper tag says page and the URL says sitemap. This is what the
    # .xml rule catches on its own, with no help from the wrapper.
    "https://liar.test/sitemap.xml": """<urlset>
        <url><loc>https://liar.test/post-sitemap.xml</loc></url>
        <url><loc>https://liar.test/real-page/</loc></url></urlset>""",

    # The firm's live site: a Yoast index with the archive children the
    # weekly scan counts but does not score. Only page- and post-sitemap
    # hold real pages. See LIVE_SITEMAP_SCOPE in audit.py.
    "https://live.test/sitemap.xml": """<sitemapindex>
        <sitemap><loc>https://live.test/post-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://live.test/page-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://live.test/attachment-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://live.test/category-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://live.test/post_tag-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://live.test/author-sitemap.xml</loc></sitemap>
      </sitemapindex>""",
    "https://live.test/post-sitemap.xml": """<urlset>
        <url><loc>https://live.test/blog/one/</loc></url>
        <url><loc>https://live.test/blog/two/</loc></url></urlset>""",
    "https://live.test/page-sitemap.xml": """<urlset>
        <url><loc>https://live.test/</loc></url></urlset>""",
    "https://live.test/attachment-sitemap.xml": """<urlset>
        <url><loc>https://live.test/photo-1/</loc></url>
        <url><loc>https://live.test/photo-2/</loc></url>
        <url><loc>https://live.test/photo-3/</loc></url></urlset>""",
    "https://live.test/category-sitemap.xml": """<urlset>
        <url><loc>https://live.test/category/news/</loc></url></urlset>""",
    "https://live.test/post_tag-sitemap.xml": "<urlset>" + "".join(
        f"<url><loc>https://live.test/tag/t{i}/</loc></url>" for i in range(7)) + "</urlset>",
    "https://live.test/author-sitemap.xml": """<urlset>
        <url><loc>https://live.test/author/a/</loc></url></urlset>""",

    # A sitemap with nothing in it.
    "https://empty.test/sitemap.xml": "<urlset></urlset>",
}

# The same live index answered at the www host, as a WordPress site may.
FAKE["https://www.live.test/sitemap.xml"] = FAKE["https://live.test/sitemap.xml"]

# An index chain longer than the depth cap allows.
FAKE["https://deep.test/sitemap.xml"] = (
    "<sitemapindex><sitemap><loc>https://deep.test/i1.xml</loc></sitemap></sitemapindex>")
for _i in range(1, 12):
    FAKE[f"https://deep.test/i{_i}.xml"] = (
        f"<sitemapindex><sitemap><loc>https://deep.test/i{_i + 1}.xml</loc>"
        "</sitemap></sitemapindex>")
FAKE["https://deep.test/i12.xml"] = (
    "<urlset><url><loc>https://deep.test/buried/</loc></url></urlset>")

# An index with more children than the file cap allows.
FAKE["https://wide.test/sitemap.xml"] = "<sitemapindex>" + "".join(
    f"<sitemap><loc>https://wide.test/c{i}.xml</loc></sitemap>" for i in range(200)
) + "</sitemapindex>"
for _i in range(200):
    FAKE[f"https://wide.test/c{_i}.xml"] = (
        f"<urlset><url><loc>https://wide.test/p{_i}/</loc></url></urlset>")


FETCHED = []
FAILURES = []


def fake_load(source: str) -> str:
    """Stands in for audit.load. Records every fetch, so a test can
    assert on how many files a run read, and raises for a URL that is
    not in FAKE, which is what a 404 or a dead host looks like."""
    FETCHED.append(source)
    if source not in FAKE:
        raise OSError(f"fabricated 404 for {source}")
    return FAKE[source]


def check(label: str, passed: bool, detail=""):
    """Records a result instead of raising, so one broken case cannot
    hide the nine after it. A first-run failure should show the whole
    picture, not the first line of it."""
    print(f"  {'ok  ' if passed else 'FAIL'}  {label}")
    if not passed:
        FAILURES.append(f"{label}{f'  ->  {detail}' if detail != '' else ''}")


def expand(url: str):
    """Runs the code under test and applies the rule that holds in every
    case: whatever the sitemap said, a page list never contains XML."""
    FETCHED.clear()
    targets, note = audit.expand_sitemap(url)
    leaked = [t for t in targets if audit.is_xml_url(t)]
    check(f"{url}: no .xml scored as a page", not leaked, leaked)
    return targets, note


def main():
    audit.load = fake_load

    print("1. A plain urlset, the shape our own site ships")
    targets, note = expand("https://plain.test/")
    check("   pages come back in sorted order",
          targets == ["https://plain.test/", "https://plain.test/about/"], targets)
    check("   no note, so the report reads exactly as it did before",
          note is None, note)

    print("2. A Yoast sitemap index, one child of it dead")
    targets, note = expand("https://wp.test/")
    check("   the children's pages are audited, not the children",
          targets == ["https://wp.test/", "https://wp.test/blog/hello/",
                      "https://wp.test/services/"], targets)
    check("   the report says an index was followed", "sitemap index" in (note or ""), note)
    check("   the report names the child it could not read",
          "dead-sitemap.xml" in (note or ""), note)

    print("3. An index nested inside another index")
    targets, note = expand("https://nest.test/")
    check("   recursion reaches the page two levels down",
          targets == ["https://nest.test/deep/"], targets)

    print("4. An index that lists itself")
    targets, note = expand("https://loop.test/")
    check("   the loop does not stop the real child being read",
          targets == ["https://loop.test/page/"], targets)
    check("   the same sitemap is fetched once, not repeatedly",
          len(FETCHED) == 2, FETCHED)

    print("5. A urlset that lists a sitemap as if it were a page")
    targets, note = expand("https://liar.test/")
    check("   the .xml is dropped and the real page kept",
          targets == ["https://liar.test/real-page/"], targets)

    print("6. A sitemap with no entries")
    targets, note = expand("https://empty.test/")
    check("   falls back to the URL we were given",
          targets == ["https://empty.test/"], targets)
    check("   and says why", "lists no pages" in (note or ""), note)

    print("7. No sitemap at all")
    targets, note = expand("https://gone.test/")
    check("   falls back to the URL we were given",
          targets == ["https://gone.test/"], targets)
    check("   and says why", "Could not read" in (note or ""), note)

    print("8. The script pointed straight at a child sitemap")
    targets, note = expand("https://wp.test/page-sitemap.xml")
    check("   audits what THAT file lists, not what /sitemap.xml lists",
          targets == ["https://wp.test/", "https://wp.test/services/"], targets)

    print("9. An index chain deeper than the depth cap")
    targets, note = expand("https://deep.test/")
    check("   the scan stops instead of following it forever",
          len(FETCHED) <= audit.SITEMAP_MAX_DEPTH + 1, len(FETCHED))
    check("   and admits pages may be missing",
          "may be missing" in (note or ""), note)

    print("10. An index with 200 children, past the file cap")
    targets, note = expand("https://wide.test/")
    check("   no more than the cap is fetched",
          len(FETCHED) <= audit.SITEMAP_MAX_FILES, len(FETCHED))
    check("   the pages it did reach are still audited",
          len(targets) == audit.SITEMAP_MAX_FILES - 1, len(targets))
    check("   and it admits pages may be missing",
          "may be missing" in (note or ""), note)

    print("11. The live site: scored on page and post sitemaps, every URL counted")
    real_base = audit.SITE_BASE
    audit.SITE_BASE = "https://live.test/"
    try:
        targets, note = expand("https://live.test/")
        check("   only page- and post-sitemap pages are scored",
              targets == ["https://live.test/", "https://live.test/blog/one/",
                          "https://live.test/blog/two/"], targets)
        check("   the archive sitemaps are still read, so they can be counted",
              "https://live.test/post_tag-sitemap.xml" in FETCHED, FETCHED)
        check("   the note counts every URL the full index lists",
              "hands Google 15 URLs" in (note or ""), note)
        check("   by sitemap",
              all(f"{n} {c}" in (note or "") for n, c in [
                  ("post-sitemap.xml", 2), ("page-sitemap.xml", 1),
                  ("attachment-sitemap.xml", 3), ("category-sitemap.xml", 1),
                  ("post_tag-sitemap.xml", 7), ("author-sitemap.xml", 1)]), note)
        check("   beside the real pages scored and the rest left out",
              "scores the 3 " in (note or "") and "the other 12 " in (note or ""), note)
        targets, note = expand("https://www.live.test/")
        check("   the www form of the live host is scoped the same way",
              len(targets) == 3, targets)
        targets, note = expand("https://live.test/post_tag-sitemap.xml")
        check("   pointed straight at a child, it still audits what that file lists",
              len(targets) == 7, targets)
    finally:
        audit.SITE_BASE = real_base
    targets, note = expand("https://live.test/")
    check("   any other site's index is not scoped: every page is scored",
          len(targets) == 15, len(targets))
    check("   and gets no count note", "hands Google" not in (note or ""), note)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
