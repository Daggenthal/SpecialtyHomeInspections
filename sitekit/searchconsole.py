"""Google Search Console: which searches showed the site and which were clicked.

This is the only place search phrases can come from. Google doesn't pass search words
to websites, so the site's own stats can't see them.

Setup (once): see README "Search phrases (Google Search Console)". It needs a Google
service-account key saved as editor/google-service-account.json and that account's
email added as a user on the Search Console property.

Uses only the standard library plus the `openssl` command (installed on Raspberry Pi OS)
to sign the login token.
"""
import base64
import datetime as _dt
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

from .paths import EDITOR_DIR, ROOT

KEY_FILE = EDITOR_DIR / "google-service-account.json"
CACHE = ROOT / "data" / "search-console-cache.json"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
CACHE_SECONDS = 6 * 3600


class SearchConsoleError(Exception):
    pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_rs256(message: bytes, private_key_pem: str) -> bytes:
    fd, path = tempfile.mkstemp(prefix="gsc-", suffix=".pem")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(private_key_pem)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", path], input=message,
                           capture_output=True, timeout=20)
        if r.returncode != 0:
            raise SearchConsoleError("Couldn't sign the Google login token (openssl failed).")
        return r.stdout
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def make_jwt(creds, now=None):
    now = int(now or time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": creds["client_email"], "scope": SCOPE,
              "aud": creds.get("token_uri", "https://oauth2.googleapis.com/token"),
              "iat": now, "exp": now + 3600}
    signing_input = (b64url(json.dumps(header, separators=(",", ":")).encode()) + "." +
                     b64url(json.dumps(claims, separators=(",", ":")).encode())).encode()
    return signing_input.decode() + "." + b64url(sign_rs256(signing_input, creds["private_key"]))


def _post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise SearchConsoleError(f"Google answered {e.code}: {detail}") from None
    except OSError as e:
        raise SearchConsoleError(f"Couldn't reach Google: {e}") from None


def configured():
    return KEY_FILE.is_file()


def top_queries(site, days=28, limit=25, use_cache=True):
    """Return {"rows":[{"query","clicks","impressions","ctr","position"}], "start","end","fetched"}."""
    key = f"{site}|{days}|{limit}"
    if use_cache and CACHE.is_file():
        try:
            c = json.loads(CACHE.read_text())
            if c.get("key") == key and time.time() - c.get("at", 0) < CACHE_SECONDS:
                return c["data"]
        except (OSError, ValueError):
            pass
    if not configured():
        raise SearchConsoleError("Search Console isn't connected yet.")
    creds = json.loads(KEY_FILE.read_text())
    tok = _post(creds.get("token_uri", "https://oauth2.googleapis.com/token"),
                urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                        "assertion": make_jwt(creds)}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded"})
    if "access_token" not in tok:
        raise SearchConsoleError("Google didn't give a login token.")
    end = _dt.date.today() - _dt.timedelta(days=2)  # Search Console data lags a couple of days
    start = end - _dt.timedelta(days=days - 1)
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["query"],
            "rowLimit": limit, "dataState": "all"}
    res = _post(API.format(site=urllib.parse.quote(site, safe="")), json.dumps(body).encode(),
                {"Authorization": "Bearer " + tok["access_token"], "Content-Type": "application/json"})
    rows = [{"query": r["keys"][0], "clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
             "ctr": round(r.get("ctr", 0) * 100, 1), "position": round(r.get("position", 0), 1)}
            for r in res.get("rows", [])]
    data = {"rows": rows, "start": start.isoformat(), "end": end.isoformat(),
            "fetched": _dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"key": key, "at": time.time(), "data": data}))
    return data
