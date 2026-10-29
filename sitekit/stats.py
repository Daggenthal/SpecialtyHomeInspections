"""Private visitor statistics, stored with the editor in data/stats.sqlite.

What is kept for each visit: the time, where the visitor came from (search engine,
social site, ad, QR code, another website or direct), the search words if the
referring site shares them, device type, city/region/country from Cloudflare's
headers, and which contact buttons they tapped.

What is never kept: IP addresses, cookies, exact location, or anything that
identifies a person. Unique visitors are counted with a hash that uses a random
salt which changes every day, so the same person can't be followed across days.
"""
import datetime as _dt
import hashlib
import json
import re
import secrets
import sqlite3
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from .paths import ROOT

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "stats.sqlite"
KINDS = {"view", "call", "text", "email", "social", "map", "report"}
MAX_FIELD = 300
_lock = threading.Lock()

BOTS = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|"
                  r"embedly|python-|curl|wget|httpclient|monitor|uptime|scrapy|go-http|java/", re.I)

SEARCH = [
    (r"(^|\.)google\.", "Google"), (r"(^|\.)bing\.com$", "Bing"), (r"duckduckgo\.com$", "DuckDuckGo"),
    (r"(^|\.)yahoo\.", "Yahoo"), (r"ecosia\.org$", "Ecosia"), (r"search\.brave\.com$", "Brave Search"),
    (r"(^|\.)yandex\.", "Yandex"), (r"baidu\.com$", "Baidu"), (r"(^|\.)aol\.com$", "AOL"),
    (r"startpage\.com$", "Startpage"), (r"(^|\.)ask\.com$", "Ask"),
]
SOCIAL = [
    (r"(^|\.)(facebook|fb)\.(com|me)$", "Facebook"), (r"(^|\.)instagram\.com$", "Instagram"),
    (r"(^|\.)(t\.co|twitter\.com|x\.com)$", "X / Twitter"), (r"(^|\.)linkedin\.com$|lnkd\.in$", "LinkedIn"),
    (r"(^|\.)nextdoor\.com$", "Nextdoor"), (r"(^|\.)youtube\.com$|youtu\.be$", "YouTube"),
    (r"(^|\.)pinterest\.", "Pinterest"), (r"(^|\.)reddit\.com$", "Reddit"), (r"(^|\.)tiktok\.com$", "TikTok"),
]
OTHER_KNOWN = [(r"(^|\.)bbb\.org$", "BBB"), (r"(^|\.)yelp\.com$", "Yelp"), (r"(^|\.)angi\.com$|angieslist", "Angi"),
               (r"(^|\.)homeadvisor\.com$", "HomeAdvisor"), (r"(^|\.)thumbtack\.com$", "Thumbtack"),
               (r"(^|\.)zillow\.com$", "Zillow"), (r"(^|\.)realtor\.com$", "Realtor.com"),
               (r"chatgpt\.com$|openai\.com$", "ChatGPT"), (r"claude\.ai$", "Claude"), (r"perplexity\.ai$", "Perplexity")]


def _clip(v, n=MAX_FIELD):
    return str(v or "")[:n].strip()


def _match(host, table):
    for pat, name in table:
        if re.search(pat, host):
            return name
    return None


def classify(referrer, params, site_host=""):
    """Return (source, medium, campaign, search_term, ref_host)."""
    p = {k.lower(): (v or "") for k, v in (params or {}).items()}
    ref = urlparse(referrer or "")
    host = (ref.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    term = ""
    if host and (_match(host, SEARCH)):
        q = parse_qs(ref.query)
        term = (q.get("q") or q.get("p") or q.get("query") or q.get("text") or [""])[0]
    campaign = _clip(p.get("utm_campaign"), 80)

    if p.get("utm_source"):
        src = _clip(p["utm_source"], 60)
        med = _clip(p.get("utm_medium") or "campaign", 40).lower()
        if med == "qr":
            src = "QR code: " + src
        return src, med, campaign, _clip(term or p.get("utm_term"), 120), host
    if p.get("gclid") or p.get("gbraid") or p.get("wbraid"):
        return "Google Ads", "paid", campaign, _clip(term or p.get("utm_term"), 120), host
    if p.get("msclkid"):
        return "Microsoft Ads", "paid", campaign, "", host
    if p.get("fbclid") and not host:
        return "Facebook", "social", campaign, "", host
    if not host or (site_host and host.endswith(site_host.lower().removeprefix("www."))):
        return "Direct / typed in", "direct", campaign, "", ""
    name = _match(host, SEARCH)
    if name:
        if name == "Google" and ref.path.startswith("/maps"):
            return "Google Maps", "maps", campaign, "", host
        return name, "search", campaign, _clip(term, 120), host
    name = _match(host, SOCIAL)
    if name:
        return name, "social", campaign, "", host
    name = _match(host, OTHER_KNOWN)
    return (name or host), "referral", campaign, "", host


def device_of(ua):
    if re.search(r"iPad|Tablet|Android(?!.*Mobile)", ua or "", re.I):
        return "Tablet"
    if re.search(r"Mobi|iPhone|Android", ua or "", re.I):
        return "Phone"
    return "Computer"


def browser_of(ua):
    ua = ua or ""
    for pat, name in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung Internet"),
                      (r"Firefox/|FxiOS", "Firefox"), (r"CriOS|Chrome/", "Chrome"), (r"Safari/", "Safari")):
        if re.search(pat, ua):
            return name
    return "Other"


def _db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS hits (
        id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
        source TEXT, medium TEXT, campaign TEXT, term TEXT, ref_host TEXT,
        device TEXT, browser TEXT, country TEXT, region TEXT, city TEXT, visitor TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS hits_day ON hits(day)")
    return con


def _salt(day):
    """A random salt per day. Old salts are deleted, so old visitor hashes can't be linked or reversed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / f".salt-{day}"
    for old in DATA_DIR.glob(".salt-*"):
        if old.name != f.name:
            old.unlink(missing_ok=True)
    if not f.exists():
        f.write_text(secrets.token_hex(16))
        f.chmod(0o600)
    return f.read_text()


def record(payload, headers, ip, tz="America/Chicago", site_host="", now=None, visitor=None):
    """Store one beacon. Returns True if stored, False if ignored (bot, junk).

    visitor: a daily visitor code already made elsewhere (the Hetzner PHP counter); then no IP is used here."""
    ua = headers.get("User-Agent", "")
    if not ua or BOTS.search(ua):
        return False
    kind = str(payload.get("k", "view"))
    if kind not in KINDS:
        return False
    now = now or _dt.datetime.now(_dt.timezone.utc)
    day = now.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")
    params = payload.get("q") if isinstance(payload.get("q"), dict) else {}
    params = {str(k)[:20]: _clip(v, 120) for k, v in list(params.items())[:12]}
    source, medium, campaign, term, ref_host = classify(_clip(payload.get("r"), 500), params, site_host)
    if not visitor:
        visitor = hashlib.sha256(f"{_salt(day)}|{ip}|{ua}".encode()).hexdigest()[:16]
    row = (int(now.timestamp()), day, kind, source, medium, campaign, term, ref_host,
           device_of(ua), browser_of(ua),
           _clip(headers.get("CF-IPCountry"), 4).upper().replace("XX", "").replace("T1", ""),
           _clip(headers.get("cf-region"), 60), _clip(headers.get("cf-ipcity"), 60), visitor)
    with _lock:
        con = _db()
        try:
            con.execute("INSERT INTO hits (ts, day, kind, source, medium, campaign, term, ref_host, device, browser,"
                        " country, region, city, visitor) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            con.commit()
        finally:
            con.close()
    return True


def summary(days=30, tz="America/Chicago", now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc)
    today = now.astimezone(ZoneInfo(tz)).date()
    start = today - _dt.timedelta(days=max(1, int(days)) - 1)
    if not DB_PATH.exists():
        return {"empty": True, "days": days, "start": start.isoformat(), "end": today.isoformat()}
    con = _db()
    q = lambda sql, *a: con.execute(sql, (start.isoformat(),) + a).fetchall()
    W = "day >= ?"
    try:
        views = q(f"SELECT COUNT(*) FROM hits WHERE {W} AND kind='view'")[0][0]
        visitors = q(f"SELECT COUNT(DISTINCT day || visitor) FROM hits WHERE {W} AND kind='view'")[0][0]
        actions = dict(q(f"SELECT kind, COUNT(*) FROM hits WHERE {W} AND kind!='view' GROUP BY kind"))
        daily = {d: (v, u) for d, v, u in q(f"SELECT day, COUNT(*), COUNT(DISTINCT visitor) FROM hits WHERE {W} AND kind='view' GROUP BY day")}
        calls_daily = dict(q(f"SELECT day, COUNT(*) FROM hits WHERE {W} AND kind IN ('call','text','email') GROUP BY day"))
        series = []
        d = start
        while d <= today:
            k = d.isoformat()
            series.append({"day": k, "views": daily.get(k, (0, 0))[0], "visitors": daily.get(k, (0, 0))[1],
                           "contacts": calls_daily.get(k, 0)})
            d += _dt.timedelta(days=1)

        def top(col, extra="", limit=12, kind="view"):
            return [{"name": n, "count": c} for n, c in q(
                f"SELECT {col}, COUNT(*) c FROM hits WHERE {W} AND kind='{kind}' AND {col} != '' {extra} "
                f"GROUP BY {col} ORDER BY c DESC LIMIT {limit}")]

        sources = [{"name": s, "medium": m, "count": c} for s, m, c in q(
            f"SELECT source, medium, COUNT(*) c FROM hits WHERE {W} AND kind='view' GROUP BY source, medium ORDER BY c DESC LIMIT 15")]
        kinds = [{"name": m, "count": c} for m, c in q(
            f"SELECT medium, COUNT(*) c FROM hits WHERE {W} AND kind='view' GROUP BY medium ORDER BY c DESC")]
        contact_sources = [{"name": s, "count": c} for s, c in q(
            f"SELECT source, COUNT(*) c FROM hits WHERE {W} AND kind IN ('call','text','email') GROUP BY source ORDER BY c DESC LIMIT 10")]
        places = [{"name": ", ".join(x for x in (city, region, country) if x), "count": c} for city, region, country, c in q(
            f"SELECT city, region, country, COUNT(*) c FROM hits WHERE {W} AND kind='view' AND (city!='' OR region!='' OR country!='') "
            f"GROUP BY city, region, country ORDER BY c DESC LIMIT 12")]
        return {
            "empty": views == 0 and not actions, "days": days, "start": start.isoformat(), "end": today.isoformat(),
            "views": views, "visitors": visitors, "actions": actions, "series": series,
            "sources": sources, "mediums": kinds, "contactSources": contact_sources,
            "campaigns": top("campaign"), "terms": top("term"), "devices": top("device"),
            "browsers": top("browser", limit=6), "places": places,
        }
    finally:
        con.close()


def prune(keep_days=800):
    """Keep about two years of history."""
    if not DB_PATH.exists():
        return
    cutoff = (_dt.date.today() - _dt.timedelta(days=keep_days)).isoformat()
    with _lock:
        con = _db()
        con.execute("DELETE FROM hits WHERE day < ?", (cutoff,))
        con.commit()
        con.close()


def parse_beacon(body: bytes):
    if not body or len(body) > 4096:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
