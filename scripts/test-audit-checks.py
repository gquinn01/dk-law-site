#!/usr/bin/env python3
"""
Smoke tests for the checks in audit.py that must never drift back.

WHY THIS FILE EXISTS. Rule 6 says the name, address and phone are
character-identical everywhere. audit.py is the mechanism that makes that
true instead of remembered, and on the founding client build the mechanism
was found to be lying.

The address-variant pattern ended each alternative with \\b, which reads
as "a word character comes next." On a real page the character after
"Rd." is a comma or a line break, so the boundary never matched. Worse
than a silent skip: the canonical string "100 Main Rd" is a PREFIX of the
variant, so the plain `in` test found it inside "100 Main Rd." and the
page was scored as CORRECTLY SPELLED. A check that reports a pass on the
exact input it exists to catch is worse than no check, because it also
tells everyone downstream to stop looking.

That bug was invisible from the outside: every page anyone had written
happened to spell the street the right way, so the check "worked" on
every input it had ever been given. Only a deliberately wrong page shows
it. So the deliberately wrong pages live here.

THE FIRM'S FACTS ARE OFF in this repo (FACTS_OFF in audit.py): the NAP,
hours, geo, email, review count and sameAs wait for the firm's written
confirmation. So this file proves two things about each of those checks:

  1. OFF IS QUIET. With the constants unset, a page carrying addresses,
     phone numbers, hours and coordinates draws no pass and no fail from
     them, and every run says in its notes what is off.
  2. THE MECHANISM STILL WORKS. Switched on with FIXTURE values (below),
     each check still catches every variant it exists to catch. The day the
     firm's real values go in, the mechanism they land in is already proven.

THE FIXTURE VALUES ARE MADE UP AND MUST NEVER BE PUBLISHED. "Example &
Sample, LLC" at "100 Example St", phone numbers in the 555-01xx fictional
range, mail at the reserved .test domain. They exist only inside this file,
switched on by facts_on() and restored after. None of them is the firm's,
and none of them came from the live site.

No network and no external packages: audit.load is swapped for a
dictionary lookup, so this runs offline in a second.

Usage:
    python3 scripts/test-audit-checks.py     # exits 1 if anything fails
"""

import contextlib
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FAILURES = []


def check(label: str, passed: bool, detail=""):
    """Records a result instead of raising, so one broken case cannot
    hide the ten after it."""
    print(f"  {'ok  ' if passed else 'FAIL'}  {label}")
    if not passed:
        FAILURES.append(f"{label}{f'  ->  {detail}' if detail != '' else ''}")


def load_script(name: str, modname: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(modname, os.path.join(HERE, name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- The fixture facts. Made up. See the docstring. ------------------------
FX_NAME = "Example & Sample, LLC"
FX_STREET = "100 Example St"
FX_CITY = "Exampleton, PA 18700"
FX_PHONE = "(570) 555-0100"
FX_TEL = "+15705550100"
FX_EMAIL = "office@example.test"
FX_WRONG_EMAIL = "info@example.test"
FX_TRACKING = "(570) 555-0199"
FX_HOURS = ("Monday to Friday, 9 a.m. to 5 p.m.",)
FX_GEO = (12.3456789, -45.6789012)   # nowhere near anywhere; deliberately not a real place
FX_REVIEWS = 120


@contextlib.contextmanager
def facts_on():
    """Every OFF fact check switched on with the fixture values, and
    everything put back afterwards, whatever happens inside."""
    names = ("NAP_NAME", "NAP_STREET", "NAP_LOCALITY", "NAP_REGION", "NAP_POSTAL",
             "NAP_PHONE_DISPLAY", "NAP_PHONE_TEL", "NAP_PHONE_RE", "NAP_EMAIL",
             "NAP_EMAIL_RE", "NAP_EMAIL_WRONG_RE", "TRACKING_PHONE_RES",
             "NAP_STREET_CANON", "NAP_CITYLINE_CANON", "NAP_STREET_MENTION_RE",
             "NAP_STREET_VARIANT_RE", "NAP_STREET_CANON_RE", "NAME_MENTION_RE",
             "NAP_CONTACT_RES", "HOURS_CANON", "HOURS_SCHEMA_DAYS", "HOURS_SCHEMA_OPENS",
             "HOURS_SCHEMA_CLOSES", "HOURS_FORBIDDEN_DAYS", "GEO_LAT", "GEO_LON",
             "REVIEW_COUNT", "REVIEW_RATING", "REVIEW_COUNTED_ON", "CHROME_TEL",
             "CHROME_MAILTO")
    saved = {n: getattr(audit, n) for n in names}
    try:
        audit.NAP_NAME = FX_NAME
        audit.NAP_STREET, audit.NAP_LOCALITY = FX_STREET, "Exampleton"
        audit.NAP_REGION, audit.NAP_POSTAL = "PA", "18700"
        audit.NAP_PHONE_DISPLAY, audit.NAP_PHONE_TEL = FX_PHONE, FX_TEL
        audit.NAP_PHONE_RE = re.compile(r"\(?570\)?[\s.\-]?555[\s.\-]?0100")
        audit.NAP_EMAIL = FX_EMAIL
        audit.NAP_EMAIL_RE = re.compile(re.escape(FX_EMAIL))
        audit.NAP_EMAIL_WRONG_RE = re.compile(re.escape(FX_WRONG_EMAIL), re.I)
        audit.TRACKING_PHONE_RES = (re.compile(r"\(?570\)?[\s.\-]?555[\s.\-]?0199"),)
        audit.NAP_STREET_CANON = FX_STREET
        audit.NAP_CITYLINE_CANON = FX_CITY
        audit.NAP_STREET_MENTION_RE = re.compile(r"\bExample\s+(?:St|Street)\b", re.I)
        audit.NAP_STREET_VARIANT_RE = re.compile(r"\b(?:100\s+)?Example\s+(?:Street\b|St\.)", re.I)
        audit.NAP_STREET_CANON_RE = re.compile(re.escape(FX_STREET) + r"(?![.\w])")
        audit.NAME_MENTION_RE = re.compile(
            r"\bExample(?:\s*(?:,|&|and)\s*|\s+)Sample(?:,?\s+LLC)?\b|\bE&S\b", re.I)
        audit.NAP_CONTACT_RES = [("phone", audit.NAP_PHONE_RE), ("email", audit.NAP_EMAIL_RE)]
        audit.HOURS_CANON = FX_HOURS
        audit.HOURS_SCHEMA_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
        audit.HOURS_SCHEMA_OPENS, audit.HOURS_SCHEMA_CLOSES = "09:00", "17:00"
        audit.HOURS_FORBIDDEN_DAYS = ("saturday", "sunday")
        audit.GEO_LAT, audit.GEO_LON = FX_GEO
        audit.REVIEW_COUNT, audit.REVIEW_RATING = FX_REVIEWS, "4.8"
        audit.REVIEW_COUNTED_ON = "2026-10-01"
        audit.CHROME_TEL, audit.CHROME_MAILTO = f"tel:{FX_TEL}", f"mailto:{FX_EMAIL}"
        yield
    finally:
        for n, v in saved.items():
            setattr(audit, n, v)


@contextlib.contextmanager
def patched(**values):
    """Any audit constants set for the duration, then restored."""
    saved = {k: getattr(audit, k) for k in values}
    try:
        for k, v in values.items():
            setattr(audit, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(audit, k, v)


PAGE = """<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Personal Injury Lawyer | Example Page Title</title>
<meta name="description" content="A description that is comfortably under one hundred and sixty characters, so the length checks never become the reason a case fails.">
<link rel="canonical" href="https://dklawllc.com/fixture/">
<meta property="og:title" content="Fixture"><meta property="og:description" content="Short.">
</head><body><main><h1>Fixture Page</h1>
{body}
</main></body></html>"""


def run(body: str):
    """Audits one fabricated page and returns its three scored buckets as
    one searchable string each."""
    html = PAGE.format(body=body)
    audit.load = lambda _src, _h=html: _h
    passes, warns, fails, notes, kind = audit.audit("fabricated.html", coverage=None)
    return " ".join(passes), " ".join(warns), " ".join(fails)


def run_kind(meta: str, body: str):
    html = PAGE.replace("</head>", meta + "</head>").format(body=body)
    audit.load = lambda _src, _h=html: _h
    passes, warns, fails, notes, kind = audit.audit("fabricated.html", coverage=None)
    return " ".join(passes), " ".join(warns), " ".join(fails), " ".join(notes), kind


def kind_meta(k: str) -> str:
    return f'<meta name="{audit.PAGE_KIND_META}" content="{k}">'


def biz(extra: dict = None, t="LegalService") -> str:
    node = {"@type": t, "@id": "https://dklawllc.com/#business"}
    node.update(extra or {})
    return ('<script type="application/ld+json">'
            + json.dumps({"@context": "https://schema.org", "@graph": [node]}) + "</script>")


def main():
    # --- 0 -----------------------------------------------------------------
    print("0. The client: DKY's parameters, and every firm fact OFF")
    check("    the site is https://dklawllc.com/", audit.SITE_BASE == "https://dklawllc.com/", audit.SITE_BASE)
    check("    the business type is LegalService", audit.SCHEMA_BUSINESS_TYPE == "LegalService")
    check("    pages declare their kind with dky-page", audit.PAGE_KIND_META == "dky-page")
    check("    FACTS_OFF names exactly the six checks that wait for the firm",
          audit.FACTS_OFF == ("NAP (name, address, phone)", "hours", "geo", "email",
                              "review count", "sameAs"), audit.FACTS_OFF)
    off = {n: getattr(audit, n) for n in (
        "NAP_NAME", "NAP_STREET", "NAP_LOCALITY", "NAP_REGION", "NAP_POSTAL", "NAP_PHONE_DISPLAY",
        "NAP_PHONE_TEL", "NAP_PHONE_RE", "NAP_EMAIL", "NAP_EMAIL_RE", "NAP_EMAIL_WRONG_RE",
        "NAP_STREET_MENTION_RE", "NAP_STREET_VARIANT_RE", "NAME_MENTION_RE", "HOURS_CANON",
        "GEO_LAT", "GEO_LON", "REVIEW_COUNT", "REVIEW_COUNTED_ON", "SAME_AS", "GBP_MAP_URL",
        "FOUNDING_DATE", "MAPS_NAP_URL", "CHROME_TEL", "CHROME_MAILTO")}
    check("    every firm-fact constant is unset: no value filled from anywhere",
          all(v is None for v in off.values()), {k: v for k, v in off.items() if v is not None})
    check("    and every per-site table is empty until pagemap.md exists",
          (audit.SERVICES, audit.REDIRECTS, audit.HONEST_404S, audit.AREA_SERVED,
           audit.TRACKING_PHONE_RES, audit.CHROME_EXTERNAL_URLS, audit.TOWN_PLACE_NAMES)
          == ((), {}, (), (), (), (), ()))
    check("    the staging switch is ON: the live site is still the live site", audit.STAGING is True)
    check("    the banner names the live site at dklawllc.com", "dklawllc.com" in audit.STAGING_BANNER)

    # No other client's facts travelled with the machinery. The patterns are
    # assembled from pieces so this file does not trip its own sweep.
    foreign = re.compile("|".join([
        "tri" + r"[\s-]*" + "county", "jay" + "mor", "south" + "ampton",
        r"215\)?[\s.\-]?322", r"215\)?[\s.\-]?709", "carw" + "ise", "docu" + "sign",
        "colli" + "sion"]), re.I)
    hits = []
    for tree in ("scripts", "templates", "agents", ".github", "docs"):
        for dp, dn, fn in os.walk(os.path.join(ROOT, tree)):
            dn[:] = [d for d in dn if d not in (".git", "__pycache__")]
            for f in fn:
                path = os.path.join(dp, f)
                text = open(path, encoding="utf-8", errors="replace").read()
                for m in foreign.finditer(text):
                    hits.append(f"{os.path.relpath(path, ROOT)}: {m.group(0)}")
    for f in ("CLAUDE.md", ".gitignore"):
        p_ = os.path.join(ROOT, f)
        if os.path.isfile(p_):
            for m in foreign.finditer(open(p_, encoding="utf-8").read()):
                hits.append(f"{f}: {m.group(0)}")
    check("    no other client's name, address, numbers or vendors anywhere in the repo's own files",
          not hits, hits[:10])

    # --- 1 -----------------------------------------------------------------
    print("1. OFF is quiet: a page full of NAP-shaped text draws nothing from the off checks")
    noisy = (f"<p>{FX_NAME}, {FX_STREET}., {FX_CITY}. Call {FX_PHONE} or {FX_TRACKING}, "
             f"or write to {FX_EMAIL} or {FX_WRONG_EMAIL}. Open Mon-Fri 8 to 4, "
             f"Saturday by appointment, closed Sunday. 250 Google reviews.</p>"
             + biz({"geo": {"@type": "GeoCoordinates", "latitude": 1, "longitude": 2},
                    "openingHoursSpecification": [{"dayOfWeek": ["Monday"], "opens": "08:00",
                                                    "closes": "16:00"}]}))
    p, w, f = run(noisy)
    for label, word in (("the address", "street address"), ("the name", "business name"),
                        ("the hours", "hours"), ("the geo", "geo"), ("a second mailbox", "mailbox"),
                        ("a tracking number", "tracking"), ("the founding year", "founding")):
        check(f"    no pass and no fail about {label}", word not in (p + f).lower(), (p, f))
    check("    and no untappable-contact warning, with no contact patterns set", "not linked" not in w, w)
    check("    the founding-year reader reads nothing while FOUNDING_DATE is unset",
          audit.founding_findings("<p>Founded in 1950.</p>") == (0, []))

    # --- 2-8: the address -------------------------------------------------
    with facts_on():
        print("2. The canonical spelling, which must keep passing (fixture NAP)")
        p, w, f = run(f"<p>{FX_STREET}, {FX_CITY}</p>")
        check("   scored as the canonical spelling", "canonical spelling" in p, p)
        check("   no critical raised", "street address is spelled" not in f, f)

        print("3. THE REGRESSION: a trailing period, the case that scored a PASS")
        p, w, f = run(f"<p>{FX_STREET}., {FX_CITY}</p>")
        check("   the period is caught as a variant", f"{FX_STREET}." in f, f)
        check("   and it is NOT reported as the canonical spelling", "canonical spelling" not in p, p)

        print("4. St. at the end of a line, with nothing after it at all")
        p, w, f = run(f"<p>{FX_STREET}.<br>{FX_CITY}</p>")
        check("   still caught", "street address is spelled" in f, f)

        print("5. Street spelled out")
        p, w, f = run(f"<p>100 Example Street, {FX_CITY}</p>")
        check("   caught as a variant", "100 Example Street" in f, f)

        print("6. Both spellings on one page")
        p, w, f = run(f"<p>{FX_STREET}, {FX_CITY}</p><p>Mail to 100 Example Street, {FX_CITY}</p>")
        check("   the variant fails even though the canonical is also present",
              "street address is spelled" in f, f)
        check("   and the page is not also credited with a pass", "canonical spelling" not in p, p)

        print("7. The street line with no city, state and ZIP")
        p, w, f = run(f"<p>{FX_STREET}</p>")
        check("   warned, not failed", "is not" in w and "street address is spelled" not in f, (w, f))

        print("8. The street named with no address at all, and a page that never names it")
        p, w, f = run("<p>We are the office on Example St near the courthouse.</p>")
        check("   failed for naming the street without the canonical address",
              "names the street" in f, f)
        p, w, f = run("<p>We represent injured people in the valley.</p>")
        check("   the address check stays out of a page that never names it",
              "street" not in f.lower() and "canonical spelling" not in p, (p, f))

        # --- 9-11: tracking number and email ---
        print("9. A call-tracking number")
        p, w, f = run(f'<p>Call <a href="tel:+15705550199">{FX_TRACKING}</a></p>')
        check("   caught as a critical", "call-tracking number" in f, f)
        p, w, f = run(f'<p>Call <a href="tel:{FX_TEL}">{FX_PHONE}</a></p>')
        check("   the firm's own phone is not mistaken for it", "call-tracking number" not in f, f)
        p, w, f = run("<p>Reach us on 570.555.0199 today.</p>")
        check("   caught when punctuated some other way", "call-tracking number" in f, f)

        print("10. The one published email address")
        p, w, f = run(f'<p><a href="mailto:{FX_WRONG_EMAIL}">{FX_WRONG_EMAIL}</a></p>')
        check("    the second mailbox is a critical", FX_WRONG_EMAIL in f, f)
        p, w, f = run(f'<p><a href="mailto:{FX_EMAIL}">{FX_EMAIL}</a></p>')
        check("    the published address is not flagged", FX_WRONG_EMAIL not in f, f)
        check("    and it is counted as a tappable contact", "tappable" in p, p)
        p, w, f = run(f"<p>Email {FX_EMAIL} and we will reply.</p>")
        check("    a bare, untappable address is caught", "not linked" in w, w)

        print("11. The tracking number, swept across the files that BECOME pages")
        hits = []
        for tree in ("templates", "docs"):
            for dp, dn, fn in os.walk(os.path.join(ROOT, tree)):
                for name in fn:
                    text = open(os.path.join(dp, name), encoding="utf-8", errors="replace").read()
                    if any(rx.search(text) for rx in audit.TRACKING_PHONE_RES):
                        hits.append(os.path.relpath(os.path.join(dp, name), ROOT))
        check("    no file under templates/ or docs/ carries the fixture tracking number", not hits, hits)
    check("    and with no tracking number known, the real list is empty", audit.TRACKING_PHONE_RES == ())

    # --- 12: links ----------------------------------------------------------
    print("12. Links, both directions: nothing dead, nothing forgotten")

    def dead_links(under):
        out = []
        for page in sorted(glob.glob(os.path.join(under, "**", "*.html"), recursive=True)):
            html_text = re.sub(r"<!--[\s\S]*?-->", " ", open(page, encoding="utf-8", errors="replace").read())
            # THE ATTRIBUTE BOUNDARY IS LOAD-BEARING: "href" is a substring
            # of "data-pending-href", and a pending link is the opposite of
            # a dead one.
            for ref in re.findall(r'(?:^|\s)(?:href|src)="([^"]+)"', html_text):
                if ref.startswith(("http://", "https://", "tel:", "mailto:", "#", "data:")):
                    continue
                if ref.startswith("/") and os.path.relpath(page, under) == "404.html":
                    target = audit.resolve_local_link(os.path.join(under, "index.html"),
                                                      "./" + ref.lstrip("/"))
                else:
                    target = audit.resolve_local_link(page, ref)
                if not os.path.isfile(target):
                    out.append(f"{os.path.relpath(page, under)} -> {ref}")
        return out

    docs = os.path.join(ROOT, "docs")
    check("    no relative link under docs/ points at a missing file", not dead_links(docs), dead_links(docs))
    live = [x for x in audit.find_pending_links(docs) if x[4]]
    check("    no data-pending-href points at a page that now exists", not live, live)
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "svc"))
        with open(os.path.join(tmp, "svc", "index.html"), "w", encoding="utf-8") as fh:
            fh.write('<a href="../gone/">dead</a>'
                     '<span data-pending-href="../soon/">waiting</span>'
                     '<!-- <a href="../commented-out/">not a link</a> -->')
        check("     DIRECTION 1: an href with no file behind it fails",
              dead_links(tmp) == ["svc/index.html -> ../gone/"], dead_links(tmp))
        check("     a link inside a comment is not a link",
              not any("commented-out" in x for x in dead_links(tmp)), dead_links(tmp))
        check("     a data-pending-href is NOT read as an href",
              not any("soon" in x for x in dead_links(tmp)), dead_links(tmp))
        check("     DIRECTION 2: a pending href stays quiet while unbuilt",
              [x for x in audit.find_pending_links(tmp) if x[4]] == [])
        os.makedirs(os.path.join(tmp, "soon"))
        open(os.path.join(tmp, "soon", "index.html"), "w").write("<h1>built</h1>")
        now_live = [x for x in audit.find_pending_links(tmp) if x[4]]
        check("     DIRECTION 2: the day its target exists, it FAILS", len(now_live) == 1, now_live)
        check("     and it reports the file, the line and the href",
              bool(now_live) and now_live[0][1] == 1 and now_live[0][2] == "../soon/", now_live)
        pth = os.path.join(tmp, "svc", "index.html")
        body = open(pth).read().replace('<span data-pending-href="../soon/">waiting</span>',
                                        '<a href="../soon/">waiting</a>')
        open(pth, "w").write(body)
        check("     converting it to a real link clears BOTH directions",
              [x for x in audit.find_pending_links(tmp) if x[4]] == []
              and dead_links(tmp) == ["svc/index.html -> ../gone/"], dead_links(tmp))
    check("     both directions share one resolver",
          "audit.resolve_local_link" in open(os.path.abspath(__file__), encoding="utf-8").read())

    # --- 13: review count ----------------------------------------------------
    print("13. The review count, the one number that rots on its own")
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as fh:
            fh.write('<!-- It was 231 on the widget. -->\n'
                     '<span class="stat-n">274</span>\n'
                     '<span class="stat-l">Google reviews</span>\n'
                     '<script>var old = "199 reviews";</script>')
        open(os.path.join(tmp, "llms.txt"), "w").write("Rated 4.9 across 274 Google reviews.\n")
        nums = sorted(n for _p, n, _s in audit.find_review_counts(tmp))
        check("     the numeral and the words in separate spans are still read as one count", 274 in nums, nums)
        check("     a comment recording the OLD number is not counted as a claim", 231 not in nums, nums)
        check("     a number inside <script> is not counted either", 199 not in nums, nums)
        check("     llms.txt is scanned, not just the pages", nums == [274, 274], nums)

    def run_review(hits, counted_on, today):
        real_find, real_date = audit.find_review_counts, audit.REVIEW_COUNTED_ON
        audit.find_review_counts = lambda root=None: hits
        audit.REVIEW_COUNTED_ON = counted_on
        try:
            passes, warns, fails, notes = [], [], [], []
            audit.check_review_count_local(passes, warns, fails, notes, today=today)
            return warns, fails, notes
        finally:
            audit.find_review_counts, audit.REVIEW_COUNTED_ON = real_find, real_date

    TODAY = date(2026, 10, 1)
    N = FX_REVIEWS
    agree = [("docs/a/index.html", N, f"{N} Google reviews")]
    disagree = agree + [("docs/b/index.html", 231, "231 Google reviews")]
    with facts_on():
        warns, fails, notes = run_review(agree, "2026-10-01", TODAY)
        check("     ON: agreement on the day it was counted is clean", not fails and not warns, fails + warns)
        check("     and it reports as a note rather than a pass", len(notes) == 1, notes)
        warns, fails, notes = run_review(disagree, "2026-10-01", TODAY)
        check("     ON: TWO PAGES THAT DISAGREE ARE A CRITICAL", len(fails) == 1, fails)
        check("     and the critical names both numbers and the file",
              bool(fails) and "231" in fails[0] and str(N) in fails[0] and "docs/b/index.html" in fails[0], fails)
        warns, fails, notes = run_review([("docs/a/index.html", 231, "231 Google reviews")], "2026-10-01", TODAY)
        check("     ON: ONE page disagreeing with REVIEW_COUNT is a critical too", len(fails) == 1, fails)
        warns, fails, notes = run_review(agree, str(TODAY - timedelta(days=35)), TODAY)
        check("     ON: exactly 35 days old is not yet stale", not warns, warns)
        warns, fails, notes = run_review(agree, str(TODAY - timedelta(days=36)), TODAY)
        check("     ON: 36 days old is a WARNING, not a critical, and says how old",
              len(warns) == 1 and not fails and "36 days old" in warns[0], warns + fails)
        warns, fails, notes = run_review(agree, str(TODAY + timedelta(days=1)), TODAY)
        check("     ON: a counted-on date in the future is caught", len(warns) == 1, warns)
        warns, fails, notes = run_review([], "2026-10-01", TODAY)
        check("     ON: no mention anywhere is a note, not a failure",
              not fails and not warns and len(notes) == 1, fails + warns + notes)
    warns, fails, notes = run_review(disagree, None, TODAY)
    check("     OFF: two pages that disagree are STILL a critical", len(fails) == 1 and "231" in fails[0], fails)
    warns, fails, notes = run_review(agree, None, TODAY)
    check("     OFF: one count published with no recorded reading warns", len(warns) == 1 and not fails, (warns, fails))
    warns, fails, notes = run_review([], None, TODAY)
    check("     OFF: no count anywhere is silent", not (warns or fails or notes), (warns, fails, notes))
    src = open(os.path.join(HERE, "audit.py"), encoding="utf-8").read()
    check("     --strict actually exits 1 on a site-wide critical", "opts.strict and (below or site_fails)" in src)
    for text, want in (("274 Google reviews", "274"), ("274 reviews", "274"),
                       ("over 231 verified Google reviews", "231"),
                       ("1,204 five-star Google reviews", "1,204"), ("2019 Google reviews", "2019"),
                       ("In 2019 our clients left reviews", None), ("since 2019, reviews poured in", None)):
        m = audit.REVIEW_COUNT_RE.search(text)
        check(f"     {text!r} reads as {want}", (m.group(1) if m else None) == want, m.group(1) if m else None)

    # --- 14 ---------------------------------------------------------------------
    print("14. No review or rating markup anywhere")
    marked = []
    for tree in ("docs", "templates"):
        for dp, _dn, fn in os.walk(os.path.join(ROOT, tree)):
            for name in fn:
                if name.endswith(".html"):
                    body = open(os.path.join(dp, name), encoding="utf-8", errors="replace").read()
                    for script in re.findall(r"(?is)<script[^>]*ld\+json[^>]*>(.*?)</script>", body):
                        if re.search(r'"(aggregateRating|ratingValue|reviewCount|reviewRating)"', script):
                            marked.append(os.path.relpath(os.path.join(dp, name), ROOT))
    check("     no page or template carries aggregateRating, ratingValue or reviewCount", not marked, marked)

    # --- 15 ---------------------------------------------------------------------
    print("15. The comment convention: comments name REVIEW_COUNT, never the number")
    import inspect

    def comment_hits(body):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "p.html"), "w").write(body)
            return audit.find_rotting_comments(tmp)
    check("     a comment quoting a literal count is caught", len(comment_hits("<!-- It was 274 reviews. -->")) == 1)
    check("     the other word order is caught too", len(comment_hits("<!-- The reviews stood at 274. -->")) == 1)
    check("     a comment wrapped across lines is still one sentence",
          len(comment_hits("<!-- It was 274\n         Google reviews. -->")) == 1)
    check("     naming REVIEW_COUNT instead is NOT caught, by construction",
          comment_hits("<!-- The count lives in REVIEW_COUNT, set 2026 in audit.py. -->") == [])
    check("     one digit beside the word is prose, not a count", comment_hits("<!-- Ask for a 5 star review. -->") == [])
    check("     five digits is not a count", comment_hits("<!-- 12345 reviews someday. -->") == [])
    params = list(inspect.signature(audit.check_comment_convention_local).parameters)
    check("     the check cannot raise a critical, having no fails list", params == ["warns", "notes"], params)
    warns, notes = [], []
    audit.check_comment_convention_local(warns, notes)
    check("     and the repo's own comments are clean right now", not warns and len(notes) == 1, warns)

    # --- 17 ---------------------------------------------------------------------
    print("17. Asset provenance: an AI-generated image must never land")
    IPTC = "http://cv.iptc.org/newscodes/digitalsourcetype/"

    def prov(xmp: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.jpg")
            open(path, "wb").write(b"\xff\xd8\xff\xe1" + xmp.encode("utf-8") + b"\xff\xd9")
            return audit.read_asset_provenance(path)
    for label, xmp, bad in (
            ("trainedAlgorithmicMedia as an element is caught",
             f"<Iptc4xmpExt:DigitalSourceType>{IPTC}trainedAlgorithmicMedia</Iptc4xmpExt:DigitalSourceType>", True),
            ("and as an ATTRIBUTE, the other legal spelling",
             f'Iptc4xmpExt:DigitalSourceType="{IPTC}trainedAlgorithmicMedia"', True),
            ("a part-generative composite is caught too",
             f"<Iptc4xmpExt:DigitalSourceType>{IPTC}compositeWithTrainedAlgorithmicMedia</Iptc4xmpExt:DigitalSourceType>", True),
            ("THE SECOND TELL: a generator in the tool field, no source type at all",
             "<xmp:CreatorTool>OkiDokiBot AI Art Generator</xmp:CreatorTool>", True),
            ("and the other generators by name", "<xmp:CreatorTool>Midjourney</xmp:CreatorTool>", True),
            ("a camera passes", f"<Iptc4xmpExt:DigitalSourceType>{IPTC}digitalCapture</Iptc4xmpExt:DigitalSourceType>", False),
            ("digitalArt passes: a person at a workstation",
             f"<Iptc4xmpExt:DigitalSourceType>{IPTC}digitalArt</Iptc4xmpExt:DigitalSourceType>", False),
            ("algorithmicMedia passes: procedural is not generative",
             f"<Iptc4xmpExt:DigitalSourceType>{IPTC}algorithmicMedia</Iptc4xmpExt:DigitalSourceType>", False),
            ("ordinary editing software passes", "<xmp:CreatorTool>Adobe Photoshop 26.0</xmp:CreatorTool>", False),
            ("a file with no metadata passes, because a label is all this can read", "", False)):
        a = prov(xmp)
        check(f"     {label}", bool(a["reasons"]) == bad, a)
    a = prov('dcterms:provenance="https://cai-manifests.adobe.com/manifests/urn-c2pa-x"'
             f'<Iptc4xmpExt:DigitalSourceType>{IPTC}digitalCapture</Iptc4xmpExt:DigitalSourceType>')
    check("     a C2PA manifest ALONE is not a tell: real stock carries one", not a["reasons"] and a["c2pa"], a)
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "assets", "img"))
        open(os.path.join(tmp, "assets", "img", "bad.jpg"), "wb").write(
            b"\xff\xd8" + f"<Iptc4xmpExt:DigitalSourceType>{IPTC}trainedAlgorithmicMedia</Iptc4xmpExt:DigitalSourceType>".encode())
        open(os.path.join(tmp, "assets", "img", "drawn.svg"), "w").write("<svg>midjourney</svg>")
        found = audit.find_assets(tmp)
        check("     find_assets reads rasters and leaves .svg alone", len(found) == 1, [x["path"] for x in found])
        with patched(SITE_DIR=tmp):
            p2, w2, f2, n2 = [], [], [], []
            audit.check_asset_provenance_local(p2, w2, f2, n2)
        check("     and it raises a CRITICAL, not a warning, naming the file and refusing the shortcut",
              len(f2) == 1 and not w2 and "bad.jpg" in f2[0] and "strip the label" in f2[0], (f2, w2))
    real = audit.find_assets(docs)
    check("     every image in the repo right now is clean", all(not a["reasons"] for a in real),
          [a["path"] for a in real if a["reasons"]])

    # --- 19: page kinds -------------------------------------------------------------
    print("19. The page kinds: each exempt from exactly its listed checks, nothing else")
    check("     exactly the house kinds, no blanket kind, utility above all",
          audit.RUBRIC_EXEMPTIONS == {"contact": ("faq-schema", "thin-content"), "post": ("faq-schema",),
                                      "blog-index": ("faq-schema",), "town": (),
                                      "privacy": ("faq-schema",)}, audit.RUBRIC_EXEMPTIONS)
    contact = kind_meta("contact")
    with facts_on():
        short = f'<p>Call <a href="tel:{FX_TEL}">{FX_PHONE}</a>.</p>'
        p, w, f, n, kind = run_kind(contact, short)
        check("     a short contact page draws no thin-content and no FAQPage warning",
              "Thin content" not in w and "no FAQPage schema" not in w, w)
        check("     both exemptions are reported as notes, not silence",
              "not measured against 300" in n and "No FAQPage schema, not measured" in n, n)
        check("     it still reports as a page, not as a special kind", kind == "page", kind)
        p, w, f, n, kind = run_kind(contact, short + "<p>Or call 570.555.0199 today.</p>")
        check("     a contact page still fails on a tracking number", "call-tracking number" in f, f)
        p, w, f, n, kind = run_kind(contact, short + f'<p><a href="mailto:{FX_WRONG_EMAIL}">{FX_WRONG_EMAIL}</a></p>')
        check("     and on the second email address", FX_WRONG_EMAIL in f, f)
        p, w, f, n, kind = run_kind(contact, short + f"<p>100 Example Street, {FX_CITY}</p>")
        check("     and on a wrong street spelling", "street address is spelled" in f, f)
        p, w, f, n, kind = run_kind(contact, f"<p>Email {FX_EMAIL}.</p>")
        check("     and still warns on an untappable contact", "not linked" in w, w)
        no_h1 = PAGE.replace("<h1>Fixture Page</h1>", "").replace("</head>", contact + "</head>").format(body=short)
        audit.load = lambda _s, _h=no_h1: _h
        _p, _w, _f, _n, _k = audit.audit("fabricated.html", coverage=None)
        check("     and still fails with no H1", any("No H1" in x for x in _f), _f)
        p, w, f, n, kind = run_kind("", short)
        check("     an UNDECLARED short page still draws both warnings",
              "Thin content" in w and "no FAQPage schema" in w, w)
        for bad_kind in ("contct", "utility", "Contact Page"):
            p, w, f, n, kind = run_kind(kind_meta(bad_kind), short)
            check(f"     {bad_kind!r} gets no exemption", "Thin content" in w, w)
        other = "tri" + "-" + "county" + "-page"
        p, w, f, n, kind = run_kind(f'<meta name="{other}" content="contact">', short)
        check("     another client's kind meta is not read: no exemption", "Thin content" in w, w)

    # --- 20: hours ------------------------------------------------------------------
    print("20. The hours: one way to write them (fixture hours)")
    with facts_on():
        H = "<p>Monday to Friday, 9&nbsp;a.m. to 5&nbsp;p.m.</p>"
        p, w, f = run(H)
        check("     the canonical string passes, no-break spaces and all",
              "Hours match the constants" in p and "hours are written" not in f, (p, f))
        for label, body in (("an hour-shaped spelling", "<p>Hours: Monday - Friday 9 AM - 5 PM</p>"),
                            ("an abbreviated range", "<p>Mon-Fri, 9 a.m. - 5 p.m.</p>"),
                            ("the right days at the wrong time", "<p>Monday to Friday, 9 a.m. to 6 p.m.</p>"),
                            ("a stray clock time beside the canonical string", H + "<p>Call before 4 p.m.</p>"),
                            ("a stray day beside the canonical string", H + "<p>Closed Tuesday afternoons.</p>")):
            p, w, f = run(body)
            check(f"     caught: {label}", "hours are written a second way" in f, f)
        for body in ("<p>Sunday: Closed</p>", H + "<p>Saturdays by appointment.</p>"):
            p, w, f = run(body)
            check(f"     a day the record does not know is a critical: {body[-28:]!r}", "no hours for" in f, f)
        p, w, f = run("<p>Hundreds of hours of preparation. Sun glare on the highway. The door was open.</p>")
        check("     words that only look like hours are left alone",
              "hours are written" not in f and "no hours for" not in f and "Hours match" not in p, (p, f))
        wrong = biz({"openingHoursSpecification": [{"@type": "OpeningHoursSpecification",
                     "dayOfWeek": list(audit.HOURS_SCHEMA_DAYS), "opens": "09:00", "closes": "16:00"}]})
        p, w, f = run(H + wrong)
        check("     a schema that closes at 16:00 is a critical", "schema's hours disagree" in f, f)
        n, strays, banned = audit.hours_findings("- Hours: Monday to Friday, 9 a.m. to 5 p.m.")
        check("     the llms.txt phrasing is canonical", n == 1 and not strays and not banned, (n, strays, banned))
        n, strays, banned = audit.hours_findings("- Hours: Mon-Fri 9-5.")
        check("     and a shorthand llms.txt line is not", bool(strays), strays)

    # --- 21 ---------------------------------------------------------------------
    print("21. An inline SVG's <title> is not the page's title")
    p, w, f = run('<svg role="img"><title>A map of the streets around the office, drawn from data</title></svg>')
    check("     the page title is still measured as the head's alone",
          f"({len('Personal Injury Lawyer | Example Page Title')} chars)" in p, p)

    # --- 22: geo ----------------------------------------------------------------
    print("22. The schema's geo is the verified pin, and only that (fixture pin)")

    def gc(lat, lon):
        return {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}
    with facts_on():
        lat, lon = FX_GEO
        p, w, f = run(biz({"geo": gc(lat, lon)}))
        check("     the verified pin passes", "Schema geo is the verified pin" in p and "verified pin:" not in f, (p, f))
        for label, geo in (("a map URL's centre, 220m off", gc(lat, lon - 0.0026)),
                           ("latitude and longitude swapped", gc(lon, lat)),
                           ("one digit off in the seventh place", gc(lat, lon + 0.0000001)),
                           ("coordinates that are not numbers", gc("north", "west"))):
            p, w, f = run(biz({"geo": geo}))
            check(f"     caught: {label}", "not the firm's verified pin" in f, f)
        p, w, f = run(biz())
        check("     caught: a business node with no geo at all", "carries no `geo`" in f, f)
        p, w, f = run('<script type="application/ld+json">{"@type":"Place","geo":'
                      + json.dumps(gc(40.0, -75.0)) + "</script>")
        check("     a geo on a node that is not the business is left alone", "verified pin" not in f + p, (p, f))
        good = (f'<iframe src="https://www.google.com/maps?q={lat},{lon}&amp;z=15&amp;output=embed"'
                ' title="Map" loading="lazy"></iframe>')
        p, w, f = run(good)
        check("     the embed centred on the verified pin passes", "centred on the verified pin" in p and "embed is wrong" not in f, (p, f))
        for label, frag in (("an embed queried by the business's NAME", good.replace(f"q={lat},{lon}", "q=Example+%26+Sample")),
                            ("an embed one digit off the pin", good.replace(str(lon), str(lon + 0.0000001))),
                            ("an embed with no title", good.replace(' title="Map"', "")),
                            ("an embed that loads eagerly", good.replace(' loading="lazy"', ""))):
            p, w, f = run(frag)
            check(f"     caught: {label}", "embed is wrong" in f, f)
    html_embed = PAGE.format(body='<iframe src="https://www.google.com/maps?q=1,2" title="Map" loading="lazy"></iframe>')
    audit.load = lambda _s, _h=html_embed: _h
    ps, ws, fs, ns, _k = audit.audit("fabricated.html", coverage=None)
    check("     OFF: an embed is noted as unchecked, not passed and not failed",
          any("geo check is OFF" in x for x in ns) and not any("embed" in x for x in ps + fs), (ps, fs, ns))

    # --- 23: blog kinds -----------------------------------------------------------
    print("23. The blog kinds: no FAQ required, and an FAQ is still measured")
    long_body = "<p>" + " ".join(["word"] * 320) + "</p>"
    faq_vis = ('<details><summary>Is the first consultation free?<span class="faq-ico"></span></summary>'
               '<p>Yes, the first consultation with the firm is free of charge.</p></details>')

    def faq_schema(ans, q="Is the first consultation free?"):
        return ('<script type="application/ld+json">{"@type":"FAQPage","mainEntity":[{'
                f'"@type":"Question","name":"{q}","acceptedAnswer":{{"@type":"Answer",'
                f'"text":"{ans}"}}}}]}}</script>')
    for k in ("post", "blog-index"):
        meta = kind_meta(k)
        p, w, f, n, kind = run_kind(meta, long_body)
        check(f"     a {k} with no FAQ draws no FAQPage warning, and says so in a note",
              "no FAQPage schema" not in w and "not measured here" in n, (w, n))
        p, w, f, n, kind = run_kind(meta, "<p>Too short to be a real post.</p>")
        check(f"     a thin {k} STILL warns", "Thin content" in w, w)
        p, w, f, n, kind = run_kind(meta, long_body + faq_vis + faq_schema("No, it costs a fee to meet."))
        check(f"     a {k} WITH a visible FAQ and a mismatched schema FAILS the mirror",
              "FAQ answer does not match its schema" in f, f)
        p, w, f, n, kind = run_kind(meta, long_body + faq_vis)
        check(f"     a {k} with a visible FAQ and NO schema is warned, not excused",
              "no FAQPage schema" in w and "not measured here" not in n, (w, n))
        p, w, f, n, kind = run_kind(meta, long_body + faq_vis + faq_schema("Yes, the first consultation with the firm is free of charge."))
        check(f"     a {k} with a matching FAQ passes the mirror", "byte-identical" in p and "FAQ" not in f, (p, f))
    p, w, f, n, kind = run_kind(kind_meta("posts"), long_body)
    check("     a misspelled blog kind gets no exemption", "no FAQPage schema" in w, w)
    p, w, f, n, kind = run_kind(kind_meta("contact"), long_body + faq_vis + faq_schema("No."))
    check("     and contact, too, is held to the mirror when it shows an FAQ",
          "FAQ answer does not match its schema" in f, f)
    p, w, f, n, kind = run_kind("", long_body + faq_vis + faq_schema("Yes, the first consultation with the firm is free of charge.", q="Is it free?"))
    check("     a question edited in one place only is caught as one difference",
          "question text differs" in f, f)

    # --- 24: empty headings --------------------------------------------------------
    print("24. Empty headings: a heading with no words is a critical")
    p, w, f = run("<h2>What happens next</h2><p>Words.</p>")
    check("     a page whose headings all carry words passes",
          "No empty headings: all 2 h1 to h6 carry words" in p and "Empty heading" not in f, (p, f))
    for label, body in (("an empty h2 closing the prose", "<p>Words.</p><h2></h2>"),
                        ("spaces and a line break", "<h3>  \n  </h3>"),
                        ("a no-break space", "<h2>&nbsp;</h2>"),
                        ("an empty strong, WordPress's other leftover", "<h2><strong> </strong></h2>"),
                        ("a comment and nothing else", "<h4><!-- a heading went here --></h4>"),
                        ("an empty link", '<h2><a href="../contact/"></a></h2>'),
                        ("the smallest heading", "<h6></h6>"),
                        ("an empty second H1 beside the real one", "<h1></h1>")):
        p, w, f = run(body)
        check(f"     caught: {label}", "Empty heading:" in f, f)
    p, w, f = run("<h2></h2><p>Words.</p><h3> </h3>")
    check("     two empty headings are both named, with their tags", "<h2> on line" in f and "<h3> on line" in f, f)
    for label, body in (("words inside a link", '<h2><a href="../contact/">Contact us</a></h2>'),
                        ("words beside an empty icon span", '<h3><span class="faq-ico"></span>Is it free?</h3>'),
                        ("a heading that is only a number", "<h3>01</h3>"),
                        ("an empty heading inside a script string", '<script>var t = "<h2></h2>";</script>')):
        p, w, f = run(body)
        check(f"     left alone: {label}", "Empty heading" not in f, f)

    # --- 25: location variance --------------------------------------------------------
    print("25. Location variance: no shared substantive H2, under 30% shared phrasing")
    check("     the ceiling is the doctrine's: under 30 percent, three-word phrases",
          audit.TOWN_SHARED_MAX == 0.30 and audit.TOWN_SHINGLE == 3, (audit.TOWN_SHARED_MAX, audit.TOWN_SHINGLE))

    def town(name, h2s, prose, pattern=""):
        secs = "".join(f"<section><h2>{h}</h2><p>{p_}</p></section>" for h, p_ in zip(h2s, prose))
        return (f'<html><head>{kind_meta("town")}</head><body>'
                f'<nav class="crumb"><ol><li>Home</li><li>{pattern}</li></ol></nav><main>'
                f'<section id="fx-band"><h2>Why clients call us</h2><p>{pattern}</p></section>{secs}'
                f'<a class="fx-card" href="#"><p>{pattern}</p></a>'
                f'</main></body></html>')

    def vary(pages):
        return audit.town_variance_findings({k: (h, (k,)) for k, h in pages.items()})
    a_text = ("The courthouse sits two blocks east of the square, and most clients park behind "
              "the bank on the corner before the morning traffic builds up on the bridge.")
    b_text = ("People coming in from the north side usually take the river road past the "
              "stadium and find the office just after the library on the left.")
    with patched(TOWN_PATTERN_SECTIONS=("fx-band",), TOWN_PATTERN_CLASSES=("fx-card",)):
        f = vary({"alpha": town("Alpha", ["Getting here from Alpha"], [a_text]),
                  "beta": town("Beta", ["Getting here from Beta"], [b_text])})
        check("     two genuinely different location pages pass both halves",
              not f["shared_h2"] and all(r < audit.TOWN_SHARED_MAX for _a, _b, r in f["pairs"]), f)

        def dense(n):
            return " ".join(f"{n} clients call first. {n} cases come in. We handle {n} claims. "
                            f"{n} consultations are free. {n} roads lead here." for _ in range(3))
        f = vary({"alpha": town("Alpha", ["For clients from Alpha"], [dense("Alpha")]),
                  "beta": town("Beta", ["For clients from Beta"], [dense("Beta")])})
        check("     caught: a copy with the place's name swapped, names masked",
              any(r >= audit.TOWN_SHARED_MAX for _a, _b, r in f["pairs"]), f)
        check("     and its H2s, which differ only by name, are not the H2 half's to catch", not f["shared_h2"])
        long_extra = " ".join(f"Paragraph {i} is about something else entirely, word {i} of many." for i in range(60))
        f = vary({"alpha": town("Alpha", ["From Alpha"], [a_text]),
                  "gamma": town("Gamma", ["From Gamma"], [a_text + " " + long_extra])})
        check("     caught: a short page contained in a long one (containment, not Jaccard)",
              any(r >= audit.TOWN_SHARED_MAX for _a, _b, r in f["pairs"]), f)
        f = vary({"alpha": town("Alpha", ["Getting to the office"], [a_text]),
                  "beta": town("Beta", ["Getting to the office"], [b_text])})
        check("     caught: a shared substantive H2, even with different prose",
              [h for _a, _b, h in f["shared_h2"]] == ["getting to the office"], f["shared_h2"])
        shared = " ".join(["Free consultation, no fee unless we win, offices in the valley."] * 12)
        f = vary({"alpha": town("Alpha", ["Getting here from Alpha"], [a_text], shared),
                  "beta": town("Beta", ["Getting here from Beta"], [b_text], shared)})
        check("     left alone: identical pattern text, and the pattern H2 it carries",
              not f["shared_h2"] and all(r < audit.TOWN_SHARED_MAX for _a, _b, r in f["pairs"]), f)
    f = vary({"alpha": town("Alpha", ["Getting here from Alpha"], [a_text], shared),
              "beta": town("Beta", ["Getting here from Beta"], [b_text], shared)})
    check("     MUTATION: with no pattern list, the same shared band IS counted",
          bool(f["shared_h2"]) or any(r >= audit.TOWN_SHARED_MAX for _a, _b, r in f["pairs"]), f)
    f = vary({"alpha": town("Alpha", ["", "From Alpha"], ["", a_text]),
              "beta": town("Beta", ["", "From Beta"], ["", b_text])})
    check("     left alone: an empty H2 on both is not a shared heading",
          not [h for _a, _b, h in f["shared_h2"] if h != "why clients call us"], f)
    with tempfile.TemporaryDirectory() as tmp:
        def put(rel, htm):
            os.makedirs(os.path.join(tmp, os.path.dirname(rel)), exist_ok=True)
            open(os.path.join(tmp, rel), "w", encoding="utf-8").write(htm)
        with patched(TOWN_HUB_PATH=os.path.join("areas", "index.html"),
                     TOWN_SLUG_RE=re.compile(r"^lawyer-(.+?)(?:-pa)?$"),
                     TOWN_PATTERN_SECTIONS=("fx-band",), TOWN_PATTERN_CLASSES=("fx-card",),
                     TOWN_PLACE_NAMES=("alpha", "beta")):
            put("lawyer-alpha-pa/index.html", town("Alpha", ["For clients from Alpha"], [dense("Alpha")]))
            tp, tw, tf, tn = [], [], [], []
            audit.check_town_variance_local(tp, tw, tf, tn, root=tmp)
            check("     one location page and no hub: nothing to compare, and a note that says so",
                  not tf and not tp and any("nothing to compare" in n for n in tn), (tf, tn))
            check("     the page's own place is read off its slug",
                  audit.own_town_names(os.path.join(tmp, "lawyer-alpha-pa", "index.html")) == ("alpha",))
            put("areas/index.html", town("Hub", ["Every place we serve"], [dense("Alpha")])
                .replace(kind_meta("town"), ""))
            tp, tw, tf, tn = [], [], [], []
            audit.check_town_variance_local(tp, tw, tf, tn, root=tmp)
            check("     caught: a location page that copies its hub, as a critical",
                  any("read as copies" in x and "areas" in x for x in tf), tf)
            put("lawyer-beta-pa/index.html", town("Beta", ["For clients from Alpha"], [b_text]))
            tp, tw, tf, tn = [], [], [], []
            audit.check_town_variance_local(tp, tw, tf, tn, root=tmp)
            check("     caught: a sibling reusing another's substantive H2, as a critical",
                  any("share a substantive H2" in x for x in tf), tf)
    tp, tw, tf, tn = [], [], [], []
    audit.check_town_variance_local(tp, tw, tf, tn)
    check("     the repo's own docs/ raises no variance critical", not tf, tf)

    # --- 27: crumb mirror ---------------------------------------------------------------
    print("27. The crumb mirror: the visible breadcrumb is the BreadcrumbList")

    def crumb(*labels, pending=None):
        items = []
        for i, x in enumerate(labels):
            if i == 0:
                items.append(f'<li><a href="../">{x}</a></li>')
            elif pending == i:
                items.append(f'<li><span data-pending-href="../hub/">{x}</span></li>')
            else:
                items.append(f"<li>{x}</li>")
        return '<nav class="crumb" aria-label="Breadcrumb"><ol>' + "".join(items) + "</ol></nav>"

    def crumb_schema(*labels, order=None, nested=False):
        els = []
        for i, x in enumerate(labels, 1):
            els.append({"@type": "ListItem", "position": i,
                        "item": {"@id": f"https://dklawllc.com/{i}/", "name": x}}
                       if nested else {"@type": "ListItem", "position": i, "name": x})
        if order:
            els = [els[k] for k in order]
        return ('<script type="application/ld+json">'
                + json.dumps({"@context": "https://schema.org",
                              "@graph": [{"@type": "BreadcrumbList", "itemListElement": els}]})
                + "</script>")
    three = ("Home", "Practice Areas", "Fixture Page")
    p, w, f, n, kind = run_kind("", crumb(*three, pending=1) + crumb_schema(*three))
    check("     a crumb that mirrors its schema passes, a pending span item included",
          "breadcrumb and the BreadcrumbList agree, 3 items" in p and "Breadcrumb" not in f, (p, f))
    p, w, f, n, kind = run_kind("", crumb(*three) + crumb_schema(*three, order=(2, 0, 1)))
    check("     the schema is read by position, not by array order", "BreadcrumbList agree" in p, (p, f))
    p, w, f, n, kind = run_kind("", crumb(*three) + crumb_schema(*three, nested=True))
    check("     a name carried on the item node is read too", "BreadcrumbList agree" in p, p)
    curly = ("Home", "Blog", "“What Do I Do After a Crash?” A Plain Guide")
    p, w, f, n, kind = run_kind("", crumb(*curly) + crumb_schema(*curly))
    check("     a long curly-quoted title mirrors byte for byte", "BreadcrumbList agree" in p, p)
    for label, page, schema, want in (
            ("a label edited on the page only", ("Home", "Practice Areas", "Fixture"), three, "label differs"),
            ("a label edited in the schema only", three, ("Home", "Our Work", "Fixture Page"), "label differs"),
            ("an item on the page, missing from the schema", three, ("Home", "Fixture Page"),
             "on the page but not in the BreadcrumbList"),
            ("an item in the schema, missing from the page", ("Home", "Fixture Page"), three,
             "in the BreadcrumbList but not on the page"),
            ("the same items in a different order", ("Home", "Fixture Page", "Practice Areas"), three, "order differs")):
        p, w, f, n, kind = run_kind("", crumb(*page) + crumb_schema(*schema))
        check(f"     caught as a critical: {label}", want in f and "BreadcrumbList agree" not in p, (p, f))
    p, w, f, n, kind = run_kind("", crumb(*three))
    check("     a visible crumb with no BreadcrumbList is a warning, not a critical",
          "visible breadcrumb with no BreadcrumbList" in w and "Breadcrumb" not in f, (w, f))
    p, w, f, n, kind = run_kind("", crumb_schema(*three))
    check("     a BreadcrumbList with no readable crumb is a note, never scored",
          "no visible breadcrumb this check can read" in n and "readcrumb" not in f + w, (n, f, w))
    p, w, f, n, kind = run_kind("", "<p>No trail here.</p>")
    check("     a page with neither says nothing about breadcrumbs", "readcrumb" not in p + w + f + n)

    # --- 29: the one-list fields ----------------------------------------------------
    print("29. The business node's one-list fields: each written and held only once it is set")
    sa = load_script("sync-area-served.py", "sync_area_served")

    def biz_page(node_extra, extra_nodes=()):
        g = {"@context": "https://schema.org", "@graph": [
            dict({"@type": "LegalService", "@id": "https://dklawllc.com/#business",
                  "name": "Fixture"}, **node_extra)] + list(extra_nodes)}
        return ('<script type="application/ld+json">\n'
                + "\n".join("  " + x for x in json.dumps(g, indent=2, ensure_ascii=False).splitlines())
                + "\n  </script>")
    page_off = biz_page({"email": "x@example.test"})
    check("     OFF: the sync changes nothing while every field is unset", sa.synced(page_off) == page_off)
    p, w, f, n, kind = run_kind("", page_off)
    check("     OFF: no served-list, profile or founding verdict on the page",
          not any(k in p + f for k in ("served list", "profile list", "foundingDate")), (p, f))
    check("     OFF: and no sameAs warning, a note naming the OFF check instead",
          "sameAs" not in w and "sameAs check is OFF" in n, (w, n))
    fx_area = (("AdministrativeArea", "Fixture County, Pennsylvania", "#area-fixture"),
               ("City", "Exampleton, Pennsylvania", "#area-fixture"))
    with patched(AREA_SERVED=fx_area):
        want = audit.area_served_nodes()
        p, w, f, n, kind = run_kind("", biz_page({"areaServed": want}))
        check("     ON: a business node carrying the list passes", "one served list" in p and "served list" not in f, (p, f))
        for label, area in (("a place dropped", want[:1]), ("the list in another order", list(reversed(want))),
                            ("a place not on the list", want + [{"@type": "City", "name": "Elsewhere, Pennsylvania"}])):
            p, w, f, n, kind = run_kind("", biz_page({"areaServed": area}))
            check(f"     ON: caught as a critical: {label}", "is not the served list" in f, f)
        service = {"@type": "Service", "name": "Fixture service",
                   "areaServed": [{"@type": "City", "name": "Exampleton, Pennsylvania"}]}
        out = sa.synced(biz_page({"areaServed": want[:1]}, [service]))
        got = json.loads(re.search(r'(?s)<script type="application/ld\+json">(.*?)</script>', out).group(1))["@graph"]
        check("     ON: the sync writes the list into the business node", got[0]["areaServed"] == want)
        check("     and leaves a Service node's own areaServed alone", got[1]["areaServed"] == service["areaServed"])
        check("     a synced page is a fixed point", sa.synced(out) == out)
    fx_same = ("https://maps.example.test/fixture", "https://social.example.test/fixture")
    with patched(SAME_AS=fx_same, GBP_MAP_URL=fx_same[0]):
        home = sa.synced(biz_page({"email": "x@example.test", "hasMap": fx_same[0]}))
        check("     ON: sameAs is written directly after hasMap",
              re.search(r'"hasMap": "[^"]+",\n\s*"sameAs": \[', home) is not None, home)
        p, w, f, n, kind = run_kind("", home)
        check("     ON: the page passes the profile list", "SAME_AS" in p and "profile list" not in f, (p, f))

        def mutate(fn):
            def one(m):
                data = json.loads(m.group(2))
                fn(data["@graph"][0])
                return m.group(1) + sa.reserialise(m.group(2), data) + m.group(3)
            return sa.BLOCK_RE.sub(one, home, count=1)
        for label, fn, repairs in (("a profile dropped", lambda n_: n_.__setitem__("sameAs", n_["sameAs"][:1]), True),
                                   ("the order changed", lambda n_: n_.__setitem__("sameAs", n_["sameAs"][::-1]), True),
                                   ("hasMap moved off the profile's URL", lambda n_: n_.__setitem__("hasMap", "https://x.test/"), False),
                                   ("no sameAs at all", lambda n_: n_.pop("sameAs"), True)):
            mutant = mutate(fn)
            p, w, f, n, kind = run_kind("", mutant)
            check(f"     ON: caught as a critical: {label}", mutant != home and "profile list" in f, f)
            if repairs:
                check(f"     and the sync repairs it: {label}", sa.synced(mutant) == home)
    with patched(FOUNDING_DATE="1950", FOUNDING_YEAR=1950):
        home = sa.synced(biz_page({"email": "x@example.test"}))
        check("     ON: foundingDate is written directly after email",
              re.search(r'"email": "[^"]+",\n\s*"foundingDate": "1950"', home) is not None, home)
        p, w, f, n, kind = run_kind("", home)
        check("     ON: and it passes as FOUNDING_DATE", "FOUNDING_DATE" in p, (p, f))
        p, w, f, n, kind = run_kind("", home.replace('"1950"', '"1950-01-01"'))
        check("     ON: a full date the firm did not confirm is a critical", "foundingDate" in f, f)
    r = subprocess.run([sys.executable, os.path.join(HERE, "sync-area-served.py"), "--check"],
                       capture_output=True, text=True)
    check("     sync-area-served.py --check exits 0 on the repo", r.returncode == 0, r.stdout[-300:])

    # --- 33: chrome -------------------------------------------------------------------
    print("33. The site chrome: identical but for the marking, every link real, stubs bare")
    sc = load_script("sync-chrome.py", "sync_chrome")
    check("     the chrome is NOT specified yet: render() refuses rather than guessing",
          sc.CHROME_SPECIFIED is False)
    try:
        sc.render("")
        refused = False
    except SystemExit as e:
        refused = "not specified" in str(e)
    check("     and the refusal names pagemap.md as the reason", refused)

    def fx_render(page):
        """A FIXTURE chrome, for the identity and resolution checks only."""
        p_ = "" if page == "" else "../"

        def link(target, label):
            here = target == page
            return (f'<a href="{"./" if here else p_ + target}"'
                    f'{" aria-current=\"page\"" if here else ""}>{label}</a>')
        head = (f'<!-- CHROME:HEAD -->\n  <header class="nav"><nav>{link("", "Home")} '
                f'{link("about/", "About")} {link("contact/", "Contact")}</nav></header>')
        foot = f'<footer class="site">{link("contact/", "Contact")}</footer>'
        return head, foot

    def pg(page, head=None, foot=None):
        h, f_ = fx_render(page)
        return (f"<html><head>\n  <meta name=\"viewport\" content=\"x\">\n</head><body>\n"
                f"  {head if head is not None else h}\n<main><h1>x</h1></main>\n  "
                f"{foot if foot is not None else f_}\n</body></html>")
    stub = '<html><head><meta http-equiv="refresh" content="0; url=../about/"></head><body><p>Moved.</p></body></html>'

    def site(**over):
        s = {"index.html": pg(""), "about/index.html": pg("about/"), "contact/index.html": pg("contact/"),
             "old-page/index.html": stub}
        s.update(over)
        return s

    def bad(found):
        return [k for k in ("missing", "differs", "marking", "links", "stub_chrome") if found[k]]
    f0 = audit.chrome_findings(site())
    check("     identical chrome on every page, each marked as itself, passes", bad(f0) == [] and f0["forms"] == 1, f0)
    h, _f = fx_render("about/")
    for label, over, want in (
            ("a page whose nav label drifts", {"about/index.html": pg("about/", head=h.replace(">Contact<", ">Reach us<"))}, "differs"),
            ("a page with no chrome", {"about/index.html": "<html><body><main>x</main></body></html>"}, "missing"),
            ("a link to itself without aria-current", {"about/index.html": pg("about/", head=h.replace(' aria-current="page"', ""))}, "marking"),
            ("aria-current on a link that lands elsewhere",
             {"about/index.html": pg("about/", head=h.replace('href="../contact/"', 'href="../contact/" aria-current="page"'))}, "marking"),
            ("a link to a page that does not exist", {"about/index.html": pg("about/", head=h.replace("../contact/", "../contact-us/"))}, "links"),
            ("a link to a redirect stub", {"about/index.html": pg("about/", head=h.replace("../contact/", "../old-page/"))}, "links"),
            ("an unrecorded external URL", {"about/index.html": pg("about/", head=h.replace("../contact/", "https://example.test/"))}, "links"),
            ("a redirect stub wearing chrome", {"old-page/index.html": stub.replace("<body>", "<body>" + h)}, "stub_chrome")):
        fx = audit.chrome_findings(site(**over))
        check(f"     caught: {label}", bool(fx[want]), {k: fx[k] for k in bad(fx)})
    r = subprocess.run([sys.executable, os.path.join(HERE, "sync-chrome.py"), "--check"], capture_output=True, text=True)
    check("     sync-chrome.py --check exits 0 on the repo", r.returncode == 0, r.stdout[-300:])

    # --- 35-37: service enumerations ---------------------------------------------------
    print("35. Every service enumeration carries the whole family in SERVICES (fixture family)")
    n, probs = audit.service_enumeration_findings("<main><p>Four services, one firm.</p></main>", "")
    check("     OFF: with SERVICES empty, nothing is read as an enumeration", (n, probs) == (0, []), (n, probs))
    fx_services = (("alpha-service/", "Alpha Service", "The first fixture line."),
                   ("beta-service/", "Beta Service", "The second fixture line."),
                   ("gamma-service/", "Gamma Service", "The third fixture line."))
    fx_text = {"alpha-service/": re.compile(r"\balpha\b", re.I), "beta-service/": re.compile(r"\bbeta\b", re.I),
               "gamma-service/": re.compile(r"\bgamma\b", re.I)}

    def card(path, label, line, rel=""):
        return f'<a class="svc-card" href="{rel}{path}"><h3>{label}</h3><p>{line}</p></a>'
    with patched(SERVICES=fx_services, SERVICE_PATHS=tuple(p_ for p_, *_ in fx_services), SERVICE_TEXT_RE=fx_text):
        grid = "<main><div class='grid'>" + "".join(card(*r) for r in fx_services) + "</div></main>"
        n, probs = audit.service_enumeration_findings(grid, "")
        check("     a grid carrying the whole family passes", probs == [] and n == 1, (n, probs))
        n, probs = audit.service_enumeration_findings(grid.replace(card(*fx_services[2]), ""), "")
        check("     a grid with one card dropped fails", any("lack Gamma Service" in x for x in probs), probs)
        n, probs = audit.service_enumeration_findings(grid.replace("The second fixture line.", "A drifted line."), "")
        check("     a card whose line drifts from its row fails", any("A drifted line." in x for x in probs), probs)
        n, probs = audit.service_enumeration_findings("<main><p>Two services, one firm.</p></main>", "")
        check("     a count typed as two fails", any("counts 2 services" in x for x in probs), probs)
        n, probs = audit.service_enumeration_findings("<main><p>Three services, one firm.</p></main>", "")
        check("     a count typed as three passes", probs == [] and n == 1, (n, probs))
        n, probs = audit.service_enumeration_findings("<main><p>We do alpha work and beta work.</p></main>", "")
        check("     a sentence naming all but one of the family fails", any("not Gamma Service" in x for x in probs), probs)
        n, probs = audit.service_enumeration_findings("<main><p>We do alpha work.</p></main>", "")
        check("     one service named alone is a mention, not an enumeration", (n, probs) == (0, []), (n, probs))
        rel = ("<main><section id='related'><div>" + card(*fx_services[0], rel="../")
               + card(*fx_services[2], rel="../") + "</div></section></main>")
        n, probs = audit.service_enumeration_findings(rel, "beta-service/")
        check("     a service page's grid is the family minus itself", probs == [], probs)
        selfgrid = rel.replace("</div></section>", card("./", "Beta Service", "The second fixture line.") + "</div></section>")
        n, probs = audit.service_enumeration_findings(selfgrid.replace('href="./"', 'href="./"'), "beta-service/")
        check("     the page appearing in its own grid fails", any("the page they sit on" in x for x in probs), probs)
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "llms.txt"), "w").write("The site covers three\n  services.\n")
            ps, fs = [], []
            audit.check_service_count_llms_local(ps, fs, tmp)
            check("     llms.txt counting the family passes, across a line wrap", fs == [] and len(ps) == 1, (ps, fs))
            open(os.path.join(tmp, "llms.txt"), "w").write("The site covers four services.\n")
            ps, fs = [], []
            audit.check_service_count_llms_local(ps, fs, tmp)
            check("     llms.txt with the count typed as four fails", len(fs) == 1, (ps, fs))

            print("37. Every photographed service card carries its page's own preview image (og:image)")
            os.makedirs(os.path.join(tmp, "alpha-service"))
            open(os.path.join(tmp, "alpha-service", "index.html"), "w").write(
                '<meta property="og:image" content="https://dklawllc.com/assets/img/alpha.jpg">'
                '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
                '<meta property="og:image:alt" content="The alpha fixture.">')
            good_card = ('<main><a class="svc-card" href="alpha-service/"><img src="assets/img/alpha.jpg" '
                         'alt="The alpha fixture." width="1200" height="630"></a></main>')
            n, probs = audit.card_image_findings(good_card, "", tmp)
            check("     a card wearing its page's preview passes", n == 1 and probs == [], (n, probs))
            for label, mutant, word in (("another image", good_card.replace("alpha.jpg", "beta.jpg"), "has image"),
                                        ("a drifted alt", good_card.replace('alt="The alpha fixture."', 'alt="Alpha."'), "has alt"),
                                        ("a drifted size", good_card.replace('width="1200"', 'width="1000"'), "has width")):
                n, probs = audit.card_image_findings(mutant, "", tmp)
                check(f"     caught: {label}", any(word in x for x in probs), probs)
    sc_cards = load_script("sync-service-cards.py", "sync_service_cards")
    check("     sync-service-cards.py writes nothing while the table is empty", sc_cards.ROW == {})
    r = subprocess.run([sys.executable, os.path.join(HERE, "sync-service-cards.py"), "--check"], capture_output=True, text=True)
    check("     sync-service-cards.py --check exits 0 on the repo", r.returncode == 0, r.stdout[-300:])
    check("     sync-chrome.py's SERVICES IS audit.SERVICES, not a copy", sc.SERVICES is audit.SERVICES)

    # --- 40: the staging flip ---------------------------------------------------------
    print("40. The staging flip, both directions: banner, noindex, robots.txt, llms.txt")
    real_render = sc.render
    sc.render = fx_render
    home_path = os.path.join(sc.DOCS, "index.html")
    stub_path = os.path.join(sc.DOCS, "old-page", "index.html")
    base = pg("")
    try:
        with patched(STAGING=True):
            home_now = sc.synced(home_path, base)
            stub_now = sc.staged(stub_path, '<html><head>\n  <meta name="viewport" content="x">\n'
                                 '  <meta http-equiv="refresh" content="0; url=../about/"></head><body></body></html>')
            p_, w_, f_ = audit.staging_page_findings(home_now)
            check("     staging: a page as synced carries its banner", p_ and not w_ and not f_, (w_, f_))
            check("     staging: and its noindex", "\n  " + audit.STAGING_ROBOTS_META in home_now)
            p_, w_, f_ = audit.staging_page_findings(home_now.replace('<p class="staging">', "<p>"))
            check("     staging: a page MISSING the banner warns", len(w_) == 1 and not f_, (w_, f_))
        with patched(STAGING=False):
            p_, w_, f_ = audit.staging_page_findings(home_now)
            check("     live: a banner left on a page is a CRITICAL", len(f_) == 1, f_)
            p_, w_, f_ = audit.staging_page_findings(stub_now, is_stub=True)
            check("     live: a noindex left on a redirect stub is a CRITICAL", len(f_) == 1, f_)
            flipped = sc.synced(home_path, home_now)
            p_, w_, f_ = audit.staging_page_findings(flipped)
            check("     live: sync-chrome takes the banner off", not f_ and 'class="staging"' not in flipped, f_)
            check("     live: sync-chrome takes the noindex off", "\n  " + audit.STAGING_ROBOTS_META not in flipped)
            check("     live: the stub loses its noindex too",
                  "\n  " + audit.STAGING_ROBOTS_META not in sc.staged(stub_path, stub_now))
        with patched(STAGING=True):
            back = sc.synced(home_path, flipped)
            check("     and back: staging puts the banner and the noindex back",
                  back.count("\n  " + audit.STAGING_ROBOTS_META) == 1 and 'class="staging"' in back)
            check("     and the sync is idempotent", sc.synced(home_path, back) == back)
    finally:
        sc.render = real_render
    smap = f"Sitemap: {audit.SITE_BASE}sitemap.xml"
    for staging, robots, llms, want in (
            (True, "User-agent: *\nDisallow: /\n", "THIS SITE IS NOT LIVE YET.\n", "clean"),
            (True, "User-agent: *\nDisallow: /\n", "The firm.\n", "warn"),
            (False, "User-agent: *\nDisallow: /\n", "The firm.\n", "fail"),
            (False, f"User-agent: *\nAllow: /\n{smap}\n", "THIS SITE IS NOT LIVE YET. Staging.\n", "fail"),
            (False, f"User-agent: *\nAllow: /\n{smap}\n", "The firm, live.\n", "clean"),
            (False, "User-agent: *\nAllow: /\n", "The firm, live.\n", "warn")):
        with patched(STAGING=staging), tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "robots.txt"), "w").write(robots)
            open(os.path.join(tmp, "llms.txt"), "w").write(llms)
            passes, warns, notes, fails = [], [], [], []
            audit.check_staging_local(passes, warns, notes, fails, root=tmp)
        got = "fail" if fails else ("warn" if warns else "clean")
        check(f"     {'staging' if staging else 'live'}: robots {robots.split(chr(10))[1]!r}, "
              f"llms {llms[:24]!r} is {want}", got == want, (warns, fails))

    # --- 41 ---------------------------------------------------------------------------
    print("41. Every real page links the firm's favicon set, and the files exist")
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "assets", "img"))
        for _rel, _a, path in audit.ICON_LINKS:
            open(os.path.join(tmp, path), "wb").write(b"x")
        head = "".join(f'<link rel="{r_}"' + (f" {a_}" if a_ else "") + f' href="{{P}}{p_}">'
                       for r_, a_, p_ in audit.ICON_LINKS)
        pv, fv = audit.icon_findings(f"<head>{head.replace('{P}', '')}</head>", "", site_dir=tmp)
        check("     a top-level page linking all three passes", pv and not fv, fv)
        pv, fv = audit.icon_findings(f"<head>{head.replace('{P}', '../')}</head>", "about/", site_dir=tmp)
        check("     a page one level down links them one level up", pv and not fv, fv)
        pv, fv = audit.icon_findings(f"<head>{head.replace('{P}', '').replace('apple-touch-icon', 'x')}</head>", "", site_dir=tmp)
        check("     a page missing one FAILS", len(fv) == 1 and "apple-touch-icon" in fv[0], fv)
    with tempfile.TemporaryDirectory() as tmp:
        pv, fv = audit.icon_findings(f"<head>{head.replace('{P}', '')}</head>", "", site_dir=tmp)
    check("     a link to a file that is not there FAILS", len(fv) == 1 and "the file" in fv[0], fv)

    # --- 42 ---------------------------------------------------------------------------
    print("42. FAQ answers open on a sentence that stands alone")
    OPENERS = [
        ("No. The first consultation is free", "No, the first consultation with the firm is free"),
        ("Yes. Pennsylvania law sets a deadline", "Yes, Pennsylvania law sets a deadline"),
        ("It can. Most cases settle", "A case can take longer than a year to resolve. Most cases settle"),
        ("They do. Every attorney", "Yes, every attorney at the firm"),
        ("This page explains the deadline.", "The deadline to file depends on the kind of claim."),
        ("Nearly. A few cases go to trial", "Almost every case settles before trial. A few cases go to trial"),
        ("Longer than you think.", "Medical records often take several weeks to arrive."),
        ("A little.", "The fee is a share of what the case recovers, agreed in writing first."),
    ]
    rest = " The rest of the answer follows here."
    befores = [("Q?", b + rest) for b, _a in OPENERS]
    afters = [("Q?", a + rest) for _b, a in OPENERS]
    got = audit.faq_opener_findings(befores)
    check(f"     all {len(OPENERS)} weak openers FAIL", len(got) == len(OPENERS),
          [x[1] for x in befores if x[1] not in [g[1] for g in got]][:3])
    check(f"     all {len(OPENERS)} rewrites PASS", audit.faq_opener_findings(afters) == [], audit.faq_opener_findings(afters)[:3])
    with patched(FAQ_OPENER_MIN_WORDS=0, FAQ_OPENER_PRONOUN_RE=re.compile(r"(?!x)x"),
                 FAQ_OPENER_FRAGMENT_RE=re.compile(r"(?!x)x")):
        check("     MUTATION: with the rule switched off every weak opener passes", audit.faq_opener_findings(befores) == [])
    faq = ('<details><summary>Does a consultation cost anything?</summary><p>No. Consultations are free.</p></details>'
           '<script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage",'
           '"mainEntity":[{"@type":"Question","name":"Does a consultation cost anything?",'
           '"acceptedAnswer":{"@type":"Answer","text":"No. Consultations are free."}}]}</script>')
    _p, _w, f = run(faq)
    check("     a page whose FAQ opens \"No.\" FAILS the audit", "does not stand alone" in f, f[:200])
    _p, _w, f = run(faq.replace("No. Consultations are free.", "No, consultations with the firm are always free."))
    check("     the same page comma-merged passes", "does not stand alone" not in f, f[:200])

    # --- 43 ---------------------------------------------------------------------------
    print("43. The business name is NAP_NAME, character for character (fixture name)")
    with facts_on():
        for label, body in (("the name without its comma", "<p>Example & Sample LLC can help.</p>"),
                            ("\"and\" for the ampersand", "<p>Example and Sample, LLC can help.</p>"),
                            ("the name with LLC dropped", "<p>Example & Sample can help.</p>"),
                            ("the short brand", "<p>Call E&amp;S today.</p>"),
                            ("an og:title", '<meta property="og:title" content="Injury Law | Example and Sample">'),
                            ("an image's alt", '<img src="assets/img/x.jpg" alt="The Example Sample office">'),
                            ("a JSON-LD name", '<script type="application/ld+json">{"name": "Example and Sample"}</script>'),
                            ("upper case", "<p>EXAMPLE & SAMPLE LLC</p>")):
            _p, _w, f = run(body)
            check(f"     FAILS: {label}", "business name is written" in f, f[:160])
        for label, body in (("the name itself, and its possessive", "<p>Example &amp; Sample, LLC and Example &amp; Sample, LLC's team.</p>"),
                            ("the logo's alt naming the wordmark as drawn", '<img src="../logo.png" alt="E&amp;S" width="10" height="10">'),
                            ("a client's words in a testimonial", '<figure class="quote"><p>Example and Sample helped me.</p></figure>'),
                            ("a slug in a URL", '<a href="../example-and-sample-history/">Read</a>'),
                            ("a comment recording an old name", "<!-- the name was Example and Sample -->")):
            _p, _w, f = run(body)
            check(f"     passes: {label}", "business name is written" not in f, f[:160])
        with tempfile.TemporaryDirectory() as tmp:
            for text, want in ((f"{FX_NAME}, {FX_STREET}.\n", "pass"), ("Example and Sample, 100 Example St.\n", "fail")):
                open(os.path.join(tmp, "llms.txt"), "w").write(text)
                passes, fails = [], []
                audit.check_name_llms_local(passes, fails, root=tmp)
                check(f"     llms.txt saying {text[:26]!r} is a {want}", bool(fails) == (want == "fail"), fails)
        with patched(NAME_MENTION_RE=re.compile(r"(?!x)x")):
            _p, _w, f = run("<p>Example and Sample can help.</p>")
            check("     MUTATION: with no name pattern the variant passes, so the pattern is what catches it",
                  "business name is written" not in f)
    check("     OFF: no name variant is read while the name is unconfirmed",
          audit.name_variants("<p>Example and Sample</p>") == [] and audit.name_mentions("x") == 0)

    # --- 44 ---------------------------------------------------------------------------
    print("44. The privacy kind and its date, the 404's staging, the redirect table")
    priv_meta = kind_meta("privacy")
    p, w, f, n, kind = run_kind(priv_meta, "<p>Short.</p>")
    check("     a privacy page draws no FAQPage warning, and says so in a note",
          "no FAQPage schema" not in w and "No FAQPage schema, not measured" in n, (w, n))
    check("     but thin content is still measured on it", "Thin content" in w, w)
    priv = PAGE.replace("</head>", priv_meta + "</head>").format(
        body='<p>Updated <time datetime="2026-10-14">October 14, 2026</time></p>'
             '<script type="application/ld+json">{"@type":"WebPage","dateModified":"2026-10-14"}</script>')
    pp, pf = audit.privacy_date_findings(priv)
    check("     a policy whose visible date is its dateModified passes", pp and not pf, pf)
    for label, mutant in (("a schema date that moved alone", priv.replace('"dateModified":"2026-10-14"', '"dateModified":"2026-09-30"')),
                          ("a visible date that moved alone", priv.replace('datetime="2026-10-14"', 'datetime="2026-09-30"')),
                          ("words that name another day", priv.replace(">October 14, 2026<", ">September 30, 2026<")),
                          ("no visible date", re.sub(r"<p>Updated <time[^>]*>[^<]*</time></p>", "", priv)),
                          ("two visible dates", priv.replace("</main>", '<p>Updated <time datetime="2026-09-30">September 30, 2026</time></p></main>'))):
        pp, pf = audit.privacy_date_findings(mutant)
        check(f"     caught: {label}", mutant != priv and bool(pf) and not pp, (pp, pf))
    err_base = ('<!DOCTYPE html><html lang="en"><head>\n  <meta charset="UTF-8">\n'
                '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                f'  {kind_meta("error-404")}\n  <title>Page not found</title>\n'
                '  <meta name="description" content="That page is not here.">\n</head>\n<body>\n'
                '<main><h1>Page not found</h1><p><a href="/">Home</a></p></main>\n</body></html>')
    err_path = os.path.join(sc.DOCS, "404.html")
    for staging in (True, False):
        with patched(STAGING=staging):
            err_now = sc.error_page(err_path, err_base)
            audit.load = lambda _s, _h=err_now: _h
            with tempfile.TemporaryDirectory() as tmp:
                with patched(SITE_DIR=tmp):
                    passes, warns, fails, notes, kind = audit.audit(os.path.join(tmp, "404.html"), coverage=None)
            check(f"     STAGING={staging}: the 404 as synced scores clean on the error rubric",
                  kind == "error-404" and not fails and not warns, (warns, fails))
            check(f"     STAGING={staging}: the banner and the noindex are {'on' if staging else 'off'}",
                  ('<p class="staging">' in err_now) == staging and (audit.STAGING_ROBOTS_META in err_now) == staging)
            check(f"     STAGING={staging}: the sync is idempotent", sc.error_page(err_path, err_now) == err_now)
            check(f"     STAGING={staging}: the 404's favicon links are root-relative",
                  '<link rel="icon" sizes="any" href="/favicon.ico">' in err_now)
    check("     the redirect table is empty, and so is docs/ of stubs", audit.redirect_table_findings(docs) == [],
          audit.redirect_table_findings(docs))
    with tempfile.TemporaryDirectory() as tmp:
        def stub_at(rel, target):
            os.makedirs(os.path.join(tmp, rel), exist_ok=True)
            open(os.path.join(tmp, rel, "index.html"), "w").write(
                f'<meta http-equiv="refresh" content="0; url=../{target}">'
                f'<link rel="canonical" href="{audit.SITE_BASE}{target}">')
        os.makedirs(os.path.join(tmp, "new-page"))
        open(os.path.join(tmp, "new-page", "index.html"), "w").write("<h1>x</h1>")
        stub_at("old-page", "new-page/")
        check("     caught: a stub the empty table does not list",
              any("/old-page/" in x and "does not list" in x for x in audit.redirect_table_findings(tmp)))
        with patched(REDIRECTS={"old-page/": "new-page/", "gone-page/": "new-page/"}, HONEST_404S=("thanks/",)):
            found = audit.redirect_table_findings(tmp)
            check("     caught: a planned redirect with no stub", any("/gone-page/" in x and "no stub" in x for x in found), found)
            stub_at("gone-page", "")
            found = audit.redirect_table_findings(tmp)
            check("     caught: a stub pointing somewhere the map does not say",
                  any("/gone-page/'s stub points at" in x for x in found), found)
            stub_at("gone-page", "new-page/")
            check("     and the table and docs/ agreeing is clean", audit.redirect_table_findings(tmp) == [])
            os.makedirs(os.path.join(tmp, "thanks"))
            check("     caught: something standing at an honest 404",
                  any("/thanks/" in x for x in audit.redirect_table_findings(tmp)))

    # --- 46 ---------------------------------------------------------------------------
    print("46. The founding year, held to FOUNDING_DATE and never fused with a place (fixture year)")
    fx_place = re.compile(r"(?i)\b(?:Exampleton|Pennsylvania|PA|here|location|address|"
                          r"building|street|corner|office)\b")
    with patched(FOUNDING_DATE="1950", FOUNDING_YEAR=1950, FOUNDING_PLACE_RE=fx_place):
        for text, want_n, want_bad in (
                ("<p>The firm, founded in 1950, represents injured people.</p>", 1, False),
                ('<div class="stat"><span class="stat-n">1950</span><span class="stat-l">Founded</span></div>', 1, False),
                ("<p>Founded in Exampleton in 1950.</p>", 1, True),
                ("<p>In this office since 1950.</p>", 1, True),
                ("<p>founded in 1950, here in the valley.</p>", 1, True),
                ("<p>Founded in 1949.</p>", 0, True),
                ("<p>Serving clients since 1985.</p>", 0, True),
                ("<!-- founded here in 1950 --><p>Published June 6, 2025</p>", 0, False)):
            n, probs = audit.founding_findings(text)
            label = re.sub("<[^>]+>", " ", text).strip()[:60]
            check(f"     {label!r}: {'caught' if want_bad else 'clean'}",
                  n == want_n and bool(probs) == want_bad, (n, probs))
        n, probs = audit.founding_findings("> The firm.\n> Founded in 1950.\n", is_html=False)
        check("     llms.txt grammar: a separate sentence is clean", n == 1 and not probs, probs)

    # --- 47: the [CONFIRM] law ------------------------------------------------------
    print("47. The [CONFIRM] law: a note while staging, a critical once STAGING is off")
    marked = "<p>The firm has offices in two counties.<!-- [CONFIRM] two counties: partner to initial --></p>"
    with patched(STAGING=True):
        audit.load = lambda _s, _h=PAGE.format(body=marked): _h
        ps, ws, fs, ns, _k = audit.audit("fabricated.html", coverage=None)
        check("     staging: a [CONFIRM] is listed in a note, with its line", any("[CONFIRM] marker" in x and "line" in x for x in ns), ns)
        check("     staging: and it is not scored", not any("CONFIRM" in x for x in ws + fs), (ws, fs))
    with patched(STAGING=False):
        ps, ws, fs, ns, _k = audit.audit("fabricated.html", coverage=None)
        check("     live: the same marker is a CRITICAL", any("[CONFIRM] marker" in x for x in fs), fs)
        audit.load = lambda _s, _h=PAGE.format(body="<p>No markers here.</p>"): _h
        ps, ws, fs, ns, _k = audit.audit("fabricated.html", coverage=None)
        check("     live: a page with no marker draws nothing about it", not any("CONFIRM" in x for x in ps + ws + fs + ns))
    check("     a marker with a note inside the brackets is read too",
          len(audit.confirm_findings("<!-- [CONFIRM: years in practice] -->")) == 1)
    check("     the word confirm in prose is not a marker", audit.confirm_findings("<p>Please confirm by phone.</p>") == [])
    audit.load = lambda _s, _h=PAGE.format(body=marked): _h
    with patched(STAGING=False):
        ps, ws, fs, ns, _k = audit.audit("https://dklawllc.com/fixture/", coverage=None)
    check("     a live-URL run (the WordPress site) is not read for markers", not any("CONFIRM" in x for x in fs + ns))

    print("     the staging inversion is for this build's files, never the live site")
    live_page = PAGE.format(body="<p>An indexable live page.</p>")
    audit.load = lambda _s, _h=live_page: _h
    with patched(STAGING=True):
        ps, ws, fs, ns, _k = audit.audit("https://dklawllc.com/fixture/", coverage=None)
        check("     a live page with no noindex is NOT a staging critical", not any("NOT noindexed" in x for x in fs), fs)
        ps, ws, fs, ns, _k = audit.audit("fabricated.html", coverage=None)
        check("     while a local page with no noindex IS one", any("NOT noindexed" in x for x in fs), fs)
        noidx = PAGE.replace("</head>", audit.STAGING_ROBOTS_META + "</head>").format(body="<p>x</p>")
        audit.load = lambda _s, _h=noidx: _h
        ps, ws, fs, ns, _k = audit.audit("https://dklawllc.com/fixture/", coverage=None)
        check("     and a live page that IS noindexed is the critical it always was", any("NOINDEX" in x for x in fs), fs)

    # --- 48: the business type --------------------------------------------------------
    print("48. The business node is a LegalService")
    p, w, f = run(biz())
    check("     a LegalService node passes", "is a `LegalService`" in p, (p, f))
    p, w, f = run(biz(t=["LegalService", "LocalBusiness"]))
    check("     a typed list including LegalService passes", "is a `LegalService`" in p, (p, f))
    p, w, f = run(biz(t="AutoBodyShop"))
    check("     another business type FAILS", "No business node is a `LegalService`" in f, f)
    p, w, f = run(biz(t="https://schema.org/LegalService"))
    check("     the full-URL spelling of the type passes", "is a `LegalService`" in p, (p, f))

    # --- 49: the run, end to end -----------------------------------------------------
    print("49. A full run: the report is DKY's, says what is OFF, and --strict means it")
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "docs"))
        r = subprocess.run([sys.executable, os.path.join(HERE, "audit.py")], cwd=tmp, capture_output=True, text=True)
        check("     an empty docs/ is not reported as a clean site: it exits 1 and says why",
              r.returncode == 1 and "No HTML pages found" in r.stderr, (r.returncode, r.stderr[-200:]))
        open(os.path.join(tmp, "docs", "index.html"), "w").write(PAGE.format(body=marked))
        r = subprocess.run([sys.executable, os.path.join(HERE, "audit.py")], cwd=tmp, capture_output=True, text=True)
        report = open(os.path.join(tmp, "audit-report.md"), encoding="utf-8").read()
        check("     the report is titled as DKY's", report.startswith("# DKY (Distasio, Kowalski & Yelen, LLC)"), report[:80])
        check("     it names its target", "Target: docs/ (local build)" in report, report[:200])
        check("     and its Site-wide notes say which checks are OFF",
              "These checks are OFF until the firm confirms" in report and "sameAs" in report)
        r = subprocess.run([sys.executable, os.path.join(HERE, "audit.py"), "--strict"], cwd=tmp, capture_output=True, text=True)
        check("     --strict exits 1 on a page under 100", r.returncode == 1, r.returncode)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for x in FAILURES:
            print(f"  - {x}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
