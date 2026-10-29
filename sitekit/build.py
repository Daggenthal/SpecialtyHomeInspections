"""Build the static website into dist/ from content/site.json."""
import datetime as _dt
import hashlib
import json
import shutil
from pathlib import Path

from . import hetzner, render
from .paths import CONTENT_FILE, DIST, ROOT, SITE_ASSETS
from .validate import validate

# Old page addresses keep working (Google results, old business cards, bookmarks).
OLD_PAGES = {
    "/about.html": "about", "/services.html": "services", "/gallery.html": "gallery",
    "/reports.html": "reports", "/faq.html": "faq", "/useful.html": "resources",
    "/schedule.html": "contact", "/defects.html": "defects", "/drones.html": "drones",
}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'; upgrade-insecure-requests")


class BuildError(Exception):
    pass


def load_content(path=CONTENT_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _short_hash(data: bytes):
    return hashlib.sha256(data).hexdigest()[:10]


def asset_versions(theme_css: str):
    v = {"theme.css": _short_hash(theme_css.encode()),
         "mobile-layout.css": _short_hash((SITE_ASSETS / "site.css").read_bytes())}
    for p in SITE_ASSETS.rglob("*"):
        if p.is_file():
            v[p.relative_to(SITE_ASSETS).as_posix()] = _short_hash(p.read_bytes())
    return v


def redirects_text(content):
    ids = {s["id"] for s in content["sections"] if s.get("enabled", True)
           and not (s.get("type") == "gallery" and not any(g.get("image") for _, g in render.shown(s.get("items"))))}
    lines = ["# Old page addresses from the previous website", "/index.html / 301"]
    spectora = next((s.get("buttonUrl") for s in content["sections"] if s.get("id") == "reports"
                     and str(s.get("buttonUrl", "")).startswith("https://")), None)
    if spectora:
        lines.append(f"/sample.pdf {spectora} 301")
    for old, sid in OLD_PAGES.items():
        lines.append(f"{old} /#{sid} 301" if sid in ids else f"{old} / 301")
    return "\n".join(lines) + "\n"


def csp_for(content):
    ep = str((content.get("stats") or {}).get("endpoint") or "")
    if ep.startswith("https://"):
        from urllib.parse import urlparse
        u = urlparse(ep)
        return CSP.replace("connect-src 'self'", f"connect-src 'self' {u.scheme}://{u.netloc}")
    return CSP


def headers_text(content=None):
    return f"""/*
  Content-Security-Policy: {csp_for(content or {})}
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()
  Strict-Transport-Security: max-age=31536000

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/media/*
  Cache-Control: public, max-age=86400

/
  Cache-Control: public, max-age=0, must-revalidate
"""


def global_headers(content=None):
    """The header lines that apply to every page (the "/*" block of _headers)."""
    out, block = [], None
    for line in headers_text(content).splitlines():
        if line and not line[0].isspace():
            block = line.strip()
        elif block == "/*" and ":" in line:
            out.append(line.strip())
    return out


def build(content=None, out: Path = DIST, allow_warnings=True):
    content = content if content is not None else load_content()
    errors, warnings = validate(content)
    if errors:
        raise BuildError("\n".join(errors))
    if warnings and not allow_warnings:
        raise BuildError("\n".join(warnings))

    theme_css = render.render_theme_css(content)
    versions = asset_versions(theme_css)
    page, used = render.render_page(content, versions=versions)
    page404 = render.render_404(content, versions=versions)

    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "assets").mkdir(parents=True)
    shutil.copytree(SITE_ASSETS, tmp / "assets", dirs_exist_ok=True)
    (tmp / "assets" / "theme.css").write_text(theme_css, encoding="utf-8")
    (tmp / "assets" / "mobile-layout.css").write_text(
        render.render_mobile_layout_css((SITE_ASSETS / "site.css").read_text(encoding="utf-8")), encoding="utf-8")
    (tmp / "index.html").write_text(page, encoding="utf-8")
    (tmp / "404.html").write_text(page404, encoding="utf-8")

    biz = content["business"]
    used = set(used) | {biz["logo"]["src"]}
    if biz.get("favicon"):
        used.add(biz["favicon"])
    missing = []
    for rel in sorted(used):
        src = ROOT / "content" / rel
        if src.is_file():
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            missing.append(rel)

    site = (biz.get("siteUrl") or "").rstrip("/")
    today = _dt.date.today().isoformat()
    (tmp / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n" + (f"Sitemap: {site}/sitemap.xml\n" if site else ""), encoding="utf-8")
    if site:
        (tmp / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{site}/</loc><lastmod>{today}</lastmod></url>\n</urlset>\n", encoding="utf-8")
    (tmp / "_headers").write_text(headers_text(content), encoding="utf-8")
    (tmp / "_redirects").write_text(redirects_text(content), encoding="utf-8")
    # Apache (Hetzner Webhosting): the same rules as _headers/_redirects, plus the PHP visit counter
    (tmp / ".htaccess").write_text(
        hetzner.htaccess_text(content, global_headers(content), redirects_text(content)), encoding="utf-8")
    st = content.get("stats") or {}
    if st.get("enabled") and str(st.get("endpoint", "")).strip() == "/api/hit":
        tz = (content.get("hours") or {}).get("timezone") or "America/Chicago"
        (tmp / "_api").mkdir()
        (tmp / "_api" / "hit.php").write_text(hetzner.hit_php(tz), encoding="utf-8")
        (tmp / "_api" / ".htaccess").write_text(hetzner.api_htaccess_text(), encoding="utf-8")
    # Cloudflare uploads skip the Apache-only files
    (tmp / ".assetsignore").write_text(".htaccess\n_api\n", encoding="utf-8")

    old = out.with_name(out.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    if old.exists():
        shutil.rmtree(old)

    return {"out": str(out), "media": len(used) - len(missing), "missing": missing, "warnings": warnings}
