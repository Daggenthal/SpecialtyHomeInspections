"""Cloudflare helpers for the editor: credentials, the setup checklist, and getting the domain attached.

Nothing here needs extra Python packages. DNS questions go to Cloudflare's public DNS-over-HTTPS
resolver, so the checklist works before (and without) any API permission. The API token is only
used to check that it works, and to clear the old website's DNS records right before the site
moves onto the real address.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .paths import CONTENT_FILE, EDITOR_SECRETS

API = "https://api.cloudflare.com/client/v4"
DOH = "https://cloudflare-dns.com/dns-query"
UA = "specialty-site-editor"
GMAIL_DEFAULT = "specialtyhomeinspections@gmail.com"

ACCOUNT_RE = re.compile(r"^[0-9a-f]{32}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{20,200}$")


# --------------------------------------------------------------------------- secrets

def read_secrets(path=EDITOR_SECRETS):
    out = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def credentials_info(path=EDITOR_SECRETS):
    """What the editor page may see. Never the token itself."""
    sec = read_secrets(path)
    token, account = sec.get("CLOUDFLARE_API_TOKEN", ""), sec.get("CLOUDFLARE_ACCOUNT_ID", "")
    return {
        "ready": bool(token and account),
        "hasToken": bool(token),
        "tokenHint": token[-4:] if len(token) >= 12 else "",
        "accountId": account,
    }


def save_credentials(token=None, account_id=None, path=EDITOR_SECRETS):
    """Keeps any other lines in the file (e.g. Hetzner settings). Mode 600."""
    sec = read_secrets(path)
    if token:
        sec["CLOUDFLARE_API_TOKEN"] = token
    if account_id:
        sec["CLOUDFLARE_ACCOUNT_ID"] = account_id
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# Private to this computer. Never commit or share this file.\n")
        for k, v in sec.items():
            f.write(f"{k}={v}\n")
    os.replace(tmp, p)
    os.chmod(p, 0o600)


def validate_fields(token, account_id, have_token):
    """Field errors in plain words, or {} when both look right."""
    errors = {}
    if not ACCOUNT_RE.match(account_id or ""):
        errors["accountId"] = "An account ID is 32 letters and numbers (0-9 and a-f)."
    if token and not TOKEN_RE.match(token):
        errors["token"] = "That doesn't look like an API token. Paste just the token, with no spaces."
    if not token and not have_token:
        errors["token"] = "Paste the API token."
    return errors


# --------------------------------------------------------------------------- HTTP

def _get(url, headers=None, timeout=10, method="GET"):
    """(status or None if unreachable, parsed JSON or {}, response headers)."""
    req = urllib.request.Request(url, method=method, headers=dict({"User-Agent": UA}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            try:
                data = json.loads(body or b"{}")
            except ValueError:
                data = {"_text": body[:200000].decode("utf-8", "replace")}
            return r.status, data, dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), dict(e.headers or {})
        except ValueError:
            return e.code, {}, dict(e.headers or {})
    except (urllib.error.URLError, OSError, ValueError):
        return None, {}, {}


def api(path, token, method="GET", timeout=12):
    return _get(API + path, {"Authorization": f"Bearer {token}"}, timeout, method)[:2]


def check_credentials(token, account_id):
    """(True | False | None, message). None means Cloudflare couldn't be reached."""
    code, body = api("/user/tokens/verify", token)
    if code is None:
        return None, "Couldn't reach Cloudflare to check these, so they were saved without checking."
    active = code == 200 and (body.get("result") or {}).get("status") == "active"
    if not active:  # tokens made under Manage Account > API Tokens verify against the account
        code2, body2 = api(f"/accounts/{account_id}/tokens/verify", token)
        active = code2 == 200 and (body2.get("result") or {}).get("status") == "active"
    if not active:
        return False, "Cloudflare didn't accept that token. Copy it again (it's only shown once, right after you create it)."
    code, _ = api(f"/accounts/{account_id}/workers/scripts", token)
    if code in (401, 403, 404):
        return False, ("The token works, but it can't publish websites on that account. Check the account ID, "
                       "and that the token was made from the \"Edit Cloudflare Workers\" template.")
    if code is None:
        return None, "The token works. Couldn't double-check the account, so it was saved without that check."
    return True, "Connected to Cloudflare."


# --------------------------------------------------------------------------- DNS (public, no token)

def dns(name, rtype):
    """Answers from Cloudflare's public resolver. [] when there are none, None when it couldn't be asked."""
    url = DOH + "?" + urllib.parse.urlencode({"name": name, "type": rtype})
    code, data, _ = _get(url, {"Accept": "application/dns-json"}, timeout=8)
    if code != 200 or not isinstance(data, dict) or "Status" not in data:
        return None
    if data.get("Status") == 3:  # NXDOMAIN
        return []
    want = {"NS": 2, "A": 1, "CNAME": 5, "MX": 15, "TXT": 16, "AAAA": 28}.get(rtype)
    return [a.get("data", "").strip().strip('"').rstrip(".").lower()
            for a in (data.get("Answer") or []) if want is None or a.get("type") == want]


def site_domain(content=None):
    """The bare domain from the business's website address, e.g. specialtyhomeinspections.biz."""
    if content is None:
        try:
            content = json.loads(Path(CONTENT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            content = {}
    url = (content.get("business") or {}).get("siteUrl") or ""
    host = urllib.parse.urlparse(url if "//" in url else "https://" + url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def on_cloudflare(nameservers):
    return bool(nameservers) and all(n.endswith(".ns.cloudflare.com") for n in nameservers)


def email_routing_on(mx):
    return bool(mx) and all("mx.cloudflare.net" in m for m in mx)


def domain_status(domain):
    ns = dns(domain, "NS")
    mx = dns(domain, "MX")
    return {
        "domain": domain,
        "nameservers": ns,
        "onCloudflare": None if ns is None else on_cloudflare(ns),
        "mx": [m.split(" ", 1)[-1] for m in (mx or [])],
        "emailRouting": None if mx is None else email_routing_on(mx),
    }


def site_live(domain):
    """Is the new site answering on the real address? Our pages load /assets/site.css; the old one didn't."""
    code, data, headers = _get(f"https://{domain}/", timeout=10)
    if code is None:
        return {"live": False, "reachable": False}
    text = data.get("_text", "") if isinstance(data, dict) else ""
    lower = {k.lower(): v for k, v in headers.items()}
    ours = "/assets/site.css" in text
    return {"live": code == 200 and ours and "cf-ray" in lower, "reachable": True, "status": code, "ours": ours}


def setup_status(content=None, stats_endpoint=None):
    """Everything the Website setup checklist shows, in one go."""
    domain = site_domain(content)
    out = {"domain": domain, "cloudflare": credentials_info()}
    if domain:
        out.update(domain_status(domain))
        out["site"] = site_live(domain)
    ep = stats_endpoint
    if ep is None and content is not None:
        ep = str((content.get("stats") or {}).get("endpoint") or "")
    out["statsEndpoint"] = ep or ""
    out["statsOnPi"] = bool(ep) and ep.startswith("https://")
    return out


# --------------------------------------------------------------------------- attaching the domain

def zone_id(domain, token):
    code, body = api("/zones?" + urllib.parse.urlencode({"name": domain}), token)
    if code == 200:
        for z in body.get("result") or []:
            if z.get("name") == domain:
                return z.get("id")
    return None


def attached_hostnames(account_id, token, script):
    """Hostnames already connected to this Worker as custom domains."""
    code, body = api(f"/accounts/{account_id}/workers/domains?" + urllib.parse.urlencode({"service": script}), token)
    if code != 200:
        return None
    return {d.get("hostname") for d in body.get("result") or [] if d.get("service") == script}


def clear_old_records(domain, hostnames, token, account_id, script, log):
    """Remove the old website's A/AAAA/CNAME records so the Worker can take the address.
    Only website records on exactly these names; mail (MX) and text (TXT) records are never touched."""
    already = attached_hostnames(account_id, token, script)
    if already is None:
        log("Couldn't list the website's current addresses; leaving DNS records alone.")
        return False
    todo = [h for h in hostnames if h not in already]
    if not todo:
        return True
    zid = zone_id(domain, token)
    if not zid:
        log(f"The token can't see {domain} in Cloudflare. It needs Zone > DNS > Edit for this domain.")
        return False
    ok = True
    for host in todo:
        for rtype in ("A", "AAAA", "CNAME"):
            code, body = api(f"/zones/{zid}/dns_records?" + urllib.parse.urlencode({"name": host, "type": rtype}), token)
            if code != 200:
                log(f"Couldn't read the {rtype} records for {host}.")
                ok = False
                continue
            for rec in body.get("result") or []:
                dcode, _ = api(f"/zones/{zid}/dns_records/{rec['id']}", token, method="DELETE")
                if dcode == 200:
                    log(f"Removed the old {rtype} record for {host} ({rec.get('content')}).")
                else:
                    log(f"Couldn't remove the old {rtype} record for {host}.")
                    ok = False
    return ok
