#!/usr/bin/env python3
"""Make the zip that puts the "Website Editor" icon on Dad's Windows PC.

    python3 tools/make_windows_kit.py http://pi.tail1234.ts.net:8787/

Writes dist-windows/Website-Editor-Setup.zip with Install.cmd, install.ps1 (with the
editor's address filled in) and the site's own favicon as the icon. Copy the zip to his
PC, unzip, double-click Install.cmd. See the README, "Dad's PC".
"""
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "deploy" / "windows"
OUT = ROOT / "dist-windows" / "Website-Editor-Setup.zip"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    url = sys.argv[1].strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or any(c in url for c in "\"'`$;&| "):
        sys.exit("Give the editor's full address, e.g. http://pi.tail1234.ts.net:8787/")
    ps1 = (KIT / "install.ps1").read_text(encoding="utf-8").replace("__EDITOR_URL__", url)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Website Editor Setup/install.ps1", ps1.replace("\r\n", "\n").replace("\n", "\r\n"))
        z.write(KIT / "Install.cmd", "Website Editor Setup/Install.cmd")
        ico = ROOT / "content" / "media" / "favicon.ico"
        if ico.is_file():
            z.write(ico, "Website Editor Setup/editor.ico")
        else:
            print("Note: content/media/favicon.ico is missing, so the icon will be Edge's.")
    print(f"Made {OUT.relative_to(ROOT)} for {url}")


if __name__ == "__main__":
    main()
