#!/usr/bin/env python3
"""Tiny static web server for the published site on the Raspberry Pi.

The Cloudflare Tunnel points at this (127.0.0.1:8080 by default). It serves files only,
honours the site's _redirects (old page addresses) and the same security headers
Cloudflare uses, and shows 404.html for missing pages.

    python3 tools/serve.py --root published --port 8080
"""
import argparse
import http.server
import json
import os
import posixpath
import sys
import threading
import time
import urllib.parse
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from sitekit import stats  # noqa: E402

HEADERS = {}
REDIRECTS = {}
ROOT_DIR = None
SITE = {"host": "", "tz": "America/Chicago"}
_RATE = {}
_RATE_LOCK = threading.Lock()


def load_site_info():
    try:
        c = json.loads((PROJECT / "content" / "site.json").read_text(encoding="utf-8"))
        SITE["host"] = urllib.parse.urlparse(c.get("business", {}).get("siteUrl", "")).hostname or ""
        SITE["tz"] = (c.get("hours") or {}).get("timezone") or "America/Chicago"
    except (OSError, ValueError):
        pass


def allowed(ip, limit=120, window=60):
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE.get(ip, []) if now - t < window]
        if len(hits) >= limit:
            _RATE[ip] = hits
            return False
        hits.append(now)
        _RATE[ip] = hits
        if len(_RATE) > 5000:
            _RATE.clear()
        return True


def load_site_rules(root: Path):
    """Read _headers (global "/*" block only) and _redirects."""
    HEADERS.clear()
    REDIRECTS.clear()
    hp = root / "_headers"
    if hp.is_file():
        block = None
        for line in hp.read_text(encoding="utf-8").splitlines():
            if line and not line[0].isspace():
                block = line.strip()
                continue
            if block == "/*" and ":" in line:
                k, v = line.strip().split(":", 1)
                if k.lower() != "strict-transport-security":  # the tunnel/Cloudflare edge handles HTTPS
                    HEADERS[k.strip()] = v.strip()
    rp = root / "_redirects"
    if rp.is_file():
        for line in rp.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and not line.startswith("#"):
                REDIRECTS[parts[0]] = (parts[1], int(parts[2]) if len(parts) > 2 else 301)


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "Static"
    sys_version = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT_DIR), **kw)

    def do_POST(self):
        """Anonymous visit counter (see sitekit/stats.py for what is and isn't stored)."""
        if urllib.parse.urlparse(self.path).path != "/api/hit":
            return self.send_error(404)
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        body = self.rfile.read(n) if 0 < n <= 4096 else b""
        ip = self.headers.get("CF-Connecting-IP") or self.client_address[0]
        data = stats.parse_beacon(body)
        if data is not None and allowed(ip):
            try:
                stats.record(data, self.headers, ip, tz=SITE["tz"], site_host=SITE["host"])
            except Exception as e:  # never break the website over a counter
                sys.stderr.write(f"stats error: {e}\n")
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def end_headers(self):
        for k, v in HEADERS.items():
            self.send_header(k, v)
        p = urllib.parse.urlparse(self.path).path
        if p.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif p.startswith("/media/"):
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
        super().end_headers()

    def send_head(self):
        path = urllib.parse.urlparse(self.path).path
        if path in REDIRECTS:
            dest, code = REDIRECTS[path]
            self.send_response(code)
            self.send_header("Location", dest)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        norm = posixpath.normpath(urllib.parse.unquote(path))
        if any(part.startswith(".") or part.startswith("_") for part in norm.split("/") if part):
            return self.not_found()
        fs = Path(self.translate_path(self.path))
        if fs.is_dir():
            fs = fs / "index.html"
        if not fs.is_file():
            return self.not_found()
        return super().send_head()

    def not_found(self):
        page = ROOT_DIR / "404.html"
        body = page.read_bytes() if page.is_file() else b"Not found"
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return None

    def log_message(self, fmt, *args):
        pass  # keep the Pi's logs quiet; Cloudflare has visitor stats


def main():
    global ROOT_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("SITE_ROOT", str(Path(__file__).resolve().parent.parent / "published")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    ROOT_DIR = Path(a.root).resolve()

    class ReloadingHandler(Handler):
        def handle(self):
            # pick up a freshly published site (the folder is swapped on publish)
            global ROOT_DIR
            ROOT_DIR = Path(a.root).resolve()
            load_site_rules(ROOT_DIR)
            super().handle()

    load_site_rules(ROOT_DIR)
    load_site_info()
    stats.prune()
    httpd = http.server.ThreadingHTTPServer((a.host, a.port), ReloadingHandler)
    print(f"Serving {ROOT_DIR} on http://{a.host}:{a.port}/")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
