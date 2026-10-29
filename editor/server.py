#!/usr/bin/env python3
"""Website editor for Specialty Home Inspections LLC.

    python3 editor/server.py setup      first-time setup (password, publishing)
    python3 editor/server.py            start the editor
    python3 editor/server.py password   change the editor password

The editor is private on purpose. It only answers:
  * requests from this computer or the home network (never the internet),
  * requests that did NOT come through Cloudflare or any other proxy,
  * requests addressed to a local hostname (blocks DNS-rebinding tricks),
  * a signed-in browser (password), and changes only from the editor page itself.
The public website is plain static files and never talks to this program.
"""
import argparse
import base64
import datetime as _dt
import getpass
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import sys
import threading
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sitekit import render  # noqa: E402
from sitekit.build import BuildError, build  # noqa: E402
from sitekit.deploy import publish, read_secrets  # noqa: E402
from sitekit.imagesize import image_size, sniff_type  # noqa: E402
from sitekit.paths import (CONTENT_FILE, DIST, EDITOR_CONFIG, EDITOR_SECRETS,  # noqa: E402
                           HISTORY_DIR, MEDIA_DIR, SITE_ASSETS)
from sitekit.validate import validate  # noqa: E402
from sitekit import hetzner, searchconsole, stats  # noqa: E402

UI_DIR = ROOT / "editor" / "ui"
DRAFT_FILE = ROOT / "content" / ".draft.json"
PUBLISHED_FILE = ROOT / "content" / ".published.json"
UPLOAD_DIR = MEDIA_DIR / "uploads"
MAX_UPLOAD = 25 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
HISTORY_KEEP = 300
PBKDF2_ROUNDS = 600_000
HIST_ID = re.compile(r"^\d{8}-\d{6}-\d{2,3}$")

DEFAULT_CONFIG = {
    "bind": "127.0.0.1",
    "port": 8787,
    "password_hash": "",
    "session_hours": 12,
    "allowed_hosts": [],
    "extra_networks": [],
    "deploy": {"targets": ["folder"], "folder": str(ROOT / "published")},
}

MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon",
    ".woff2": "font/woff2", ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8",
}

PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "cf-visitor", "cf-ipcountry", "cdn-loop",
                 "x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded", "true-client-ip")


# --------------------------------------------------------------------------- security helpers

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, rounds, salt, dk = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        test = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(test, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def client_allowed(ip: str, extra_networks=()) -> bool:
    """Only this computer and the home network. Never a public internet address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return not addr.is_multicast and not addr.is_unspecified
    for net in extra_networks:
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def proxy_headers_present(headers) -> bool:
    keys = {k.lower() for k in headers.keys()}
    return any(h in keys for h in PROXY_HEADERS)


def host_allowed(host: str, extra_hosts=()) -> bool:
    if not host:
        return False
    host = host.strip().lower()
    if host.startswith("["):
        name = host[1:host.find("]")] if "]" in host else host
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    try:
        a = ipaddress.ip_address(name)
        return a.is_loopback or a.is_private or a.is_link_local
    except ValueError:
        pass
    if name in ("localhost",) or name.endswith((".local", ".lan", ".home.arpa", ".internal", ".localhost")):
        return True
    me = socket.gethostname().lower()
    if name in (me, me.split(".")[0]):
        return True
    return name in {h.lower() for h in extra_hosts}


# --------------------------------------------------------------------------- state

class State:
    def __init__(self, config):
        self.config = config
        self.sessions = {}
        self.fails = {}
        self.lock = threading.RLock()
        self.publish_lock = threading.Lock()
        self.draft = None
        if DRAFT_FILE.is_file():
            try:
                self.draft = json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.draft = None

    # sessions
    def new_session(self):
        tok = secrets.token_urlsafe(32)
        self.sessions[tok] = time.time() + 3600 * float(self.config.get("session_hours", 12))
        return tok

    def valid_session(self, tok):
        exp = self.sessions.get(tok or "")
        if not exp:
            return False
        if exp < time.time():
            self.sessions.pop(tok, None)
            return False
        return True

    # login throttling
    def locked_out(self, ip):
        n, until = self.fails.get(ip, (0, 0))
        return until > time.time()

    def record_fail(self, ip):
        n, _ = self.fails.get(ip, (0, 0))
        n += 1
        wait = 0 if n < 5 else min(15 * 60, 30 * 2 ** (n - 5))
        self.fails[ip] = (n, time.time() + wait)

    # content
    @staticmethod
    def saved():
        return json.loads(CONTENT_FILE.read_text(encoding="utf-8"))

    def current(self):
        return self.draft if self.draft is not None else self.saved()


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def dump(content):
    return json.dumps(content, indent=2, ensure_ascii=False) + "\n"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def history_list():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    items = sorted(HISTORY_DIR.glob("*.json"), reverse=True)
    out = []
    for p in items:
        try:
            meta = json.loads(p.read_text(encoding="utf-8")).get("_saved", {})
        except (OSError, ValueError):
            meta = {}
        out.append({"id": p.stem, "when": meta.get("when", p.stem), "note": meta.get("note", "")})
    return out


def snapshot(content, note):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    now = _dt.datetime.now()
    stamp, n = now.strftime("%Y%m%d-%H%M%S"), 1
    while (HISTORY_DIR / f"{stamp}-{n:02d}.json").exists():
        n += 1
    data = dict(content)
    data["_saved"] = {"when": now.strftime("%Y-%m-%d %H:%M:%S"), "note": note}
    atomic_write(HISTORY_DIR / f"{stamp}-{n:02d}.json", dump(data))
    for old in sorted(HISTORY_DIR.glob("*.json"))[:-HISTORY_KEEP]:
        old.unlink(missing_ok=True)


def media_list():
    out = []
    if not MEDIA_DIR.is_dir():
        return out
    for p in sorted(MEDIA_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            rel = "media/" + p.relative_to(MEDIA_DIR).as_posix()
            dims = image_size(p)
            out.append({"path": rel, "w": dims[0] if dims else None, "h": dims[1] if dims else None,
                        "bytes": p.stat().st_size, "uploaded": rel.startswith("media/uploads/")})
    return out


def published_info():
    try:
        return json.loads(PUBLISHED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def safe_join(base: Path, rel: str):
    p = (base / rel).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        return None
    return p


# --------------------------------------------------------------------------- HTTP

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SHI-Editor/1"
    sys_version = ""
    state: State = None  # set at startup

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\n" % (self.client_address[0], fmt % args))

    # ---- response helpers
    def _headers_common(self, ctype, length, extra=None):
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
                         "connect-src 'self'; font-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
                         "base-uri 'none'; form-action 'self'; object-src 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)

    def send_bytes(self, code, data: bytes, ctype, extra=None):
        self.send_response(code)
        self._headers_common(ctype, len(data), extra)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_json(self, obj, code=200, extra=None):
        self.send_bytes(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def send_file(self, path: Path):
        if not path or not path.is_file():
            return self.send_bytes(404, b"Not found", "text/plain; charset=utf-8")
        self.send_bytes(200, path.read_bytes(), MIME.get(path.suffix.lower(), "application/octet-stream"))

    def redirect(self, where):
        self.send_response(303)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- gatekeeping
    def guard(self):
        cfg = self.state.config
        ip = self.client_address[0]
        reason = None
        if not client_allowed(ip, cfg.get("extra_networks", [])):
            reason = "not on the home network"
        elif proxy_headers_present(self.headers):
            reason = "came through a proxy or Cloudflare"
        elif not host_allowed(self.headers.get("Host", ""), cfg.get("allowed_hosts", [])):
            reason = "addressed to an unknown hostname"
        if reason:
            self.log_message("BLOCKED request (%s): %s", reason, self.path)
            self.send_bytes(403, b"The website editor is only available on the home network.", "text/plain; charset=utf-8")
            return False
        return True

    def cookie_token(self):
        raw = self.headers.get("Cookie", "")
        m = re.search(r"(?:^|;\s*)shi_session=([A-Za-z0-9_\-]+)", raw)
        return m.group(1) if m else None

    def authed(self):
        return self.state.valid_session(self.cookie_token())

    def same_origin(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if self.headers.get("X-SHI") != "1":
            return False
        return origin is not None and origin in (f"http://{host}", f"https://{host}")

    def read_body(self, limit):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if n < 0 or n > limit:
            return None
        return self.rfile.read(n)

    def read_json(self):
        body = self.read_body(MAX_JSON)
        if body is None:
            return None
        try:
            return json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            return None

    # ---- GET
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.guard():
            return
        url = urlparse(self.path)
        path = url.path

        if path == "/login":
            return self.send_file(UI_DIR / "login.html")
        if path.startswith("/ui/"):
            return self.send_file(safe_join(UI_DIR, path[4:]))
        if path == "/favicon.ico":
            return self.send_file(MEDIA_DIR / "favicon.ico")

        if not self.authed():
            if path.startswith("/api/") or path.startswith("/files/") or path == "/preview":
                return self.send_json({"error": "Please sign in again."}, 401)
            return self.redirect("/login")

        if path == "/":
            return self.send_file(UI_DIR / "editor.html")
        if path == "/api/state":
            return self.api_state()
        if path == "/api/history":
            return self.send_json({"items": history_list()})
        if path.startswith("/api/history/"):
            hid = path.rsplit("/", 1)[-1]
            if not HIST_ID.match(hid):
                return self.send_json({"error": "Unknown version."}, 404)
            p = HISTORY_DIR / f"{hid}.json"
            if not p.is_file():
                return self.send_json({"error": "Unknown version."}, 404)
            data = json.loads(p.read_text(encoding="utf-8"))
            data.pop("_saved", None)
            return self.send_json({"content": data})
        if path == "/preview":
            return self.preview(parse_qs(url.query))
        if path == "/api/stats":
            q = parse_qs(url.query)
            try:
                days = max(1, min(800, int((q.get("days") or ["30"])[0])))
            except ValueError:
                days = 30
            cur = self.state.current()
            tz = (cur.get("hours") or {}).get("timezone") or "America/Chicago"
            host = urlparse((cur.get("business") or {}).get("siteUrl", "")).hostname or ""
            try:  # bring in new visits from Hetzner (at most every few minutes; never blocks the page on errors)
                hetzner.pull_stats(self.state.config, tz=tz, site_host=host, force="refresh" in q, timeout=30)
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"stats download failed: {e}\n")
            return self.send_json(stats.summary(days, tz=tz))
        if path == "/api/search-terms":
            return self.api_search_terms(parse_qs(url.query))
        if path == "/files/assets/theme.css":
            css = render.render_theme_css(self.state.current())
            return self.send_bytes(200, css.encode(), MIME[".css"])
        if path == "/files/assets/mobile-layout.css":
            css = render.render_mobile_layout_css((SITE_ASSETS / "site.css").read_text(encoding="utf-8"))
            return self.send_bytes(200, css.encode(), MIME[".css"])
        if path.startswith("/files/assets/"):
            return self.send_file(safe_join(SITE_ASSETS, path[len("/files/assets/"):]))
        if path.startswith("/files/media/"):
            return self.send_file(safe_join(MEDIA_DIR, path[len("/files/media/"):]))
        if path.startswith("/files/history/"):
            return self.send_bytes(404, b"Not found", "text/plain; charset=utf-8")
        self.send_bytes(404, b"Not found", "text/plain; charset=utf-8")

    def preview(self, q):
        st = self.state
        content = st.current()
        hid = (q.get("version") or [None])[0]
        if hid and HIST_ID.match(hid) and (HISTORY_DIR / f"{hid}.json").is_file():
            content = json.loads((HISTORY_DIR / f"{hid}.json").read_text(encoding="utf-8"))
        editing = (q.get("edit") or ["0"])[0] == "1"
        content = json.loads(json.dumps(content))
        content.setdefault("stats", {})["enabled"] = False  # previews never count as visits
        layout = (q.get("layout") or [None])[0]
        if layout in ("responsive", "mobile"):
            content = json.loads(json.dumps(content))
            content.setdefault("theme", {})["layout"] = layout
        extra_head = '<link rel="stylesheet" href="/ui/preview-bridge.css">' if editing else ""
        extra_body = '<script src="/ui/preview-bridge.js"></script>' if editing else ""
        try:
            html, _ = render.render_page(content, media_base="/files/", asset_base="/files/assets/",
                                         preview=editing, extra_head=extra_head, extra_body=extra_body)
        except Exception as e:  # show the problem instead of a blank frame
            html = f"<!doctype html><title>Preview</title><p>The preview couldn't be drawn: {render.esc(e)}</p>"
        self.send_bytes(200, html.encode("utf-8"), MIME[".html"])

    def api_search_terms(self, q):
        site = self.state.config.get("search_console_site", "")
        if not site or not searchconsole.configured():
            return self.send_json({"connected": False})
        try:
            days = max(7, min(480, int((q.get("days") or ["28"])[0])))
        except ValueError:
            days = 28
        try:
            data = searchconsole.top_queries(site, days=days, use_cache=(q.get("refresh") or ["0"])[0] != "1")
        except searchconsole.SearchConsoleError as e:
            return self.send_json({"connected": True, "error": str(e)})
        data["connected"] = True
        data["site"] = site
        self.send_json(data)

    def api_state(self):
        st = self.state
        saved_text = CONTENT_FILE.read_text(encoding="utf-8")
        saved = json.loads(saved_text)
        pub = published_info()
        cfg = st.config
        sec = read_secrets()
        errors, warnings = validate(st.current())
        self.send_json({
            "saved": saved,
            "draft": st.draft,
            "savedHash": sha(dump(saved)),
            "published": pub,
            "media": media_list(),
            "issues": {"errors": errors, "warnings": warnings},
            "publishTargets": cfg.get("deploy", {}).get("targets", []),
            "cloudflareReady": bool(sec.get("CLOUDFLARE_API_TOKEN") and sec.get("CLOUDFLARE_ACCOUNT_ID")),
            "siteUrl": saved.get("business", {}).get("siteUrl", ""),
        })

    # ---- POST
    def do_POST(self):
        if not self.guard():
            return
        path = urlparse(self.path).path
        if not self.same_origin():
            return self.send_json({"error": "Request refused."}, 403)

        if path == "/api/login":
            return self.api_login()
        if not self.authed():
            return self.send_json({"error": "Please sign in again."}, 401)

        routes = {
            "/api/logout": self.api_logout, "/api/draft": self.api_draft, "/api/save": self.api_save,
            "/api/discard-draft": self.api_discard, "/api/publish": self.api_publish,
            "/api/upload": self.api_upload, "/api/media/delete": self.api_media_delete,
        }
        fn = routes.get(path)
        if not fn:
            return self.send_json({"error": "Unknown action."}, 404)
        fn()

    def api_login(self):
        st = self.state
        ip = self.client_address[0]
        if st.locked_out(ip):
            return self.send_json({"error": "Too many wrong passwords. Please wait a few minutes."}, 429)
        data = self.read_json() or {}
        pw = str(data.get("password", ""))
        if not st.config.get("password_hash") or not verify_password(pw, st.config["password_hash"]):
            st.record_fail(ip)
            time.sleep(0.6)
            return self.send_json({"error": "That password isn't right."}, 401)
        st.fails.pop(ip, None)
        tok = st.new_session()
        hours = float(st.config.get("session_hours", 12))
        cookie = f"shi_session={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age={int(hours * 3600)}"
        self.send_json({"ok": True}, extra={"Set-Cookie": cookie})

    def api_logout(self):
        self.state.sessions.pop(self.cookie_token(), None)
        self.send_json({"ok": True}, extra={"Set-Cookie": "shi_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})

    def _content_from_body(self):
        data = self.read_json()
        if not isinstance(data, dict) or not isinstance(data.get("content"), dict):
            self.send_json({"error": "The editor sent something unexpected. Please reload the page."}, 400)
            return None, None
        return data["content"], data

    def api_draft(self):
        content, _ = self._content_from_body()
        if content is None:
            return
        with self.state.lock:
            self.state.draft = content
            atomic_write(DRAFT_FILE, dump(content))
        errors, warnings = validate(content)
        self.send_json({"ok": True, "issues": {"errors": errors, "warnings": warnings}})

    def api_save(self):
        content, data = self._content_from_body()
        if content is None:
            return
        errors, warnings = validate(content)
        if errors:
            return self.send_json({"ok": False, "errors": errors}, 422)
        with self.state.lock:
            before = CONTENT_FILE.read_text(encoding="utf-8")
            text = dump(content)
            if text != before:
                snapshot(json.loads(before), "Before saving")
                atomic_write(CONTENT_FILE, text)
                snapshot(content, str(data.get("note", "Saved"))[:120])
            self.state.draft = None
            DRAFT_FILE.unlink(missing_ok=True)
        self.send_json({"ok": True, "savedHash": sha(text), "warnings": warnings})

    def api_discard(self):
        with self.state.lock:
            self.state.draft = None
            DRAFT_FILE.unlink(missing_ok=True)
        self.send_json({"ok": True})

    def api_publish(self):
        data = self.read_json() or {}
        force = bool(data.get("force"))
        st = self.state
        if not st.publish_lock.acquire(blocking=False):
            return self.send_json({"error": "Already publishing. Please wait for it to finish."}, 409)
        try:
            text = CONTENT_FILE.read_text(encoding="utf-8")
            content = json.loads(text)
            errors, warnings = validate(content)
            if errors:
                return self.send_json({"ok": False, "errors": errors}, 422)
            if warnings and not force:
                return self.send_json({"ok": False, "needsConfirm": True, "warnings": warnings})
            try:
                report = build(content)
            except BuildError as e:
                return self.send_json({"ok": False, "errors": str(e).splitlines()}, 422)
            dep = st.config.get("deploy", {})
            results = publish(dep.get("targets", []), dep.get("folder"), cfg=st.config)
            ok = bool(results) and all(r[1] for r in results)
            if ok:
                atomic_write(PUBLISHED_FILE, json.dumps({
                    "hash": sha(text), "when": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "targets": [r[0] for r in results]}, indent=2))
                snapshot(content, "Published")
            self.send_json({"ok": ok, "results": [{"target": t, "ok": k, "message": m} for t, k, m in results],
                            "missing": report.get("missing", []),
                            "error": None if results else "No publish target is set up yet. Run the setup again."})
        finally:
            st.publish_lock.release()

    def api_upload(self):
        raw_name = unquote(self.headers.get("X-Filename", "photo"))
        data = self.read_body(MAX_UPLOAD)
        if not data:
            return self.send_json({"error": "That picture is too big (25 MB max) or empty."}, 413)
        ext = sniff_type(data)
        kind = self.headers.get("X-Kind", "image")
        if kind == "pdf" and ext != "pdf":
            return self.send_json({"error": "That file isn't a PDF."}, 415)
        if kind != "pdf" and ext in (None, "pdf"):
            return self.send_json({"error": "Only JPEG, PNG, GIF or WebP pictures can be added here."}, 415)
        base = re.sub(r"[^a-z0-9]+", "-", Path(raw_name).stem.lower()).strip("-")[:40] or ("document" if ext == "pdf" else "photo")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{base}-{secrets.token_hex(2)}.{ext}"
        target = UPLOAD_DIR / name
        with open(target, "xb") as f:
            f.write(data)
        dims = image_size(target)
        self.send_json({"ok": True, "path": f"media/uploads/{name}",
                        "w": dims[0] if dims else None, "h": dims[1] if dims else None})

    def api_media_delete(self):
        data = self.read_json() or {}
        rel = str(data.get("path", ""))
        if not rel.startswith("media/uploads/"):
            return self.send_json({"error": "Only pictures you added yourself can be deleted."}, 403)
        used_in = json.dumps(self.state.current()) + CONTENT_FILE.read_text(encoding="utf-8")
        if f'"{rel}"' in used_in:
            return self.send_json({"error": "That picture is still used on the website. Remove it from the page first."}, 409)
        p = safe_join(MEDIA_DIR, rel[len("media/"):])
        if not p or not p.is_file():
            return self.send_json({"error": "Picture not found."}, 404)
        trash = MEDIA_DIR.parent / ".trash"
        trash.mkdir(exist_ok=True)
        shutil.move(str(p), trash / p.name)  # recoverable, never hard-deleted
        self.send_json({"ok": True})


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, handler):
        if ":" in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, handler)


# --------------------------------------------------------------------------- config + CLI

def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if EDITOR_CONFIG.is_file():
        user = json.loads(EDITOR_CONFIG.read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save_private(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    v = input(f"{prompt}{suffix}: ").strip()
    return v or (default or "")


def yes(prompt, default=True):
    v = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not v else v.startswith("y")


def prompt_password():
    while True:
        a = getpass.getpass("New editor password (at least 10 characters): ")
        if len(a) < 10:
            print("Too short, try again.")
            continue
        if a != getpass.getpass("Type it again: "):
            print("They didn't match, try again.")
            continue
        return a


def cmd_password():
    cfg = load_config()
    cfg["password_hash"] = hash_password(prompt_password())
    save_private(EDITOR_CONFIG, json.dumps(cfg, indent=2) + "\n")
    print("Password changed. Anyone signed in will need the new one next time.")


def cmd_setup():
    cfg = load_config()
    print("\nWebsite editor setup\n--------------------")
    cfg["password_hash"] = hash_password(prompt_password())
    lan = yes("Edit from other computers or tablets in the house (not just this one)?", True)
    cfg["bind"] = "0.0.0.0" if lan else "127.0.0.1"
    cfg["port"] = int(ask("Editor port", str(cfg.get("port", 8787))))
    targets = []
    if yes("Publish to a folder on this computer (Raspberry Pi + Cloudflare Tunnel)?", True):
        cfg["deploy"]["folder"] = ask("Folder the web server serves", cfg["deploy"].get("folder") or str(ROOT / "published"))
        targets.append("folder")
    if yes("Publish to Cloudflare (Workers)?", False):
        sec = read_secrets()
        acct = ask("Cloudflare account ID", sec.get("CLOUDFLARE_ACCOUNT_ID", ""))
        tok = getpass.getpass("Cloudflare API token (input hidden): ").strip() or sec.get("CLOUDFLARE_API_TOKEN", "")
        save_private(EDITOR_SECRETS, f"CLOUDFLARE_ACCOUNT_ID={acct}\nCLOUDFLARE_API_TOKEN={tok}\n")
        targets.append("cloudflare")
    if yes("Publish to Hetzner Webhosting over SFTP? (you'll finish that with tools/hetzner_setup.py)", False):
        targets.append("hetzner")
    cfg["deploy"]["targets"] = targets
    if lan and yes("Will people reach this editor over Tailscale (a private network, not the internet)?", False):
        nets = set(cfg.get("extra_networks") or [])
        nets.update({"100.64.0.0/10", "fd7a:115c:a1e0::/48"})   # Tailscale's private address ranges
        cfg["extra_networks"] = sorted(nets)
        name = ask("This computer's Tailscale name (e.g. pi or pi.tail1234.ts.net), or leave empty", "")
        if name:
            hosts = set(cfg.get("allowed_hosts") or [])
            hosts.update({name.lower(), name.lower().split(".")[0]})
            cfg["allowed_hosts"] = sorted(hosts)
    print("\nSearch phrases (optional): see the README section on Google Search Console.")
    site = ask("Search Console property (e.g. sc-domain:specialtyhomeinspections.biz), or leave empty",
               cfg.get("search_console_site", ""))
    cfg["search_console_site"] = site.strip()
    save_private(EDITOR_CONFIG, json.dumps(cfg, indent=2) + "\n")
    if "hetzner" in targets and not hetzner.configured(cfg):
        print("\nNext, connect to Hetzner:  python3 tools/hetzner_setup.py")
    print("\nSaved. Start the editor with:  python3 editor/server.py\n")


def lan_addresses():
    addrs = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


def cmd_run():
    cfg = load_config()
    if not cfg.get("password_hash"):
        print("No password set yet. Run:  python3 editor/server.py setup")
        sys.exit(1)
    Handler.state = State(cfg)
    bind, port = cfg.get("bind", "127.0.0.1"), int(cfg.get("port", 8787))
    httpd = Server((bind, port), Handler)
    print(f"Website editor running. Open http://localhost:{port}/ on this computer.")
    if bind not in ("127.0.0.1", "::1", "localhost"):
        for a in lan_addresses():
            print(f"  From another device at home: http://{a}:{port}/  or  http://{socket.gethostname()}.local:{port}/")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description="Specialty Home Inspections website editor")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "setup", "password"])
    args = ap.parse_args()
    {"run": cmd_run, "setup": cmd_setup, "password": cmd_password}[args.command]()


if __name__ == "__main__":
    main()
