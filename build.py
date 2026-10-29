#!/usr/bin/env python3
"""Build the website into dist/.   Usage: python3 build.py"""
import sys

from sitekit.build import BuildError, build

if __name__ == "__main__":
    try:
        r = build()
    except BuildError as e:
        print("Build stopped:\n" + str(e), file=sys.stderr)
        sys.exit(1)
    print(f"Built {r['out']} with {r['media']} media files.")
    for w in r["warnings"]:
        print("Warning:", w)
    for m in r["missing"]:
        print("Missing:", m)
