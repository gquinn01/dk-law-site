#!/usr/bin/env python3
"""
Writes the business node's one-list fields from scripts/audit.py into the
shared business node of every page under docs/: AREA_SERVED as
areaServed, SAME_AS as sameAs, and FOUNDING_DATE as foundingDate.

WHY A SCRIPT. The business node repeats in full on every page, and a list
typed into 26 pages is 26 chances for one of them to drift. On the
founding client build a town had its own page and was missing from the
served list every page carried. Here each list lives once, this writes it
everywhere, and scripts/audit.py fails any page whose node says otherwise.

sameAs is placed directly after the node's hasMap, because the list opens
on that same Maps URL; foundingDate directly after email. One script,
because all three are the business node's one-value fields and a second
script would be a second thing to forget to run.

EACH FIELD IS WRITTEN ONLY ONCE ITS CONSTANT IS SET. While AREA_SERVED is
empty, or SAME_AS or FOUNDING_DATE is None (the firm has not confirmed
them; see FACTS_OFF in scripts/audit.py), that field is left exactly as
the page has it. Nothing is written from a value nobody confirmed.

WHAT IT TOUCHES. Only those fields of a node whose @type is a
LocalBusiness type. Every other node, including a Service node's own
areaServed (a location page names its place there), is left as it is.

HOW IT WRITES. Each JSON-LD block is parsed, the field replaced, and the
block serialised again with json.dumps(indent=2, ensure_ascii=False) under
the block's own leading indentation. A block that does not round-trip byte
for byte through exactly that is refused, so the only bytes that change
are the field's.

    python3 scripts/sync-area-served.py           # write every page
    python3 scripts/sync-area-served.py --check   # exit 1 if any page is out of date
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK_RE = re.compile(r'(?s)(<script type="application/ld\+json">)(.*?)(</script>)')


def reserialise(body: str, data) -> str:
    """The block as json.dumps writes it, under the block's own indentation
    and with its own leading and trailing whitespace."""
    first = body.lstrip("\n")
    indent = re.match(r"[ ]*", first).group(0)
    out = "\n".join(indent + line for line in
                    json.dumps(data, indent=2, ensure_ascii=False).splitlines())
    head = body[:len(body) - len(body.lstrip("\n"))]
    tail = body[len(body.rstrip()):]
    return head + out + tail


def synced(html: str) -> str:
    want = audit.area_served_nodes() if audit.AREA_SERVED else None
    profiles = list(audit.SAME_AS) if audit.SAME_AS else None
    founding = audit.FOUNDING_DATE or None
    if want is None and profiles is None and founding is None:
        return html

    def with_same_as(n: dict) -> dict:
        """The node with foundingDate directly after email and sameAs
        directly after hasMap (each at the end if its anchor is missing),
        every other key in its own order. A field whose constant is unset
        is left as the node has it."""
        out = {}
        own = {"sameAs": profiles, "foundingDate": founding}
        for k, v in n.items():
            if k in own and own[k] is not None:
                continue
            out[k] = v
            if k == "email" and founding is not None:
                out["foundingDate"] = founding
            if k == "hasMap" and profiles is not None:
                out["sameAs"] = profiles
        if founding is not None:
            out.setdefault("foundingDate", founding)
        if profiles is not None:
            out.setdefault("sameAs", profiles)
        return out

    def one(m):
        body = m.group(2)
        data = json.loads(body)
        if reserialise(body, data) != body:
            raise SystemExit("FAILED: a JSON-LD block does not round-trip byte for byte, so "
                             "rewriting it would change more than its areaServed and sameAs. "
                             "Nothing written.")
        items = data if isinstance(data, list) else [data]
        def is_business(n) -> bool:
            t = n.get("@type") if isinstance(n, dict) else None
            types = t if isinstance(t, list) else [t]
            return bool(audit.LOCAL_BUSINESS_TYPES.intersection(x for x in types if isinstance(x, str)))

        for it in items:
            if not isinstance(it, dict):
                continue
            graph = it.get("@graph")
            nodes = graph if isinstance(graph, list) else [it]
            for i, n in enumerate(nodes):
                if is_business(n):
                    if want is not None:
                        n["areaServed"] = want
                    fixed = with_same_as(n)
                    n.clear()
                    n.update(fixed)
        return m.group(1) + reserialise(body, data) + m.group(3)

    return BLOCK_RE.sub(one, html)


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for path in sorted(glob.glob(os.path.join(ROOT, "docs", "**", "index.html"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            html = f.read()
        new = synced(html)
        if new != html:
            stale.append(os.path.relpath(path, ROOT))
            if not check:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
    if check:
        if stale:
            print(f"{len(stale)} page(s) carry a served list, profiles or founding date "
                  f"that are not AREA_SERVED, SAME_AS and FOUNDING_DATE:")
            for p in stale:
                print(f"  {p}")
            print("Run scripts/sync-area-served.py.")
            return 1
        def state(name, value, n=None):
            if not value:
                return f"{name} (unset, not written)"
            return f"{name} ({n})" if n else f"{name} ({value})"
        print("Every page's business node carries "
              + ", ".join((state("AREA_SERVED", audit.AREA_SERVED, f"{len(audit.AREA_SERVED)} places"),
                           state("SAME_AS", audit.SAME_AS, f"{len(audit.SAME_AS or ())} profiles"),
                           state("FOUNDING_DATE", audit.FOUNDING_DATE))) + ".")
        return 0
    print(f"wrote {len(stale)} page(s)" + ("" if not stale else ":"))
    for p in stale:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
