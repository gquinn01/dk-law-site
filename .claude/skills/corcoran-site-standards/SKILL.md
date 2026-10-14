---
name: corcoran-site-standards
description: >-
  Corcoran Communications' website-building doctrine — the standards behind
  corcoranpr.com, applied to every site the firm builds or reviews. Use this
  skill for ANY website work for Corcoran or its clients — building or
  reviewing site pages, writing or editing web copy, headlines, FAQs,
  service/industry/location pages, meta titles and descriptions, schema and
  structured data, turning a site audit's output into a plain-English client
  report, planning a new client site, or running a launch or cutover. Trigger
  whenever the user mentions a website build, web copy, page review, landing
  page, FAQ, local SEO, AEO, site audit, client site, or rewriting a page,
  even if they never name this skill or the word standards.
---

# Corcoran Site Standards

The doctrine that built corcoranpr.com, distilled so every future site holds the same line. These rules were each earned by a real mistake or a real win during the founding build; the reasons are included because the reasons are what generalize.

## 1. Facts are sacred — the prime law

Every claim on a site must be true and verified by a human who can stand behind it: the **fact-checker of record** (Greg for Corcoran's site; the client-owner for a client site). Numbers, dates, client names, experience claims, service scope — all of it passes through that person before it ships.

- Never invent a statistic, a date, a client, or a result — not even a plausible one, not even as a placeholder that "will be fixed later." Placeholders ship. If a number is unverified, the page ships without it.
- Client-attributed numbers require the client's written permission. Client names appear only where the relationship is public and the relationship is the point.
- When compressing facts into copy, watch for **fabrication-by-fusion**: two true statements merged into one false one ("serving X since YEAR" when the firm existed in YEAR but served X later). Decouple rather than fuse.
- A hedge is honest when the data limits us: "where your systems allow us to see it" attaches to every metric that needs someone else's data.

## 2. Scope honesty

A page may only sell what the business actually does. The founding build's worst late bug was a service page selling day-to-day social posting when the firm only runs ads — it passed every automated check because no machine knows what a business really sells. Interrogate scope claims explicitly: for every "we handle/manage/produce/respond" sentence, ask the fact-checker "do you actually do this?"

- Disqualifiers are house style, not weakness: "If you need someone to run your accounts, we are not the right fit, and it is better to know that now." Saying who shouldn't call saves both sides a wasted conversation and makes every other claim more credible.
- When scope changes, sweep the WHOLE site plus llms.txt and schema descriptions — and remember bare-text service lists hide from link-based greps.

## 3. Voice and language

- Plain language throughout. The reader's own industry vocabulary is not jargon — "covers" for restaurateurs, "bays" for shop owners, "billed an hour" for law firms signal insider knowledge. Marketing-speak ("strategy session," "solutions," "leverage") is the jargon to kill. Match the register of the audience: the corner-shop idiom on the collision page reads wrong on the law-firm page.
- No em dashes anywhere, including code comments. American spelling.
- Outcomes language: results are counted in phone calls, form fills, and booked jobs — never impressions, reach, or rankings alone.
- The page speaks to the reader, never about itself.
- A sentence over ~35 words gets rewritten.
- **Protected voice**: deliberate zingers, firm-philosophy lines, and factual-consequence endings ("We would rather earn the next month than trap you in the last one") are features, not defects. Editorial sweeps repair mechanical faults; they do not flatten voice. When a line is deliberate style, prefer repair over replacement, and prefer leaving it alone over repair.

## 4. The editorial tests (T1–T9)

Run these against copy; cite the test by number when flagging:

1. **Self-reference** — copy about the copy ("this page explains...").
2. **Wrong actor** — sentences that put the work on the reader when the firm does it, or vice versa; ambiguous "we/you" duty.
3. **Double negatives.**
4. **Reports-as-homework** — framing deliverables as burdens ("clients read the reports" → "clients *can* read the reports").
5. **Ambiguous antecedents and counts** — a "yours," "it," or number whose referent takes a second read.
6. **Wrong-note endings** — sections that end on a minor or off-key beat instead of their strongest line.
7. **Borrowed history** — implying experience or timeline the business doesn't have.
8. **Stale-clock phrases** — copy that dates itself ("recently," "new this year").
9. **Over-long plain-language failures** (see the 35-word rule).

Sweep doctrine: machine sweeps catch drift; humans catch truth and register. Present findings as before/after pairs, **propose-first — nothing applied until the fact-checker approves**. Pattern text that repeats across pages ships byte-identical everywhere it lands, with the page list confirmed before applying.

## 5. FAQ law

- **The standalone test**: every answer's opening sentence must survive being lifted without its question — that is exactly what AI assistants do with it. Bare particles fail ("No." / "Yes." / "Two things.") — comma-merge them into the sentence that follows ("No, monitoring and marketing plans run month to month..."). Echoing the question's key phrase in the answer strengthens the match. Surviving the lift also means being TRUE alone, not merely grammatical: an opener can read perfectly and still carry only half the truth ("Greg writes them" before "an AI drafts them") — the reassurance after it does not travel when an assistant quotes only sentence one. The whole truth goes in the opener.
- **The mirror law**: visible FAQ text and FAQPage schema are byte-identical, questions and answers, both directions. Enforce with an automated check that scores mismatches as defects, not notes.
- House-canonical answers (like the contracts answer) render as ONE distinct string on every page that carries them. A page whose engagement model doesn't fit the canonical answer omits the question entirely rather than writing a variant — absence beats a second rendering.
- Two pages sharing a distinctive opener verbatim is a twin; vary one. A line on 20+ pages is a refrain; keep it uniform.

## 6. Structure, SEO, and AEO law

- One H1 per page. Title ≤60 characters, meta description ≤160, og:description ≤160 — **counted by machine, never by eye** (eyeballed counts have a documented failure record).
- Canonical, og:url, sitemap entries, and schema @id are absolute to the production domain; all internal links are relative.
- Schema: one @graph per page repeating the full business node under a shared @id; Service nodes reference it; BreadcrumbList mirrors the visible breadcrumb; NO price, offer, review, or rating markup unless the data is real and the owner has decided to publish it.
- NAP (name, address, phone) is character-identical everywhere it appears — site, schema, Google Business Profile, every directory. The business-name field takes the real name with nothing appended.
- AEO: robots.txt stays open to the major AI crawlers; maintain llms.txt; well-mirrored FAQs are the AI-answer surface.
- Redirects never lie about relevance: an old URL maps to a genuinely equivalent page or gets an honest 404 — never a forced mapping to a sales page.

## 7. Location pages earn their existence

Doorway pages get sites devalued. A town page exists only when it carries: three checkable local facts, a unique FAQ, and verified variance against its hub and every sibling (<30% shared vocabulary, no shared substantive H2s). Coverage without pages is legitimate: county hubs carry the county, and smaller towns get named inside a bigger page. New town pages are gated on Search Console evidence of real demand — data decides, not guesses.

## 8. Process discipline

- **Definition of done**: the full audit passes at 100/100 in strict mode, and the diff is reviewed before commit. No exceptions, including "small" changes.
- **Mechanism over memory**: any rule worth keeping becomes an automated check. A rule that lives only in a comment or a memory will be violated; a rule the build fails on will not.
- **Record exceptions where future workers will look**: a deliberate deviation (a missing section, a root-relative page, an absent FAQ) gets a comment in the file and a line in the constitution stating what is absent and why, so a future consistency sweep doesn't "fix" it.
- **Suspect the tool first**: when a result looks unrealistically bad (or good), verify what was actually measured before acting — the founding build's harshest audit report turned out to be scoring XML files as web pages, and its phantom bugs were stale caches. Hard-refresh before judging; reproduce before fixing.
- Verify claims of completion mechanically (diff tails against HEAD, grep for residuals) rather than by eye.

## 9. Design and conversion doctrine

- **Content first**: structure and the words are agreed before anything is designed. Design serves copy that already works; it never rescues copy that doesn't.
- **Palette law**: the palette is defined in exactly one place (the shared stylesheet). Solid colors by default — no glows, and no gradients on text, buttons, cards, or accents. Section-background gradients are the one sanctioned exception, permitted only as a dated, recorded decision in the site's constitution (corcoranpr.com: decided 2026-08-11). Small accent text on light backgrounds gets its own darker accessible shade.
- **Motion as evidence, not costume**: animation exists only where it proves something true — numbers counting up because they're real, a diagram pulsing because the system is genuinely alive. Ambient decoration (animated borders, glow effects) reads as the template every AI-startup site uses, and it taxes phones. When in doubt, less.
- **Button grammar**: a filled button means act (the one conversion action, the phone); a text link means read more. Never inflate navigation into buttons — the grammar only protects the real CTA if it is never violated. No exit links adjacent to forms.
- **Real photos only** — the owner, the shop, the work. No stock, no AI-generated imagery. The site that tells clients real beats stock must live by it.
- **Brand assets**: derive, never guess — new marks (avatars, square crops) are built from the existing logo's actual letterforms, not a lookalike font. Record resolution ceilings and asset roles in the brand folder's README. Wordmarks die in small circles; avatar slots need a lettermark with high contrast at 48px.
- **Keyword validation before pages exist**: service page titles and the page list are chosen against real search volume and intent for the actual geography (Keyword Planner or equivalent), not guessed.
- **Local listings**: consistency beats completeness. Exact NAP everywhere; the name field takes the real business name with nothing appended; full profiles only on the platforms customers and AI actually read (Google, Bing, Apple, Yelp, Facebook) using the same description text everywhere; decline every premium-listing upsell; a wrong existing listing outranks a missing one as a problem. Keep a written record of every listing touched. Reviews are the ranking engine: ask real clients personally, paced, never incentivized or ghost-written.

## 10. Client builds

- The client is fact-checker of record for their own site — hold them to it as a role, not a courtesy.
- The machinery (audit script, stamp script, templates, agent job descriptions, the constitution's laws) goes into the client repo from its first commit, so the standards enforce themselves from day one.
- Small and true beats big and padded: a local business needs the pages that are fact, not a page count.
- The client owns their accounts: GA4 property, Google Business Profile, domain, form endpoint — structured so the exit promise ("you keep everything") is easy to keep. Analytics goes in the client's Google account, never the agency's.
- Cutover law: change web DNS records only, **never MX** — email must survive every launch. Archive the old site completely before it goes dark; it is the last copy.
- The weekly Site Auditor filing a plain-English Monday report on the client's site IS the monitoring product their retainer buys.
- Client-facing reports (including audit translations): plain language, no spin, honest about what's fine, clear about what's costing them, one memorable number. Harsh is acceptable only when true.
- **Correcting a published record** (a report, an Issue, a post): strike, never delete — the record stays readable. Strike stale instructions hardest: a stale instruction recruits a reader, while a stale claim only misleads one. Never over-strike into live work. Every correction carries a pointer to its evidence, and every editorial change to the record is itself recorded.
- **AI disclosure**: a blog the agents draft — the firm's own or a client's — says so plainly in a visible FAQ: the drafting named, the human fact-check and approval named, with an opening sentence that is true alone. A firm that sells AI-powered work does not hide its own use of it.
