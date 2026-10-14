# Checking mobile layout, without fooling yourself

Sits next to `audit.py` because it is the other half of "is this page
actually fine": the audit checks the markup, this checks the layout.

## The trap

Headless Chrome on macOS will not lay a page out below roughly 500px.
Ask for `--window-size=375,N` and it lays out at about 500px wide and
then crops the screenshot to 375px. What you get back is the left 375px
of a 500px page. Every section loses its right-hand padding, cards run
off the edge, and headings look clipped.

It looks exactly like a horizontal overflow bug. It is not one. On
2026-08-16 this cost most of a session: a site-wide mobile defect was
reported, a fix was attempted against the wrong cause, and the page had
been correct the whole time.

## The tell

Render the same page at several widths and compare the DOCUMENT HEIGHT.
A page that genuinely reflows gets taller as it gets narrower. If the
height is identical at 375, 420, 460 and 500, the layout viewport never
changed and you are looking at the clamp, not the page.

That was the actual evidence: 12680px at all four widths, changing only
at 560.

## The method that works

Load the page in an iframe of the width you want to test, inside a
window wide enough to escape the clamp. The iframe gets a real viewport
of exactly that width.

```html
<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>html,body{margin:0;background:#ff00ff}
iframe{width:375px;height:16000px;border:0;display:block}</style>
</head><body><iframe src="services/web-design/" scrolling="no"></iframe></body></html>
```

Save it into `docs/` as a temporary file, serve the repo, and shoot it
in a 600px window:

```
python3 -m http.server 8800 --bind 127.0.0.1 &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=4000 \
  --window-size=600,16000 --screenshot=out.png \
  "http://127.0.0.1:8800/docs/_probe.html"
```

The magenta background makes the iframe edge obvious: anything magenta
inside x < 375 means the frame is not the width you think it is. Delete
the probe file afterwards. It must never be committed, because a stray
page in `docs/` is a page the audit will score and a crawler can find.

## Reading the result

Cards and inputs sit inside `.wrap`, which carries 30px of side padding.
In a correct 375px render they span x=30 to x=344, so the insets are
30px on both sides. Symmetric insets mean the page fits. An inset of 0
on the right means content is being clipped.

Checked this way on 2026-08-16, the homepage, a service page and a town
page all came back 30/30 at 375px.

## Before calling anything a layout bug

1. Reproduce it with the iframe method, not a window screenshot.
2. Check the document height across widths, as above.
3. If it is real, bisect by removing one section at a time. If removing
   every section individually fails to change the result, the page is
   not the cause and the tooling is.

## The second trap: a tall probe iframe breaks `vh`

Added 2026-09-23, after it produced a wrong number four times.

The iframe method above fixes the width. **It does not fix the height, and
the hero's size is written in `vh`:**

```
.heroB                      min-height: clamp(420px, 84vh, 600px)
.heroB, max-width 599px     min-height: clamp(380px, 76vh, 560px)
.heroB-copy                 padding-top: clamp(10px, 4vh, 44px)
.heroB--ox .heroB-copy      padding-bottom: clamp(50px, 7vh, 58px)
```

`vh` resolves against the **iframe's own height**, not the phone you think
you are testing. A probe frame 16000px tall makes `76vh` 12160px, so every
clamp pins to its maximum and the hero renders at its tallest possible size.
The CTA row then sits lower than it ever would on a phone, and the fold
measurement reports a miss that does not exist.

**What it cost:** on the founding client build, a service page was reported as missing 360x640 by 17px
in four separate records, and CLAUDE.md's own note that it "clears by 2" was
flagged as a false record three times. CLAUDE.md was right. The probe was
wrong.

```
                        tall iframe (wrong)    iframe = viewport (right)
home  360x640 cutover   597  misses by 17      578  CLEARS by 2
coll  390x664 banner    629  misses by 23      580  CLEARS by 24
```

**The rule: for anything that measures the fold, the iframe's height must be
the viewport height you are testing, not a tall scroll surface.** Check it
in the probe itself: report `innerHeight` and the computed `min-height`
beside the answer, so a wrong basis is visible in the output instead of
hiding in it.

That does mean the frame shows only the first screen. That is all the fold
measurement needs. Measure page HEIGHT in a tall frame and the FOLD in a
viewport-sized one; they are two different questions and one frame cannot
answer both.

## The third trap: a probe iframe SHORTER than the page

Added 2026-09-24, after a section map came back about 400px wrong in the
lower half of a page.

This is the complement of the one above, and the two pull in opposite
directions, which is exactly why both are easy to walk into.

**If the iframe is shorter than the page, the iframe scrolls.** A scrollbar
appears inside it and takes about 15px of layout width with it. A frame you
asked for at 390 then lays the page out at about 375. Nothing announces
this. The numbers keep arriving and they look reasonable.

**What it does to a map is worse than a flat offset.** Above the first
element whose text re-wraps at the narrower width, every box is right. At
that element the page gets taller, and from there down every reading is
wrong by an error that GROWS as more paragraphs re-wrap beneath it. So the
top of the report agrees with the rendered page and the bottom does not,
which is the shape most likely to be believed.

**What it cost:** a 20000px frame against a 21610px page. The map was out
by roughly 400px near the footer and correct at the top.

```
                        iframe 20000 (short)    iframe 21700 (tall enough)
page width laid out     ~375                    390
lower-page boxes        ~400px off              to the pixel
```

**The rule: a section probe's iframe must be AT LEAST as tall as the page it
measures.** Against the fold rule above (a fold probe's iframe must EQUAL
the real viewport), that is not a contradiction. They are different
measurements. A fold probe asks what fits on one screen, so its frame has to
be one screen. A section probe asks where things sit in the whole document,
so its frame has to contain the whole document.

**Two ways to make the mistake visible instead of trusting the number:**

1. **Probe twice at two different tall heights and require the maps to
   agree.** A frame that is tall enough gives the same answer as a taller
   one. A frame that is short does not.
2. **Check one landmark against rendered pixels.** The footer's top edge is
   a good one: find it in the report, then find it in a screenshot. If they
   disagree, the frame is the suspect, not the page.

Either check is cheap, and either would have caught this in one run.

## The fold budget on a phone, and the 60px nobody counts

Added 2026-09-10, after the hero CTA pair was found sitting below the
fold on every phone.

**The usable height is 604px, not 664.** A 390x664 viewport is what an
iPhone 12, 13 or 14 shows in Safari with its own chrome around it. The
call bar is `position: fixed; bottom: 0` and 60px tall, and it covers
whatever is under it rather than pushing it up. So anything below 604
is not on screen, and tuning a hero against 664 is tuning against 60px
that are already spent.

The staging banner spends another 57px at 390, because its sentence
wraps to two lines. That comes off at cutover, so **measure both
states**: it is the only difference between what a reviewer sees today
and what a customer will see.

## Measuring it, rather than judging it by eye

Same iframe trick as above, plus same-origin measurement. The parent
window can read the iframe's DOM, so the probe reports numbers instead
of a picture:

```js
var d = f.contentDocument, w = f.contentWindow;
function box(el) {
  var r = el.getBoundingClientRect();
  return {t: Math.round(r.top + w.scrollY), b: Math.round(r.bottom + w.scrollY)};
}
box(d.querySelector('.hero .cta-row')).b <= 604   // the whole test
```

Run it once as the page stands, then inject
`.staging{display:none !important}` into the iframe's head and run it
again. That second number is the real one.

Read it back with `--dump-dom` and a marker string around the JSON,
not with `--screenshot`. A screenshot tells you something looks wrong;
these numbers tell you by how much, which is what you need to fix it.

**Shoot one picture at the end anyway**, with a 2px line absolutely
positioned at 604, and check that the line falls where the arithmetic
said it would. The numbers catch the bug and the picture catches a
wrong assumption in the numbers.

Delete every probe file afterwards. A stray page in `docs/` is a page
the audit scores and a crawler can find.
