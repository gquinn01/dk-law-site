#!/usr/bin/env python3
"""
Writes the site chrome, the header and the footer, into every real page
under docs/, and the staging machinery and favicon links into every page.

WHY A SCRIPT. The chrome repeats in full on every page, and a menu typed
into 36 pages is 36 chances for one of them to drift. Here the chrome is
defined once, this writes it everywhere, and scripts/audit.py fails any page
whose chrome differs from every other page's in anything but the
current-page marking.

THE NAV AND THE FOOTER ARE NOT WRITTEN YET. What they carry is content: the
page list, the labels, the firm's NAP. The page list is pagemap.md's, which
is not written yet and ships nothing until the partner approves it in
writing, and the NAP is OFF until the firm confirms it (FACTS_OFF in
scripts/audit.py). So render() refuses until CHROME_SPECIFIED is True, and
this script will not write a header onto a page from a guess. The house
shape it will follow, carried from the founding client build: the logo is
the way home, so the nav carries no Home item; nav labels are the live
site's own words; the one filled button is the one conversion action; the
footer lists only pages that exist.

WHAT IT TOUCHES. On every page that is not a redirect stub: everything from
the CHROME:HEAD marker to the end of the <header>, and the <footer
class="site"> element. A redirect stub stays bare. docs/404.html carries no
chrome and takes only the staging machinery and the favicon links, written
root-relative (see error_page()).

It also writes three things in every page that follow a switch or a set
rather than the nav, and these work today:

  - the favicon links, audit.ICON_LINKS, as the last lines of the <head>;
  - the noindex tag, audit.STAGING_ROBOTS_META, present while
    audit.STAGING is True and absent once it is False (on stubs too);
  - the visible staging banner, audit.STAGING_BANNER, just before the
    header, on the same switch.

So the cutover flip is: set STAGING to False and run this. On the founding
build the flip as first written left the banner on 37 pages, because
nothing wrote it and nothing removed it.

THE CURRENT PAGE is the one thing allowed to differ between pages: every
chrome link that lands on the page itself is written "./" and carries
aria-current="page".

    python3 scripts/sync-chrome.py           # write every page
    python3 scripts/sync-chrome.py --check   # exit 1 if any page is out of date
"""
import glob
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

# The firm's phone and mailbox, from the NAP in scripts/audit.py. None while
# the NAP is OFF.
PHONE_TEL = audit.CHROME_TEL
PHONE_TEXT = audit.NAP_PHONE_DISPLAY
EMAIL = audit.NAP_EMAIL

# The service family is audit.SERVICES, the one list: the nav, the footer
# and every body enumeration take it from there, and the audit fails any
# enumeration that is not the whole family.
SERVICES = audit.SERVICES

# FALSE until pagemap.md exists with the partner's written approval and the
# chrome's items, labels and NAP are decided. See the docstring.
CHROME_SPECIFIED = False


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def render(page: str) -> tuple:
    """(head, foot) for the page at docs/<page>, where page is "" for home
    and "slug/" for every other page. Refuses until CHROME_SPECIFIED."""
    if not CHROME_SPECIFIED:
        raise SystemExit("FAILED: the site chrome is not specified yet. The nav and footer are "
                         "content: they come from pagemap.md, approved in writing by the named "
                         "partner, and from the firm's confirmed NAP. Nothing written.")
    raise SystemExit("FAILED: CHROME_SPECIFIED is True but render() has not been written. "
                     "Write it from pagemap.md before turning the switch on.")


HEAD_RE = re.compile(r"(?s)(?:<!-- CHROME:HEAD.*?-->\s*)?<header class=\"nav\">.*?</header>")
FOOT_RE = re.compile(r'(?s)<footer class="site">.*?</footer>')


def page_of(path: str) -> str:
    rel = os.path.relpath(os.path.dirname(path), DOCS)
    return "" if rel == "." else rel.replace(os.sep, "/") + "/"


def is_stub(text: str) -> bool:
    return re.search(r'http-equiv=["\']refresh', text, re.I) is not None


ICONS_RE = re.compile(r"(?s)\n  <!-- ICONS, written by scripts/sync-chrome\.py.*?-->\n"
                      r"(?:  <link rel=\"(?:icon|apple-touch-icon)\"[^>]*>\n)*")
ROBOTS_LINE = "\n  " + audit.STAGING_ROBOTS_META
VIEWPORT_RE = re.compile(r"\n  <meta name=\"viewport\"[^>]*>")
BANNER_BLOCK = "  " + audit.STAGING_BANNER + "\n\n"


def icons(page: str) -> str:
    p = "../" * page.count("/")
    lines = "".join(f'  <link rel="{rel}"' + (f" {attrs}" if attrs else "") + f' href="{p}{path}">\n'
                    for rel, attrs, path in audit.ICON_LINKS)
    return ("\n  <!-- ICONS, written by scripts/sync-chrome.py from audit.ICON_LINKS: the\n"
            "       firm's own site icon, made by scripts/prepare-favicon.py. -->\n" + lines)


def staged(path: str, text: str) -> str:
    """The noindex tag on the STAGING switch: present while staging,
    absent after. Stubs as well as pages."""
    has = ROBOTS_LINE in text
    if audit.STAGING and not has:
        m = VIEWPORT_RE.search(text)
        if not m:
            raise SystemExit(f"FAILED: {os.path.relpath(path, ROOT)} has no viewport line to "
                             f"put the noindex tag after. Nothing written.")
        text = text[:m.end()] + ROBOTS_LINE + text[m.end():]
    elif not audit.STAGING and has:
        text = text.replace(ROBOTS_LINE, "", 1)
    return text


def synced(path: str, text: str) -> str:
    page = page_of(path)
    head, foot = render(page)
    if len(HEAD_RE.findall(text)) != 1 or len(FOOT_RE.findall(text)) != 1:
        raise SystemExit(f"FAILED: {os.path.relpath(path, ROOT)} does not carry exactly one header "
                         f"and one footer to replace. Nothing written.")
    text = HEAD_RE.sub(lambda m: head, text)
    text = FOOT_RE.sub(lambda m: foot, text)
    text = staged(path, text)
    # The banner sits on its own just before the chrome's header comment.
    has = BANNER_BLOCK in text
    if audit.STAGING and not has:
        i = text.index("  <!-- CHROME:HEAD")
        text = text[:i] + BANNER_BLOCK + text[i:]
    elif not audit.STAGING and has:
        text = text.replace(BANNER_BLOCK, "", 1)
    # The favicon links, the last lines of the head.
    text = ICONS_RE.sub("\n", text, count=1) if ICONS_RE.search(text) else text
    i = text.index("</head>")
    before = text[:i].rstrip("\n") + "\n"
    return before + icons(page).lstrip("\n") + text[i:]


ERROR_PAGE = os.path.join(DOCS, "404.html")


def error_page(path: str, text: str) -> str:
    """docs/404.html. It carries no chrome, because it is served at the
    missing URL at any depth and the chrome's links are relative. It takes
    the rest of the staging machinery from the same switch as every page:
    the noindex tag, the banner (just inside <body>, where there is no
    header to sit above) and the favicon links, ROOT-RELATIVE for the same
    reason its other links are."""
    text = staged(path, text)
    # Read the banner itself, not the block with its trailing blank line:
    # the banner goes in here with ONE newline after it, so testing for the
    # block found nothing on a second run and wrote the banner twice (found
    # while building this repo's harness; the founding repo's 404 happened
    # to carry a blank line after <body> and never showed it).
    has = audit.STAGING_BANNER in text
    if audit.STAGING and not has:
        i = text.index("<body>\n") + len("<body>\n")
        text = text[:i] + "\n" + BANNER_BLOCK.rstrip("\n") + "\n" + text[i:]
    elif not audit.STAGING and has:
        text = text.replace("\n" + BANNER_BLOCK.rstrip("\n") + "\n", "", 1)
    text = ICONS_RE.sub("\n", text, count=1) if ICONS_RE.search(text) else text
    i = text.index("</head>")
    lines = "".join(f'  <link rel="{rel}"' + (f" {attrs}" if attrs else "") + f' href="/{fp}">\n'
                    for rel, attrs, fp in audit.ICON_LINKS)
    block = ("  <!-- ICONS, written by scripts/sync-chrome.py from audit.ICON_LINKS: the\n"
             "       firm's own site icon, made by scripts/prepare-favicon.py. -->\n" + lines)
    return text[:i].rstrip("\n") + "\n" + block + text[i:]


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    paths = sorted(glob.glob(os.path.join(DOCS, "**", "index.html"), recursive=True))
    if os.path.isfile(ERROR_PAGE):
        paths.append(ERROR_PAGE)
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if path == ERROR_PAGE:
            new = error_page(path, text)
        else:
            new = staged(path, text) if is_stub(text) else synced(path, text)
        if new != text:
            stale.append(os.path.relpath(path, ROOT))
            if not check:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
    if check:
        if stale:
            print(f"{len(stale)} page(s) carry chrome that is not the generator's:")
            for p in stale:
                print(f"  {p}")
            print("Run scripts/sync-chrome.py.")
            return 1
        print("Every page carries the generated chrome.")
        return 0
    print(f"wrote {len(stale)} page(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
