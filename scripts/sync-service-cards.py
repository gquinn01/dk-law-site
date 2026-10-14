#!/usr/bin/env python3
"""
Writes every service card's words from audit.SERVICES, and the Related
Services section on each service page.

ONE RENDERING PER SERVICE. audit.SERVICES is the one table of the family:
(path, label, line). The label and the line on a service card are the
same everywhere a card appears (house precedent from the founding client
build). This writes them into every svc-card under docs/ that links a
service page, touching only the card's h3 and p. Each page's card order
stays its own.

A PHOTOGRAPHED CARD PREVIEWS ITS PAGE. Where a card carries an <img>, the
image is written from the image its target page presents as its own
preview, its og:image, by audit.preview_of(): the same file, width, height
and alt, verbatim. Change a page's preview and the card follows on the
next run; the audit fails a card that has not.

RELATED SERVICES. Each service page carries the family MINUS ITSELF AND
MINUS audit.RELATED_LEAVES_OUT, in the family's order, after the FAQ, in
the card style without photographs. "Related Services" is a chrome-style
label, furniture rather than a claim. The section sits between the
RELATED markers and is rewritten whole. Its ground is the design
system's to decide; the section carries no ground class until then.

EMPTY TABLE, NOTHING WRITTEN. audit.SERVICES is empty until pagemap.md
exists with the partner's written approval, and while it is empty this
writes nothing.

The audit fails a card whose words are not its row's, a service page's grid
that lacks a sibling, and one that carries the page itself.

    python3 scripts/sync-service-cards.py           # write every page
    python3 scripts/sync-service-cards.py --check   # exit 1 if any page is out of date
"""
import glob
import html
import os
import posixpath
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
ROW = {p: (lbl, ln) for p, lbl, ln in audit.SERVICES}

CARD_RE = re.compile(r'(?s)(<(a|div) class="svc-card" (?:href|data-pending-href)="([^"]+)">)(.*?)(</\2>)')
RELATED_RE = re.compile(r"(?s)    <!-- RELATED:START.*?<!-- RELATED:END -->\n")


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def page_of(path: str) -> str:
    rel = os.path.relpath(os.path.dirname(path), DOCS)
    return "" if rel == "." else rel.replace(os.sep, "/") + "/"


def target_of(page: str, href: str) -> str:
    if href == "./":
        return page
    return posixpath.normpath(posixpath.join("/" + page, href)).strip("/") + "/"


def card_words(text: str, page: str) -> str:
    def fix(m):
        t = target_of(page, m.group(3))
        if t not in ROW:
            return m.group(0)
        lbl, ln = ROW[t]
        body = re.sub(r"(?s)<h3>.*?</h3>", lambda _m: f"<h3>{esc(lbl)}</h3>", m.group(4), count=1)
        body = re.sub(r"(?s)<p>.*?</p>", lambda _m: f"<p>{esc(ln)}</p>", body, count=1)
        hero = audit.preview_of(t) if "<img" in body else None
        if hero:
            src = posixpath.relpath("/" + hero["src"], "/" + page) if page else hero["src"]
            tag = (f'<img src="{src}" alt="{hero["alt"]}" width="{hero["width"]}" '
                   f'height="{hero["height"]}" loading="lazy" decoding="async">')
            body = re.sub(r"<img\b[^>]*>", lambda _m: tag, body, count=1)
        return m.group(1) + body + m.group(5)
    main = re.search(r"(?s)<main\b.*?</main>", text)
    if not main:
        return text
    return text[:main.start()] + CARD_RE.sub(fix, main.group(0)) + text[main.end():]


def related(page: str) -> str:
    cards = "\n".join(
        f'          <a class="svc-card" href="../{p}">\n'
        f'            <div class="svc-card-body">\n'
        f'              <h3>{esc(lbl)}</h3>\n'
        f'              <p>{esc(ln)}</p>\n'
        f'            </div>\n'
        f'          </a>' for p, lbl, ln in audit.SERVICES
        if p != page and p not in audit.RELATED_LEAVES_OUT)
    return f'''    <!-- RELATED:START, written by scripts/sync-service-cards.py.
         The family in audit.SERVICES minus this page and minus
         audit.RELATED_LEAVES_OUT, in the family's order.
         Edit the table, never this block. -->
    <section id="related">
      <div class="wrap">
        <div class="sec-head">
          <h2 class="sec-title">Related Services</h2>
        </div>
        <div class="grid2">
{cards}
        </div>
      </div>
    </section>
    <!-- RELATED:END -->
'''


def synced(path: str, text: str) -> str:
    page = page_of(path)
    text = card_words(text, page)
    if page in ROW:
        block = related(page)
        n = len(RELATED_RE.findall(text))
        if n > 1:
            raise SystemExit(f"FAILED: {os.path.relpath(path, ROOT)} carries {n} Related Services blocks. Nothing written.")
        if n == 1:
            text = RELATED_RE.sub(lambda m: block, text)
        else:
            if text.count("  </main>") != 1:
                raise SystemExit(f"FAILED: {os.path.relpath(path, ROOT)} has no single </main> to place the section before.")
            text = text.replace("  </main>", block + "  </main>")
    return text


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for path in sorted(glob.glob(os.path.join(DOCS, "**", "index.html"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if re.search(r'http-equiv=["\']refresh', text, re.I):
            continue
        new = synced(path, text)
        if new != text:
            stale.append(os.path.relpath(path, ROOT))
            if not check:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
    if check:
        if stale:
            print(f"{len(stale)} page(s) carry service cards that are not the table's:")
            for p in stale:
                print(f"  {p}")
            print("Run scripts/sync-service-cards.py.")
            return 1
        print("Every service card carries the table's words, and every service page its Related Services.")
        return 0
    print(f"wrote {len(stale)} page(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
