#!/usr/bin/env python3
"""Daily check that everything still works, so nothing breaks quietly.

    python3 tools/healthcheck.py           check and print
    python3 tools/healthcheck.py --notify  also send a phone notification if something is wrong
                                           (and once more when it's fixed). The daily timer uses this.

Checks: the live site, its certificate (Hetzner renews it; this catches a failed renewal),
the www redirect, the visit counter, the mail (MX) record that keeps john@ forwarding,
the domain's expiry date, the Hetzner SFTP login, the editor, the latest backup, disk space.

Notifications use ntfy (free, no account). In editor/config.json:
    "notify": {"ntfy": "https://ntfy.sh/some-long-random-topic-name"}
and install the ntfy app on your phone, subscribed to that same topic.
"""
import argparse
import datetime as _dt
import json
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sitekit import hetzner  # noqa: E402
from sitekit.paths import CONTENT_FILE, EDITOR_CONFIG  # noqa: E402

STATE = ROOT / "data" / "health-state.json"
UA = {"User-Agent": "specialty-healthcheck/1 (site owner's uptime check)"}
OK, WARN, FAIL = "ok", "warn", "fail"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(url, timeout=20, follow=True, method="GET"):
    req = urllib.request.Request(url, headers=UA, method=method)
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.geturl(), r.read(400_000).decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, url, "", dict(e.headers or {})


def load():
    cfg = {}
    try:
        cfg = json.loads(EDITOR_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    content = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
    return cfg, content


# --------------------------------------------------------------------------- checks

def check_site(site, name):
    code, final, body, _ = get(site)
    if code != 200:
        return FAIL, f"{site} answered {code}"
    if name.lower() not in body.lower():
        return FAIL, f"{site} loads, but the business name isn't on the page"
    if "data-years-since" not in body:
        return WARN, f"{site} loads, but it's still the OLD website (domain not switched yet, or not published)"
    return OK, f"{site} is up"


def check_cert(host):
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            cert = t.getpeercert()
    except ssl.SSLCertVerificationError as e:
        return FAIL, f"certificate problem: {e.verify_message}"
    except OSError as e:
        return FAIL, f"couldn't connect to {host}:443 ({e})"
    end = _dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), _dt.timezone.utc)
    days = (end - _dt.datetime.now(_dt.timezone.utc)).days
    issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName", "?")
    if days < 7:
        return FAIL, f"certificate expires in {days} days ({issuer}). Hetzner should have renewed it; check konsoleH > SSL"
    if days < 20:
        return WARN, f"certificate expires in {days} days ({issuer}); Hetzner usually renews well before this"
    return OK, f"certificate valid for {days} more days ({issuer})"


def check_www(host):
    apex = host[4:] if host.startswith("www.") else host
    other = "www." + apex if not host.startswith("www.") else apex
    try:
        code, final, _, _ = get(f"https://{other}/")
    except Exception as e:  # noqa: BLE001
        return WARN, f"https://{other}/ didn't answer ({e.__class__.__name__}); is the www record set?"
    return (OK, f"{other} goes to {urlparse(final).hostname}") if urlparse(final).hostname == host else \
        (WARN, f"{other} ends up at {final} instead of {host}")


def check_counter(site):
    code, _, _, _ = get(site.rstrip("/") + "/api/hit", follow=False)
    return (OK, "visit counter answers") if code == 204 else (WARN, f"visit counter answered {code} (expected 204)")


def check_mx(apex):
    code, _, body, _ = get(f"https://dns.google/resolve?name={apex}&type=MX")
    try:
        ans = [a["data"] for a in json.loads(body).get("Answer", []) if a.get("type") == 15]
    except ValueError:
        return WARN, "couldn't look up the mail record"
    return (OK, "mail record: " + ", ".join(ans)) if ans else \
        (FAIL, "no MX (mail) record: mail to john@ won't be forwarded. Add it in DNS (README, \"Domain, DNS and email\")")


def check_domain_expiry(apex):
    try:
        code, _, body, _ = get(f"https://rdap.org/domain/{apex}")
        ev = {e.get("eventAction"): e.get("eventDate") for e in json.loads(body).get("events", [])}
        end = _dt.datetime.fromisoformat(ev["expiration"].replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return WARN, "couldn't look up the domain's expiry date"
    days = (end - _dt.datetime.now(_dt.timezone.utc)).days
    if days < 14:
        return FAIL, f"the DOMAIN expires in {days} days! Renew it now (auto-renew off?)"
    if days < 45:
        return WARN, f"the domain expires in {days} days; check auto-renew is on"
    return OK, f"domain registered for {days} more days"


def check_sftp(cfg):
    if not hetzner.configured(cfg):
        return WARN, "Hetzner publishing isn't set up yet"
    ok, log = hetzner.check_connection(cfg)
    return (OK, "Hetzner SFTP login works") if ok else (FAIL, "Hetzner SFTP login failed: " + log.splitlines()[-1][-200:])


def check_editor(cfg):
    port = int(cfg.get("port", 8787))
    try:
        code, _, _, _ = get(f"http://127.0.0.1:{port}/login", timeout=5)
    except Exception:  # noqa: BLE001
        code = 0
    return (OK, "editor is running") if code == 200 else (FAIL, f"editor isn't answering on port {port}")


def check_backup(cfg):
    folder = Path((cfg.get("backup") or {}).get("local_dir") or Path.home() / "backups" / "specialty-site").expanduser()
    mark = folder / ".last-ok"
    if not mark.is_file():
        return FAIL, f"no successful backup yet in {folder}"
    hours = (time.time() - mark.stat().st_mtime) / 3600
    return (OK, f"last backup check {hours:.0f} h ago") if hours < 50 else (FAIL, f"last good backup was {hours / 24:.0f} days ago")


def check_disk(cfg):
    out = []
    folder = Path((cfg.get("backup") or {}).get("local_dir") or ROOT).expanduser()
    for label, p in (("project", ROOT), ("backups", folder if folder.exists() else ROOT)):
        u = shutil.disk_usage(p)
        out.append((label, u.free / u.total, u.free // 2**30))
    worst = min(out, key=lambda x: x[1])
    text = ", ".join(f"{l} {f:.0%} free ({g} GB)" for l, f, g in out)
    return (OK, text) if worst[1] > 0.10 else (WARN if worst[1] > 0.03 else FAIL, "low disk space: " + text)


def run_all(cfg, content):
    site = (content.get("business") or {}).get("siteUrl", "").rstrip("/") + "/"
    host = urlparse(site).hostname or ""
    apex = host[4:] if host.startswith("www.") else host
    name = (content.get("business") or {}).get("name", "")
    checks = [
        ("Website", lambda: check_site(site, name)),
        ("Certificate", lambda: check_cert(host)),
        ("www address", lambda: check_www(host)),
        ("Visit counter", lambda: check_counter(site)),
        ("Email forwarding", lambda: check_mx(apex)),
        ("Domain renewal", lambda: check_domain_expiry(apex)),
        ("Hetzner login", lambda: check_sftp(cfg)),
        ("Editor", lambda: check_editor(cfg)),
        ("Backups", lambda: check_backup(cfg)),
        ("Disk space", lambda: check_disk(cfg)),
    ]
    results = []
    for label, fn in checks:
        try:
            level, msg = fn()
        except (urllib.error.URLError, OSError) as e:
            level, msg = FAIL, f"couldn't reach it ({getattr(e, 'reason', e)})"
        except Exception as e:  # noqa: BLE001
            level, msg = FAIL, f"check crashed: {e.__class__.__name__}: {e}"
        results.append((label, level, msg))
    return results


def notify(cfg, title, text, priority="default"):
    url = (cfg.get("notify") or {}).get("ntfy")
    if not url:
        return False
    req = urllib.request.Request(url, data=text.encode("utf-8"), method="POST",
                                 headers={"Title": title, "Priority": priority, "Tags": "house"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"(couldn't send the notification: {e})")
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--test-notify", action="store_true", help="send a test notification and stop")
    a = ap.parse_args()
    cfg, content = load()
    if a.test_notify:
        sys.exit(0 if notify(cfg, "Website check", "Test notification from the Pi. If you see this, alerts work.")
                 else "No ntfy address in editor/config.json (\"notify\": {\"ntfy\": ...}) or it failed.")
    results = run_all(cfg, content)
    icon = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
    for label, level, msg in results:
        print(f"{icon[level]} {label:<17} {msg}")
    bad = [(l, m) for l, lv, m in results if lv == FAIL]
    if a.notify:
        try:
            prev = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = {}
        if bad:
            notify(cfg, "Website problem", "\n".join(f"{l}: {m}" for l, m in bad), "high")
        elif prev.get("failing"):
            notify(cfg, "Website OK again", "Everything passed the daily check.")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"failing": [l for l, _ in bad],
                                     "when": _dt.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
