"""Hetzner Webhosting support (or any Apache + PHP shared hosting with SFTP).

Three jobs:
  htaccess_text()   Apache rules: HTTPS, one address (www or not), security headers,
                    caching, old page redirects, the 404 page, the visit counter.
  hit_php()         the visit counter, one small PHP file. It writes one line per visit
                    to a folder OUTSIDE public_html; nothing on the server can read it back
                    over the web. The editor downloads those files over SFTP.
  deploy_sftp()     uploads dist/ with rclone over SFTP (no SSH shell needed, so it works
                    on Webhosting S and M). Changed images and styles go up first, the page
                    itself last, then files that no longer exist are removed.
  pull_stats()      downloads new visit lines into data/stats.sqlite and deletes finished
                    days from the server.

Settings live in editor/config.json under "deploy" -> "hetzner" (see README, "Hetzner").
"""
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from . import stats
from .paths import DIST, ROOT

DEFAULTS = {
    "host": "",                 # the server name konsoleH shows for SFTP, e.g. www123.your-server.de
    "port": 22,
    "user": "",                 # the main FTP user (only that one may log in with a key)
    "key_file": "editor/keys/hetzner",          # relative paths are inside the project folder
    "known_hosts": "editor/keys/known_hosts",
    "remote_dir": "public_html",
    "stats_dir": "stats-data",  # next to public_html, never reachable from the web
    "rclone": "",               # leave empty to find rclone automatically
}

# Things that are on the server but are not ours: never deleted, never uploaded.
PROTECT = ["/.well-known/**", "/cgi-bin/**", "/_api/data/**", "/stats-data/**", "/.user.ini", "/php.ini"]
# Build files only Cloudflare / the Pi server use.
SKIP = ["/_headers", "/_redirects", "/.assetsignore"]
LAST = ["/index.html", "/404.html", "/.htaccess"]

INGEST_STATE = stats.DATA_DIR / "remote-hits.json"
_last_pull = {"t": 0.0}


# --------------------------------------------------------------------------- .htaccess

def _rx(path):
    return re.escape(path.lstrip("/")).replace("\\/", "/")


def _quote(v):
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def htaccess_text(content, headers_block, redirects):
    """headers_block: the "/*" header lines from build.headers_text; redirects: build.redirects_text."""
    site = (content.get("business") or {}).get("siteUrl") or ""
    host = (urlparse(site).hostname or "").lower()
    apex = host[4:] if host.startswith("www.") else host
    lines = [
        "# Made by the website editor on every Publish. Edits here are overwritten.",
        "# Apache rules for Hetzner Webhosting (see README, \"Hetzner\").",
        "",
        "Options -Indexes -MultiViews",
        "DirectoryIndex index.html",
        "ErrorDocument 404 /404.html",
        "ErrorDocument 403 /404.html",
        "AddDefaultCharset utf-8",
        "AddType text/javascript .js",
        "AddType image/webp .webp",
        "AddType image/svg+xml .svg",
        "",
        "<IfModule mod_rewrite.c>",
        "RewriteEngine On",
        "",
        "# Always https (the certificate check under /.well-known/ is let through)",
        "RewriteCond %{HTTPS} !=on",
        "RewriteCond %{HTTP:X-Forwarded-Proto} !=https",
        "RewriteCond %{REQUEST_URI} !^/\\.well-known/",
        "RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=301,L,NE]",
    ]
    if apex:
        other = apex if host.startswith("www.") else "www." + apex
        lines += [
            "",
            f"# One address for the site: {other} goes to {host}",
            f"RewriteCond %{{HTTP_HOST}} ^{re.escape(other)}\\.?$ [NC]",
            f"RewriteRule ^ https://{host}%{{REQUEST_URI}} [R=301,L,NE]",
        ]
    lines += [
        "",
        "# Hidden files and build files are never shown",
        "RewriteCond %{THE_REQUEST} \\s/+([^?\\s]*/)?[._](?!well-known/)",
        "RewriteRule ^ - [R=404,L]",
        "",
        "# Anonymous visit counter",
        "RewriteRule ^api/hit$ _api/hit.php [L]",
        "",
        "# Old page addresses from the previous website",
    ]
    for line in redirects.splitlines():
        parts = line.split()
        if len(parts) < 2 or line.startswith("#"):
            continue
        src, dest = parts[0], parts[1]
        code = parts[2] if len(parts) > 2 else "301"
        if src == "/index.html":
            # only when someone typed it, not when Apache serves the home page itself
            lines.append("RewriteCond %{THE_REQUEST} \\s/+index\\.html[\\s?]")
        if dest.startswith("/"):
            dest = "https://%{HTTP_HOST}" + dest      # stay on https and on the address they used
        lines.append(f"RewriteRule ^{_rx(src)}$ {dest} [R={code},L,NE]")
    lines += ["</IfModule>", "", "<IfModule mod_headers.c>"]
    for raw in headers_block:
        k, v = raw.split(":", 1)
        k, v = k.strip(), v.strip()
        if k.lower() == "strict-transport-security":
            lines.append(f"Header always set {k} {_quote(v)} \"expr=%{{HTTPS}} == 'on'\"")
        else:
            lines.append(f"Header always set {k} {_quote(v)}")
    lines += [
        "Header always unset X-Powered-By",
        "Header set Cache-Control \"public, max-age=31536000, immutable\" \"expr=%{REQUEST_URI} =~ m#^/assets/#\"",
        "Header set Cache-Control \"public, max-age=86400\" \"expr=%{REQUEST_URI} =~ m#^/media/#\"",
        "Header set Cache-Control \"public, max-age=0, must-revalidate\" \"expr=%{REQUEST_URI} !~ m#^/(assets|media|api|_api)/#\"",
        "</IfModule>",
        "",
        "<IfModule mod_deflate.c>",
        "AddOutputFilterByType DEFLATE text/html text/css text/javascript application/javascript "
        "application/json image/svg+xml text/plain application/xml",
        "</IfModule>",
        "",
    ]
    return "\n".join(lines)


def api_htaccess_text():
    return ("# Only the counter itself may be reached here.\n"
            "<IfModule mod_authz_core.c>\nRequire all denied\n"
            "<Files \"hit.php\">\nRequire all granted\n</Files>\n</IfModule>\n")


# --------------------------------------------------------------------------- the PHP counter

def hit_php(tz="America/Chicago"):
    bots = stats.BOTS.pattern.replace("~", "\\~")
    kinds = ", ".join(f"'{k}'" for k in sorted(stats.KINDS))
    return f"""<?php
// Anonymous visit counter for the website (made by the website editor; edits are overwritten).
// Kept per visit: the time, what happened (page view, call tap, ...), the referring page,
// campaign tags such as utm_source, the browser's name string, and a visitor code that
// changes every day so nobody can be followed from one day to the next.
// Never kept: IP addresses, cookies, anything that identifies a person.
// The lines go to a folder outside public_html. The editor downloads them over SFTP.
declare(strict_types=1);
header('Cache-Control: no-store');
header('X-Robots-Tag: noindex');
http_response_code(204);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') exit;

$dir = dirname(__DIR__, 2) . '/stats-data';
if (!is_dir($dir) && !@mkdir($dir, 0700, true)) {{
    $dir = __DIR__ . '/data';                     // fallback, blocked from the web by .htaccess
    if (!is_dir($dir) && !@mkdir($dir, 0700, true)) exit;
}}
$body = file_get_contents('php://input', false, null, 0, 4097);
if (!is_string($body) || $body === '' || strlen($body) > 4096) exit;
$d = json_decode($body, true);
if (!is_array($d)) exit;
$ua = substr((string)($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 300);
if ($ua === '' || preg_match('~{bots}~i', $ua)) exit;
$k = (string)($d['k'] ?? 'view');
if (!in_array($k, [{kinds}], true)) exit;

$day = (new DateTime('now', new DateTimeZone('{tz}')))->format('Y-m-d');
$file = $dir . '/hits-' . $day . '.jsonl';
if (is_file($file) && filesize($file) > 20 * 1024 * 1024) exit;   // never fill the disk

// A random code for today only. Yesterday's is deleted, so old visitor codes can't be linked.
$saltFile = $dir . '/.salt-' . $day;
foreach (glob($dir . '/.salt-*') ?: [] as $f) {{ if ($f !== $saltFile) @unlink($f); }}
$h = @fopen($saltFile, 'x');
if ($h) {{ fwrite($h, bin2hex(random_bytes(16))); fclose($h); @chmod($saltFile, 0600); }}
$salt = (string)@file_get_contents($saltFile);
$visitor = substr(hash('sha256', $salt . '|' . ($_SERVER['REMOTE_ADDR'] ?? '') . '|' . $ua), 0, 16);

$q = [];
if (is_array($d['q'] ?? null)) {{
    foreach (array_slice($d['q'], 0, 12, true) as $key => $val) {{
        if (is_scalar($val)) $q[substr((string)$key, 0, 20)] = substr((string)$val, 0, 120);
    }}
}}
$rec = ['t' => time(), 'k' => $k, 'r' => substr((string)($d['r'] ?? ''), 0, 500), 'q' => $q, 'ua' => $ua, 'v' => $visitor];
@file_put_contents($file, json_encode($rec, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE) . "\\n", FILE_APPEND | LOCK_EX);
"""


# --------------------------------------------------------------------------- rclone over SFTP

def settings(cfg):
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("deploy", {}).get("hetzner") or {}).items() if v not in (None, "")})
    for k in ("key_file", "known_hosts"):
        p = Path(str(out[k])).expanduser()
        out[k] = str(p if p.is_absolute() else ROOT / p)
    return out


def configured(cfg):
    s = settings(cfg)
    return bool(s["host"] and s["user"] and Path(s["key_file"]).expanduser().is_file())


def _rclone_bin(s):
    return s.get("rclone") or shutil.which("rclone") or shutil.which("rclone.exe")


def _env(s):
    env = dict(os.environ)
    env.update({
        "RCLONE_CONFIG_HETZNER_TYPE": "sftp",
        "RCLONE_CONFIG_HETZNER_HOST": s["host"],
        "RCLONE_CONFIG_HETZNER_PORT": str(s["port"]),
        "RCLONE_CONFIG_HETZNER_USER": s["user"],
        "RCLONE_CONFIG_HETZNER_KEY_FILE": str(Path(s["key_file"]).expanduser()),
        "RCLONE_CONFIG_HETZNER_SHELL_TYPE": "none",       # SFTP only, never asks for a shell
        "RCLONE_CONFIG_HETZNER_DISABLE_HASHCHECK": "true",
        "RCLONE_CONFIG_HETZNER_IDLE_TIMEOUT": "10s",
        "NO_COLOR": "1",
    })
    kh = Path(s["known_hosts"]).expanduser()
    if kh.is_file():
        env["RCLONE_CONFIG_HETZNER_KNOWN_HOSTS_FILE"] = str(kh)
    return env


def _run(s, args, timeout):
    exe = _rclone_bin(s)
    if not exe:
        return 127, "rclone isn't installed on this computer (see README, \"Hetzner\")."
    try:
        r = subprocess.run([exe, *args, "--stats=0", "--retries", "3", "--low-level-retries", "5"],
                           env=_env(s), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "The server took too long to answer. Check the internet connection and try again."
    log = "\n".join(l for l in ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines()
                    if l.strip() and "Config file" not in l)
    return r.returncode, log


def _filters(extra_excludes=()):
    out = []
    for p in [*PROTECT, *SKIP, *extra_excludes]:
        out += ["--exclude", p]
    return out


def deploy_sftp(cfg, dist=DIST, timeout=600):
    s = settings(cfg)
    if not s["host"] or not s["user"]:
        return False, "Hetzner isn't set up yet. Run:  python3 tools/hetzner_setup.py"
    if not Path(s["key_file"]).expanduser().is_file():
        return False, f"The key file {s['key_file']} is missing. Run:  python3 tools/hetzner_setup.py"
    if not (Path(dist) / "index.html").is_file():
        return False, "There's no built website to upload."
    if not Path(s["known_hosts"]).expanduser().is_file():
        return False, ("The server's fingerprint hasn't been saved yet, so the upload can't be sure it's talking "
                       "to Hetzner. Run:  python3 tools/hetzner_setup.py")
    target = f"hetzner:{s['remote_dir'].strip('/')}"
    # 1) new and changed pictures, styles and scripts (the old page still works with them)
    code, log1 = _run(s, ["copy", str(dist), target, *_filters(LAST)], timeout)
    if code != 0:
        return False, "Upload to Hetzner failed:\n" + "\n".join(log1.splitlines()[-15:])
    # 2) the page itself, then remove files the site no longer uses
    code, log2 = _run(s, ["sync", str(dist), target, *_filters()], timeout)
    if code != 0:
        return False, "Upload to Hetzner failed:\n" + "\n".join(log2.splitlines()[-15:])
    return True, f"Uploaded to {s['host']}."


def check_connection(cfg, timeout=60):
    s = settings(cfg)
    code, log = _run(s, ["lsf", "--max-depth", "1", "hetzner:"], timeout)
    return code == 0, log


# --------------------------------------------------------------------------- visit counter download

def _load_state():
    try:
        return json.loads(INGEST_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(st):
    INGEST_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = INGEST_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, INGEST_STATE)


def ingest_dir(folder: Path, tz="America/Chicago", site_host=""):
    """Read new lines from downloaded hits-YYYY-MM-DD.jsonl files into the stats database.
    Returns (lines added, names of files that are complete and can be removed from the server)."""
    st = _load_state()
    added = 0
    today = _dt.datetime.now(ZoneInfo(tz)).date()
    done = []
    for f in sorted(Path(folder).glob("hits-*.jsonl")):
        m = re.fullmatch(r"hits-(\d{4}-\d{2}-\d{2})\.jsonl", f.name)
        if not m:
            continue
        seen = int(st.get(f.name, 0))
        with f.open(encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
        complete = lines[:-1]                     # the last piece may still be being written
        for line in complete[seen:]:
            try:
                rec = json.loads(line)
                now = _dt.datetime.fromtimestamp(int(rec["t"]), _dt.timezone.utc)
                ok = stats.record({"k": rec.get("k", "view"), "r": rec.get("r", ""), "q": rec.get("q") or {}},
                                  {"User-Agent": str(rec.get("ua", ""))}, "", tz=tz, site_host=site_host,
                                  now=now, visitor=str(rec.get("v", ""))[:16])
                added += 1 if ok else 0
            except (ValueError, KeyError, TypeError):
                pass
        st[f.name] = len(complete)
        if _dt.date.fromisoformat(m.group(1)) < today - _dt.timedelta(days=1):
            done.append(f.name)
    _save_state(st)
    return added, done


def pull_stats(cfg, tz="America/Chicago", site_host="", min_interval=300, force=False, timeout=90):
    """Download new visits. Quietly does nothing if Hetzner isn't set up or was checked recently."""
    if not configured(cfg) or not Path(settings(cfg)["known_hosts"]).expanduser().is_file():
        return {"pulled": False, "reason": "not set up"}
    if not force and time.time() - _last_pull["t"] < min_interval:
        return {"pulled": False, "reason": "checked recently"}
    _last_pull["t"] = time.time()
    s = settings(cfg)
    local = stats.DATA_DIR / "remote-hits"
    local.mkdir(parents=True, exist_ok=True)
    remote = f"hetzner:{s['stats_dir'].strip('/')}"
    code, log = _run(s, ["copy", remote, str(local), "--include", "hits-*.jsonl"], timeout)
    if code != 0:
        return {"pulled": False, "reason": "download failed", "log": log[-500:]}
    added, done = ingest_dir(local, tz=tz, site_host=site_host)
    st = _load_state()
    for name in done:
        c, _ = _run(s, ["deletefile", f"{remote}/{name}"], timeout)
        if c == 0:
            (local / name).unlink(missing_ok=True)
            st.pop(name, None)
    _save_state(st)
    return {"pulled": True, "added": added, "cleaned": len(done)}
