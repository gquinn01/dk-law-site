#!/usr/bin/env python3
"""
Asset cache-busting stamper.

WHY THIS EXISTS. GitHub Pages serves docs/assets/site.css and
docs/assets/site.js with `cache-control: max-age=600`. A browser
therefore holds either file for up to ten minutes WITHOUT revalidating.
Edit the stylesheet, push, reload, and for those ten minutes you are
looking at the old one. Twice during the build that looked exactly like
a CSS bug and got chased as one.

The fix is a version stamp in the URL:

    assets/site.css?v=1a2b3c4d

Change the file and the stamp changes, so the URL changes, so the cache
misses and the browser fetches the new bytes. Leave the file alone and
the stamp is stable, so nothing is invalidated for no reason and no diff
noise lands in commits that never touched CSS.

The stamp is the first 8 hex characters of the file's SHA-256. A date
would not do: two edits on one day produce the same date, and the second
one would serve stale.

USAGE. After changing site.css or site.js, run this in the same commit:

    python3 scripts/stamp-assets.py            # rewrite the stamps
    python3 scripts/stamp-assets.py --check    # exit 1 if any are stale

It is idempotent: running it twice in a row changes nothing the second
time. It rewrites every reference under docs/ AND in templates/, so the
master mold never falls behind the site.

FORGETTING IS NOT POSSIBLE. scripts/audit.py records a stale or missing
stamp as a CRITICAL against that page, which drops it under 100/100 and
fails `--strict`. That is the same trick that keeps sitemap.xml and
llms.txt from drifting: the checklist is not a thing to remember, it is
a thing the build fails without.

No external packages needed, pure Python standard library.
"""

import argparse
import glob
import hashlib
import os
import re
import sys

SITE_DIR = "docs"
TEMPLATE_DIR = "templates"

# The files that get stamped, named by their path relative to docs/.
ASSETS = ("assets/site.css", "assets/site.js")

STAMP_LEN = 8


def stamp_for(rel_asset: str) -> str:
    """First 8 hex of the asset's SHA-256. The stamp IS the content."""
    with open(os.path.join(SITE_DIR, rel_asset), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:STAMP_LEN]


def asset_pattern(rel_asset: str) -> re.Pattern:
    """Matches the asset in href/src at ANY depth, stamped or not.

    The leading path is whatever the page uses to reach the site root:
    "", "../", "../../", "../../../", or the template's {{ROOT}} token,
    or the single leading slash docs/404.html is allowed. Captured so it
    is written back untouched, because the depth is the page's business
    and not this script's.
    """
    name = re.escape(rel_asset)
    return re.compile(
        r'((?:href|src)=")'                 # 1: the attribute opener
        r'((?:\{\{ROOT\}\}|/|(?:\.\./)*))'  # 2: the path to the site root
        + name +                            #    assets/site.css|js
        r'(?:\?v=[0-9a-f]+)?'               #    an existing stamp, if any
        r'(")'                              # 3: the closing quote
    )


def targets() -> list:
    return (sorted(glob.glob(os.path.join(SITE_DIR, "**", "*.html"), recursive=True))
            + sorted(glob.glob(os.path.join(TEMPLATE_DIR, "*.html"))))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Stamp site.css and site.js with a content hash, so a cached copy "
                    "can never be served in place of a changed one.")
    ap.add_argument("--check", action="store_true",
                    help="Report stale stamps and exit 1 without writing anything.")
    opts = ap.parse_args()

    # Before the design system exists there is nothing to stamp. Say so and
    # stop, rather than crash: the build has not started, which is not an
    # error. The day one file exists, both must, because every page links
    # both.
    present = [a for a in ASSETS if os.path.isfile(os.path.join(SITE_DIR, a))]
    if not present:
        print(f"Nothing to stamp: no {' or '.join(ASSETS)} under {SITE_DIR}/ yet.")
        return 0
    if len(present) != len(ASSETS):
        missing = [a for a in ASSETS if a not in present]
        print(f"FAILED: {', '.join(missing)} missing under {SITE_DIR}/ while "
              f"{', '.join(present)} exists. Both are linked from every page.", file=sys.stderr)
        return 1
    stamps = {a: stamp_for(a) for a in ASSETS}
    for a, s in stamps.items():
        print(f"{a}  ->  ?v={s}")

    patterns = {a: asset_pattern(a) for a in ASSETS}
    changed, stale = [], []

    for path in targets():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        out = src
        for a, rx in patterns.items():
            out = rx.sub(lambda m, a=a: f'{m.group(1)}{m.group(2)}{a}?v={stamps[a]}{m.group(3)}', out)
        if out == src:
            continue
        stale.append(path)
        if not opts.check:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
            changed.append(path)

    if opts.check:
        if stale:
            print(f"\n{len(stale)} file(s) carry a stale or missing stamp:", file=sys.stderr)
            for p in stale:
                print(f"  {p}", file=sys.stderr)
            print("\nRun: python3 scripts/stamp-assets.py", file=sys.stderr)
            return 1
        print(f"\nAll stamps current across {len(targets())} file(s).")
        return 0

    if changed:
        print(f"\nRestamped {len(changed)} file(s):")
        for p in changed:
            print(f"  {p}")
    else:
        print(f"\nNothing to do: all stamps already current across {len(targets())} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
