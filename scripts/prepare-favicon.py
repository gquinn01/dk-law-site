#!/usr/bin/env python3
"""
Turns the firm's own site icon into the favicon set every page links,
and prints every number it used. Carried from the founding client build,
whose pre-launch sweep found no favicon on any page while the live site had
one, so cutover as built would have dropped the mark Google shows beside
every result.

The irreversible decisions live in a script that can be re-run and
audited.

WHERE THE SOURCE COMES FROM. The firm's own published site icon, the
largest original its live WordPress site at https://dklawllc.com/
publishes, NOT YET READ OR RECORDED. When it is, record here the file's
URL, its pixel size, the date it was read and who confirmed it is the
firm's current mark. A WordPress head usually links small derivatives;
take the largest original. It is not committed: --src names the fetched
file, which lives outside the repo. AFTER CUTOVER THAT URL STOPS
RESOLVING, and the archive of the old site is then the only copy.

It is the firm's mark, unchanged: no redraw, no crop, no recolour. The
brand rule says derive, never guess. If the firm has no square icon, this
script is not the place to make one.

WHAT IT DOES:

  1. Reads the source's provenance through audit.read_asset_provenance
     and REFUSES a flagged file, like every other prepare script.
  2. Requires a square PNG of at least 192 pixels a side.
  3. Resizes with sips (the only image tool on a stock Mac) to each size.
  4. Strips every PNG chunk but the ones that carry pixels (IHDR, PLTE,
     tRNS, IDAT, IEND), structurally, so no metadata ships.
  5. Writes favicon.ico as an ICO whose three entries (16, 32, 48) are
     PNGs, which every current browser reads, with nothing but struct.
  6. Builds in a temp directory and installs only on success.

WHAT IT EMITS, and the head links scripts/sync-chrome.py writes for them:

    docs/favicon.ico                  16, 32, 48    rel="icon" sizes="any"
    docs/assets/img/icon-192.png      192           rel="icon" type="image/png"
    docs/assets/img/icon-180.png      180           rel="apple-touch-icon"

Usage:
    python3 scripts/prepare-favicon.py --src /path/outside/repo/site-icon.png
    python3 scripts/prepare-favicon.py --src ... --out-dir /tmp/x   # draws without touching docs/
"""

import argparse
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOCS = os.path.join(REPO, "docs")

ICO_SIZES = (16, 32, 48)
PNGS = (("assets/img/icon-192.png", 192), ("assets/img/icon-180.png", 180))
KEEP = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}
SIG = b"\x89PNG\r\n\x1a\n"


def load_audit():
    spec = importlib.util.spec_from_file_location("audit", os.path.join(HERE, "audit.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def chunks(data):
    if data[:8] != SIG:
        raise SystemExit("FAILED: not a PNG")
    i = 8
    while i < len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        yield data[i + 4:i + 8], data[i + 8:i + 8 + n], data[i:i + 12 + n]
        i += 12 + n


def png_size(data):
    for kind, body, _raw in chunks(data):
        if kind == b"IHDR":
            return struct.unpack(">II", body[:8])
    raise SystemExit("FAILED: PNG has no IHDR")


def strip(data):
    """Only the chunks that carry pixels. Each kept chunk's CRC is
    re-checked, so a corrupt file fails here rather than in a browser."""
    out, dropped = [SIG], []
    for kind, body, raw in chunks(data):
        if zlib.crc32(kind + body) != struct.unpack(">I", raw[-4:])[0]:
            raise SystemExit(f"FAILED: bad CRC on {kind!r}")
        if kind in KEEP:
            out.append(raw)
        else:
            dropped.append(kind.decode("latin-1"))
    return b"".join(out), dropped


def resize(src, size, tmp):
    out = os.path.join(tmp, f"r{size}.png")
    subprocess.run(["sips", "-s", "format", "png", "-z", str(size), str(size), src, "--out", out],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    data, dropped = strip(open(out, "rb").read())
    w, h = png_size(data)
    if (w, h) != (size, size):
        raise SystemExit(f"FAILED: sips gave {w}x{h} for {size}")
    return data, dropped


def ico(entries):
    """An ICO of PNG entries: a 6-byte header, a 16-byte directory entry
    each, then the PNGs. A width or height of 256 is written as 0."""
    head = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dirs, blobs = [], []
    for size, data in entries:
        b = size if size < 256 else 0
        dirs.append(struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset))
        blobs.append(data)
        offset += len(data)
    return head + b"".join(dirs) + b"".join(blobs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--src", required=True, help="the firm's site icon, fetched outside the repo")
    ap.add_argument("--out-dir", default=DOCS, help="where to install (default docs/)")
    a = ap.parse_args()

    if os.path.abspath(a.src).startswith(REPO + os.sep):
        raise SystemExit("FAILED: --src must live outside the repo")
    audit = load_audit()
    prov = audit.read_asset_provenance(a.src)
    print(f"source        {a.src}")
    print(f"  bytes       {prov['bytes']}")
    print(f"  provenance  DigitalSourceType={prov['source_type'] or '(none)'} "
          f"CreatorTool={prov['tool'] or '(none)'} C2PA={prov['c2pa']}")
    if prov["reasons"]:
        raise SystemExit("FAILED: the source is flagged: " + "; ".join(prov["reasons"]))
    raw = open(a.src, "rb").read()
    w, h = png_size(raw)
    print(f"  size        {w}x{h}")
    if w != h or w < 192:
        raise SystemExit(f"FAILED: need a square PNG of at least 192 a side, got {w}x{h}")

    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "out")
        os.makedirs(os.path.join(stage, "assets", "img"))
        entries = []
        for size in ICO_SIZES:
            data, dropped = resize(a.src, size, tmp)
            entries.append((size, data))
            print(f"ico entry     {size:>3}  {len(data):>6} bytes  dropped {dropped or 'nothing'}")
        blob = ico(entries)
        open(os.path.join(stage, "favicon.ico"), "wb").write(blob)
        print(f"favicon.ico   {len(blob)} bytes, {len(entries)} PNG entries")
        for rel, size in PNGS:
            data, dropped = resize(a.src, size, tmp)
            open(os.path.join(stage, rel), "wb").write(data)
            print(f"{rel:<28} {size}x{size}  {len(data):>6} bytes  dropped {dropped or 'nothing'}")
        for rel in ["favicon.ico"] + [r for r, _s in PNGS]:
            got = audit.read_asset_provenance(os.path.join(stage, rel))
            if got["reasons"] or got["source_type"] or got["tool"] or got["c2pa"]:
                raise SystemExit(f"FAILED: {rel} still carries metadata: {got}")
        for rel in ["favicon.ico"] + [r for r, _s in PNGS]:
            dst = os.path.join(a.out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(stage, rel), dst)
            print(f"installed     {dst}")


if __name__ == "__main__":
    sys.exit(main())
