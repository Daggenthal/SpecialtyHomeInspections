#!/usr/bin/env python3
"""Copy the original pictures (logo, badges, photos) from the old website into content/media/.

Every file is checked against the SHA-256 fingerprint recorded from the live server on
2026-10-28. A file is only saved if it is byte-for-byte identical, so the logo can't be
altered, recompressed or swapped on the way in.

    python3 tools/import_old_site.py           download anything missing
    python3 tools/import_old_site.py --check   only verify what's already here
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tools" / "original_manifest.json"
MEDIA = ROOT / "content" / "media"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify files already here, download nothing")
    args = ap.parse_args()

    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    base = m["source"]
    ok = bad = fetched = 0
    for f in m["files"]:
        dest = MEDIA / f["dest"]
        if dest.is_file() and sha256(dest.read_bytes()) == f["sha256"]:
            ok += 1
            continue
        if args.check:
            print(f"  MISSING or CHANGED: {f['dest']}")
            bad += 1
            continue
        url = base + f["orig"]
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (site migration)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
        except Exception as e:  # noqa: BLE001
            print(f"  could not download {url}: {e}")
            bad += 1
            continue
        if len(data) != f["bytes"] or sha256(data) != f["sha256"]:
            print(f"  REFUSED {f['orig']}: it doesn't match the recorded original (got {len(data)} bytes).")
            bad += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        fetched += 1
        ok += 1
        print(f"  saved {f['dest']}")

    total = len(m["files"])
    print(f"\n{ok}/{total} files verified identical to the originals" + (f" ({fetched} downloaded now)." if fetched else "."))
    logo = MEDIA / "logo.jpg"
    if logo.is_file():
        print(f"Logo SHA-256: {sha256(logo.read_bytes())}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
