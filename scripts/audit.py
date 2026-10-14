#!/usr/bin/env python3
"""
SEO + AEO Site Auditor: the "scanning" half of your agent team.

This is a real, working audit script. It checks a page for the on-page
factors that matter most for local businesses, both classic SEO
(ranking in Google) and AEO / answer engine optimization (being the
answer that AI assistants like ChatGPT, Claude, Perplexity, and
Google's AI Overviews give when someone asks "best spa near me").
It then writes a markdown report. In the GitHub workflow, an AI agent
(Claude) reads this report, explains it in plain English, and files it
as a GitHub Issue with recommended fixes.

The site is no longer one page, so this audits EVERY page and scores
each one separately. A single page dragging the site down is visible by
name in the summary table instead of being averaged away.

Usage:
    python3 scripts/audit.py                           # every page under docs/
    python3 scripts/audit.py docs/index.html           # one local file
    python3 scripts/audit.py docs/services/seo/        # a folder
    python3 scripts/audit.py https://example.com/      # a live site, expanded
                                                       # via its sitemap.xml
    python3 scripts/audit.py --strict                  # exit 1 if any page < 100

No external packages needed: pure Python standard library.
"""

import argparse
import glob
import hashlib
import json
import math
import os
import posixpath
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

# The live site's page list comes from its own sitemap. Locally we glob
# the folder that IS the live site.
SITE_DIR = "docs"
SITEMAP_PATH = os.path.join(SITE_DIR, "sitemap.xml")
LLMS_PATH = os.path.join(SITE_DIR, "llms.txt")

# --- The client ----------------------------------------------------------
# Distasio, Kowalski & Yelen, LLC, a personal injury and medical
# malpractice law firm with a general practice side, in Wilkes-Barre, PA.
# The firm brands as DKY. The site is https://dklawllc.com/; dky.law carries
# the firm's email and redirects to the site.
#
# CLIENT_LABEL IS A WORKING LABEL, NOT THE NAME OF RECORD. It is the name as
# Corcoran's engagement brief gives it, used to title reports so a reader
# knows whose report they hold. The NAME OF RECORD is NAP_NAME below, and it
# is OFF: the firm has not yet confirmed its own name spelling. Nothing here
# may be copied into a page as the firm's name.
CLIENT_LABEL = "Distasio, Kowalski & Yelen, LLC"
CLIENT_BRAND = "DKY"
SITE_BASE = "https://dklawllc.com/"
SITE_DOMAIN = "dklawllc.com"

# The schema.org type of the firm's business node. LegalService, a
# LocalBusiness subtype. Attorney nodes come later and are a separate
# decision; when they land, re-read geo_findings, which holds EVERY
# LocalBusiness-type node to the firm's pin.
SCHEMA_BUSINESS_TYPE = "LegalService"

# The page-kind declaration a page carries in its head:
#   <meta name="dky-page" content="contact">
# See SPECIAL_KINDS and RUBRIC_EXEMPTIONS below for what a kind does.
PAGE_KIND_META = "dky-page"

# --- THE FIRM'S FACTS: OFF UNTIL THE FIRM CONFIRMS THEM -------------------
# NAP, HOURS, GEO, EMAIL, REVIEW COUNT AND sameAs CHECKS ARE OFF.
#
# Every constant in the blocks below is None, on purpose. The machinery is
# here and tested (scripts/test-audit-checks.py switches each check on with
# made-up fixture values and proves it still catches what it exists to
# catch), but no DKY value is filled in, for two reasons that are both
# rulings, not gaps:
#
#   1. The values must come from the FIRM, in writing. The standards make
#      the client fact-checker of record, and the firm has not yet confirmed
#      its own name spelling. A NAP check built on a guessed spelling would
#      enforce the guess on every page.
#   2. The values are NOT read off the live site. The live WordPress site
#      at dklawllc.com is the content source of record for claims, but its
#      NAP is exactly what the firm has not confirmed, so copying it here
#      would launder an unconfirmed spelling into a rule.
#
# No other client's values are carried either. Every value that was here in
# the repo this machinery came from was another business's fact.
#
# WHEN THE FIRM CONFIRMS: fill the constants, set the matching regexes,
# record who confirmed and when beside each block, and delete its line from
# FACTS_OFF. Every run states what is off, in the report's Site-wide notes,
# so an OFF check can never be read as a PASS.
FACTS_OFF = (
    "NAP (name, address, phone)",
    "hours",
    "geo",
    "email",
    "review count",
    "sameAs",
)
FACTS_OFF_NOTE = (
    "**These checks are OFF until the firm confirms its own values: "
    + ", ".join(FACTS_OFF) + ".** OFF is not PASS: nothing on any page was "
    "checked against a canonical value for them, because none is recorded yet. "
    "The firm has not confirmed its own name spelling, and the values are not "
    "read off the live site. When the firm confirms them in writing, they go "
    "into scripts/audit.py with the confirmer's name and date, and these checks "
    "switch on.")

# --- The NAP -------------------------------------------------------------
# Name, address, phone. Rule 6: character-identical everywhere they appear,
# on the site, in schema, on the Google Business Profile and in every
# directory. This block is the single place the canonical spelling lives,
# so a page and a check can never disagree about it.
#
# OFF. See FACTS_OFF above. When filled, record PROVENANCE here: who at the
# firm confirmed each value, in writing, and on what date.
NAP_NAME = None
NAP_STREET = None
NAP_LOCALITY = None
NAP_REGION = None
NAP_POSTAL = None
NAP_PHONE_DISPLAY = None
NAP_PHONE_TEL = None

# The phone and email, in the formats they could plausibly be typed. Every
# visible mention of either is meant to be tappable: a reader on a phone
# should never have to memorize a number and retype it in the dialer.
# Mentions inside JSON-LD are data, not copy, and are skipped.
#
# The phone regex must be loose about punctuation: the point of the check
# is to CATCH a number typed some other way, and a pattern that only
# matched the canonical spelling would sail past "570.555.0100" as if it
# were not a phone number at all. Shape, for when it is filled:
#   re.compile(r"\(?AAA\)?[\s.\-]?BBB[\s.\-]?CCCC")
NAP_PHONE_RE = None

# The one published email address. OFF. When the firm names it, NAP_EMAIL
# takes it and the regex follows. If the live site prints a SECOND
# address anywhere (a footer is the usual place), that one goes in
# NAP_EMAIL_WRONG_RE: two addresses for one business read as two businesses
# to entity matching, and whether the other forwards, is read, or is dead
# is the firm's to answer.
NAP_EMAIL = None
NAP_EMAIL_RE = re.compile(re.escape(NAP_EMAIL)) if NAP_EMAIL else None
NAP_EMAIL_WRONG_RE = None

# --- Call-tracking numbers -----------------------------------------------
# A call-tracking number (CallRail and the like) swaps into the page
# VISUALLY at runtime, which is the supported way to run call tracking
# without breaking NAP consistency. So a tracking number never belongs in
# this site's source: not in the HTML, the schema, the template or a
# comment. Baked into the markup it is a second phone number for one
# business, and it is the number a crawler and an AI assistant would then
# hand out as the firm's. A CRITICAL, because it is the kind of thing that
# gets pasted in during a hurried migration and is invisible by eye.
#
# EMPTY: no tracking number is known for this firm. If the live site runs
# one, add a loose-punctuation pattern for it here, one per number.
TRACKING_PHONE_RES = ()

# --- The chrome's recorded external links --------------------------------
# The header and the footer are written by scripts/sync-chrome.py, and
# every link they carry must land on a real page under docs/ or on one of
# CHROME_EXTERNAL_URLS, character for character. EMPTY until the chrome is
# specified in pagemap.md.
#
# The footer's map link, once the NAP exists, is DERIVED from the NAP
# constants, so it searches the name of record and cannot drift from it.
MAPS_NAP_URL = (("https://www.google.com/maps/search/?api=1&query="
                 + urllib.parse.quote(f"{NAP_NAME}, {NAP_STREET}, {NAP_LOCALITY}, "
                                      f"{NAP_REGION} {NAP_POSTAL}", safe=""))
                if NAP_NAME and NAP_STREET else None)
CHROME_EXTERNAL_URLS = tuple(u for u in (MAPS_NAP_URL,) if u)

# The contact patterns that are actually live. Built from whichever of the
# two above is set, so turning one on or off changes nothing else.
NAP_CONTACT_RES = [(k, rx) for k, rx in
                   (("phone", NAP_PHONE_RE), ("email", NAP_EMAIL_RE))
                   if rx is not None]

# --- Address consistency -------------------------------------------------
# The street address is the NAP field that drifts, because it is the one
# with abbreviations in it. "St" becomes "Street", the ZIP goes missing,
# the comma moves. Each variant is a slightly different business to a
# search engine's entity matching, and none of it is visible by eye across
# thirty-odd pages.
#
# So: any page that names the street at all is claiming to carry the
# address, and gets checked for the canonical spelling of it. OFF until
# the NAP is confirmed. Shapes, for when it is filled:
#   NAP_STREET_MENTION_RE   the street's distinctive word, re.I
#   NAP_STREET_VARIANT_RE   every OTHER spelling: the suffix written out,
#                           and the abbreviation WITH a trailing period
#                           ("Rd." is a variant of "Rd"; see the lesson at
#                           NAP_STREET_CANON_RE below)
NAP_STREET_CANON = NAP_STREET
NAP_CITYLINE_CANON = (f"{NAP_LOCALITY}, {NAP_REGION} {NAP_POSTAL}"
                      if NAP_LOCALITY else None)
NAP_STREET_MENTION_RE = None

# --- The name, spelled one way -------------------------------------------
# Any mention of the firm must be NAP_NAME character for character. Read in
# what a reader or a machine is handed as text: visible copy, titles, meta
# and og content, alt text and JSON-LD. Not read: comments (history may
# name an old name), URLs (slugs keep the old site's spelling on purpose),
# the logo's own alt (an image is not text, and its alt may name the
# wordmark as drawn), and client testimonials, which ship exactly as their
# writers wrote them.
#
# OFF: the firm has not confirmed its own name spelling. When it does,
# NAP_NAME takes that string and NAME_MENTION_RE matches every way the name
# could be written (with and without the commas, "&" and "and", with and
# without "LLC", the short brand), so that each one that is not NAP_NAME
# exactly fails.
NAME_MENTION_RE = None
NAME_LOGO_IMG_RE = re.compile(r'<img\b[^>]*\bsrc="[^"]*\blogo\.png"[^>]*>', re.I)
NAME_QUOTE_RE = re.compile(r'(?is)<figure\b[^>]*\bclass="[^"]*\bquote\b[^"]*"[^>]*>.*?</figure>')
NAME_TEXT_ATTR_RE = re.compile(r'\b(?:alt|content|title|aria-label)="([^"]*)"', re.I)
NAME_URL_RE = re.compile(r"https?://[^\s\"'<>]+|\b(?:href|src|srcset|data-pending-href)=\"[^\"]*\"", re.I)


def name_variants(text: str) -> list:
    """Every mention of the firm's name that is not NAP_NAME exactly, from
    raw HTML or plain text. Read: text, JSON-LD, and the attributes that
    carry text (alt, content, title, aria-label). Not read: comments, URLs,
    markup itself (a page-kind meta is code), the logo's alt, and client
    testimonials. Empty while the name check is OFF."""
    if NAME_MENTION_RE is None or not NAP_NAME:
        return []
    t = re.sub(r"(?s)<!--.*?-->", " ", text)
    t = re.sub(r"(?is)<style\b.*?</style>", " ", t)
    t = NAME_QUOTE_RE.sub(" ", t)
    t = NAME_LOGO_IMG_RE.sub(" ", t)
    t = NAME_URL_RE.sub(" ", t)
    t = re.sub(r"<[^>]*>", lambda m: " " + " ".join(NAME_TEXT_ATTR_RE.findall(m.group(0))) + " ", t)
    t = unescape(t)
    return [m.group(0) for m in NAME_MENTION_RE.finditer(t)
            if re.sub(r"\s+", " ", m.group(0)) != NAP_NAME]


def name_mentions(text: str) -> int:
    """How many mentions name_variants reads, right or wrong."""
    if NAME_MENTION_RE is None:
        return 0
    t = re.sub(r"(?s)<!--.*?-->", " ", text)
    t = NAME_QUOTE_RE.sub(" ", NAME_LOGO_IMG_RE.sub(" ", t))
    t = NAME_URL_RE.sub(" ", t)
    t = re.sub(r"<[^>]*>", lambda m: " " + " ".join(NAME_TEXT_ATTR_RE.findall(m.group(0))) + " ", t)
    return len(NAME_MENTION_RE.findall(unescape(t)))

# --- The hours, defined once ---------------------------------------------
# The hours are a fact readers act on, so a copy that drifts is a firm that
# answers the phone at the wrong time. They appear in footer text, a
# contact page, llms.txt and every page's openingHoursSpecification, with
# nothing holding them together unless this does.
#
# OFF. See FACTS_OFF. When the firm confirms its hours, in writing:
#   HOURS_CANON          the visible strings, exactly as every page writes
#                        them, e.g. ("Monday to Friday, 9 a.m. to 5 p.m.",)
#   HOURS_SCHEMA_DAYS    the schema's dayOfWeek list
#   HOURS_SCHEMA_OPENS   "09:00"
#   HOURS_SCHEMA_CLOSES  "17:00"
#   HOURS_FORBIDDEN_DAYS days the record does not know, as lowercase day
#                        names; any mention of one is a critical, because a
#                        page that says anything about such a day is saying
#                        something nobody confirmed
#
# The check, per page and on llms.txt: every day name, every "Mon-Fri" style
# range and every clock time in visible text must sit inside one of the
# canonical strings. Anything else is the hours written a second way, and it
# is a critical, same as a second spelling of the street. The schema must
# say the same thing.
HOURS_CANON = None
HOURS_SCHEMA_DAYS = None
HOURS_SCHEMA_OPENS = None
HOURS_SCHEMA_CLOSES = None
HOURS_FORBIDDEN_DAYS = ()

# --- The firm's coordinates, defined once --------------------------------
# OFF. See FACTS_OFF. When filled: Google's own place point for the office,
# VERIFIED, and recorded with how it was verified and who confirmed it.
#
# THE LESSON THIS CARRIES, from the founding client build: a live site's
# geo was a Google Maps URL's "@lat,lon", the viewport CENTRE, which Google
# shifts sideways for its side panel. It sat about 220m from the building.
# Take coordinates from the place's own data, never from a map URL.
#
# The check: every business node's geo in every page's schema equals these
# exactly.
GEO_LAT = None
GEO_LON = None


def geo_findings(nodes: list) -> tuple:
    """(business nodes checked, every way their geo departs from the
    constants). A business node with no geo is a departure: the node
    repeats in full on every page, so a missing value is drift. Nothing
    is checked while the geo check is OFF."""
    out, n = [], 0
    if GEO_LAT is None or GEO_LON is None:
        return n, out
    for node in nodes:
        t = node.get("@type")
        names = {type_name(x) for x in (t if isinstance(t, list) else [t]) if x}
        if not LOCAL_BUSINESS_TYPES.intersection(names):
            continue
        n += 1
        geo = node.get("geo")
        if not isinstance(geo, dict):
            out.append("the business node carries no `geo`")
            continue
        try:
            lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
        except (TypeError, ValueError):
            out.append(f"`geo` is not two numbers: {geo!r}")
            continue
        if (lat, lon) != (GEO_LAT, GEO_LON):
            out.append(f"`geo` is {lat}, {lon}; the constants say {GEO_LAT}, {GEO_LON}")
    return n, out
HOURS_DAY_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b"
    r"|\b(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)\.?\s*(?:-|–|to|thru|through)\s*"
    r"(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)\b", re.I)
HOURS_TIME_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am\b|pm\b)", re.I)


def hours_findings(text: str):
    """(canonical mentions, stray mentions, forbidden-day mentions) in one
    run of visible text. Entities decoded and no-break spaces flattened
    first, so 9&nbsp;a.m. and 9 a.m. are the same string. Nothing is read
    while the hours check is OFF."""
    if not HOURS_CANON:
        return 0, [], []
    t = " ".join(unescape(text).replace(" ", " ").split())
    spans = [(m.start(), m.end())
             for canon in HOURS_CANON
             for m in re.finditer(re.escape(canon), t)]
    inside = lambda m: any(a <= m.start() and m.end() <= b for a, b in spans)
    forbidden = tuple(d.lower() for d in HOURS_FORBIDDEN_DAYS)
    strays, banned = [], []
    for rx in (HOURS_DAY_RE, HOURS_TIME_RE):
        for m in rx.finditer(t):
            if forbidden and m.group(0).lower().startswith(tuple(d[:3] for d in forbidden)):
                continue
            if not inside(m):
                strays.append(t[max(0, m.start() - 30):m.end() + 30].strip())
    for day in forbidden:
        for m in re.finditer(r"(?i)\b" + re.escape(day) + r"s?\b", t):
            banned.append(t[max(0, m.start() - 30):m.end() + 30].strip())
    return len(spans), strays, banned


def hours_schema_findings(nodes: list) -> list:
    """Every way the business node's openingHoursSpecification departs
    from the constants. An absent specification is not a departure; a
    page with no business node is checked elsewhere. Nothing is checked
    while the hours check is OFF."""
    out = []
    if not HOURS_SCHEMA_DAYS:
        return out
    for node in nodes:
        specs = node.get("openingHoursSpecification")
        if specs is None:
            continue
        specs = specs if isinstance(specs, list) else [specs]
        want = (sorted(HOURS_SCHEMA_DAYS), HOURS_SCHEMA_OPENS, HOURS_SCHEMA_CLOSES)
        got = []
        for sp in specs:
            days = sp.get("dayOfWeek", [])
            days = days if isinstance(days, list) else [days]
            got.append((sorted(str(d).rsplit("/", 1)[-1] for d in days),
                        str(sp.get("opens", "")), str(sp.get("closes", ""))))
        if got != [want]:
            out.append(f"`openingHoursSpecification` says {got}, the constants say {[want]}")
    return out

# THE TRAILING PERIOD IS A VARIANT, and this is the founding build's most
# expensive lesson about this check. "100 Main Rd." is not "100 Main Rd",
# and character-identical has no rounding.
#
# The first version of the variant pattern ended each alternative with \b,
# which reads as "a word character has to come next." After "Rd." the next
# character on a real page is a comma or a line break, neither of which is
# a word character, so the boundary never matched and the variant sailed
# through. Worse, it scored as a PASS, because the canonical string is a
# PREFIX of the variant: a plain `in` test found it inside "Rd." and
# reported the address as correctly spelled. A check that says PASS on the
# thing it exists to catch is worse than no check.
#
# So both halves are fixed by construction. An abbreviation with a period
# ("Rd\.") is self-terminating and needs no boundary; a spelled-out suffix
# ("Road") keeps one. And the canonical test is a regex with a lookahead,
# so the canonical street only counts when nothing word-like or a period
# follows it. OFF until the NAP is confirmed.
NAP_STREET_VARIANT_RE = None
NAP_STREET_CANON_RE = (re.compile(re.escape(NAP_STREET_CANON) + r"(?![.\w])")
                       if NAP_STREET_CANON else None)

# --- Staging ------------------------------------------------------------
# THE SITE IS NOINDEXED ON PURPOSE, AND THIS IS THE SWITCH THAT SAYS SO.
#
# The firm's real site is live on WordPress at dklawllc.com right now. This
# build is not it. A crawlable staging copy is a second address answering
# for one business, which is the harm rule 6 exists to prevent, so until
# cutover every page carries <meta name="robots" content="noindex, nofollow">,
# docs/robots.txt disallows everything, and the canonicals point at the
# PRODUCTION domain from day one so any signal that does leak lands on the
# real site.
#
# The audit therefore INVERTS its noindex check while this is True. A page
# with noindex passes; a page WITHOUT it fails. The risk during staging is
# not that a page is noindexed, it is that one page quietly is not, and gets
# indexed at a github.io address while the real site is still live. A
# deliberate exception that the build does not enforce is just a comment,
# and comments get violated.
#
# STAGING ALSO GATES THE [CONFIRM] LAW. While it is True, a page carrying a
# [CONFIRM] marker is reported as a note (a draft is allowed to wait on a
# partner's initials). Once it is False, any [CONFIRM] left on a page is a
# CRITICAL and --strict fails. See CONFIRM_RE.
#
# AT CUTOVER, all of it moves together, in one commit:
#   1. set this to False;
#   2. run scripts/sync-chrome.py, which takes the noindex tag and the
#      visible banner off every page, because it writes both from this
#      switch (STAGING_ROBOTS_META and STAGING_BANNER below);
#   3. replace docs/robots.txt with an open one that names the sitemap and
#      blocks no AI crawler;
#   4. rewrite docs/llms.txt's staging paragraph (the one carrying
#      LLMS_STAGING_MARK).
# With this False, a noindex tag, a banner, a disallow-all robots.txt, the
# llms.txt paragraph or a [CONFIRM] left behind is a CRITICAL, so a
# half-done flip fails loudly. Record the date here and in CLAUDE.md when it
# happens.
STAGING = True

# The two staging fragments every page carries while STAGING is True, held
# here once so scripts/sync-chrome.py writes the same bytes the check below
# reads. The banner's comment names the switch, not a date, so it stays
# true until the day it is deleted.
STAGING_ROBOTS_META = '<meta name="robots" content="noindex, nofollow">'
STAGING_BANNER = (
    '<!-- Removed at cutover, with the noindex tag and the robots.txt disallow.\n'
    '       A human who opens this page should not have to guess why it is not\n'
    '       indexed. -->\n'
    '  <p class="staging">Staging build. Not the live site. The firm\'s live site '
    f'is at {SITE_DOMAIN}</p>')
STAGING_BANNER_RE = re.compile(r'<p\s+class="staging"', re.I)
# docs/llms.txt's staging paragraph opens with this. Matched case-blind, and
# so is the word "staging" anywhere in llms.txt once the switch is off.
LLMS_STAGING_MARK = "THIS SITE IS NOT LIVE YET"


def staging_robots_meta() -> str:
    """The robots tag a generated page carries: the noindex while staging,
    nothing after cutover."""
    return STAGING_ROBOTS_META if STAGING else ""


def staging_banner() -> str:
    """The visible banner a generated page carries: present while staging,
    nothing after cutover."""
    return STAGING_BANNER if STAGING else ""


# --- The [CONFIRM] law -----------------------------------------------------
# The live site is the content source of record. Any claim on the new site
# that the live site does not already make carries a [CONFIRM] marker in the
# HTML comment beside it, and a row in proposed-changes.md naming the
# partner who must initial it.
#
# BOTH SIDES OF THE CUTOVER, enforced rather than remembered:
#   STAGING True    every marker is listed in a NOTE on its page, with its
#                   line, so the Monday report shows what is still waiting.
#                   A draft is allowed to wait; it is not allowed to wait
#                   silently.
#   STAGING False   any marker on any page is a CRITICAL. --strict fails.
#
# Matched in the raw HTML, comments included, because a comment is exactly
# where the marker lives. Local files only: a live run reads the WordPress
# site, which carries none of ours.
CONFIRM_RE = re.compile(r"\[CONFIRM\b[^\]]*\]")


def confirm_findings(html_text: str) -> list:
    """Every [CONFIRM] marker in a page, as (line, the marker and a little
    of what follows it)."""
    out = []
    for m in CONFIRM_RE.finditer(html_text):
        line = html_text.count("\n", 0, m.start()) + 1
        tail = " ".join(html_text[m.start():m.end() + 70].split())
        out.append((line, tail))
    return out


# --- The favicon set -------------------------------------------------------
# The firm's own site icon, made by scripts/prepare-favicon.py and linked
# from every real page's head by scripts/sync-chrome.py. Each entry is
# (rel, attributes after rel, path under docs/). A page missing one, or a
# file missing from docs/, fails.
ICON_LINKS = (
    ("icon", 'sizes="any"', "favicon.ico"),
    ("icon", 'type="image/png" sizes="192x192"', "assets/img/icon-192.png"),
    ("apple-touch-icon", "", "assets/img/icon-180.png"),
)

# --- The review count, and the day it was counted ------------------------
# A REVIEW COUNT IS THE ONE NUMBER ON A SITE THAT ROTS ON ITS OWN. It is
# true on the day it is read and quietly wrong every week after, and
# nothing on the page changes when it goes wrong. So it is recorded here
# with the day it was counted, and the check below enforces both halves.
#
# OFF. See FACTS_OFF. When filled: the count and rating as read off the
# firm's own Google Business Profile, the date read, and who read it.
#
# WHAT STILL RUNS WHILE IT IS OFF: agreement between pages. Two pages that
# state two different review counts are one of them wrong whatever the
# constant says, so that half of the check stays live. The constant's own
# half (a page disagreeing with REVIEW_COUNT) and the staleness clock wait
# for a value.
#
# THE FOUNDING BUILD'S WARNING: a live site's review widget and the
# business's own profile disagreed by 43 reviews in the same week. Read the
# profile, never a widget.
#
# NO Review OR AggregateRating MARKUP GOES WITH IT, ever. Google's own
# guidelines rule out self-serving review markup on a business's own site,
# and the standards allow no review or rating markup unless the data is
# real and the owner has decided to publish it. A count lives in visible
# text and nowhere else.
REVIEW_COUNT = None
REVIEW_RATING = None
REVIEW_COUNTED_ON = None

# Past this many days the count is old enough that publishing it without
# re-reading the profile is a guess. A WARNING, not a critical: the number
# is not wrong yet, it is just no longer known to be right.
REVIEW_STALE_DAYS = 35

# "274 Google reviews", "based on 274 reviews", "over 231 verified Google
# reviews". Matched against VISIBLE TEXT, after comments and scripts are
# stripped, so a comment recording what the number used to be is history
# rather than a contradiction. Up to three words may sit between the number
# and "reviews", and a "+" after the number is read as the number. A year
# followed by words is not a count ("In 2019 our clients left reviews"), so
# a 19xx or 20xx with words after it is skipped; a bare "2019 reviews"
# still counts. A comma is read only as a thousands separator.
REVIEW_COUNT_RE = re.compile(
    r"\b(?!(?:19|20)\d\d\s+[A-Za-z]+\s+(?!reviews?\b))"
    r"(\d{1,3}(?:,\d{3})+|\d{1,7})\+?\s+(?:[A-Za-z][\w'’-]*\s+){0,3}?reviews?\b", re.I)

# THE SERVICE FAMILY: THE ONE TABLE OF ITS CARDS. Each row is (path, label,
# line): the page, its one name across the site, and its one card line.
# scripts/sync-chrome.py imports it for the nav and the footer, and
# scripts/sync-service-cards.py for every service card and each service
# page's Related Services section. The enumeration check below holds every
# page to it: every grid carries the family (a service page's own grid, the
# family minus itself), and every card carries its row's label and line,
# so a card cannot drift and a service cannot be half-added.
#
# EMPTY until pagemap.md exists with the partner's written approval: the
# page list is the build spec's to decide, not this file's. While it is
# empty the enumeration checks do not run, and say so.
SERVICES = ()
SERVICE_PATHS = tuple(p for p, _l, _ln in SERVICES)
# Pages a Related Services list leaves out, beyond the page itself. A
# ruling per site, recorded with its reason. None yet.
RELATED_LEAVES_OUT = ()
COUNT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")

# A count typed beside "services" ("Four services, one firm", "the four
# services"). It must be the family's own size, spelled as a word.
SERVICE_COUNT_RE = re.compile(r"\b(" + "|".join(COUNT_WORDS[1:]) + r"|\d+)\s+services\b", re.I)

# A BARE-TEXT ENUMERATION: one sentence naming ALL BUT ONE of the family or
# more, in words, with no links for a link-based scan to find. That is the
# half-added shape exactly: a sentence written when the family was one
# smaller. Keyed by SERVICES path; each pattern matches the ways that
# service is named in prose. Filled with SERVICES.
SERVICE_TEXT_RE = {}

JSONLD_RE = re.compile(
    r"(?is)<script[^>]+type=\"application/ld\+json\"[^>]*>(.*?)</script>")

# --- Asset provenance: no AI-generated image enters this repo ----------
# Added on the founding client build, after two licensed candidate assets
# for one illustration were both caught by reading their metadata.
#
# The standards say real photos only, no stock and no AI-generated
# imagery, and the reason is the firm's own argument: a site that tells
# clients real beats stock has to live by it. That rule had no
# mechanism, so it was a rule that depended on somebody remembering to
# look. Twice in one afternoon the thing that caught an AI asset was a
# person deciding to check, which is exactly the shape of rule that
# rule 8 says gets violated.
#
# WHAT THE TWO CANDIDATES CARRIED, both licensed from Adobe Stock and
# both rejected:
#
#   AdobeStock_1060063701  IPTC DigitalSourceType = trainedAlgorithmicMedia
#   AdobeStock_746591791   xmp:CreatorTool = "OkiDokiBot AI Art Generator"
#
# Two different tells in two different tags, which is why this reads
# both and does not trust either one alone. The first is Adobe's own
# C2PA label, the standard IPTC code for "a generative model made these
# pixels". The second carries no DigitalSourceType at all and names the
# generator in the tool field instead.
#
# THE LIMIT, AND IT IS A REAL ONE. This reads labels. It cannot read
# pixels, so it cannot catch an AI asset whose metadata was stripped,
# and stripping is one command. The check is a floor and not a
# guarantee: it makes the labelled case impossible to ship by accident,
# and the unlabelled case stays a human judgement at purchase time. A
# report that says "no AI marker" is saying the file makes no such
# claim, not that a person made it.
#
# WHAT IS DELIBERATELY NOT A FAIL. digitalCapture is a camera.
# digitalArt and algorithmicMedia are a person at a workstation, which
# is what a real 3D ghosted render is, and failing those would ban the
# asset this check was written to let through.
AI_SOURCE_TYPES = (
    "trainedalgorithmicmedia",
    "compositewithtrainedalgorithmicmedia",
)

# Generator names and phrases that mean the same thing when they turn up
# in a tool field. Deliberately specific: "firefly" alone is a typeface
# and a product name, so it is spelled "adobe firefly", and bare "ai" is
# not here at all because it matches half the software on earth.
AI_TOOL_RE = re.compile(
    r"midjourney|stable\s?diffusion|dall[·.\-\s]?e\b|adobe firefly"
    r"|okidokibot|leonardo\.ai|ideogram|nightcafe|craiyon|starryai"
    r"|ai (?:art|image) generator|text[-\s]to[-\s]image"
    r"|generative (?:fill|expand)|ai[-\s]generated",
    re.I)

# Where the tells live. Both tags appear as an element or as an
# attribute depending on how the XMP was written, so both spellings are
# matched rather than assumed.
SOURCE_TYPE_RE = re.compile(
    r"DigitalSourceType\s*[>=]\s*[\"']?\s*"
    r"(?:http://cv\.iptc\.org/newscodes/digitalsourcetype/)?([A-Za-z]+)")
CREATOR_TOOL_RE = re.compile(r"CreatorTool\s*[>=]\s*[\"']?([^<\"'\r\n]{1,120})")

# Raster formats only. An .svg under docs/ is our own drawing, in the
# repo as text, and it is reviewed as code rather than as an asset.
ASSET_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")

# --- The convention that keeps comments from rotting ------------------
# COMMENTS NEVER CARRY THE LITERAL REVIEW COUNT OR THE STAT ORDER. They
# name `REVIEW_COUNT` and "the band's DOM order" instead.
#
# WHY THERE IS A CONVENTION AT ALL. The check above strips comments
# before reading review counts, deliberately, so that a comment
# recording history is not read as the page contradicting itself. The
# cost of that choice showed up on the founding build: the stat band's own
# comment had been carrying a stale count AND a stale order through two
# commits, and nothing could have caught it, because the one mechanism
# that reads counts is the one that had been told to look away.
#
# So the convention removes the thing that rots, and this check watches
# for it coming back. A comment that says `REVIEW_COUNT` stays true
# when the number changes; a comment that says the number does not.
#
# THE CONVENTION AND THE CHECK FIT EACH OTHER BY CONSTRUCTION: `\breview\b`
# cannot match inside `REVIEW_COUNT`, because the character after
# "REVIEW" is an underscore and an underscore is a word character. The
# approved way of writing it is exactly the way this pattern cannot fire
# on, which is what makes the rule easy to keep rather than easy to
# resent.
#
# WARN-LEVEL, AND STRUCTURALLY INCAPABLE OF FAILING: the function is not
# handed a `fails` list. A rotting comment misleads the next reader and
# costs nothing to a visitor, so it should never stop a build. It is
# also the kind of thing that turns into a false positive on somebody's
# perfectly reasonable prose, and a false positive that fails a build
# gets the check deleted rather than fixed.
HTML_COMMENT_RE = re.compile(r"(?s)<!--(.*?)-->")

# "a few words" is three. Two to four digits, because a one-digit number
# beside "review" is prose ("a 5 star review") and five digits is not a
# count this firm will have in this decade.
_NEARBY_WORDS = r"(?:[\w'\u2019()\-.,:;/]+ ){0,3}"
COMMENT_REVIEW_NUM_RE = re.compile(
    r"\b\d{2,4}\b " + _NEARBY_WORDS + r"reviews?\b"
    r"|\breviews?\b " + _NEARBY_WORDS + r"\d{2,4}\b", re.I)

# --- Links that are waiting on a page that does not exist yet ---------
# THE SITE NEVER WRITES A LINK TO A PAGE THAT HAS NOT BEEN BUILT. That
# rule is enforced: a relative href with no file behind it fails the
# build. The cost of enforcing it is a set of elements that SHOULD be
# links and are not yet: the logo before the homepage exists, the
# breadcrumb's "Home", a mention of a service whose page is still to come.
#
# Waiting was the unmechanized part. Nothing recorded what each one was
# waiting for, and nothing would notice the day the wait ended, so the
# failure mode is a page that ships built and unlinked with a span
# sitting where its link should be.
#
# So each carries data-pending-href with the URL it becomes. The test
# then cuts BOTH ways: a real href to a missing file fails, and a
# pending href to a file that now EXISTS fails until it is converted.
# The second direction is the one that was missing.
PENDING_HREF_RE = re.compile(r'data-pending-href="([^"]+)"')

# SITE_BASE, the site's own base URL, is defined with the client at the top
# of this file. It is how a local file's served URL is worked out, so the
# checks below know whether a page is in sitemap.xml under its OWN address.

# A sitemap is not always a list of pages. It may be a <sitemapindex>,
# a list of OTHER sitemaps, which is what WordPress and Yoast ship by
# default. We follow an index into its children, with two caps so a
# malformed or looping sitemap cannot spin a scan forever: how deep the
# nesting may go, and how many sitemap files one run will fetch at all.
SITEMAP_MAX_DEPTH = 3
SITEMAP_MAX_FILES = 50

# --- LocalBusiness and everything that IS one -------------------------
# The "is this a local business page" check used to hold a hand-written
# list of about twenty types, which meant every schema.org subtype
# nobody had thought to type out was reported as having no
# LocalBusiness schema at all. A real prospect's site was flagged on
# every page for exactly this: it publishes a complete AutoBodyShop
# node, address, telephone, geo and hours included, and AutoBodyShop is
# a LocalBusiness subtype the list happened to omit. The finding was
# false, and it was the kind of false that a prospect can check in a
# minute.
#
# So this is the full set: LocalBusiness plus every class under it in
# the schema.org vocabulary, all 130 of them, derived from
# schemaorg-current-https.jsonld (schema.org v29, read 2026-08-28) by
# walking rdfs:subClassOf down from schema:LocalBusiness. None of them
# is superseded. It is baked in as a literal rather than fetched so the
# audit still runs with no network, which is how it runs against our
# own pages. To refresh it after a schema.org release, walk the
# vocabulary again; do not add names by hand, which is the habit that
# produced the short list.
LOCAL_BUSINESS_TYPES = frozenset({
    "LocalBusiness", "AccountingService", "AdultEntertainment",
    "AmusementPark", "AnimalShelter", "ArchiveOrganization",
    "ArtGallery", "Attorney", "AutoBodyShop", "AutoDealer",
    "AutoPartsStore", "AutoRental", "AutoRepair", "AutoWash",
    "AutomatedTeller", "AutomotiveBusiness", "Bakery",
    "BankOrCreditUnion", "BarOrPub", "BeautySalon", "BedAndBreakfast",
    "BikeStore", "BookStore", "BowlingAlley", "Brewery",
    "CafeOrCoffeeShop", "Campground", "Casino", "ChildCare",
    "ClothingStore", "ComedyClub", "ComputerStore", "ConvenienceStore",
    "CovidTestingFacility", "DaySpa", "Dentist", "DepartmentStore",
    "Distillery", "DryCleaningOrLaundry", "Electrician",
    "ElectronicsStore", "EmergencyService", "EmploymentAgency",
    "EntertainmentBusiness", "ExerciseGym", "FastFoodRestaurant",
    "FinancialService", "FireStation", "Florist", "FoodEstablishment",
    "FurnitureStore", "GardenStore", "GasStation", "GeneralContractor",
    "GolfCourse", "GovernmentOffice", "GroceryStore", "HVACBusiness",
    "HairSalon", "HardwareStore", "HealthAndBeautyBusiness",
    "HealthClub", "HobbyShop", "HomeAndConstructionBusiness",
    "HomeGoodsStore", "Hospital", "Hostel", "Hotel", "HousePainter",
    "IceCreamShop", "IndividualPhysician", "InsuranceAgency",
    "InternetCafe", "JewelryStore", "LegalService", "Library",
    "LiquorStore", "Locksmith", "LodgingBusiness", "MedicalBusiness",
    "MedicalClinic", "MensClothingStore", "MobilePhoneStore", "Motel",
    "MotorcycleDealer", "MotorcycleRepair", "MovieRentalStore",
    "MovieTheater", "MovingCompany", "MusicStore", "NailSalon",
    "NightClub", "Notary", "OfficeEquipmentStore", "Optician",
    "OutletStore", "PawnShop", "PetStore", "Pharmacy", "Physician",
    "PhysiciansOffice", "Plumber", "PoliceStation", "PostOffice",
    "ProfessionalService", "PublicSwimmingPool", "RadioStation",
    "RealEstateAgent", "RecyclingCenter", "Resort", "Restaurant",
    "RoofingContractor", "SelfStorage", "ShoeStore", "ShoppingCenter",
    "SkiResort", "SportingGoodsStore", "SportsActivityLocation",
    "SportsClub", "StadiumOrArena", "Store", "TattooParlor",
    "TelevisionStation", "TennisComplex", "TireShop",
    "TouristInformationCenter", "ToyStore", "TravelAgency",
    "VacationRental", "WholesaleStore", "Winery"
})

# A @type may be written as a bare name, a full URL, or a compact IRI
# ("AutoBodyShop", "https://schema.org/AutoBodyShop", "schema:AutoBodyShop").
# All three are valid JSON-LD and all three appear in the wild, so the
# name is normalized before anything is matched against it. Without
# this, a page using the URL form reads as having no recognized type at
# all, which would fail the FAQPage check the same way.
TYPE_NAME_RE = re.compile(r"^(?:https?://(?:www\.)?schema\.org/|schema:)")


def type_name(raw) -> str:
    """The bare schema.org class name from any of its written forms."""
    if not isinstance(raw, str):
        return ""
    return TYPE_NAME_RE.sub("", raw.strip()).strip("/")


# --- Pages that are not pages -----------------------------------------
# Two kinds of file under docs/ exist for machines rather than readers: a
# redirect stub standing at an old WordPress URL, and the 404 page. Both
# would fail the page rubric for things that are deliberate. A stub has
# no FAQ, no schema and forty words; the 404 page has no canonical,
# because a canonical on an error page would claim the URL is the real
# version of something. Above all, neither belongs in sitemap.xml, and
# "not listed in sitemap.xml" is a critical for a real page.
#
# So each declares itself in the head and gets a short rubric of its own:
#   <meta name="dky-page" content="redirect-stub">
#   <meta name="dky-page" content="error-404">
# They still score through the same formula and still appear in the
# table, so a malformed stub drops off 100/100 and fails --strict exactly
# like anything else. What changes is WHICH checks apply.
SPECIAL_KINDS = ("redirect-stub", "error-404")

# --- Execution pages: the full rubric, minus checks NAMED per kind ------
# HOUSE PRECEDENT, ruled by Greg Quinn of Corcoran on the founding client
# build and carried in the starter kit. EXECUTION PAGES MEASURE
# DIFFERENTLY. Two checks below measure a page whose job is to persuade and
# to answer: the FAQPage check and the 300-word thin-content check. A
# contact page does neither. Its job is to put every way of reaching the
# firm within one tap and the call inside the first screen,
# and the fold probe is what measures that. A check that forced 300 words
# of filler or an invented FAQ onto it would be the check designing the
# page. The check serves the page, never the reverse.
#
# WHY NOT LET IT SCORE 83 AND RECORD IT: a permanent sub-bar score teaches
# the Monday reader to skim past warnings, and the report is worth paying
# for only while a warning means something.
#
# THE LIMITS ARE THE PERMISSION:
#   - A page opts in by declaring it in its own head, where the next
#     reader sees it: <meta name="dky-page" content="contact">.
#   - A kind is exempt from exactly the checks listed against it, by
#     name, and from nothing else. Every other check runs as usual, and
#     the page still counts as a page in the report.
#   - KINDS ARE PER-KIND AND EXPLICIT. A new page that trips its own
#     rubric mismatch declares ITS OWN kind with its own recorded scope.
#     There is never a blanket pass, and never one for "utility".
#   - An exempt check still reports, as a note naming the exemption, so
#     the report says what was not measured rather than going quiet.
# scripts/test-audit-checks.py holds both directions: a contact-kind page
# still fails what it should, and an undeclared page gets no exemption.
#
# THE BLOG'S TWO KINDS, house precedent from the founding build.
# A POST IS A READ AND AN INDEX ROUTES: neither page type answers questions,
# so neither is measured for an answer block. Each is exempt from
# faq-schema and NOTHING ELSE. Thin-content stays live on both, on purpose:
# a post under 300 words SHOULD warn, because a thin post is a real
# editorial problem in a way a missing FAQ is not.
#
# THE EXEMPTION MEANS NOT REQUIRED, NEVER UNMEASURED. It applies only to a
# page that shows NO visible FAQ. A post that carries one (an FAQ-rich post
# is a real AEO play) is measured like every other page: no schema warns,
# and the mirror law fails any difference between the visible text and the
# FAQPage node, both directions. That holds for contact too.
#
# A LOCATION ("town") PAGE IS DECLARED AND EXEMPT FROM NOTHING, house
# precedent from the founding build. It carries a real FAQ and has to
# earn its words, so faq-schema and thin-content both stay measured. The
# empty tuple is written out rather than left to the .get() default, so the
# kind is a ruled entry like the others and a later edit that adds an
# exemption to it is a visible change to a ruled list, not a new key.
# The tier's own gate is check_town_variance_local, further down.
RUBRIC_EXEMPTIONS = {
    "contact": ("faq-schema", "thin-content"),
    "post": ("faq-schema",),
    "blog-index": ("faq-schema",),
    "town": (),
    # The privacy policy, house precedent from the founding build. A policy states
    # what happens to a reader's information; it does not answer questions,
    # and it carries no visible FAQ, so faq-schema and NOTHING ELSE. Thin
    # content stays live on it, as on a post. The kind also carries its own
    # date check, privacy_date_findings, because the policy promises its
    # reader that the date on the page changes when the policy does.
    "privacy": ("faq-schema",),
}

REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv=["']refresh["'][^>]*content=["']\s*\d+\s*;\s*url=([^"']+)["']""",
    re.I)

# --- Cache-busting stamps ---------------------------------------------
# docs/assets/site.css and site.js are referenced as
# `assets/site.css?v=<first 8 hex of the file's SHA-256>`, written by
# scripts/stamp-assets.py. GitHub Pages serves both with
# `cache-control: max-age=600`, so without the stamp a ten-minute-old
# browser cache hands back the OLD stylesheet, which during the build
# twice looked exactly like a CSS bug and got chased as one.
#
# The stamper is a command someone has to run. This check is what makes
# forgetting to run it impossible: a stale or missing stamp is a critical
# against the page, same as a missing sitemap entry.
STAMPED_ASSETS = ("assets/site.css", "assets/site.js")
STAMP_RE = {
    a: re.compile(r'(?:href|src)="(?:\{\{ROOT\}\}|/|(?:\.\./)*)'
                  + re.escape(a) + r'(\?v=([0-9a-f]+))?"')
    for a in STAMPED_ASSETS
}


def current_stamps() -> dict:
    """First 8 hex of each stamped asset's SHA-256. Empty dict if they
    cannot be read, which is the case on a live-URL run, and the check
    then does nothing rather than guessing."""
    out = {}
    for a in STAMPED_ASSETS:
        try:
            with open(os.path.join(SITE_DIR, a), "rb") as f:
                out[a] = hashlib.sha256(f.read()).hexdigest()[:8]
        except OSError:
            return {}
    return out


def page_url(source: str) -> str:
    """The absolute URL a local file will serve at, so a page can be
    looked up in the sitemap under its own address."""
    rel = os.path.relpath(source, SITE_DIR).replace(os.sep, "/")
    if rel == "index.html":
        rel = ""
    elif rel.endswith("/index.html"):
        rel = rel[:-len("index.html")]
    return SITE_BASE + rel


def check_asset_stamps(html: str, stamps: dict, passes: list, fails: list):
    """Every page that links the shared stylesheet or script must carry
    the CURRENT stamp for it."""
    if not stamps:
        return
    for asset, rx in STAMP_RE.items():
        m = rx.search(html)
        if not m:
            continue                      # this page does not use it
        want = stamps[asset]
        if m.group(2) == want:
            passes.append(f"`{asset}` carries the current cache-busting stamp `?v={want}`.")
        elif m.group(1) is None:
            fails.append(
                f"**`{asset}` is referenced with no `?v=` stamp.** GitHub Pages serves it with "
                f"`max-age=600`, so a browser can hand back a ten-minute-old copy and make a "
                f"shipped change look broken. Run `python3 scripts/stamp-assets.py`.")
        else:
            fails.append(
                f"**`{asset}` carries a stale stamp** (`?v={m.group(2)}`, the file is now "
                f"`?v={want}`). The page will serve a cached older copy of the file. Run "
                f"`python3 scripts/stamp-assets.py`.")


def special_audit(source: str, html: str, p, kind: str, coverage: dict):
    """The short rubric for a redirect stub or the 404 page.

    Both are scored on what they are actually FOR, and both are checked
    for the thing that matters most about them: that they stayed out of
    sitemap.xml. Neither is checked against llms.txt, which lists pages a
    reader or an assistant would want, and these are not that."""
    passes, warns, fails, notes = [], [], [], []
    own = page_url(source)
    listed = coverage is not None and own in coverage["sitemap_locs"]

    if kind == "redirect-stub":
        sp, sw, sf = staging_page_findings(html, is_stub=True)
        passes += sp
        warns += sw
        fails += sf
        canon = (p.canonical or "").strip()
        if canon.startswith(SITE_BASE):
            passes.append(f"Canonical points at the new page: {canon}")
        else:
            fails.append(
                f"**A redirect stub needs an absolute `rel=canonical` at its target.** "
                f"Found: {canon or 'nothing'}. That tag is what passes the old URL's ranking "
                f"signal to the page that replaced it.")

        m = REFRESH_RE.search(html)
        if not m:
            fails.append(
                "**No `<meta http-equiv=\"refresh\">`.** GitHub Pages cannot issue a real 301, "
                "so the meta refresh is what actually moves a reader. Without it this file is a "
                "dead end with a canonical on it.")
        else:
            raw = m.group(1).strip()
            # Fragments are compared away: the canonical deliberately
            # carries none (Google strips them anyway) while the refresh
            # target keeps its anchor so the reader lands in the right
            # section. Same page, two jobs.
            target = urljoin(own, raw).split("#")[0]
            if target == canon.split("#")[0]:
                passes.append(f"Meta refresh and canonical agree on the destination: {target}")
            else:
                fails.append(
                    f"**The meta refresh and the canonical disagree.** The refresh sends readers "
                    f"to {target} and the canonical sends crawlers to {canon.split('#')[0]}. "
                    f"Pick one destination and use it in both.")
            if re.search(r"<a[^>]+href=\"" + re.escape(raw) + r"\"", html):
                passes.append("A real link to the destination is on the page, for anyone the "
                              "refresh and the script both miss.")
            else:
                warns.append(
                    f"**No visible link to {raw}.** If the refresh is blocked and JavaScript is "
                    f"off, the reader is stranded. Add one sentence with a real link.")
    else:
        t = p.title.strip()
        if not t:
            fails.append("**Missing <title> tag.** The error page is a page a reader lands on; "
                         "give it a name.")
        elif len(t) > 60:
            warns.append(f"**Title is {len(t)} characters** (aim for \u226460): \u201c{t}\u201d")
        else:
            passes.append(f"Title tag present and a good length ({len(t)} chars): \u201c{t}\u201d")

        d = p.meta.get("description", "").strip()
        if not d:
            fails.append("**Missing meta description.**")
        elif len(d) > 160:
            warns.append(f"**Meta description is {len(d)} characters** (aim for \u2264160).")
        else:
            passes.append(f"Meta description present and a good length ({len(d)} chars).")

        h1s = [h.strip() for h in p.h1s if h.strip()]
        if len(h1s) != 1:
            fails.append(f"**{len(h1s)} H1 headings found.** The error page needs exactly one.")
        else:
            passes.append(f"Exactly one H1: \u201c{h1s[0][:80]}\u201d")

        if p.has_viewport:
            passes.append("Mobile viewport tag present.")
        else:
            fails.append("**No viewport meta tag.**")

        missing_alt = [src for src, alt in p.images if alt is None or not alt.strip()]
        if p.images and missing_alt:
            fails.append(f"**{len(missing_alt)} of {len(p.images)} images missing alt text.**")
        elif p.images:
            passes.append(f"All {len(p.images)} images have alt text.")

        check_asset_stamps(html, current_stamps(), passes, fails)

        # THE STAGING MACHINERY, BOTH WAYS: the error page is one a
        # human reads, so it carries the banner and the noindex while
        # STAGING is True and neither once it is False, like every page.
        # scripts/sync-chrome.py writes both into it from the switch.
        sp, sw, sf = staging_page_findings(html)
        passes += sp
        warns += sw
        fails += sf
        bare = re.sub(r"(?s)<!--.*?-->", " ", html)
        noindex = re.search(r'<meta\s+name="robots"[^>]*noindex', bare, re.I) is not None
        if STAGING and noindex:
            passes.append("Noindexed while the build is staging, like every page.")
        elif STAGING:
            fails.append("**The error page is not noindexed and the build is still staging.** "
                         "Run `scripts/sync-chrome.py`, which writes the tag from `STAGING`.")
        elif noindex:
            fails.append("**The error page is still noindexed and `STAGING` is off.** Run "
                         "`scripts/sync-chrome.py`, which removes it.")
        else:
            passes.append("No noindex tag: `STAGING` is off.")

        notes.append("Scored as the error page, not as a page: no canonical is expected on it "
                     "(one would claim this URL is the real version of something), and it is "
                     "deliberately absent from sitemap.xml and llms.txt.")

    if coverage is None:
        pass
    elif listed:
        fails.append(
            f"**Listed in `docs/sitemap.xml` at {own}, and it must not be.** A "
            + ("redirect stub is not a page; listing it asks Google to index a file whose only "
               "job is to point at another one."
               if kind == "redirect-stub" else
               "sitemap is a list of pages worth visiting, and an error page is not one.")
            + " Remove its `<url>` block.")
    else:
        passes.append(f"Correctly absent from `docs/sitemap.xml`: {own}")

    if kind == "redirect-stub":
        notes.append("Scored as a redirect stub, not as a page: no schema, no FAQ, no word count "
                     "and no llms.txt entry are expected on it.")
    return passes, warns, fails, notes




# THE EMPTY-HEADING CHECK. A heading with no words is announced by a
# screen reader as a heading with no name, and it is invisible by eye,
# which is how a WordPress leftover, an empty <h2> closing a migrated post,
# shipped on the founding build and was found only by a layout probe. A
# CRITICAL, by house ruling: nobody means to ship one. "Empty" is text content that is nothing but
# whitespace, no-break spaces included, which is what a reader hears.
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


class PageParser(HTMLParser):
    """Walks the HTML and collects everything the audit needs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        # An inline <svg> may carry its own <title>, which names the graphic,
        # not the page. Without this depth count its text was appended to the
        # page title, so an inline map would have silently lengthened the
        # measured title. Found while building a contact page's map.
        self._svg_depth = 0
        self._in_jsonld = False
        self.meta = {}            # name/property -> content
        self.h1s = []
        self._in_h1 = False
        self.jsonld_blocks = []
        self.images = []          # list of (src, alt-or-None)
        self.links_internal = 0
        self.links_external = 0
        self.canonical = None
        self.has_viewport = False
        self.contacts_linked = 0  # phone/email mentions inside tel:/mailto:
        self.contacts_bare = []   # (line, kind) for the ones that are not
        self._href_stack = []     # open <a> hrefs, innermost last
        self._skip_depth = 0      # inside <script>/<style>
        # Visible FAQ items, as (question, answer) of rendered text. The
        # house rule is that each one is byte-identical to its schema
        # twin, so this collects what a reader sees and the FAQ mirror
        # check compares it against the FAQPage node.
        self.faq_visible = []
        self._details_depth = 0
        self._in_summary = False
        self._in_faq_answer = False
        self._faq_q = None
        self._faq_a = None
        self._skip_faq_ico = 0    # the chevron <span>, art with no words
        # Every h1 to h6 as (tag, line, text), for the empty-heading check.
        # A stack rather than a flag, so a heading's text is its own even
        # if markup ever nests one inside another by mistake.
        self.headings = []
        self._heading_stack = []
        # The visible breadcrumb, as the rendered text of each <li> of the
        # first <nav> whose class names a crumb, for the crumb mirror
        # check. None when the page has no such nav; an empty list
        # when it has one this parser cannot read as a list.
        self.crumb_visible = None
        self._crumb_nav = 0       # depth inside the crumb nav, 0 outside
        self._crumb_done = False  # only the first crumb nav is read
        self._crumb_li = None     # the open item's text, or None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip_depth += 1
        if tag == "svg":
            self._svg_depth += 1
        if tag in HEADING_TAGS:
            self._heading_stack.append([tag, self.getpos()[0], ""])
        if tag == "nav":
            if self._crumb_nav:
                self._crumb_nav += 1
            elif not self._crumb_done and "crumb" in (a.get("class") or "").split():
                self._crumb_nav = 1
                self.crumb_visible = []
        if tag == "li" and self._crumb_nav:
            self._crumb_li = ""
        if tag == "title" and not self._svg_depth:
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self.h1s.append("")
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key.lower()] = a.get("content", "")
            if (a.get("name") or "").lower() == "viewport":
                self.has_viewport = True
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_jsonld = True
            self.jsonld_blocks.append("")
        elif tag == "img":
            self.images.append((a.get("src", ""), a.get("alt")))
        elif tag == "details":
            self._details_depth += 1
            self._faq_q, self._faq_a = None, None
        elif tag == "summary" and self._details_depth:
            self._in_summary = True
            self._faq_q = ""
        elif tag == "span" and self._in_summary and "faq-ico" in (a.get("class") or ""):
            self._skip_faq_ico += 1
        elif tag == "p" and self._details_depth and self._faq_a is None:
            self._in_faq_answer = True
            self._faq_a = ""
        elif tag == "a":
            href = a.get("href", "")
            self._href_stack.append(href)
            if href.startswith("http"):
                self.links_external += 1
            elif href and not href.startswith(("#", "mailto:", "tel:")):
                self.links_internal += 1

    def handle_endtag(self, tag):
        if tag == "li" and self._crumb_nav and self._crumb_li is not None:
            self.crumb_visible.append(" ".join(self._crumb_li.split()))
            self._crumb_li = None
        if tag == "nav" and self._crumb_nav:
            self._crumb_nav -= 1
            if not self._crumb_nav:
                self._crumb_done = True
        if tag in HEADING_TAGS and self._heading_stack and self._heading_stack[-1][0] == tag:
            self.headings.append(tuple(self._heading_stack.pop()))
        if tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "summary":
            self._in_summary = False
        elif tag == "span" and self._skip_faq_ico:
            self._skip_faq_ico -= 1
        elif tag == "p" and self._in_faq_answer:
            self._in_faq_answer = False
        elif tag == "details":
            if self._details_depth:
                self._details_depth -= 1
            if self._faq_q is not None:
                self.faq_visible.append((self._faq_q.strip(), (self._faq_a or "").strip()))
            self._faq_q, self._faq_a = None, None
        elif tag == "a":
            if self._href_stack:
                self._href_stack.pop()
        elif tag == "script":
            self._in_jsonld = False
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_h1 and self.h1s:
            self.h1s[-1] += data
        if self._in_jsonld and self.jsonld_blocks:
            self.jsonld_blocks[-1] += data
        if self._in_summary and not self._skip_faq_ico and self._faq_q is not None:
            self._faq_q += data
        if self._in_faq_answer and self._faq_a is not None:
            self._faq_a += data
        if self._skip_depth:
            return
        if self._crumb_li is not None and not self._svg_depth:
            self._crumb_li += data
        for h in self._heading_stack:
            h[2] += data
        if not NAP_CONTACT_RES:
            return
        linked = any(h.startswith(("tel:", "mailto:")) for h in self._href_stack)
        for kind, rx in NAP_CONTACT_RES:
            for _ in rx.finditer(data):
                if linked:
                    self.contacts_linked += 1
                else:
                    self.contacts_bare.append((self.getpos()[0], kind))


def load(source: str) -> str:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "SEO-Audit-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    with open(source, encoding="utf-8") as f:
        return f.read()


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def check_ai_access(base_url: str, warns: list, passes: list, notes: list):
    """AEO checks that only make sense against a LIVE site:
    is the site letting AI assistants' crawlers in, and does it offer
    an llms.txt guide for AI agents?

    These are properties of the SITE, not of any one page, so they run
    once per run and are reported in their own section. Running them per
    page would just refetch the same two files five more times."""
    parts = urlparse(base_url)
    root = f"{parts.scheme}://{parts.netloc}"

    # --- robots.txt: are AI crawlers blocked? ---
    # If these bots are blocked, the business is invisible to the AI
    # assistants a growing share of customers ask for recommendations.
    ai_bots = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "anthropic-ai",
               "PerplexityBot", "Google-Extended"]
    try:
        robots = load(root + "/robots.txt")
        blocked = []
        current_agents = []
        for line in robots.splitlines():
            line = line.split("#")[0].strip()
            if line.lower().startswith("user-agent:"):
                current_agents.append(line.split(":", 1)[1].strip())
            elif line.lower().startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path == "/":
                    for agent in current_agents:
                        for bot in ai_bots:
                            if bot.lower() == agent.lower():
                                blocked.append(bot)
            elif not line:
                current_agents = []
        if blocked:
            warns.append(f"**robots.txt blocks AI crawlers: {', '.join(sorted(set(blocked)))}.** "
                         "Blocked bots can't read the site, so AI assistants are less likely to "
                         "recommend this business. Unblock them unless the client explicitly wants out.")
        else:
            passes.append("AEO: robots.txt does not block the major AI crawlers (GPTBot, ClaudeBot, PerplexityBot, etc.).")
    except Exception:
        notes.append("Could not fetch robots.txt. If the site truly has none, crawlers default to full access (fine), but add one to be explicit.")

    # --- llms.txt: a curated guide for AI agents ---
    # Honest status (2026): Google says it ignores llms.txt, but Anthropic
    # recommends it, OpenAI publishes them, and Perplexity has been seen
    # reading them. It costs 20 minutes: cheap insurance, not a magic bullet.
    try:
        llms = load(root + "/llms.txt")
        if llms.strip():
            passes.append("AEO: llms.txt present, so AI agents get a curated guide to the business.")
    except Exception:
        notes.append("No llms.txt found. Optional (Google ignores it) but Anthropic/OpenAI agent "
                     "tooling reads it: a 20-minute add for extra AI visibility.")


def check_staging_local(passes: list, warns: list, notes: list, fails: list = None,
                        root: str = None):
    """The half of the staging exception that is a property of the SITE
    rather than of any page: docs/robots.txt and docs/llms.txt. The per-page
    half (the noindex tag and the visible banner) is in staging_page_findings.

    BOTH DIRECTIONS. While STAGING is True, robots.txt must disallow
    everything and llms.txt must say the site is not live. Once it is False,
    either one left behind is a CRITICAL: the pre-launch sweep simulated the
    flip on the founding build, and this check passed a site whose
    llms.txt still pointed assistants at the old site, because it only
    ever looked one way.

    SITE_DIR is resolved when this is CALLED, so the tests can point it at a
    temporary directory."""
    fails = fails if fails is not None else warns
    root = root or SITE_DIR
    path = os.path.join(root, "robots.txt")
    try:
        with open(path, encoding="utf-8") as f:
            body = "\n".join(line.split("#")[0] for line in f.read().splitlines())
    except OSError:
        body = None
        (warns if STAGING else notes).append(
            f"**No `{path}`.** While the build is staging this file is what stops a crawler "
            f"fetching the pages at all; the meta tags are the second line, not the first.")
    if body is not None:
        blocks_all = re.search(r"(?im)^\s*disallow:\s*/\s*$", body) is not None
        if STAGING and blocks_all:
            passes.append("`docs/robots.txt` disallows everything, which is correct while the "
                          "firm's real site is still live. It comes off at cutover, together with "
                          "the pages' noindex tags.")
        elif STAGING:
            warns.append("**`docs/robots.txt` does not disallow everything and the build is still "
                         "staging.** The pages are noindexed but nothing is stopping a crawler "
                         "reading them. Add `Disallow: /` under `User-agent: *`.")
        elif blocks_all:
            fails.append("**`docs/robots.txt` still disallows everything and `STAGING` is off.** "
                         "The site is live and invisible. This is the staging file; replace it with "
                         "the open one that names the sitemap and blocks no AI crawler.")
        elif not re.search(r"(?im)^\s*sitemap:\s*" + re.escape(SITE_BASE + "sitemap.xml") + r"\s*$",
                           body):
            warns.append("**`docs/robots.txt` is open but does not name the sitemap.** Add "
                         f"`Sitemap: {SITE_BASE}sitemap.xml`.")
        else:
            passes.append("`docs/robots.txt` is open and names the sitemap, so crawlers and AI "
                          "agents can read the site.")

    lpath = os.path.join(root, "llms.txt")
    try:
        with open(lpath, encoding="utf-8") as f:
            llms = f.read()
    except OSError:
        return
    marked = LLMS_STAGING_MARK.lower() in llms.lower()
    if STAGING and marked:
        passes.append("`docs/llms.txt` tells assistants this build is not live yet, which is "
                      "true until cutover.")
    elif STAGING:
        warns.append(f"**`docs/llms.txt` has lost its staging paragraph** (\"{LLMS_STAGING_MARK}\") "
                     "while the build is still staging. An assistant reading it would take this "
                     "build for the firm's live site.")
    elif marked or re.search(r"\bstaging\b", llms, re.I):
        fails.append("**`docs/llms.txt` still carries staging language and `STAGING` is off.** "
                     "It tells every assistant that reads it that this site is not the firm's "
                     "live site. Rewrite the staging paragraph as part of the cutover commit.")
    else:
        passes.append("`docs/llms.txt` carries no staging language.")


def staging_page_findings(html_text: str, is_stub: bool = False) -> tuple:
    """(passes, warns, fails) for one page's visible staging banner and, on
    a redirect stub, its noindex tag. A real page's noindex is scored in
    audit() itself, which has always run both ways.

    While STAGING is True a real page MISSING the banner warns: a human who
    opens a noindexed page should be told why. Once it is False, a banner is
    a CRITICAL, and so is a noindex left on a stub. Comments are stripped
    first, so a comment that mentions the banner is not the banner."""
    passes, warns, fails = [], [], []
    bare = re.sub(r"(?s)<!--.*?-->", " ", html_text)
    has_banner = STAGING_BANNER_RE.search(bare) is not None
    if is_stub:
        noindex = re.search(r'<meta\s+name="robots"[^>]*noindex', bare, re.I) is not None
        if not STAGING and noindex:
            fails.append("**This redirect stub is still noindexed and `STAGING` is off.** The "
                         "stub's noindex comes off with every page's at cutover. Run "
                         "`scripts/sync-chrome.py`.")
        if has_banner:
            fails.append("**A redirect stub carries the staging banner.** A stub stays bare.")
        return passes, warns, fails
    if STAGING and has_banner:
        passes.append("Carries the visible staging banner, so a human who opens it knows why "
                      "it is not indexed.")
    elif STAGING:
        warns.append("**No visible staging banner, and the build is still staging.** Run "
                     "`scripts/sync-chrome.py`, which writes it from `STAGING`.")
    elif has_banner:
        fails.append("**The staging banner is still on this page and `STAGING` is off.** Every "
                     "visitor to the live site is told it is not the live site. Run "
                     "`scripts/sync-chrome.py`, which removes it.")
    else:
        passes.append("No staging banner: `STAGING` is off and the page says nothing about it.")
    return passes, warns, fails


def icon_findings(html_text: str, page_rel: str, site_dir: str = None) -> tuple:
    """(passes, fails) for one real page's favicon links. Every
    ICON_LINKS entry must be linked from the head at the page's own relative
    path, and its file must exist under docs/. The founding build's
    pre-launch sweep found none on any page while the live site had one, so
    cutover would have dropped the mark Google shows beside every result."""
    site_dir = site_dir or SITE_DIR
    head = html_text.split("</head>", 1)[0]
    prefix = "../" * page_rel.count("/")
    missing = []
    for rel, attrs, path in ICON_LINKS:
        want = f'<link rel="{rel}"' + (f" {attrs}" if attrs else "") + f' href="{prefix}{path}">'
        if want not in head:
            missing.append(want)
        elif not os.path.isfile(os.path.join(site_dir, path)):
            missing.append(f"the file docs/{path}")
    if missing:
        return [], [f"**Favicon set incomplete: missing {'; '.join(f'`{m}`' for m in missing)}.** "
                    "Run `scripts/sync-chrome.py`; the files come from "
                    "`scripts/prepare-favicon.py`."]
    return [f"Links the firm's favicon set: {len(ICON_LINKS)} icon links, every file present."], []


def visible_text(html: str) -> str:
    """What a reader actually sees: comments, scripts and styles removed,
    tags stripped, entities decoded, whitespace collapsed. Comments come
    out FIRST and on purpose, so an explanatory comment that records an
    old number is not read as the page claiming it."""
    s = re.sub(r"(?s)<!--.*?-->", " ", html)
    s = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()


def find_review_counts(root: str = SITE_DIR) -> list:
    """Every visible review-count mention under docs/, as
    (path, count, snippet). Walks .html and .txt, because llms.txt is
    read by the same assistants the pages are written for and a number
    that disagrees there disagrees just as loudly."""
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith((".html", ".txt")):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                continue
            text = visible_text(raw) if name.endswith(".html") else raw
            for m in REVIEW_COUNT_RE.finditer(text):
                hits.append((path, int(m.group(1).replace(",", "")),
                             text[max(0, m.start() - 40):m.end() + 24].strip()))
    return hits


def find_rotting_comments(root: str = SITE_DIR) -> list:
    """Every HTML comment under docs/ that carries a number near the word
    "review", as (path, line, snippet). Whitespace is collapsed first, so
    a comment wrapped across five lines reads as one sentence and the
    "few words" window means what it says."""
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                continue
            for m in HTML_COMMENT_RE.finditer(raw):
                body = re.sub(r"\s+", " ", m.group(1)).strip()
                for hit in COMMENT_REVIEW_NUM_RE.finditer(body):
                    hits.append((path, raw.count("\n", 0, m.start()) + 1,
                                 hit.group(0).strip()))
    return hits


def check_comment_convention_local(warns: list, notes: list):
    """THE CONVENTION: a comment names `REVIEW_COUNT` and "the band's DOM
    order", never the literal count and never the literal order.

    NO `fails` LIST, ON PURPOSE. This check cannot raise a critical
    because it was never handed anywhere to put one. A rotting comment
    misleads the next person to read the file and costs a visitor
    nothing, so it must never stop a build, and a check that can only
    warn is one nobody has a reason to delete.
    """
    hits = find_rotting_comments()
    if not hits:
        notes.append(
            "**No HTML comment under `docs/` carries a literal review count.** The "
            "convention is that comments name `REVIEW_COUNT` and the band's DOM order "
            "rather than quoting either, so they stay true when the values change. "
            "`\\breview\\b` cannot match inside `REVIEW_COUNT`, so the approved "
            "spelling is the one this check cannot fire on.")
        return
    where = "; ".join(f"`{pth}` line {ln} (\"{snip}\")" for pth, ln, snip in hits[:6])
    more = "" if len(hits) <= 6 else f", and {len(hits) - 6} more"
    warns.append(
        f"**{len(hits)} HTML comment{'' if len(hits) == 1 else 's'} under `{SITE_DIR}/` "
        f"carr{'ies' if len(hits) == 1 else 'y'} a number next to the word \"review\": "
        f"{where}{more}.** The review-count check strips comments before it reads counts, "
        "so a number quoted in one can go stale with nothing to catch it, which is exactly "
        "what happened on the founding build. Rewrite it to name `REVIEW_COUNT` instead of quoting "
        "a value. This is a warning and it will never fail a build.")


def resolve_local_link(page_path: str, ref: str) -> str:
    """The file a relative reference points at, from the page holding it.
    A directory and an extensionless path both mean that folder's
    index.html, which is how this site's URLs work.

    SHARED ON PURPOSE. audit.py's pending-link inventory and
    test-audit-checks.py's no-dead-links test both call this, so the two
    directions of the same rule cannot drift apart by one resolving
    "../" differently from the other."""
    target = os.path.normpath(os.path.join(os.path.dirname(page_path),
                                           ref.split("?")[0].split("#")[0]))
    if os.path.isdir(target) or not os.path.splitext(target)[1]:
        target = os.path.join(target, "index.html")
    return target


def find_pending_links(root: str = SITE_DIR) -> list:
    """Every data-pending-href under docs/, as
    (path, line, href, target, ready). `ready` is True when the target
    file now exists, which means the wait is over and the element should
    have become a real link."""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                continue
            # COMMENTS COME OUT FIRST, the same way the dead-link scan
            # drops them. A pending attribute QUOTED IN A COMMENT is not a
            # pending attribute, it is an explanation of one, and on
            # the founding build an explanation of the mechanism tripped the
            # mechanism. The two halves of the link rule now agree about
            # what a comment is.
            raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
            for m in PENDING_HREF_RE.finditer(raw):
                href = m.group(1)
                target = resolve_local_link(path, href)
                out.append((path, raw.count("\n", 0, m.start()) + 1, href,
                            target, os.path.isfile(target)))
    return out


def check_pending_links_local(warns: list, notes: list):
    """THE INVENTORY OF WHAT IS WAITING, in every Monday report.

    A note, not a warning, while everything is genuinely still waiting:
    an unbuilt page is the plan working, not a defect. The gate is
    test-audit-checks.py, which fails the build the day a target exists
    and its element is still a span.
    """
    pend = find_pending_links()
    if not pend:
        notes.append(
            "**Nothing is waiting to become a link.** No element under "
            f"`{SITE_DIR}/` carries `data-pending-href`, so either every page "
            "this site references exists, or nothing references one that does not.")
        return

    ready = [x for x in pend if x[4]]
    by_href = {}
    for _path, _line, href, _target, is_ready in pend:
        by_href.setdefault(href, {"n": 0, "ready": is_ready})
        by_href[href]["n"] += 1

    lines = []
    for href in sorted(by_href):
        info = by_href[href]
        mark = " **<- BUILT, convert these to real links**" if info["ready"] else ""
        lines.append(f"  - `{href}`, {info['n']} element"
                     f"{'' if info['n'] == 1 else 's'}{mark}")
    body = "\n".join(lines)

    head = (f"**{len(pend)} element{'' if len(pend) == 1 else 's'} waiting to become "
            f"link{'' if len(pend) == 1 else 's'}**, across "
            f"{len({x[3] for x in pend})} target page"
            f"{'' if len({x[3] for x in pend}) == 1 else 's'}:")
    why = ("\n\nEach carries `data-pending-href` with the URL it becomes. They are "
           "not links yet because this site never writes a link to a page that has "
           "not been built, and each target above is still unbuilt. This is the plan "
           "working, not a defect. `scripts/test-audit-checks.py` fails the build "
           "from the day a target exists, so none of them can be forgotten.")
    if ready:
        why = ("\n\n**" + str(len(ready)) + " of them are ready now**: the target file "
               "exists, so the element should already be a real link. The link test is "
               "failing on this and will keep failing until it is converted." + why)
    notes.append(head + "\n" + body + why)


# --- Location-page variance, rule 7's gate --------------------------------
# The doctrine's rule 7: a location page exists only with verified variance
# against its hub and every sibling, under 30 percent shared vocabulary and
# no shared substantive H2. A page declares itself a location page with
#   <meta name="dky-page" content="town">
# and is compared with every other declared one and the hub, if the hub
# exists. With fewer than two pages it compares nothing, and says so.
#
# THE MEASURE, calibrated on the founding client build: THREE-WORD
# SHINGLES, CONTAINMENT, PLACE NAMES MASKED. Each page's substantive text is
# lowercased and every place name in TOWN_PLACE_NAMES, plus the page's own
# place from its slug, becomes one token; the text is cut into every run of
# three consecutive words; and a pair's figure is the phrases they share
# over the phrases of the SMALLER page. A pair at or over TOWN_SHARED_MAX
# fails.
#
# WHY NOT SINGLE WORDS: two honest pages about one business share their
# trade's words by necessity. Single-word overlap between honest sibling
# pages ran 46 to 65 percent on the founding build, and they were not
# lookalikes. The doorway problem is shared PHRASING, and three-word
# phrases separated it cleanly: 7 to 10 percent between honest service
# pages, 56 to 65 between a live site's town pages that differed by little
# more than the town's name. WHY MASKED: a copy with the name swapped must
# read as the copy it is. WHY CONTAINMENT, NOT JACCARD: a short page tucked
# inside a long one is a lookalike, and Jaccard would let the long one's
# extra text dilute it away.
#
# PATTERN TEXT IS DEFINED HERE, NEVER IN MARKUP. What the location template
# repeats on every page by design is left out of both measures: anything in
# a <nav>, the sections whose ids are in TOWN_PATTERN_SECTIONS, and the
# elements whose classes are in TOWN_PATTERN_CLASSES. A page cannot mark its
# own shared prose as pattern to escape the measure, because the list is
# not the page's to write. Everything else, the FAQ included, is compared.
# EMPTY until the location template exists; each entry is added with its
# reason when it is.
#
# THE H2 HALF compares substantive H2s literally, case and spacing aside,
# with no masking.
#
# THE GATE ON THE TIER ITSELF, from rule 7: new location pages are gated on
# Search Console evidence of real demand. Data decides, not guesses.
TOWN_KIND = "town"
# The hub, docs-relative, once pagemap.md names one. None until then.
TOWN_HUB_PATH = None
# A location page's own place, read off its slug. None until pagemap.md
# fixes the slug pattern; shape: re.compile(r"^prefix-(.+?)(?:-pa)?$").
TOWN_SLUG_RE = None
TOWN_PATTERN_SECTIONS = ()
TOWN_PATTERN_CLASSES = ()
TOWN_SHINGLE = 3
TOWN_SHARED_MAX = 0.30
# Every place name the location pages may carry, lowercase. Filled with the
# location pages.
TOWN_PLACE_NAMES = ()
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "source", "track", "wbr"}


class _TownText(HTMLParser):
    """The substantive text and H2s inside <main>, pattern text left out."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []           # [tag, skipping] per open element
        self.main = 0
        self.words = []
        self.h2s = []
        self._h2 = None

    def _skipping(self):
        return bool(self.stack) and self.stack[-1][1]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.main += 1
        if tag in _VOID:
            return
        classes = (a.get("class") or "").split()
        skip = (self._skipping() or tag in ("nav", "script", "style")
                or (tag == "section" and a.get("id") in TOWN_PATTERN_SECTIONS)
                or any(c in TOWN_PATTERN_CLASSES for c in classes))
        self.stack.append([tag, skip])
        if tag == "h2" and not skip:
            self._h2 = ""

    def handle_endtag(self, tag):
        if tag == "main" and self.main:
            self.main -= 1
        if tag == "h2" and self._h2 is not None:
            # An empty H2 is the empty-heading check's critical, not a
            # heading two pages can share.
            if self._h2.strip():
                self.h2s.append(" ".join(self._h2.split()))
            self._h2 = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.main or self._skipping():
            return
        self.words.append(data)
        if self._h2 is not None:
            self._h2 += data


def town_place_mask(text: str, own: tuple = ()) -> list:
    """Lowercased words with every place name, and the page's own place,
    reduced to one token, so a renamed copy reads as a copy."""
    t = text.lower().replace("’", "'")
    for name in sorted(set(TOWN_PLACE_NAMES) | set(own), key=len, reverse=True):
        t = re.sub(r"\b" + re.escape(name) + r"\b", " zzplace ", t)
    return re.findall(r"[a-z0-9']+", t)


def town_shingles(html_text: str, own: tuple = ()) -> tuple:
    p = _TownText()
    p.feed(html_text)
    w = town_place_mask(" ".join(p.words), own)
    grams = {" ".join(w[i:i + TOWN_SHINGLE]) for i in range(len(w) - TOWN_SHINGLE + 1)}
    return grams, p.h2s


def town_variance_findings(pages: dict) -> dict:
    """pages is {label: (html, own_names)}. Every pair is compared, the hub
    included when it is among them. Returns the shared substantive H2s and
    every pair's shared-phrase figure."""
    data = {k: town_shingles(h, own) for k, (h, own) in pages.items()}
    shared_h2, pairs = [], []
    keys = sorted(data)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ga, ha = data[a]
            gb, hb = data[b]
            common = {x.lower() for x in ha} & {x.lower() for x in hb}
            shared_h2 += [(a, b, h) for h in sorted(common)]
            small = min(len(ga), len(gb))
            pairs.append((a, b, len(ga & gb) / small if small else 1.0))
    return {"shared_h2": shared_h2, "pairs": pairs}


def own_town_names(path: str) -> tuple:
    """The place a location page is about, read off its slug by
    TOWN_SLUG_RE. Empty until the slug pattern is fixed."""
    if TOWN_SLUG_RE is None:
        return ()
    slug = os.path.basename(os.path.dirname(path))
    m = TOWN_SLUG_RE.match(slug)
    return (m.group(1).replace("-", " "),) if m else ()


def check_town_variance_local(passes: list, warns: list, fails: list, notes: list,
                              root: str = None):
    """Rule 7's variance, measured across every declared location page and
    the hub. A shared substantive H2 and a pair over the ceiling are
    criticals: this is the gate that stops the second location page
    shipping as a copy of the first."""
    root = root or SITE_DIR
    towns = {}
    kind_re = re.compile(r'<meta name="' + re.escape(PAGE_KIND_META) + r'" content="([^"]*)"')
    for dirpath, _dirs, files in os.walk(root):
        if "index.html" not in files:
            continue
        path = os.path.join(dirpath, "index.html")
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        m = kind_re.search(raw)
        if m and m.group(1).strip().lower() == TOWN_KIND:
            towns[os.path.relpath(path, root)] = (raw, own_town_names(path))
    hub = os.path.join(root, TOWN_HUB_PATH) if TOWN_HUB_PATH else None
    compared = dict(towns)
    if hub and os.path.isfile(hub):
        with open(hub, encoding="utf-8") as f:
            compared[TOWN_HUB_PATH] = (f.read(), ())
    if len(compared) < 2:
        notes.append(
            f"**Location variance: {len(towns)} location page{'' if len(towns) == 1 else 's'}"
            f"{', no hub' if not (hub and os.path.isfile(hub)) else ''}, so nothing to compare.** "
            f"The gate arms the day a second location page or the hub lands: no shared "
            f"substantive H2, and under {TOWN_SHARED_MAX:.0%} shared three-word phrases "
            f"between any two (rule 7).")
        return
    found = town_variance_findings(compared)
    for a, b, h in found["shared_h2"]:
        fails.append(f"**Location pages share a substantive H2:** `{a}` and `{b}` both carry "
                     f"“{h}”. Rule 7 forbids it; give each section its own heading.")
    over = [(a, b, r) for a, b, r in found["pairs"] if r >= TOWN_SHARED_MAX]
    for a, b, r in over:
        fails.append(f"**Location pages read as copies:** `{a}` and `{b}` share {r:.0%} of their "
                     f"three-word phrases, place names masked, against a ceiling under "
                     f"{TOWN_SHARED_MAX:.0%}. Rewrite one of them; the doctrine calls a page "
                     f"like this a doorway.")
    if not found["shared_h2"] and not over:
        worst = max(r for _a, _b, r in found["pairs"])
        passes.append(f"Location variance holds across {len(compared)} pages: no shared substantive "
                      f"H2, and the closest pair shares {worst:.0%} of its three-word phrases "
                      f"(ceiling under {TOWN_SHARED_MAX:.0%}).")


# --- The business node's one-list fields ----------------------------------
# THE SERVED LIST: ONE LIST, NOT TYPED PER PAGE. The shared business node's
# areaServed on every page is written from this by
# scripts/sync-area-served.py, and the audit fails any page whose node
# says otherwise. Rows are (type, name, the @id fragment of the area it
# sits in). EMPTY until the firm confirms where it serves; while empty the
# check does not run, and says so.
AREA_SERVED_BASE = SITE_BASE
AREA_SERVED = ()

# THE FIRM'S PROFILES: ONE LIST. The business node's sameAs on every page
# is written from this by scripts/sync-area-served.py, beside AREA_SERVED,
# and the audit fails any page whose node says otherwise. The Google
# Business Profile's Maps URL comes first and is the same value as the
# node's hasMap, which the check holds too.
#
# OFF. See FACTS_OFF. When filled, every profile is opened and confirmed
# as the firm's own, and the firm says so in writing. A stray duplicate
# profile is the firm's to retire, not ours to list.
GBP_MAP_URL = None
SAME_AS = None

# THE FOUNDING DATE. None until the firm confirms it in writing; years in
# practice is the proof-line class of claim. When filled ("YYYY" or
# "YYYY-MM"), scripts/sync-area-served.py writes it into every business
# node as foundingDate, and founding_findings holds visible text to it:
# any founding or tenure year must be this one, and THE YEAR NEVER SHARES A
# CLAUSE WITH A PLACE unless the firm has confirmed it stood in that place
# for all of that time (the fabrication-by-fusion test, rule 1).
FOUNDING_DATE = None
FOUNDING_YEAR = int(FOUNDING_DATE[:4]) if FOUNDING_DATE else None


def area_served_nodes() -> list:
    """The areaServed array every business node carries: the areas carry
    their @id, every place names the area it sits in."""
    out = []
    for kind, name, ref in AREA_SERVED:
        if kind == "AdministrativeArea":
            out.append({"@type": kind, "@id": AREA_SERVED_BASE + ref, "name": name})
        else:
            out.append({"@type": kind, "name": name,
                        "containedInPlace": {"@id": AREA_SERVED_BASE + ref}})
    return out


# --- The site chrome --------------------------------------------------
# The header and the footer are written by scripts/sync-chrome.py. Two
# checks hold them, across every real page:
#
#   IDENTITY. The chrome is the same on every page, compared with every
#   href and src resolved to the site path it lands on and the current-page
#   marking set aside. The marking is the ONE permitted difference, and it
#   is itself checked: a chrome link that lands on the page it sits on
#   carries aria-current="page", and no other link does.
#
#   RESOLUTION. Every chrome link lands on a real page under docs/ (not a
#   redirect stub), or is the firm's own phone or mailbox, or is one of
#   CHROME_EXTERNAL_URLS character for character.
#
# A redirect stub stays bare: chrome on a stub is a failure too.
CHROME_HEAD_RE = re.compile(r'(?s)<header class="nav">.*?</header>')
CHROME_FOOT_RE = re.compile(r'(?s)<footer class="site">.*?</footer>')
# The firm's own phone and mailbox, derived from the NAP so they cannot
# drift from it. None while the NAP is OFF.
CHROME_TEL = f"tel:{NAP_PHONE_TEL}" if NAP_PHONE_TEL else None
CHROME_MAILTO = f"mailto:{NAP_EMAIL}" if NAP_EMAIL else None


def _chrome_page_url(rel_path: str) -> str:
    d = os.path.dirname(rel_path).replace(os.sep, "/")
    return "/" if d in ("", ".") else f"/{d}/"


def chrome_findings(pages: dict) -> dict:
    """pages maps a docs-relative path ("index.html", "blog/index.html") to
    its HTML. Returns {"missing": [...], "marking": [...], "differs": [...],
    "links": [...], "stub_chrome": [...], "forms": int}."""
    from urllib.parse import urljoin
    from html import escape as _esc
    out = {"missing": [], "marking": [], "differs": [], "links": [], "stub_chrome": [], "forms": 0}
    real = {}
    for rel, raw in pages.items():
        if REFRESH_RE.search(raw):
            if CHROME_HEAD_RE.search(raw) or CHROME_FOOT_RE.search(raw) or 'class="nav"' in raw:
                out["stub_chrome"].append(rel)
            continue
        real[rel] = raw
    live = {_chrome_page_url(r) for r in real}
    forms = {}
    for rel, raw in sorted(real.items()):
        h, f = CHROME_HEAD_RE.findall(raw), CHROME_FOOT_RE.findall(raw)
        if len(h) != 1 or len(f) != 1:
            out["missing"].append(rel)
            continue
        here = _chrome_page_url(rel)
        chrome = re.sub(r"(?s)<!--.*?-->", "", h[0] + f[0])
        for m in re.finditer(r"<a\b[^>]*>", chrome):
            tag = m.group(0)
            hm = re.search(r'\bhref="([^"]*)"', tag)
            href = unescape(hm.group(1)) if hm else ""
            current = 'aria-current="page"' in tag
            if href.startswith(("http://", "https://")):
                if href not in CHROME_EXTERNAL_URLS:
                    out["links"].append((rel, href))
                if current:
                    out["marking"].append((rel, href, "an external link marked as the current page"))
                continue
            if href and href in (CHROME_TEL, CHROME_MAILTO):
                continue
            if not href or href.startswith(("#", "javascript:", "tel:", "mailto:")):
                out["links"].append((rel, href or "(no href)"))
                continue
            target = urljoin(here, href)
            if target not in live:
                out["links"].append((rel, href))
            if (target == here) != current:
                out["marking"].append((rel, href, "lands on this page without aria-current" if not current
                                       else "carries aria-current but lands elsewhere"))

        def norm_attr(m):
            v = unescape(m.group(2))
            if not v.startswith(("http://", "https://", "tel:", "mailto:", "#")):
                v = urljoin(here, v)
            return f'{m.group(1)}="{_esc(v, quote=True)}"'
        norm = re.sub(r'\b(href|src)="([^"]*)"', norm_attr, chrome)
        norm = re.sub(r'\s+aria-current="page"', "", norm)
        norm = re.sub(r"\s+", " ", norm).strip()
        forms.setdefault(norm, []).append(rel)
    out["forms"] = len(forms)
    if len(forms) > 1:
        major = max(forms.values(), key=len)
        for pgs in forms.values():
            if pgs is not major:
                out["differs"].extend(pgs)
    return out


def check_chrome_local(passes: list, fails: list, root: str = None):
    root = root or SITE_DIR
    pages = {}
    for dirpath, _dirs, files in os.walk(root):
        if "index.html" in files:
            path = os.path.join(dirpath, "index.html")
            with open(path, encoding="utf-8") as f:
                pages[os.path.relpath(path, root)] = f.read()
    if not pages:
        return
    found = chrome_findings(pages)
    for rel in found["missing"]:
        fails.append(f"**`{rel}` carries no site chrome,** or more than one header or footer. "
                     f"Run `scripts/sync-chrome.py`.")
    for rel in found["differs"]:
        fails.append(f"**`{rel}`'s header or footer differs from every other page's.** The chrome "
                     f"is identical on every page but for the current-page marking; run "
                     f"`scripts/sync-chrome.py` rather than editing a page's chrome by hand.")
    for rel, href, why in found["marking"]:
        fails.append(f"**`{rel}`: the chrome link `{href}` {why}.** The current page is the one "
                     f"thing the chrome may mark, and it must mark it exactly.")
    for rel, href in found["links"]:
        fails.append(f"**`{rel}`: the chrome link `{href}` lands nowhere real.** Every nav and "
                     f"footer link must reach a page under docs/ or a recorded URL "
                     f"(`CHROME_EXTERNAL_URLS`), character for character.")
    for rel in found["stub_chrome"]:
        fails.append(f"**`{rel}` is a redirect stub carrying site chrome.** A stub stays bare.")
    if not any(found[k] for k in ("missing", "differs", "marking", "links", "stub_chrome")):
        n = sum(1 for r in pages.values() if not REFRESH_RE.search(r))
        passes.append(f"The site chrome is identical on all {n} pages but for the current-page "
                      f"marking, which is exact, and every nav and footer link lands on a real "
                      f"page or a recorded URL.")


class _CardGroups(HTMLParser):
    """Every service card inside <main>, grouped by the element that holds
    it. A card is anything whose class names svc-card and whose href or
    data-pending-href lands on a service page. Each card's first h3 and
    first p are read too, so its words answer to SERVICES."""
    VOID = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "col", "embed", "track"}

    def __init__(self, page_rel: str):
        super().__init__(convert_charrefs=True)
        self.page_rel, self.stack, self.n, self.inmain = page_rel, [], 0, False
        self.groups = {}
        self.cards = []          # [target, h3 text, p text]
        self.card_depth = None   # stack depth of the open card
        self.field = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.inmain = True
        cls = (a.get("class") or "").split()
        href = a.get("href") if a.get("href") is not None else a.get("data-pending-href")
        if self.inmain and "svc-card" in cls and href is not None and self.stack:
            target = self.page_rel if href == "./" else \
                posixpath.normpath(posixpath.join("/" + self.page_rel, href)).strip("/") + "/"
            if target in SERVICE_PATHS:
                parent = self.stack[-1]
                self.groups.setdefault(parent, []).append(target)
                self.cards.append([target, None, None])
                self.card_depth = len(self.stack)
        if self.card_depth is not None and tag in ("h3", "p"):
            i = 1 if tag == "h3" else 2
            if self.cards[-1][i] is None:
                self.cards[-1][i] = ""
                self.field = i
        if tag not in self.VOID:
            self.n += 1
            self.stack.append((self.n, tag, a.get("id") or "", " ".join(cls)))

    def handle_data(self, data):
        if self.field is not None:
            self.cards[-1][self.field] += data

    def handle_endtag(self, tag):
        if tag == "main":
            self.inmain = False
        if tag in ("h3", "p"):
            self.field = None
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k][1] == tag:
                del self.stack[k:]
                if self.card_depth is not None and k <= self.card_depth:
                    self.card_depth = None
                break


def _main_text_units(html_text: str) -> list:
    """<main>'s visible text one block at a time, so a heading or a list
    item never runs into its neighbour and forms a sentence nobody wrote."""
    m = re.search(r"(?is)<main\b[^>]*>(.*)</main>", html_text)
    body = m.group(1) if m else ""
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", " ", body)
    body = re.sub(r"(?i)</?(p|li|h[1-6]|summary|figcaption|td|th|dt|dd|div|section|article|ul|ol|a)\b[^>]*>", "\n", body)
    out = []
    for block in visible_text_blocks(body):
        out += [s for s in re.split(r"(?<=[.!?])\s+", block) if s]
    return out


def visible_text_blocks(body: str) -> list:
    return [re.sub(r"\s+", " ", unescape(re.sub(r"(?s)<[^>]+>", " ", b))).strip()
            for b in body.split("\n") if re.sub(r"(?s)<[^>]+>", "", b).strip()]


def service_enumeration_findings(html_text: str, page_rel: str, meta: str = "") -> tuple:
    """(enumerations found, problems). Three shapes, each held to the full
    family in SERVICES: a group of service cards under one parent, a count
    typed beside "services", and one sentence naming all but one of the
    family or more, in words. The chrome is not read here; check_chrome_local
    holds it, and it is generated from the same list. Nothing is read while
    SERVICES is empty: an empty family is no family to hold a page to."""
    found, problems = 0, []
    if not SERVICES:
        return found, problems
    want = len(SERVICES)
    p = _CardGroups(page_rel)
    p.feed(html_text)
    # A SERVICE PAGE'S OWN GRID IS ITS RELATED SERVICES: the family minus
    # itself minus RELATED_LEAVES_OUT. Anywhere else a grid is
    # the whole family.
    on_service = page_rel in SERVICE_PATHS
    expect = [x for x in SERVICE_PATHS
              if not on_service or (x != page_rel and x not in RELATED_LEAVES_OUT)]
    label = {x: lbl for x, lbl, _ln in SERVICES}
    for (_n, tag, gid, gcls), targets in p.groups.items():
        if len(set(targets)) < 2:
            continue
        found += 1
        missing = [label[x] for x in expect if x not in targets]
        where = f"<{tag}{' id=' + gid if gid else ''}{' class=' + gcls if gcls else ''}>"
        if missing:
            problems.append(f"the service cards in {where} lack {', '.join(missing)}")
        if page_rel in targets:
            problems.append(f"the service cards in {where} carry {label[page_rel]}, the page they sit on; "
                            f"a service page's grid is the family minus itself")
        left_out = [label[x] for x in RELATED_LEAVES_OUT if on_service and x != page_rel and x in targets]
        if left_out:
            problems.append(f"the service cards in {where} carry {', '.join(left_out)}, which the Related "
                            f"Services list leaves out (RELATED_LEAVES_OUT)")
        dup = sorted({x for x in targets if targets.count(x) > 1})
        if dup:
            problems.append(f"the service cards in {where} repeat {', '.join(dup)}")
    # EVERY CARD SAYS WHAT ITS ROW SAYS: one rendering per service.
    for target, h3, para in p.cards:
        row = next(r for r in SERVICES if r[0] == target)
        got = (" ".join((h3 or "").split()), " ".join((para or "").split()))
        if got != (row[1], row[2]):
            problems.append(f"the card for {target} reads \u201c{got[0]}\u201d / \u201c{got[1]}\u201d; "
                            f"SERVICES says \u201c{row[1]}\u201d / \u201c{row[2]}\u201d")
    units = _main_text_units(html_text) + ([meta] if meta else [])
    for u in units:
        for m in SERVICE_COUNT_RE.finditer(u):
            found += 1
            w = m.group(1).lower()
            n = int(w) if w.isdigit() else COUNT_WORDS.index(w)
            if n != want:
                problems.append(f"\u201c{m.group(0)}\u201d counts {n} services; the family is {COUNT_WORDS[want]}")
        # The business name is removed first, because a firm name that
        # contains a service's words is not a service.
        s = u.replace(NAP_NAME, "") if NAP_NAME else u
        named = [path for path, rx in SERVICE_TEXT_RE.items() if rx.search(s)]
        # Never fewer than two: one service named in a sentence is a
        # mention, not an enumeration, however small the family.
        if len(named) >= max(2, len(SERVICES) - 1):
            found += 1
            missing = [lbl for path, lbl, _ln in SERVICES if path not in named]
            if missing:
                problems.append(f"\u201c{u[:110]}\u201d names {len(named)} services in words and not "
                                f"{', '.join(missing)}")
    return found, problems


# A SERVICE CARD PREVIEWS ITS PAGE, house precedent from the founding
# build. A card that carries a photograph carries THE IMAGE ITS TARGET PAGE
# PRESENTS AS ITS OWN PREVIEW: the page's og:image, with og:image:width,
# og:image:height and og:image:alt, verbatim. That is the hero everywhere
# except where a page deliberately carries a clean preview crop, and that
# exception is the point: whatever was ruled out of a link preview stays
# off the card too. One rule, no per-card forks.
# scripts/sync-service-cards.py writes it from preview_of(); this holds it.
# A card with no image is not read.
_ATTR_RE = re.compile(r'([a-zA-Z-]+)="([^"]*)"')
_OG_RE = re.compile(r'<meta property="og:image(|:width|:height|:alt)" content="([^"]*)">')
_CARD_IMG_RE = re.compile(r'(?s)<a class="svc-card" href="([^"]+)">\s*(<img\b[^>]*>)')


def preview_of(page_rel: str, site_dir: str = None):
    """A page's own preview image, from its og:image tags, as {src
    (docs-relative), alt (raw, as written), width, height}, or None if the
    page carries no og:image."""
    path = os.path.join(site_dir or SITE_DIR, page_rel, "index.html")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    og = dict(_OG_RE.findall(text))
    if not og.get(""):
        return None
    src = urllib.parse.urlparse(og[""]).path.lstrip("/")
    return {"src": src, "alt": og.get(":alt"), "width": og.get(":width"), "height": og.get(":height")}


def card_image_findings(html_text: str, page_rel: str, site_dir: str = None) -> tuple:
    """(cards with an image, problems). Every such card's image must be its
    target service page's own preview: file, width, height and alt."""
    m = re.search(r"(?s)<main\b.*?</main>", html_text)
    n, problems = 0, []
    for href, tag in _CARD_IMG_RE.findall(m.group(0) if m else ""):
        target = posixpath.normpath(posixpath.join("/" + page_rel, href)).strip("/") + "/"
        if target not in SERVICE_PATHS:
            continue
        n += 1
        want = preview_of(target, site_dir)
        if want is None:
            problems.append(f"the card for {target} carries an image, and {target} has no og:image to preview")
            continue
        a = dict(_ATTR_RE.findall(tag))
        src = posixpath.normpath(posixpath.join("/" + page_rel, a.get("src", ""))).lstrip("/")
        for k, got, exp in (("image", src, want["src"]), ("alt", a.get("alt"), want["alt"]),
                            ("width", a.get("width"), want["width"]), ("height", a.get("height"), want["height"])):
            if got != exp:
                problems.append(f"the card for {target} has {k} \u201c{got}\u201d; its page's og:image has "
                                f"\u201c{exp}\u201d")
    return n, problems


def check_service_count_llms_local(passes: list, fails: list, root: str = None):
    """llms.txt tells AI agents how many services a page shows. The count
    word answers to the family, the same as on a page. Not read while
    SERVICES is empty."""
    if not SERVICES:
        return
    path = os.path.join(root or SITE_DIR, "llms.txt")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return
    text = re.sub(r"\s+", " ", text)
    bad, n = [], 0
    for m in SERVICE_COUNT_RE.finditer(text):
        n += 1
        w = m.group(1).lower()
        if (int(w) if w.isdigit() else COUNT_WORDS.index(w)) != len(SERVICES):
            bad.append(m.group(0))
    for x in sorted(set(bad)):
        fails.append(f"**`llms.txt` says \u201c{x}\u201d {bad.count(x)} time(s); the family in SERVICES is "
                     f"{COUNT_WORDS[len(SERVICES)]}.** Derive the word from the list.")
    if n and not bad:
        passes.append(f"`llms.txt` counts the services as the family does, {COUNT_WORDS[len(SERVICES)]}, "
                      f"in all {n} mentions.")


# --- The redirect table --------------------------------------------------
# pagemap.md's redirect column, as data: every old URL that 301s, and where.
# On the founding build a pre-launch sweep found nine of eleven planned
# redirects with no stub at all, because nothing compared the map with
# docs/. This does, both ways: every row has a stub whose canonical is its
# target, and every stub under docs/ is a row. HONEST_404S are the old URLs
# the map answers with a 404, and nothing may stand at them.
#
# EMPTY: pagemap.md is not written yet. Every redirect is approved in
# writing by the named partner before it ships, and that approval is
# recorded with the approver's name. Change pagemap.md first, then this
# table, then the stubs. While the table is empty, any stub standing in
# docs/ fails as unlisted, which is the point.
REDIRECTS = {}
HONEST_404S = ()


def redirect_table_findings(root: str = None) -> list:
    """Every way docs/ and the redirect table disagree, as sentences."""
    root = root or SITE_DIR
    out = []
    stubs = {}
    for dirpath, _dirs, files in os.walk(root):
        if "index.html" in files:
            path = os.path.join(dirpath, "index.html")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if REFRESH_RE.search(text):
                rel = os.path.relpath(dirpath, root).replace(os.sep, "/") + "/"
                stubs[rel] = text
    for old, target in REDIRECTS.items():
        text = stubs.get(old)
        if text is None:
            out.append(f"/{old} redirects to /{target} on the map and has no stub in docs/")
            continue
        m = re.search(r'<link\s+rel="canonical"\s+href="([^"]*)"', text)
        if not m or m.group(1) != SITE_BASE + target:
            out.append(f"/{old}'s stub points at {m.group(1) if m else 'nothing'}, the map says "
                       f"{SITE_BASE + target}")
        if not os.path.isfile(os.path.join(root, target, "index.html")):
            out.append(f"/{old} redirects to /{target}, which is not a page in docs/")
    for rel in sorted(set(stubs) - set(REDIRECTS)):
        out.append(f"/{rel} is a stub in docs/ that the redirect table does not list")
    for rel in HONEST_404S:
        if os.path.exists(os.path.join(root, rel)):
            out.append(f"/{rel} is an honest 404 on the map and something stands at it in docs/")
    return out


def check_redirects_local(passes: list, fails: list, root: str = None):
    found = redirect_table_findings(root)
    if found:
        fails.append("**docs/ and the redirect table (`REDIRECTS`, pagemap.md's redirect "
                     "column) disagree:** " + "; ".join(found) + ".")
    else:
        passes.append(f"Every one of the {len(REDIRECTS)} redirects on the map has its stub, "
                      f"pointing where the map says, every stub is on the map, and the "
                      f"{len(HONEST_404S)} honest 404s stay empty.")


def check_name_llms_local(passes: list, fails: list, root: str = None):
    """llms.txt names the firm as NAP_NAME and nothing else. An assistant
    reads this file for the name it will repeat. Not read while the name
    check is OFF."""
    if NAME_MENTION_RE is None or not NAP_NAME:
        return
    path = os.path.join(root or SITE_DIR, "llms.txt")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    bad = name_variants(text)
    if bad:
        fails.append(f"**`llms.txt` writes the business name {', '.join(sorted(set(f'`{b}`' for b in bad)))}, "
                     f"not `{NAP_NAME}`.** It is the file assistants read for the name they repeat.")
    else:
        n = name_mentions(text)
        passes.append(f"`llms.txt` names the firm as `{NAP_NAME}` in all {n} mentions.")


# A tenure claim: a year in one clause with an ownership or founding word,
# or "since" a year. A place: one of FOUNDING_PLACE_WORDS (the firm's
# street, town and county, filled with the NAP), or a word that points at
# a spot. The clause is cut at . ; : ! ? and the comma, and
# the text at block elements, so a stat's numeral and its label are one
# unit and two neighbouring stats are not.
FOUNDING_CUE_RE = re.compile(
    r"(?i)\b(?:family|owned|founded|founding|established|opened|est\.)|\bsince\s+(?:[A-Za-z]+\s+)?(?:1[89]|20)\d\d\b")
FOUNDING_YEAR_RE = re.compile(r"\b((?:1[89]|20)\d\d)\b")
FOUNDING_PLACE_WORDS = ()
FOUNDING_PLACE_RE = re.compile(
    r"(?i)\b(?:" + "".join(re.escape(w) + "|" for w in FOUNDING_PLACE_WORDS)
    + r"Pennsylvania|PA|here|location|address|building|street|corner|office)\b")
_BLOCK_TAG_RE = re.compile(
    r"(?i)</?(?:p|div|li|ul|ol|h[1-6]|section|article|header|footer|nav|main|td|th|tr|"
    r"dd|dt|figcaption|blockquote|br|aside|summary|details|button|label)\b[^>]*>")


def founding_findings(text: str, is_html: bool = True) -> tuple:
    """(founding-year mentions, problems). Every tenure claim's year must be
    FOUNDING_YEAR, and no clause carrying it may name a place, nor may the
    clause right after it open on "here", "in", "on" or "at" and name one
    ("since 1980, here in Wilkes-Barre"). THE LIMIT: it reads years. "For
    decades ... right here in Wilkes-Barre" names no year and is not read.
    Nothing is read while FOUNDING_DATE is unset."""
    if FOUNDING_YEAR is None:
        return 0, []
    if is_html:
        t = re.sub(r"(?is)<!--.*?-->|<(script|style)\b[^>]*>.*?</\1\s*>", " ", text)
        t = _BLOCK_TAG_RE.sub("\x00", re.sub(r"\s+", " ", t))
        t = re.sub(r"(?s)<[^>]+>", " ", t)
        blocks = unescape(t).split("\x00")
    else:
        blocks = re.split(r"\n\s*\n", text)
    n, problems = 0, []
    for block in blocks:
        b = " ".join(block.replace("\u00a0", " ").replace(">", " ").split())
        clauses = [c.strip() for c in re.split(r"[.;:!?,](?=\s|$)", b)]
        for i, c in enumerate(clauses):
            years = FOUNDING_YEAR_RE.findall(c)
            if not years or not FOUNDING_CUE_RE.search(c):
                continue
            for y in years:
                if int(y) != FOUNDING_YEAR:
                    problems.append(f"a tenure year other than {FOUNDING_YEAR}: \u201c{c}\u201d")
            if str(FOUNDING_YEAR) not in years:
                continue
            n += 1
            nxt = clauses[i + 1] if i + 1 < len(clauses) else ""
            if FOUNDING_PLACE_RE.search(c) or (
                    re.match(r"(?i)(?:right\s+)?(?:here|in|on|at)\b", nxt)
                    and FOUNDING_PLACE_RE.search(nxt)):
                problems.append(f"the founding year fused with a place: \u201c{c}"
                                f"{', ' + nxt if nxt and not FOUNDING_PLACE_RE.search(c) else ''}\u201d")
    return n, problems


def check_founding_llms_local(passes: list, fails: list):
    """llms.txt states the founding year to AI agents, so it answers to the
    same rule as every page."""
    try:
        with open(LLMS_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    n, problems = founding_findings(text, is_html=False)
    for x in problems:
        fails.append(f"**`{LLMS_PATH}`: {x}.** The founding claim is the date as the firm "
                     f"confirmed it (FOUNDING_DATE); a place beside it is a second claim.")
    if n and not problems:
        passes.append(f"`{LLMS_PATH}` states the founding year as {FOUNDING_YEAR}, unfused.")


def check_hours_llms_local(passes: list, fails: list):
    """docs/llms.txt states the hours to AI agents, so it answers to the
    same constants as every page. Same test, same severity."""
    try:
        with open(LLMS_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    n_ok, strays, banned = hours_findings(text)
    for x in strays:
        fails.append(f"**`{LLMS_PATH}` writes the hours a second way:** \u201c{x}\u201d. "
                     f"It must say {' and '.join(f'`{c}`' for c in HOURS_CANON)} exactly.")
    for x in banned:
        fails.append(f"**`{LLMS_PATH}` mentions a day the record has no hours for:** "
                     f"\u201c{x}\u201d.")
    if n_ok and not strays and not banned:
        passes.append(f"`{LLMS_PATH}` states the hours exactly as the constants do.")


def check_review_count_local(passes: list, warns: list, fails: list,
                             notes: list, today: date = None):
    """THE REVIEW COUNT, ENFORCED RATHER THAN REMEMBERED.

    Two failures, and they are different in kind:

    DISAGREEMENT IS A CRITICAL. Two different review counts on one site
    is one of them being wrong, and a visitor cannot tell which. Once
    REVIEW_COUNT is set it counts as one of the instances, so a page that
    drifts from the constant fails even when it is the only page saying
    anything. WHILE IT IS OFF, pages are still held to each other.

    AGE IS A WARNING. Past REVIEW_STALE_DAYS the number is not known to be
    wrong, it is only no longer known to be right, and the fix is to read
    the profile again rather than to edit the page.

    Local runs only. It reads files under docs/, and on a live run the
    target is the firm's WordPress site, where these files are not what
    is being audited.
    """
    today = today or date.today()
    hits = find_review_counts()

    counts = {}
    for path, n, snip in hits:
        counts.setdefault(n, []).append((path, snip))

    if REVIEW_COUNT is None:
        if len(counts) > 1:
            where = "; ".join(
                f"**{n}** in " + ", ".join(sorted({f"`{pth}`" for pth, _ in counts[n]}))
                for n in sorted(counts))
            fails.append(
                f"**The site states {len(counts)} different review counts: {where}.** "
                "One business has one review count. The review-count constant is OFF "
                "until the firm confirms it, so no count should be on a page yet at all.")
        elif hits:
            warns.append(
                f"**A review count is published ({sorted(counts)[0]}) while the review-count "
                f"check is OFF.** {len(hits)} place{'' if len(hits) == 1 else 's'} under "
                f"`{SITE_DIR}/` state it, and nothing recorded says the firm confirmed it or "
                "when it was read. Take it off the page, or record it in `REVIEW_COUNT` with "
                "the date and the reader.")
        return

    try:
        counted_on = date.fromisoformat(REVIEW_COUNTED_ON)
    except ValueError:
        fails.append(f"**`REVIEW_COUNTED_ON` is not a date** (`{REVIEW_COUNTED_ON}`). "
                     "It has to be ISO `YYYY-MM-DD`, because the staleness check "
                     "subtracts it from today.")
        return

    seen = dict(counts)
    seen.setdefault(REVIEW_COUNT, []).append(("scripts/audit.py", f"REVIEW_COUNT = {REVIEW_COUNT}"))
    distinct = sorted(seen)

    if len(distinct) > 1:
        where = "; ".join(
            f"**{n}** in " + ", ".join(sorted({f"`{pth}`" for pth, _ in seen[n]}))
            for n in distinct)
        fails.append(
            f"**The site states {len(distinct)} different review counts: {where}.** "
            "One business has one review count, and a visitor who spots two has no way "
            "to tell which is the real one. Read the Google Business Profile, then "
            "update `REVIEW_COUNT`, `REVIEW_COUNTED_ON` and every page in one commit.")
    elif not hits:
        notes.append(
            f"**No page states a review count.** `REVIEW_COUNT` is {REVIEW_COUNT}, recorded "
            f"{REVIEW_COUNTED_ON}, and nothing publishes it yet. Nothing to disagree.")

    age = (today - counted_on).days
    if age < 0:
        warns.append(
            f"**`REVIEW_COUNTED_ON` is in the future** ({REVIEW_COUNTED_ON}, {-age} day"
            f"{'' if -age == 1 else 's'} from now). One of the date and the clock is wrong.")
    elif age > REVIEW_STALE_DAYS:
        warns.append(
            f"**The review count is {age} days old.** {REVIEW_COUNT} reviews and "
            f"{REVIEW_RATING} stars were counted on {REVIEW_COUNTED_ON}, and anything past "
            f"{REVIEW_STALE_DAYS} days is a guess rather than a reading. Open the Google "
            "Business Profile, read the current count, and update the constants and the "
            "pages together. This is a warning, not a critical: the number is not known "
            "to be wrong, it is no longer known to be right.")
    elif hits:
        notes.append(
            f"**Review count agrees everywhere and is {age} day{'' if age == 1 else 's'} old.** "
            f"{REVIEW_COUNT} reviews and {REVIEW_RATING} stars, counted {REVIEW_COUNTED_ON}, "
            f"stated identically in {len(hits)} place{'' if len(hits) == 1 else 's'} under "
            f"`{SITE_DIR}/`. Visible text only: there is no review or rating markup on this "
            "site, deliberately.")


def read_asset_provenance(path: str) -> dict:
    """What one image file says about where it came from.

    Returns the DigitalSourceType, the CreatorTool and whether a C2PA
    manifest is referenced, plus a verdict. A C2PA manifest on its own
    is not a tell: legitimate stock carries one too, and it is the
    assertion inside the label that matters, not the presence of a
    label.

    The whole file is scanned as latin-1 rather than only its metadata
    segments. Parsing JPEG APP markers, PNG chunks, WebP RIFF and AVIF
    boxes correctly is four parsers and a dependency, and the strings
    being matched are long enough that compressed pixel data producing
    one by chance is not a thing that happens. The failure direction is
    also the safe one: a false positive stops a build and gets read by
    a person, a false negative ships an AI asset.
    """
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("latin-1", "replace")

    source_type = ""
    for m in SOURCE_TYPE_RE.finditer(text):
        val = m.group(1).strip()
        if val:
            source_type = val
            if val.lower() in AI_SOURCE_TYPES:
                break

    tool = ""
    for m in CREATOR_TOOL_RE.finditer(text):
        val = m.group(1).strip()
        if val:
            tool = val
            if AI_TOOL_RE.search(val):
                break

    reasons = []
    if source_type.lower() in AI_SOURCE_TYPES:
        reasons.append(f"IPTC DigitalSourceType is `{source_type}`")
    if tool and AI_TOOL_RE.search(tool):
        reasons.append(f"CreatorTool is `{tool}`")
    # A generator named anywhere else in the metadata counts too. The
    # side-view candidate hid in the tool field; the next one may not.
    if not reasons:
        loose = AI_TOOL_RE.search(text)
        if loose:
            reasons.append(f"the file carries the string `{loose.group(0)}`")

    return {
        "path": path,
        "bytes": len(raw),
        "source_type": source_type,
        "tool": tool,
        "c2pa": "cai-manifests.adobe.com" in text or "c2pa" in text.lower(),
        "reasons": reasons,
    }


def find_assets(root: str = None) -> list:
    """Every raster image under docs/, with its provenance read.

    SITE_DIR is resolved when this is CALLED and not when it is
    defined, because a default argument binds once at import and the
    tests point the check at a temporary directory.
    """
    root = root or SITE_DIR
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.lower().endswith(ASSET_EXTS):
                try:
                    out.append(read_asset_provenance(os.path.join(dirpath, name)))
                except OSError:
                    continue
    return sorted(out, key=lambda a: a["path"])


def check_asset_provenance_local(passes: list, warns: list, fails: list,
                                 notes: list):
    """AN AI-GENERATED IMAGE IS A CRITICAL, not a warning.

    Rule 9 bans AI imagery outright, so the threshold here is not a
    judgement call this script gets to make. It is also the cheapest
    possible thing to get wrong: the metadata that gives an asset away is
    invisible in every image viewer, a C2PA manifest is readable by anyone
    who opens the published file, and the firm that tells clients real
    beats stock has to live by it.

    Local runs only, like the rest of these. On a live run the target
    is the WordPress site and there are no files to read.
    """
    assets = find_assets()
    if not assets:
        notes.append(
            f"**No raster images under `{SITE_DIR}/`.** Nothing to check yet. Every "
            "licensed asset gets its metadata read before it lands, and this is what "
            "reads it.")
        return

    bad = [a for a in assets if a["reasons"]]
    if bad:
        for a in bad:
            fails.append(
                f"**`{a['path']}` is AI-generated: " + "; ".join(a["reasons"]) + ".** "
                "Rule 9 allows no AI imagery. Do not strip the "
                "label to make it pass: the provenance is the fact, the label is only "
                "where it is written down, and removing it is a lie about the asset "
                "plus a licence breach. Replace the file with one whose source is a "
                "camera or a person at a workstation.")

    clean = [a for a in assets if not a["reasons"]]
    if clean:
        labelled = [a for a in clean if a["source_type"]]
        detail = ""
        if labelled:
            kinds = sorted({a["source_type"] for a in labelled})
            detail = (f" {len(labelled)} carr{'ies' if len(labelled) == 1 else 'y'} an "
                      f"explicit source type ({', '.join(kinds)}).")
        passes.append(
            f"No AI-generation marker on {len(clean)} of {len(assets)} image"
            f"{'' if len(assets) == 1 else 's'} under `{SITE_DIR}/`.{detail}")

    notes.append(
        "**What the asset check can and cannot do.** It reads the labels a file carries: "
        "the IPTC `DigitalSourceType`, the XMP `CreatorTool`, and any generator named "
        "elsewhere in the metadata. It cannot read pixels, so an AI image whose metadata "
        "was stripped passes it. Treat a clean result as 'the file makes no AI claim', "
        "not as 'a person made this'. The judgement at purchase time is still the "
        "control that matters, and this is the floor under it.")


# --- The FAQ standalone test, as a check -----------------------------------
# The standards' FAQ law: every answer's opening sentence must survive being
# lifted without its question, because that is exactly what an assistant
# does with it. The founding build's pre-launch sweep found 27 answers
# opening "No.", "It can.", "A little." and the like, none of which says
# anything alone. An opener FAILS when it:
#   - is under FAQ_OPENER_MIN_WORDS words ("No.", "The town has none.");
#   - opens on a pronoun whose antecedent is in the question ("It does:
#     windshields...", "This page times the drive...");
#   - opens on a comparative fragment ("Longer than the figure...",
#     "Nearly.", "Not quite.", "A little.").
# A bare particle comma- or colon-merged into a full sentence passes ("No,
# a consultation does not commit you to anything."), which is what the
# standards prescribe.
FAQ_OPENER_MIN_WORDS = 6
FAQ_OPENER_PRONOUN_RE = re.compile(r"^(?:it|they|this|that|these|those)\b", re.I)
FAQ_OPENER_FRAGMENT_RE = re.compile(
    r"^(?:longer|shorter|nearly|mostly|partly|not quite|a little|somewhat)\b", re.I)


def faq_opener(answer: str) -> str:
    """The answer's first sentence, as an assistant would lift it."""
    return re.split(r"(?<=[.!?])\s+", unescape(re.sub(r"<[^>]+>", "", answer)).strip(), maxsplit=1)[0]


def faq_opener_findings(qas) -> list:
    """[(question, opener, why)] for every answer whose opener fails."""
    bad = []
    for q, a in qas:
        first = faq_opener(a)
        n = len(re.findall(r"[\w\u2019'-]+", first))
        if n < FAQ_OPENER_MIN_WORDS:
            bad.append((q, first, f"{n} word{'' if n == 1 else 's'}"))
        elif FAQ_OPENER_PRONOUN_RE.match(first):
            bad.append((q, first, "it opens on a pronoun"))
        elif FAQ_OPENER_FRAGMENT_RE.match(first):
            bad.append((q, first, "it opens on a fragment"))
    return bad


PRIVACY_KIND = "privacy"
UPDATED_RE = re.compile(r'Updated\s+<time\s+datetime="([^"]+)"[^>]*>([^<]*)</time>')


def privacy_date_findings(html_text: str) -> tuple:
    """(passes, fails) for the privacy policy's date. The approved copy
    tells its reader "When this policy changes, the date on this page changes
    with it", so the visible "Updated" date and the WebPage dateModified are
    ONE fact: exactly one visible date, inside <main>, equal to the schema's,
    and its words naming the same day. A CRITICAL: a policy whose date lies
    breaks the one promise it makes about itself."""
    bare = re.sub(r"(?s)<!--.*?-->", " ", html_text)
    m = re.search(r"(?is)<main\b[^>]*>(.*)</main>", bare)
    shown = UPDATED_RE.findall(m.group(1) if m else "")
    mods = []
    for block in re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', bare):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in (data.get("@graph", [data]) if isinstance(data, dict) else []):
            if isinstance(node, dict) and type_name(node.get("@type")) == "WebPage":
                mods.append(node.get("dateModified"))
    if len(shown) != 1 or len(mods) != 1:
        return [], [f"**The policy needs exactly one visible \"Updated\" date and one WebPage "
                    f"dateModified** (found {len(shown)} and {len(mods)}). Its own copy promises "
                    f"that the date on the page changes with the policy."]
    (iso, words), mod = shown[0], mods[0]
    try:
        spelled = date.fromisoformat(iso)
        said = f"{spelled:%B} {spelled.day}, {spelled.year}"
    except ValueError:
        said = None
    if iso != mod or words.strip() != said:
        return [], [f"**The policy's visible date and its schema disagree:** the page says "
                    f"\"{words.strip()}\" ({iso}), the WebPage dateModified says {mod}. They are "
                    f"one fact; change both in the same commit as the words."]
    return [f"The policy's visible date, {words.strip()}, is its WebPage dateModified."], []


def audit(source: str, coverage: dict = None):
    """Scores one page. `coverage` carries the parsed sitemap.xml and
    llms.txt for local runs, so a page that was built but never published
    into either file gets caught here rather than by a customer."""
    html = load(source)
    p = PageParser()
    p.feed(html)

    # A redirect stub or the 404 page declares itself in the head and is
    # scored against its own short rubric instead of this one. See
    # SPECIAL_KINDS at the top of the file for why.
    kind = (p.meta.get(PAGE_KIND_META) or "").strip().lower()
    if kind in SPECIAL_KINDS:
        return special_audit(source, html, p, kind, coverage) + (kind,)
    # A declared execution kind keeps this whole rubric and loses only the
    # checks RUBRIC_EXEMPTIONS names for it. It still reports as a page.
    exempt = RUBRIC_EXEMPTIONS.get(kind, ())
    exempt_why = {
        "contact": (f"Declared `{PAGE_KIND_META}` kind `contact`, an execution page: "
                    f"exempt by house precedent (RUBRIC_EXEMPTIONS)."),
        "post": (f"Declared `{PAGE_KIND_META}` kind `post`: a post is a read, not an "
                 f"answer block. Exempt by house precedent (RUBRIC_EXEMPTIONS)."),
        "blog-index": (f"Declared `{PAGE_KIND_META}` kind `blog-index`: an index routes, "
                       f"it does not answer. Exempt by house precedent (RUBRIC_EXEMPTIONS)."),
        "privacy": (f"Declared `{PAGE_KIND_META}` kind `privacy`: a policy states, it does "
                    f"not answer. Exempt by house precedent (RUBRIC_EXEMPTIONS)."),
    }.get(kind, "")
    declared_kind = kind
    kind = "page"

    passes, warns, fails, notes = [], [], [], []

    # --- Title tag ---
    t = p.title.strip()
    if not t:
        fails.append("**Missing <title> tag.** This is the strongest on-page ranking signal. Add one: `Business | Service | Town, ST`.")
    elif len(t) > 60:
        warns.append(f"**Title is {len(t)} characters** (aim for ≤60 so Google doesn't cut it off): “{t}”")
    else:
        passes.append(f"Title tag present and a good length ({len(t)} chars): “{t}”")

    # --- Meta description ---
    d = p.meta.get("description", "").strip()
    if not d:
        fails.append("**Missing meta description.** It's your free ad copy on the Google results page. Add one under 160 characters with a clear offer.")
    elif len(d) > 160:
        warns.append(f"**Meta description is {len(d)} characters** (aim for ≤160): “{d[:80]}…”")
    else:
        passes.append(f"Meta description present and a good length ({len(d)} chars).")

    # --- H1 ---
    h1s = [h.strip() for h in p.h1s if h.strip()]
    if len(h1s) == 0:
        fails.append("**No H1 heading.** Every page needs exactly one H1 containing the main service + location.")
    elif len(h1s) > 1:
        warns.append(f"**{len(h1s)} H1 headings found.** Use exactly one; demote the rest to H2.")
    else:
        passes.append(f"Exactly one H1: “{h1s[0][:80]}”")

    # --- Empty headings ---
    empty = [(tag, line) for tag, line, text in p.headings if not text.strip()]
    if empty:
        where = ", ".join(f"<{tag}> on line {line}" for tag, line in empty)
        fails.append(f"**Empty heading: {where}.** A heading with no words is announced by a "
                     f"screen reader as a heading with no name, and nobody sees it by eye. "
                     f"Delete the element; do not fill it with filler.")
    else:
        passes.append(f"No empty headings: all {len(p.headings)} h1 to h6 carry words.")

    # --- Every service enumeration carries the whole family, in its words ---
    if not is_url(source):
        _rel = os.path.relpath(os.path.dirname(os.path.abspath(source)),
                               os.path.abspath(SITE_DIR)).replace(os.sep, "/")
        _rel = "" if _rel == "." or _rel.startswith("..") else _rel + "/"
        n_enum, enum_problems = service_enumeration_findings(html, _rel, d)
        for x in enum_problems:
            fails.append(f"**A service enumeration does not answer to SERVICES:** {x}. Every place the "
                         f"site lists its services carries all {len(SERVICES)} in SERVICES (a service "
                         f"page's own grid, the family minus itself and RELATED_LEAVES_OUT), and every card carries its row's "
                         f"label and line, so a service cannot be half-added and a card cannot drift. "
                         f"Run scripts/sync-service-cards.py.")
        if n_enum and not enum_problems:
            passes.append(f"All {n_enum} service enumeration(s) on the page carry the family of "
                          f"{len(SERVICES)}, and every card its row's label and line.")

    # --- A service card's image is its page's own preview ---
    if not is_url(source):
        n_ci, ci_problems = card_image_findings(html, _rel)
        for x in ci_problems:
            fails.append(f"**A service card does not preview its page:** {x}. A card that carries a "
                         f"photograph carries the image its target page presents as its own preview, "
                         f"its og:image, the same file, size and alt. Run "
                         f"scripts/sync-service-cards.py.")
        if n_ci and not ci_problems:
            passes.append(f"All {n_ci} photographed service card(s) carry their page's own preview "
                          f"image, file, size and alt.")

    # --- A Google Maps embed is the verified pin, by coordinates ---
    # House precedent from the founding build: a map embed is CENTRED ON
    # GEO_LAT, GEO_LON, never on the business's name. A name query renders
    # the Business Profile's card onto the page from Google's side, where no
    # other check of ours can see it, and a profile that disagrees with the
    # site (its hours, its name) is then on the page. So any Google Maps
    # iframe must query exactly the pin, carry a title, and load lazily.
    # While geo is OFF there is no pin to hold it to, and the report says so.
    for tag in re.findall(r"<iframe\b[^>]*>", html, re.I):
        src = unescape((re.search(r'\bsrc="([^"]*)"', tag) or [None, ""])[1])
        if "google." not in src or "/maps" not in src:
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(src).query).get("q", [""])[0]
        problems = []
        if GEO_LAT is None or GEO_LON is None:
            want = None
            notes.append("**A Google Maps embed is on this page, and the geo check is OFF**, so "
                         "its query was not held to a verified pin. When the firm's coordinates "
                         "are confirmed, the embed must query exactly them, never the name.")
        else:
            want = f"{GEO_LAT},{GEO_LON}"
        if want is not None and q != want:
            problems.append(f"it queries “{q}”, not the verified pin {want}"
                            + (" (a NAME query brings the Business Profile's card with it)"
                               if re.search(r"[A-Za-z]", q) else ""))
        if not re.search(r'\btitle="[^"]+"', tag):
            problems.append("it has no title, so a screen reader announces an unnamed frame")
        if 'loading="lazy"' not in tag:
            problems.append("it does not load lazily, so its weight lands on every visit")
        if problems:
            fails.append("**The Google Maps embed is wrong:** " + "; ".join(problems) + ".")
        elif want is not None:
            passes.append(f"The Google Maps embed is centred on the verified pin, {want}, "
                          f"by coordinates, titled, and lazy-loaded.")

    # --- The [CONFIRM] law: a note while staging, a critical after ---
    # See CONFIRM_RE. Local files only.
    if not is_url(source):
        marks = confirm_findings(html)
        if marks:
            where = "; ".join(f"line {ln}: \u201c{tail}\u201d" for ln, tail in marks[:8])
            more = "" if len(marks) <= 8 else f"; and {len(marks) - 8} more"
            if STAGING:
                notes.append(f"**{len(marks)} [CONFIRM] marker{'' if len(marks) == 1 else 's'} "
                             f"waiting on a partner's initials:** {where}{more}. Each is a claim "
                             f"the live site does not already make, with a row in "
                             f"proposed-changes.md naming the partner who must initial it. "
                             f"Allowed while STAGING is True; a critical the day it is False.")
            else:
                fails.append(f"**{len(marks)} [CONFIRM] marker{'' if len(marks) == 1 else 's'} "
                             f"on a live page:** {where}{more}. A [CONFIRM] is a claim no "
                             f"partner has initialed, and STAGING is off, so it is published. "
                             f"Get the named partner's written approval and remove the marker, "
                             f"or take the claim off the page.")

    # --- The policy's date is a promise, privacy pages only ---
    if declared_kind == PRIVACY_KIND:
        pp, pf = privacy_date_findings(html)
        passes += pp
        fails += pf

    # --- Structured data (JSON-LD) ---
    types = []
    faq_nodes = []            # every FAQPage node found, for the mirror check
    crumb_nodes = []          # every BreadcrumbList node, for the crumb mirror
    business_same_as = False  # sameAs found ON the business node, not just anywhere
    business_nodes = []       # the business node(s), for the served-list check
    for block in p.jsonld_blocks:
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            # A page that describes several things at once (a business, a
            # service, a breadcrumb, an FAQ) puts them in an @graph so they
            # can reference each other by @id. Unwrap it, or every node
            # inside is invisible and the page looks like it has no schema
            # at all. Most modern CMS sites emit one, so this matters when
            # auditing a prospect's site too.
            unwrapped = []
            for item in items:
                graph = item.get("@graph") if isinstance(item, dict) else None
                if graph:
                    unwrapped.extend(graph if isinstance(graph, list) else [graph])
                else:
                    unwrapped.append(item)
            for item in unwrapped:
                t2 = item.get("@type")
                if t2:
                    names = [type_name(t) for t in
                             (t2 if isinstance(t2, list) else [t2])]
                    names = [n for n in names if n]
                    types.extend(names)
                    if "FAQPage" in names:
                        faq_nodes.append(item)
                    if "BreadcrumbList" in names:
                        crumb_nodes.append(item)
                    # sameAs is only an entity signal where it sits on
                    # the BUSINESS. See the check further down for the
                    # false pass this exists to prevent.
                    if LOCAL_BUSINESS_TYPES.intersection(names) and item.get("sameAs"):
                        business_same_as = True
                    if LOCAL_BUSINESS_TYPES.intersection(names):
                        business_nodes.append(item)
        except (json.JSONDecodeError, AttributeError):
            warns.append("**A JSON-LD block failed to parse.** Broken structured data is invisible to Google. Validate at validator.schema.org.")
    if types:
        passes.append(f"Structured data found: {', '.join(types)}.")
        if not LOCAL_BUSINESS_TYPES.intersection(types):
            warns.append("**No LocalBusiness-type schema detected.** For a local business this is the #1 upgrade: add name, address, phone, hours, and geo as JSON-LD.")
    else:
        fails.append("**No structured data (JSON-LD) at all.** This is how you speak directly to Google's machines and AI search. Most competitors are missing it, so it is an easy win.")

    # --- AEO: is the page built to BE the answer? ---
    # AI assistants and Google's AI Overviews lift answers from pages that
    # ask the question and answer it directly. FAQPage schema + real Q&A
    # text is the closest thing to raising your hand.
    if "FAQPage" in types:
        passes.append("AEO: FAQPage schema present: the page offers ready-made Q&As for AI answers and rich results.")
    elif "faq-schema" in exempt and not p.faq_visible:
        # Not required, never unmeasured: a page of an exempt kind that DOES
        # show a visible FAQ falls through to the warning below and to the
        # mirror law, exactly like every other page.
        notes.append(f"**No FAQPage schema, not measured here.** {exempt_why}")
    else:
        warns.append("**AEO gap: no FAQPage schema.** Add a real FAQ section (the questions customers "
                     "actually call to ask) marked up as FAQPage; it's the closest thing to raising "
                     "your hand when an AI assembles an answer.")

    # --- FAQ mirror: does the schema say what the page says? ---
    # Assistants and rich results quote acceptedAnswer, not the visible
    # copy, so the two drifting apart means the machines are handing out a
    # sentence the reader never sees. The house rule is that each visible
    # question and answer is byte-identical to its schema twin: edit one,
    # edit both. Runs on parsed page text, so it works the same against a
    # local file or a fetched live URL.
    schema_faq = []
    for node in faq_nodes:
        entities = node.get("mainEntity") or []
        for q in entities if isinstance(entities, list) else [entities]:
            if not isinstance(q, dict):
                continue
            ans = q.get("acceptedAnswer") or {}
            schema_faq.append((str(q.get("name", "")).strip(),
                               str(ans.get("text", "")).strip() if isinstance(ans, dict) else ""))
    if schema_faq and not p.faq_visible:
        # Schema but nothing this check can read. On our pages that means
        # the FAQ section is gone; on a prospect's it usually means their
        # FAQ is built from divs we do not recognize. Not worth scoring a
        # stranger's site down for markup we simply cannot see, so it says
        # so and stops.
        notes.append(f"{len(schema_faq)} FAQ question(s) in FAQPage schema, but no visible "
                     f"<details>/<summary> FAQ was found to compare them against. Either the "
                     f"page's FAQ is missing, or it is built with markup this check does not read.")
    elif p.faq_visible and not schema_faq:
        # The AEO check above already warns that FAQPage schema is absent,
        # and that warning is itself a scoring defect. Saying it again per
        # question would punish one mistake several times over.
        pass
    elif schema_faq or p.faq_visible:
        by_schema = dict(schema_faq)
        by_page = dict(p.faq_visible)
        only_schema = [q for q in by_schema if q not in by_page]
        only_page = [q for q in by_page if q not in by_schema]
        mismatched = [q for q in by_schema if q in by_page and by_schema[q] != by_page[q]]

        # One on each side is almost always the same item with its
        # question edited in one place only. Say that, rather than
        # reporting it twice as two unrelated absences.
        if len(only_schema) == 1 and len(only_page) == 1:
            fails.append(
                f"**FAQ question text differs between the page and its schema.** "
                f"Schema asks “{only_schema[0][:90]}”, the page asks “{only_page[0][:90]}”. "
                f"Each question must be byte-identical in both: edit one, edit both.")
            only_schema, only_page = [], []
        for q in only_schema:
            fails.append(f"**FAQ in schema but not on the page: “{q[:90]}”.** "
                         f"Schema promising an answer the reader never sees is the kind of thing "
                         f"Google penalizes as mismatched structured data. Add it or drop it.")
        for q in only_page:
            fails.append(f"**FAQ on the page but not in schema: “{q[:90]}”.** "
                         f"It cannot be quoted by AI answers or rich results until it is in the "
                         f"FAQPage node.")
        for q in mismatched:
            fails.append(f"**FAQ answer does not match its schema: “{q[:70]}”.** "
                         f"The page says “{by_page[q][:80]}…” and the schema says "
                         f"“{by_schema[q][:80]}…”. Assistants quote the schema, so this is the "
                         f"sentence being handed out instead of yours. Edit one, edit both.")
        if not (only_schema or only_page or mismatched) and schema_faq:
            passes.append(f"All {len(schema_faq)} FAQ questions and answers are byte-identical "
                          f"between the visible page and the FAQPage schema.")

    # --- FAQ standalone openers ---
    # An assistant lifts the first sentence of an answer without its
    # question. See FAQ_OPENER_* for the rule.
    opener_qas = schema_faq or list(p.faq_visible or [])
    if opener_qas:
        bad = faq_opener_findings(opener_qas)
        for q, first, why in bad:
            fails.append(f"**An FAQ answer's first sentence does not stand alone ({why}):** "
                         f"\u201c{q[:70]}\u201d opens \u201c{first[:80]}\u201d. Assistants lift "
                         f"the opener without its question, so it has to carry its own subject. "
                         f"Comma-merge a bare particle into the sentence after it (\u201cNo, "
                         f"...\u201d), or name the subject.")
        if not bad:
            passes.append(f"All {len(opener_qas)} FAQ answers open on a sentence that stands "
                          f"alone without its question.")

    # --- Crumb mirror: does the BreadcrumbList say what the crumb says? ---
    # The FAQ mirror's law applied to the
    # breadcrumb: Google shows the BreadcrumbList's names as the result's
    # path, so a crumb edited on the page and not in the schema hands out a
    # trail the reader never sees. Labels and order must be byte-identical,
    # both directions. SEVERITY ARGUED FROM THE FAQ MIRROR, case by case:
    #   both present, any difference ...... a CRITICAL, as FAQ drift is;
    #   a visible crumb, no BreadcrumbList . a WARNING, as a visible FAQ
    #                                        with no FAQPage schema is;
    #   a BreadcrumbList, no readable crumb  a NOTE, as FAQ schema with no
    #                                        readable FAQ is: the weekly scan
    #                                        reads the live WordPress site,
    #                                        whose crumb markup this parser
    #                                        may not recognise, and a stranger's
    #                                        markup is not scored down.
    # A crumb nav whose items are not <li>s reads as unreadable, not empty.
    schema_crumb = []
    for node in crumb_nodes[:1]:
        elements = node.get("itemListElement") or []
        elements = [e for e in (elements if isinstance(elements, list) else [elements])
                    if isinstance(e, dict)]
        def _pos(e):
            try:
                return float(e.get("position"))
            except (TypeError, ValueError):
                return float("inf")
        for e in sorted(elements, key=_pos):
            name = e.get("name")
            if name is None and isinstance(e.get("item"), dict):
                name = e["item"].get("name")
            schema_crumb.append(" ".join(str(name or "").split()))
    page_crumb = p.crumb_visible or []
    if page_crumb and schema_crumb:
        if page_crumb == schema_crumb:
            passes.append(f"The visible breadcrumb and the BreadcrumbList agree, "
                          f"{len(page_crumb)} items in the same order: "
                          + " / ".join(page_crumb) + ".")
        else:
            only_page = [x for x in page_crumb if x not in schema_crumb]
            only_schema = [x for x in schema_crumb if x not in page_crumb]
            if len(only_page) == 1 and len(only_schema) == 1 and len(page_crumb) == len(schema_crumb):
                fails.append(f"**Breadcrumb label differs between the page and its schema.** The page "
                             f"says “{only_page[0][:80]}”, the BreadcrumbList says "
                             f"“{only_schema[0][:80]}”. Each label must be byte-identical in both: "
                             f"edit one, edit both.")
            else:
                for x in only_page:
                    fails.append(f"**Breadcrumb item on the page but not in the BreadcrumbList: "
                                 f"“{x[:80]}”.** Search results show the schema's trail, so this "
                                 f"step is missing from it.")
                for x in only_schema:
                    fails.append(f"**Breadcrumb item in the BreadcrumbList but not on the page: "
                                 f"“{x[:80]}”.** The schema is handing out a step the reader "
                                 f"never sees.")
                if not only_page and not only_schema:
                    fails.append("**Breadcrumb order differs between the page and its schema.** "
                                 "The page reads " + " / ".join(page_crumb) + "; the BreadcrumbList "
                                 "reads " + " / ".join(schema_crumb) + ". Same items, same order.")
    elif page_crumb:
        warns.append("**A visible breadcrumb with no BreadcrumbList schema.** Search results cannot "
                     "show the trail " + " / ".join(page_crumb) + " until it is marked up; add a "
                     "BreadcrumbList with the same labels in the same order.")
    elif schema_crumb:
        notes.append(f"A BreadcrumbList of {len(schema_crumb)} items, but no visible breadcrumb this "
                     f"check can read to compare it against: either the page shows none, or it is "
                     f"built with markup this check does not read.")

    # --- The business node is the firm's schema type ---
    # SCHEMA_BUSINESS_TYPE, LegalService. Local files only: the live
    # WordPress site's schema is not ours until cutover. Attorney nodes,
    # when they come, sit beside it and do not replace it.
    if business_nodes and not is_url(source):
        def _types(n):
            t = n.get("@type")
            return {type_name(x) for x in (t if isinstance(t, list) else [t]) if x}
        if any(SCHEMA_BUSINESS_TYPE in _types(n) for n in business_nodes):
            passes.append(f"The business node is a `{SCHEMA_BUSINESS_TYPE}`.")
        else:
            got = sorted(set().union(*(_types(n) for n in business_nodes)))
            fails.append(f"**No business node is a `{SCHEMA_BUSINESS_TYPE}`** (found "
                         f"{', '.join(got)}). The firm's node carries SCHEMA_BUSINESS_TYPE "
                         f"in scripts/audit.py.")

    # --- The served list: every business node carries AREA_SERVED ---
    # One list, written by scripts/sync-area-served.py. A page whose node
    # names a different set, order or shape is a critical: two pages that
    # serve different towns describe two businesses. Local files only: the
    # live WordPress site's schema is not ours until cutover, and scoring
    # it against this list would fill every Monday report with criticals
    # that describe the old site, not this one.
    if business_nodes and not is_url(source) and AREA_SERVED:
        want = area_served_nodes()
        if all(n.get("areaServed") == want for n in business_nodes):
            passes.append(f"The business node's areaServed is the one served list, AREA_SERVED "
                          f"({len(want)} places).")
        else:
            got = [a.get("name") for a in (business_nodes[0].get("areaServed") or []) if isinstance(a, dict)]
            missing = [x[1] for x in AREA_SERVED if x[1] not in got]
            extra = [x for x in got if x not in [y[1] for y in AREA_SERVED]]
            fails.append("**The business node's areaServed is not the served list.** "
                         + (f"Missing: {', '.join(missing)}. " if missing else "")
                         + (f"Not in AREA_SERVED: {', '.join(extra)}. " if extra else "")
                         + "Every page carries one list, AREA_SERVED in scripts/audit.py; run "
                           "scripts/sync-area-served.py rather than editing a page's schema.")

    # --- The founding date: every business node carries FOUNDING_DATE ---
    if business_nodes and not is_url(source) and FOUNDING_DATE:
        founded = [n.get("foundingDate") == FOUNDING_DATE for n in business_nodes]
        if all(founded):
            passes.append(f"The business node's foundingDate is FOUNDING_DATE ({FOUNDING_DATE}).")
        else:
            fails.append(f"**The business node's foundingDate is not FOUNDING_DATE** "
                         f"({FOUNDING_DATE}). Run scripts/sync-area-served.py rather "
                         f"than editing a page's schema.")

    # --- The profiles: every business node carries SAME_AS ---
    # Same shape as the served list: one list, written by the sync, a
    # critical when a page's node differs, local files only. hasMap is
    # held with it, because the list opens on the same Maps URL. OFF until
    # the firm confirms its profiles (FACTS_OFF).
    if business_nodes and not is_url(source) and SAME_AS:
        same = [n.get("sameAs") == list(SAME_AS) for n in business_nodes]
        maps = [n.get("hasMap") == GBP_MAP_URL for n in business_nodes]
        if all(same) and all(maps):
            passes.append(f"The business node's sameAs is the one profile list, SAME_AS "
                          f"({len(SAME_AS)} profiles), opening on its hasMap.")
        else:
            got = business_nodes[0].get("sameAs") or []
            got = got if isinstance(got, list) else [got]
            missing = [u for u in SAME_AS if u not in got]
            extra = [u for u in got if u not in SAME_AS]
            fails.append("**The business node's sameAs or hasMap is not the profile list.** "
                         + (f"Missing: {', '.join(missing)}. " if missing else "")
                         + (f"Not in SAME_AS: {', '.join(map(str, extra))}. " if extra else "")
                         + ("" if all(maps) else f"hasMap is not GBP_MAP_URL ({GBP_MAP_URL}). ")
                         + "Every page carries one list, SAME_AS in scripts/audit.py, in its "
                           "order; run scripts/sync-area-served.py rather than editing a page's schema.")

    # Entity clarity: sameAs links tie the business to its profiles
    # (Google Business Profile, Yelp, Instagram...), which is how AI
    # systems confirm the business is real and reviewed.
    # THIS USED TO BE A SUBSTRING SEARCH over the whole JSON-LD, and a
    # substring search finds sameAs anywhere: on an areaServed entry
    # pointing at a Wikipedia article for the county, for instance, which
    # is a perfectly ordinary thing to publish and says nothing at all
    # about whether the BUSINESS has verified profiles. The page then
    # scored a pass on an entity signal it did not have. A check that can
    # be satisfied by the wrong node is the same class of defect as the
    # address check that was satisfied by a prefix, so it is fixed the
    # same way: look at the node that has to carry it.
    if business_same_as:
        passes.append("AEO: the business node carries sameAs profile links, a strong entity signal for AI systems.")
    elif SAME_AS is None and not is_url(source):
        notes.append("**No `sameAs` on the business node, and the sameAs check is OFF** until the "
                     "firm confirms its profiles. Not scored: the profiles cannot be listed before "
                     "the firm says which are its own.")
    else:
        warns.append("**AEO gap: no `sameAs` links on the business node.** Add links to the Google "
                     "Business Profile, Yelp, and social profiles so AI systems can verify the entity "
                     "and its reviews. A sameAs elsewhere in the graph, on an areaServed place for "
                     "example, does not count: it says nothing about this business.")

    # --- Social sharing ---
    # The 160-character ceiling on og:description is a HOUSE RULE, not a
    # standard. Open Graph itself sets no limit, and the networks all cut
    # at different points (and move the goalposts), so nobody can tell you
    # the "correct" length. What we can do is keep one number in the head
    # of every page: the meta description is capped at 160 above, and the
    # two descriptions are usually near-copies of each other, so letting
    # og: run longer just means the pair drifts apart. A NOTE, not a
    # warning and never a critical: notes are the one bucket score_of()
    # does not count, which is right for a rule we invented. An over-long
    # og:description still shares fine, so it should never be the reason
    # a page drops off 100. The missing-tags case below stays a warning,
    # because that one is a real defect.
    og_d = p.meta.get("og:description", "").strip()
    if not (p.meta.get("og:title") and og_d):
        warns.append("**Missing Open Graph tags** (og:title / og:description), so shared links will look broken or bare on Facebook/LinkedIn.")
    else:
        passes.append(f"Open Graph tags present ({len(og_d)}-char og:description), so the site will look right when shared on social.")
        if len(og_d) > 160:
            notes.append(f"og:description is {len(og_d)} characters, past the 160 the meta description keeps. House consistency rule, not a spec: trim it when convenient, preserving the promises over the connectives. “{og_d[:80]}…”")

    # --- Technical basics ---
    if p.canonical:
        passes.append(f"Canonical URL set: {p.canonical}")
    else:
        warns.append("**No canonical URL.** Add `<link rel=\"canonical\" ...>` to avoid duplicate-content confusion.")

    if p.has_viewport:
        passes.append("Mobile viewport tag present (site is mobile-friendly at the HTML level).")
    else:
        fails.append("**No viewport meta tag.** Google indexes mobile-first; this is a must-fix.")

    # See STAGING at the top of this file for why this check is inverted
    # while the build is not live. LOCAL FILES ONLY: STAGING describes this
    # build, not the firm's live WordPress site, which the weekly scan reads
    # and which must never be noindexed. Ungated, the inversion scored every
    # live page a critical for being indexable (found on this repo's first
    # live smoke run; the founding repo carries the same gap).
    robots = p.meta.get("robots", "")
    if STAGING and not is_url(source):
        if "noindex" in robots:
            passes.append("Correctly noindexed for staging: the real site is still live on "
                          "WordPress, and this build must not answer for the same business.")
            notes.append("**Recorded staging exception.** This page carries `noindex, nofollow`, "
                         "`docs/robots.txt` disallows everything, and the canonical points at "
                         "the production domain. All three are deliberate, all three come off "
                         "together at cutover, and none of them is a defect to be fixed before "
                         "then. `STAGING` in `scripts/audit.py` is the switch. On a live site "
                         "this check runs the other way and a noindexed page is a critical.")
        else:
            fails.append("**This page is NOT noindexed and the build is still staging.** Every "
                         "page carries `<meta name=\"robots\" content=\"noindex, nofollow\">` "
                         "until cutover, because the firm's real site is live right now and a "
                         "crawlable second copy is a second address answering for one business. "
                         "Add the tag, or set `STAGING = False` if this really is cutover day.")
    elif "noindex" in robots:
        fails.append("**Page is set to NOINDEX.** It is telling Google to ignore it entirely. Fix immediately unless intentional.")

    # --- The staging banner and the favicon set ---
    # Only for a file that lives under docs/: a fabricated test page is
    # not a page of this site and carries neither.
    if not is_url(source):
        _in = os.path.relpath(os.path.dirname(os.path.abspath(source)),
                              os.path.abspath(SITE_DIR)).replace(os.sep, "/")
        if not _in.startswith(".."):
            sp, sw, sf = staging_page_findings(html)
            passes += sp
            warns += sw
            fails += sf
            ip, ifl = icon_findings(html, "" if _in == "." else _in + "/")
            passes += ip
            fails += ifl

    # --- Images ---
    missing_alt = [src for src, alt in p.images if alt is None or not alt.strip()]
    if p.images and missing_alt:
        warns.append(f"**{len(missing_alt)} of {len(p.images)} images missing alt text.** Alt text helps image search and accessibility.")
    elif p.images:
        passes.append(f"All {len(p.images)} images have alt text.")

    # --- Tappable phone and email ---
    # A bare number in body copy is a number the reader has to memorize
    # and retype. Every visible mention should be a tel:/mailto: link, so
    # a phone reader taps once. Silent regression is the real risk here:
    # this is the kind of thing that gets missed when a new FAQ answer or
    # card is written, which is exactly why it is checked on every page.
    if p.contacts_bare:
        where = ", ".join(f"line {ln} ({kind})" for ln, kind in p.contacts_bare[:5])
        warns.append(f"**{len(p.contacts_bare)} phone/email mention(s) not linked** ({where}). "
                     f"Wrap each one so it is tappable on a phone: a `tel:` or `mailto:` link.")
    elif p.contacts_linked:
        passes.append(f"All {p.contacts_linked} phone/email mentions are tappable tel:/mailto: links.")

    # The second mailbox. See NAP_EMAIL_WRONG_RE for why this is a
    # critical and not a tidy-up.
    if NAP_EMAIL_WRONG_RE is not None and NAP_EMAIL_WRONG_RE.search(html):
        fails.append(
            f"**This page prints `{NAP_EMAIL_WRONG_RE.search(html).group(0)}`.** The one address "
            f"this site publishes is `{NAP_EMAIL}`. An old site's second address travels during "
            "a migration without anyone typing it. Two addresses for one business read as two "
            "businesses to entity matching, and only one of them is the mailbox the firm "
            "actually reads.")

    # A call-tracking number. See TRACKING_PHONE_RES.
    for rx in TRACKING_PHONE_RES:
        m = rx.search(html)
        if m:
            fails.append(
                f"**This page contains a call-tracking number ({m.group(0)}).** It must never "
                "appear in this site's source, schema or templates. The tracking script swaps "
                "numbers into the page visually at runtime; a tracking number written into the "
                "markup is a second phone number for one business, and it is the number crawlers "
                "and AI assistants will hand out. Use the firm's own number and let the snippet "
                "do its job.")

    # --- The name, spelled one way ---
    bad_names = name_variants(html)
    if bad_names:
        shown = ", ".join(f"`{v}`" for v in sorted(set(bad_names)))
        fails.append(
            f"**The business name is written {shown} here, not `{NAP_NAME}`** "
            f"({len(bad_names)} time{'' if len(bad_names) == 1 else 's'}). NAP is character-identical "
            f"everywhere or it is nothing: each variant reads as a slightly different business "
            f"to entity matching. The logo's alt may name the wordmark as drawn; every other "
            f"mention, visible, meta, alt or schema, is `{NAP_NAME}`.")
    elif name_mentions(html):
        passes.append(f"The business name is written `{NAP_NAME}` everywhere it appears.")

    # --- The street address, spelled one way ---
    if NAP_STREET_MENTION_RE is not None and NAP_STREET_MENTION_RE.search(html):
        has_street = NAP_STREET_CANON_RE.search(html) is not None
        has_cityline = NAP_CITYLINE_CANON in html
        variant = NAP_STREET_VARIANT_RE.search(html)
        # A variant fails even when the canonical spelling is ALSO on the
        # page, which an old `and not has_street` guard once let through.
        # That was not a hypothetical on the founding build: its live
        # WordPress site printed the short suffix in its footer and the long
        # one in its JSON-LD, on the same page. One page, two businesses.
        if variant:
            fails.append(
                f"**The street address is spelled `{variant.group(0)}` here, not "
                f"`{NAP_STREET_CANON}`.** NAP is character-identical everywhere or it is "
                f"nothing: each variant reads as a slightly different business to "
                f"Google's entity matching, which is how a business ends up competing with "
                f"itself in the Map Pack. A trailing period counts, and so does a variant "
                f"that sits alongside the correct spelling somewhere else on the page. "
                f"Use `{NAP_STREET_CANON}`.")
        elif not has_street:
            fails.append(
                f"**This page names the street but not `{NAP_STREET_CANON}`.** If the page "
                f"carries the address it carries the canonical spelling. If it should "
                f"not carry the address at all, take the mention out.")
        elif not has_cityline:
            warns.append(
                f"**The street line is here but `{NAP_CITYLINE_CANON}` is not.** A street "
                f"address without its city, state and ZIP is not a NAP match. Add the "
                f"full line.")
        else:
            passes.append(f"NAP address is the canonical spelling: "
                          f"{NAP_STREET_CANON}, {NAP_CITYLINE_CANON}.")

    # --- The hours: every copy says the constants, and nothing else ---
    vis = re.sub(r"(?s)<!--.*?-->|<script.*?</script>|<style.*?</style>", " ", html)
    vis = re.sub(r"<[^>]+>", " ", vis)
    n_ok, strays, banned = hours_findings(vis)
    biz_nodes = []
    for block in p.jsonld_blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict):
                g = item.get("@graph")
                biz_nodes.extend(x for x in (g if isinstance(g, list) else [item])
                                 if isinstance(x, dict) and "openingHoursSpecification" in x)
    schema_off = hours_schema_findings(biz_nodes)
    for x in strays:
        fails.append(f"**The hours are written a second way:** \u201c{x}\u201d. Every copy "
                     f"says {' and '.join(f'`{c}`' for c in HOURS_CANON)}, character for "
                     f"character (HOURS_* in scripts/audit.py), because a reader acts "
                     f"on the hours and two versions of them is one wrong.")
    for x in banned:
        fails.append(f"**A day the record has no hours for is mentioned:** \u201c{x}\u201d. "
                     f"Nobody confirmed anything about it, open or closed. It is the firm's "
                     f"question to answer, not a fact to publish.")
    for x in schema_off:
        fails.append(f"**The schema's hours disagree with the constants:** {x}.")
    if n_ok and not strays and not banned and not schema_off:
        passes.append(f"Hours match the constants in all {n_ok} visible mention"
                      f"{'' if n_ok == 1 else 's'}"
                      f"{' and the schema' if biz_nodes else ''}.")

    # --- The founding year: FOUNDING_YEAR, and never fused with a place ---
    n_found, found_probs = founding_findings(html)
    for x in found_probs:
        fails.append(f"**{x[0].upper() + x[1:]}.** The founding claim is the date the firm "
                     f"confirmed (FOUNDING_DATE in scripts/audit.py), {FOUNDING_YEAR}. Where it "
                     f"stood for all of that time is a second claim, so no sentence fuses the "
                     f"two unless the firm has confirmed that too.")
    if n_found and not found_probs:
        passes.append(f"The founding year reads {FOUNDING_YEAR} in {n_found} place"
                      f"{'' if n_found == 1 else 's'}, and no clause fuses it with a place.")

    # --- The firm's coordinates: every business node says the constants ---
    all_nodes = []
    for block in p.jsonld_blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict):
                g = item.get("@graph")
                all_nodes.extend(x for x in (g if isinstance(g, list) else [item])
                                 if isinstance(x, dict))
    n_geo, geo_off = geo_findings(all_nodes)
    for x in geo_off:
        fails.append(f"**The schema's geo is not the firm's verified pin:** {x}. "
                     f"GEO_LAT and GEO_LON in scripts/audit.py are the one place it "
                     f"lives. Never take coordinates from a "
                     f"map URL: its @lat,lon is the viewport centre, not the pin.")
    if n_geo and not geo_off:
        passes.append(f"Schema geo is the verified pin, {GEO_LAT}, {GEO_LON}.")

    # --- Word count (thin content check) ---
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", html)
    words = len(text.split())
    if words < 300 and "thin-content" in exempt:
        notes.append(f"**~{words} words, not measured against 300 here.** {exempt_why}")
    elif words < 300:
        warns.append(f"**Thin content: ~{words} words.** Local pages generally need 300+ words of real, useful text to rank.")
    else:
        passes.append(f"Healthy content depth: ~{words} words on the page.")

    # --- Cache-busting stamps on the shared assets ---
    check_asset_stamps(html, current_stamps() if not is_url(source) else {}, passes, fails)

    # --- Published where crawlers can find it ---
    # A page that exists but is in neither sitemap.xml nor llms.txt is a
    # page Google and the AI assistants may never discover. On a live run
    # this is moot: the page list came FROM the sitemap.
    if coverage is not None and p.canonical:
        canon = p.canonical.strip()
        if canon in coverage["sitemap_locs"]:
            passes.append(f"Listed in sitemap.xml, so crawlers get pointed at it: {canon}")
        else:
            fails.append(f"**Not listed in `docs/sitemap.xml`.** The page is live at {canon} but "
                         "the sitemap never mentions it, so Google has to stumble on it. Add a "
                         "`<url>` block with today's date.")
        # Word-boundary match: without it, the homepage's canonical would
        # match any deeper URL that starts with it and always "pass".
        if re.search(re.escape(canon) + r"(?![\w/.\-])", coverage["llms_text"]):
            passes.append("AEO: listed in llms.txt, so AI agents get a guided route to the page.")
        else:
            warns.append(f"**Not listed in `docs/llms.txt`.** Add {canon} under `## Key pages` so "
                         "AI assistants reading the guide know this page exists.")

    return passes, warns, fails, notes, kind


def score_of(n_pass: int, n_warn: int, n_fail: int) -> int:
    """Unchanged formula: the share of checks that passed. Notes are free."""
    return round(100 * n_pass / max(1, n_pass + n_warn + n_fail))


def is_xml_url(url: str) -> bool:
    """True for a URL that points at an XML file. Those are sitemaps and
    feeds, never pages. Scoring one against the HTML rubric produces a
    page-shaped verdict about a file no reader will ever open."""
    return urlparse(url).path.lower().endswith(".xml")


def new_sitemap_stats() -> dict:
    """What one expansion learned about the sitemaps it read, so the
    report can say what was followed and what was skipped."""
    return {"files": 0, "indexes": 0, "unreadable": [], "capped": False}


def collect_sitemap_pages(sitemap_url: str, depth: int = 0, seen: set = None,
                          stats: dict = None) -> list:
    """Returns the page URLs one sitemap lists, following an index.

    A <urlset> lists pages. A <sitemapindex> lists other sitemaps, and
    its <loc> entries are those sitemaps' own addresses. Both use the
    same <loc> tag, so the wrapper tag is the only thing that says which
    kind of list you are holding. Reading an index as if it were a
    urlset is what put category-sitemap.xml, page-sitemap.xml and
    post-sitemap.xml through the page rubric on the first prospect scan.

    Anything ending in .xml is dropped here whatever the wrapper said,
    so a sitemap that is mislabeled, or an index nested deeper than we
    follow, still cannot put a sitemap into the page list."""
    if seen is None:
        seen = set()
    if stats is None:
        stats = new_sitemap_stats()
    # Three ways to stop: already been here (an index can point at
    # itself), too deep, or too many files fetched for one run. The last
    # two mean we may be leaving real pages unread, so they get recorded
    # and reported. Revisiting a sitemap we already read costs nothing.
    if sitemap_url in seen:
        return []
    if depth > SITEMAP_MAX_DEPTH or stats["files"] >= SITEMAP_MAX_FILES:
        stats["capped"] = True
        return []
    seen.add(sitemap_url)
    stats["files"] += 1

    xml = load(sitemap_url)
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    if re.search(r"<\s*sitemapindex[\s>]", xml):
        stats["indexes"] += 1
        pages = []
        for child in locs:
            # One dead child sitemap must not cost us the others.
            try:
                pages.extend(collect_sitemap_pages(child, depth + 1, seen, stats))
            except Exception:
                stats["unreadable"].append(child)
        return pages
    return [u for u in locs if not is_xml_url(u)]


def expand_sitemap(url: str):
    """A live site's page list comes from its own sitemap. If that can't
    be read we still audit the URL we were given, and say why."""
    parts = urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    # Pointing the script straight at a sitemap means audit what THAT
    # file lists, not what /sitemap.xml lists.
    entry = url if is_xml_url(url) else root + "/sitemap.xml"
    fallback = [] if is_xml_url(url) else [url]
    stats = new_sitemap_stats()
    try:
        locs = collect_sitemap_pages(entry, stats=stats)
    except Exception:
        return fallback, (f"Could not read {entry}, so only the page you named was "
                          "audited. Add a sitemap so every page gets scanned.")

    followed = []
    if stats["indexes"]:
        n = stats["files"] - 1
        followed.append(f"{entry} is a sitemap index, so the {n} sitemap"
                        f"{'' if n == 1 else 's'} under it "
                        f"{'was' if n == 1 else 'were'} read instead of being scored as pages.")
    if stats["capped"]:
        followed.append(f"That index nests deeper than {SITEMAP_MAX_DEPTH} levels or lists more "
                        f"than {SITEMAP_MAX_FILES} sitemaps, so the scan stopped following it "
                        "and some pages may be missing from this report.")
    if stats["unreadable"]:
        followed.append("These child sitemaps could not be read: "
                        + ", ".join(stats["unreadable"]) + ".")
    if not locs:
        followed.append(f"{entry} lists no pages, so only the page you named was audited.")
        return fallback, " ".join(followed)
    return sorted(set(locs)), (" ".join(followed) if followed else None)


def resolve_targets(args):
    """No arguments audits the whole site. Paths, folders and URLs all work."""
    if not args:
        return sorted(glob.glob(os.path.join(SITE_DIR, "**", "*.html"), recursive=True)), None
    if len(args) == 1 and is_url(args[0]):
        return expand_sitemap(args[0])
    targets = []
    for a in args:
        if is_url(a) or os.path.isfile(a):
            targets.append(a)
        elif os.path.isdir(a):
            targets.extend(sorted(glob.glob(os.path.join(a, "**", "*.html"), recursive=True)))
        else:
            targets.append(a)   # let it fail loudly with a real filename
    return targets, None


def local_coverage():
    """Reads sitemap.xml and llms.txt once, for the two publish checks."""
    try:
        with open(SITEMAP_PATH, encoding="utf-8") as f:
            sitemap = f.read()
        with open(LLMS_PATH, encoding="utf-8") as f:
            llms = f.read()
    except OSError:
        return None
    return {
        "sitemap_locs": set(re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap)),
        "llms_text": llms,
    }


def section(title: str, items: list, level: str = "###") -> list:
    return [f"{level} {title}", ""] + [f"- {x}" for x in items] + [""] if items else []


def main():
    ap = argparse.ArgumentParser(
        description="Audit every page of the site for SEO and AEO, scoring each one.")
    ap.add_argument("targets", nargs="*",
                    help="Files, folders or a live URL. Default: every .html under docs/")
    ap.add_argument("--strict", action="store_true",
                    help="Exit 1 if any page scores under 100. Use it in a build gate.")
    opts = ap.parse_args()

    targets, expand_note = resolve_targets(opts.targets)
    if not targets:
        # A live run that found nothing has a reason, and the note is it.
        print(expand_note or f"No HTML pages found under {SITE_DIR}/.", file=sys.stderr)
        return 1

    live = [t for t in targets if is_url(t)]
    coverage = None if live else local_coverage()

    results = []
    for t in targets:
        # One unreadable page must never take the whole run down with it.
        # load() reaches the network for a live URL, and every network
        # error is an exception: DNS, TLS, timeout, 500, a redirect loop.
        # Uncaught, that ends the process with a traceback, no report file
        # is written, and the weekly agent has nothing to read, which is
        # exactly how one founding-repo scheduled run died on a transient DNS
        # failure at the runner. A page we cannot read is a finding, so
        # record it as a critical against that page and keep going.
        try:
            passes, warns, fails, notes, kind = audit(t, coverage=None if is_url(t) else coverage)
        except Exception as e:
            passes, warns, notes, kind = [], [], [], "page"
            fails = [f"**Could not read this page** ({type(e).__name__}: {e}). "
                     "For a live URL that usually means the site or the network was "
                     "unreachable when the scan ran, not that the page is broken. "
                     "Re-run before acting on it."]
        results.append({"source": t, "passes": passes, "warns": warns,
                        "fails": fails, "notes": notes, "kind": kind,
                        "score": score_of(len(passes), len(warns), len(fails))})

    # Site-wide AEO checks run once, against the live site only.
    site_passes, site_warns, site_notes, site_fails = [], [], [], []
    if live:
        check_ai_access(live[0], site_warns, site_passes, site_notes)
    else:
        check_staging_local(site_passes, site_warns, site_notes, site_fails)
        check_review_count_local(site_passes, site_warns, site_fails, site_notes)
        check_town_variance_local(site_passes, site_warns, site_fails, site_notes)
        check_chrome_local(site_passes, site_fails)
        check_asset_provenance_local(site_passes, site_warns, site_fails, site_notes)
        check_comment_convention_local(site_warns, site_notes)
        check_pending_links_local(site_warns, site_notes)
        check_hours_llms_local(site_passes, site_fails)
        check_founding_llms_local(site_passes, site_fails)
        check_name_llms_local(site_passes, site_fails)
        check_redirects_local(site_passes, site_fails)
        check_service_count_llms_local(site_passes, site_fails)
    if expand_note:
        site_notes.append(expand_note)
    # The firm-fact checks that are OFF, stated on every run, live or
    # local, so an OFF check is never read as a PASS.
    if FACTS_OFF:
        site_notes.insert(0, FACTS_OFF_NOTE)

    total_pass = sum(len(r["passes"]) for r in results) + len(site_passes)
    total_warn = sum(len(r["warns"]) for r in results) + len(site_warns)
    total_fail = sum(len(r["fails"]) for r in results) + len(site_fails)
    site_score = score_of(total_pass, total_warn, total_fail)
    perfect = [r for r in results if r["score"] == 100]

    # The audited set is no longer all one thing: real pages, redirect
    # stubs standing at old WordPress URLs, and the 404 page. Spelling out
    # the mix keeps the headline count from reading as a page count.
    def _n(kind):
        return sum(1 for r in results if r.get("kind") == kind)

    parts = []
    if _n("page"):
        parts.append(f"{_n('page')} page{'' if _n('page') == 1 else 's'}")
    if _n("redirect-stub"):
        parts.append(f"{_n('redirect-stub')} redirect stub{'' if _n('redirect-stub') == 1 else 's'}")
    if _n("error-404"):
        parts.append(f"{_n('error-404')} error page")
    mix = f" ({', '.join(parts)})" if len(parts) > 1 else ""

    lines = [
        f"# {CLIENT_BRAND} ({CLIENT_LABEL}): SEO + AEO Audit Report", "",
        f"Target: {', '.join(opts.targets) if live else SITE_DIR + '/ (local build)'}", "",
        f"**Site score: {site_score}/100**: {len(perfect)} of {len(results)} "
        f"{'page' if len(results) == 1 else 'pages'} at 100/100{mix}",
        f"**{total_pass} passing · {total_warn} warnings · {total_fail} critical** across the site",
        "",
        "| Page | Score | Passing | Warnings | Critical |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        flag = "" if r["score"] == 100 else " ⚠️"
        lines.append(f"| `{r['source']}` | {r['score']}/100{flag} | {len(r['passes'])} | "
                     f"{len(r['warns'])} | {len(r['fails'])} |")
    lines.append("")

    if site_passes or site_warns or site_notes or site_fails:
        lines += ["## Site-wide", ""]
        lines += section("🔴 Critical: fix these first", site_fails)
        lines += section("🟡 Warnings: worth fixing", site_warns)
        lines += section("🟢 Passing", site_passes)
        lines += section("ℹ️ Notes (optional improvements)", site_notes)

    for r in results:
        lines += [f"## Page: `{r['source']}`: {r['score']}/100", ""]
        lines += section("🔴 Critical: fix these first", r["fails"])
        lines += section("🟡 Warnings: worth fixing", r["warns"])
        lines += section("🟢 Passing", r["passes"])
        lines += section("ℹ️ Notes (optional improvements)", r["notes"])

    report = "\n".join(lines)
    print(report)
    with open("audit-report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("\n(Report saved to audit-report.md)", file=sys.stderr)

    below = [r for r in results if r["score"] < 100]
    if below:
        print(f"{len(below)} page(s) under 100/100: "
              + ", ".join(r["source"] for r in below), file=sys.stderr)
    # A SITE-WIDE CRITICAL HAS TO TRIP --strict TOO. Before the review-count
    # check there were none, so strict only ever read per-page scores, and a
    # site-wide critical would have printed a red heading and exited 0.
    if site_fails:
        print(f"{len(site_fails)} site-wide critical(s).", file=sys.stderr)
    return 1 if (opts.strict and (below or site_fails)) else 0


if __name__ == "__main__":
    sys.exit(main())
