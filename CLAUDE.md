# Distasio, Kowalski & Yelen, LLC (DKY)

This is a **client build** for **Distasio, Kowalski & Yelen, LLC**, a
personal injury and medical malpractice law firm with a general practice
side, in Wilkes-Barre, PA. The firm brands as DKY. Corcoran Communications
builds and monitors the site. The firm owns it.

**The site domain is `dklawllc.com`** (`https://dklawllc.com/`). **`dky.law`
carries the firm's email and redirects to the site.**

The name above is the name as Corcoran's engagement brief gives it. **The
firm has not yet confirmed its own name spelling**, so it is not the name of
record: `NAP_NAME` in `scripts/audit.py` is unset until the firm confirms it
in writing.

---

## The laws of this repo

### 1. The build spec is `pagemap.md`, and it is not written yet

**`pagemap.md` at the repo root will be the page map of record. It does not
exist yet, and nothing ships until it exists with the partner's written
approval.** It, not this file and not an idea anyone has later, says which
pages exist, which old URLs redirect and where, and which get an honest 404.
If a page is not on it, it does not get built. If the map should change, the
map changes first and the build follows.

The engagement's plan, pricing and client notes stay OUT of this repo,
because this repo is public. `pagemap.md` will carry only what the build
needs.

### 2. The corcoran-site-standards skill governs every page

It lives at `.claude/skills/corcoran-site-standards/SKILL.md`, in this repo,
from the first commit: a **byte-identical copy** of the firm's standards,
kept unedited on purpose so it does not fork per client. It is the law here,
not a reference. Read it before writing a line of copy or a line of markup.
Definition of done: `python3 scripts/audit.py --strict` passes at 100/100
and the diff is reviewed before commit.

### 3. The live site is the content source of record

**The live WordPress site at `https://dklawllc.com/` is the content source
of record. Its content is fact-checked and usable. Every claim on the new
site is checked against it, and the new site never claims anything the old
site does not already claim.**

**Corcoran writes every page itself**, in plain language, to the standard.
**The firm's September 17 package (Jeff's appendices) is a brief** for what
each page should do and for the firm's own vocabulary. **It is never copy to
paste.**

### 4. A claim the live site does not make carries a `[CONFIRM]`

**Any claim not on the live site carries a `[CONFIRM]` marker in the HTML
comment beside it, and a row in `proposed-changes.md` naming the partner who
must initial it.** `proposed-changes.md` is created with the first such
claim; it does not exist yet because no page does.

**A page with a `[CONFIRM]` fails the audit in strict mode once `STAGING` is
off.** This is enforced, not remembered: `scripts/audit.py` lists every
marker as a note on its page while `STAGING` is True (a draft may wait on a
partner's initials, but not silently), and scores every marker as a
**critical** once `STAGING` is False. `scripts/test-audit-checks.py`
section 47 holds both directions.

### 5. Every change is approved in writing by the named partner

**Every page, redirect and text change is approved in writing by the named
partner before it ships, and the approval is recorded with the approver's
name.** Proposals are made as before/after pairs, propose-first: nothing is
applied until the partner approves it.

### 6. The client owns its accounts

**The firm owns its GA4 property, its Google Business Profile, both domains
(`dklawllc.com` and `dky.law`), and its form endpoint.** Never the agency's.
That is what makes the exit promise, "you keep everything," easy to keep.

### 7. Never touch MX records on either domain

At cutover, change **web DNS records only**. **Never touch MX records, on
`dklawllc.com` or on `dky.law`.** The firm's email lives on `dky.law` and has
to survive every launch: mail that bounces during a gap is gone. Archive the
old WordPress site completely before it goes dark; it is the last copy.

---

## The firm's facts are OFF

**The NAP (name, address, phone), hours, geo, email, review count and
`sameAs` checks are OFF** in `scripts/audit.py` (`FACTS_OFF`), with a note
at the top of the file and a line in every report's Site-wide notes, so an
OFF check is never read as a PASS.

They stay off until the firm supplies firm-confirmed values in writing.
**No other client's values were carried, and DKY's are deliberately not
filled in from the live site**, because the firm has not yet confirmed its
own name spelling. When the values arrive: fill the constants in
`scripts/audit.py`, record who confirmed each and when beside it, set the
matching regexes (the comments give the shapes), and delete the line from
`FACTS_OFF`. The harness already proves each check works, switched on with
made-up fixture values.

The schema business type is **`LegalService`** (`SCHEMA_BUSINESS_TYPE`), and
the audit fails a local page whose business node is anything else.
**Attorney nodes come later**, as a separate decision.

## Staging ships noindexed on purpose

`STAGING = True` in `scripts/audit.py`. Until cutover every page carries
`noindex, nofollow` and a visible staging banner, `docs/robots.txt`
disallows everything, and canonicals are absolute to
`https://dklawllc.com/`, because the firm's real site is live and a
crawlable copy is a second address answering for one business. The audit
enforces all of it both ways. The flip is one commit: `STAGING = False`, run
`scripts/sync-chrome.py`, open `robots.txt`, rewrite `llms.txt`'s staging
paragraph. Record the date here when it happens.

## GitHub Pages

**Off, on purpose.** Turning it on before cutover would publish a site at a
github.io address while the firm's real site is still live. Leave it off.

## The audit target

The `SITE_URL` repo variable is set to `https://dklawllc.com/`, so **the
weekly Site Auditor scans the firm's LIVE WordPress site** until cutover.
`docs/` is a placeholder, and a local run over it would report nothing. The
live sitemap is WordPress's `<sitemapindex>`; `scripts/audit.py` follows it,
and `scripts/test-sitemap-expansion.py` keeps it doing so.

**The live scan's scope is deliberate (decided 2026-10-14): page and post
sitemaps only.** When the target is the live site, `scripts/audit.py`
scores only the pages in `page-sitemap.xml` and `post-sitemap.xml`
(`LIVE_SITEMAP_SCOPE`). The reason: on 2026-10-14 the full index listed 938
URLs, and only 111 of them were real pages (46 pages and 65 posts). The
other 827 were WordPress attachment, tag, category and author archives:
nobody wrote them, and scoring them buried the real pages under the same
few failures repeated hundreds of times. The archive sitemaps are still
fetched and counted. Every report's Site-wide notes give the full index's
URL count by sitemap, beside the real pages scored, so the gap between
what Google is handed and what exists is reported every week instead of
lost. **Do not widen the scope in a sweep.** Widening it is a decision, and
it gets recorded here. `scripts/test-sitemap-expansion.py` case 11 tests
the scope. **At cutover**,
decide explicitly whether to clear `SITE_URL` (scan `docs/`) or keep the
live domain, and record the decision here.

## The two agents

- **Site Auditor** (`agents/site-auditor.md`), Mondays 12:53 UTC. Files the
  weekly report as a GitHub Issue labeled `audit-report`, titled
  `DKY: Weekly SEO Audit, <date>`. That report is the monitoring product the
  retainer buys.
- **Google Watcher** (`agents/google-watcher.md`), daily 11:29 UTC. Files a
  `google-update` Issue only when something matters to this firm. Most days
  it files nothing, and silence is a feature.

Neither runs on the hour (changed 2026-10-15). GitHub delays scheduled
runs at the start of every hour, and the sibling repos' reports were
landing mid-afternoon; the workflow files carry the reasoning. Do not
tidy the minutes back to :00.

A Watcher alert lives one week (decided 2026-10-14, same rule as the
agency's own repo). The auditor reads every open `google-update` issue
on Monday, folds each into the report as a priority, an item for the
owner, or a no-action line, and then closes it with that line as the
comment. An off-site item lives in the Monday report, never in an open
issue. A further development on a closed alert is a new issue naming
the old number, never a reopen. The Monday report is the one thing a
person has to read. The auditor's `Bash(gh issue:*)` grant already
covers `gh issue close`; the workflows did not change.

Both need the `ANTHROPIC_API_KEY` secret. **The repo's owner adds it through
the GitHub website.** Do not add, print, echo or otherwise handle secrets
from a terminal.

## What is in here

| Path | What it is |
|---|---|
| `.claude/skills/corcoran-site-standards/` | The law. Unedited copy of the firm's standards. |
| `scripts/audit.py` | The SEO and AEO scanner. Scores every page separately. Holds the client block, the OFF firm facts, the staging switch, the `[CONFIRM]` law, the business type, and the one-list tables (`SERVICES`, `REDIRECTS`, `AREA_SERVED`), all empty until `pagemap.md` and the firm fill them. |
| `scripts/test-audit-checks.py` | The audit's test harness: every check proven both ways, the OFF checks proven quiet and proven working with fixture values. |
| `scripts/test-sitemap-expansion.py` | Tests the sitemap expansion. Run it before touching that code. |
| `scripts/build-sitemap.py` | Generates `docs/sitemap.xml` from the pages' own `dateModified`. |
| `scripts/stamp-assets.py` | Cache-busting stamps for `docs/assets/site.css` and `site.js`, once they exist. |
| `scripts/sync-chrome.py` | Writes the header, footer, favicon links, noindex and staging banner into every page. The nav and footer are **not specified yet** and it refuses to write them until `pagemap.md` and the NAP exist; the staging and favicon machinery works today. |
| `scripts/sync-area-served.py` | Writes `AREA_SERVED`, `SAME_AS` and `FOUNDING_DATE` into every business node, each only once it is set. |
| `scripts/sync-service-cards.py` | Writes every service card and Related Services section from `SERVICES`. |
| `scripts/prepare-favicon.py` | Turns the firm's own site icon into the favicon set. |
| `scripts/fetch_seo_news.py` | Pulls the headline sweep the Google Watcher reads. |
| `scripts/cascade-analyzer.html` | CSS cascade analyzer. |
| `scripts/mobile-check.md` | The mobile check procedure. |
| `templates/service-page-template.html` | The service and location page template. Every firm fact a token with no default. |
| `agents/` | The two agents' job descriptions. |
| `.github/workflows/` | The two agent schedules. |
| `docs/` | The site. A placeholder: the build has not started. |

## Before you commit

```
python3 scripts/test-sitemap-expansion.py     # exits 1 if anything fails
python3 scripts/test-audit-checks.py          # exits 1 if anything fails
python3 scripts/stamp-assets.py               # after touching site.css or site.js
python3 scripts/build-sitemap.py              # after adding or removing a page
python3 scripts/sync-area-served.py           # after changing a one-list field or adding a page
python3 scripts/sync-chrome.py                # after adding a page or changing the nav
python3 scripts/sync-service-cards.py         # after changing SERVICES or a service card
python3 scripts/audit.py --strict             # every page at 100/100
```

The five middle commands take `--check`, which exits 1 instead of rewriting.

## Reporting a stop

**Every mid-run stop ends with a section titled `===== RELAY TO THE
STRATEGY CHAT =====`**, holding only the question, the options, and the
measurements behind them. Everything above that section is for the record.
**A completed run needs no relay beyond "pushed".**
