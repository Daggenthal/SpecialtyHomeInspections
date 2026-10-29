"""Render content/site.json into HTML.

One renderer is used for both the published site and the editor's live
preview, so what John sees while editing is exactly what goes live.

Text formatting John can use in any paragraph field:
    **bold words**            -> bold
    [link text](https://...)  -> link
    a blank line              -> new paragraph
Review text is NEVER formatted: it is escaped and shown exactly as stored.
"""
import contextvars
import datetime as _dt
import html
import json
import re
from zoneinfo import ZoneInfo

from .imagesize import image_size
from .paths import ROOT

LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
SAFE_HREF = re.compile(r"^(https?://|mailto:|tel:|sms:|#|/)", re.I)

esc = lambda s: html.escape(str(s if s is not None else ""), quote=True)

# --------------------------------------------------------------------------- {years} / {since}
# Any text can say "{years}" (years since the business started) or "{since}" (the year it started).
# The page is built with today's number, and site.js recalculates it in the visitor's browser,
# so it goes up by itself every anniversary without republishing.

_FOUNDED = contextvars.ContextVar("founded", default=None)
TOKEN_RE = re.compile(r"\{(years|since)\}")


def parse_founded(value):
    try:
        return _dt.date.fromisoformat(str(value or ""))
    except ValueError:
        return None


def years_since(founded, today=None):
    if not founded:
        return None
    today = today or _dt.datetime.now(ZoneInfo("America/Chicago")).date()
    n = today.year - founded.year - ((today.month, today.day) < (founded.month, founded.day))
    return max(0, n)


def _tokens_html(text):
    f = _FOUNDED.get()
    if not f:
        return text
    return TOKEN_RE.sub(lambda m: f'<span data-years-since="{f.isoformat()}">{years_since(f)}</span>'
                        if m.group(1) == "years" else str(f.year), text)


def tokens_plain(text, founded=None):
    f = founded or _FOUNDED.get()
    if not f:
        return str(text or "")
    return TOKEN_RE.sub(lambda m: str(years_since(f)) if m.group(1) == "years" else str(f.year), str(text or ""))


# --------------------------------------------------------------------------- text

def _fmt(raw):
    out = _tokens_html(esc(raw))
    return BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)


def _href_attrs(url):
    url = url.strip()
    if not SAFE_HREF.match(url):
        return None
    attrs = f'href="{esc(url)}"'
    if url.lower().startswith("http"):
        attrs += ' target="_blank" rel="noopener noreferrer"'
    return attrs


def inline(raw):
    raw = str(raw or "")
    out, pos = [], 0
    for m in LINK_RE.finditer(raw):
        out.append(_fmt(raw[pos:m.start()]))
        attrs = _href_attrs(m.group(2))
        out.append(f"<a {attrs}>{_fmt(m.group(1))}</a>" if attrs else _fmt(m.group(1)))
        pos = m.end()
    out.append(_fmt(raw[pos:]))
    return "".join(out).replace("\n", "<br>")


def paras(raw, cls=""):
    blocks = [b.strip("\n") for b in re.split(r"\n\s*\n", str(raw or "")) if b.strip()]
    c = f' class="{cls}"' if cls else ""
    return "\n".join(f"<p{c}>{inline(b)}</p>" for b in blocks)


def tel_href(phone):
    digits = re.sub(r"[^\d+]", "", phone or "")
    if digits and not digits.startswith("+") and len(digits) == 10:
        digits = "+1" + digits
    return digits


# --------------------------------------------------------------------------- icons

ICONS = {
    "phone": '<path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z"/>',
    "text": '<path d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="8.5" cy="11" r="1.2"/><circle cx="12" cy="11" r="1.2"/><circle cx="15.5" cy="11" r="1.2"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="m4 7 8 6 8-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "check": '<path d="m5 12.5 4.2 4.2L19 7" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
    "up": '<path d="M12 19V5m-7 7 7-7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    "sun": '<circle cx="12" cy="12" r="4.2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "quote": '<path d="M9.5 6C6 7.3 4 10 4 13.5V18h6v-6H7c0-2.3 1.3-3.9 3.3-4.6zm10 0C16 7.3 14 10 14 13.5V18h6v-6h-3c0-2.3 1.3-3.9 3.3-4.6z"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "facebook": '<path d="M14 8.5V6.8c0-.8.5-1.3 1.4-1.3H17V2.2A21 21 0 0 0 14.6 2C12.2 2 10.6 3.5 10.6 6.1v2.4H8v3.6h2.6V22H14v-9.9h2.7l.4-3.6z"/>',
    "x": '<path d="M17.8 3h3.3l-7.2 8.2L22.4 21h-6.6l-5.2-6.8L4.6 21H1.3l7.7-8.8L.9 3h6.8l4.7 6.2zm-1.2 16.1h1.8L6.6 4.8H4.6z"/>',
    "linkedin": '<path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9.75h4V21H3zm7 0h3.8v1.6h.06c.53-1 1.83-2.05 3.77-2.05 4.03 0 4.77 2.65 4.77 6.1V21h-4v-4.9c0-1.17-.02-2.67-1.63-2.67-1.63 0-1.88 1.27-1.88 2.59V21H10z"/>',
    "doc": '<path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    "drone": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="18" r="3"/><path d="M8.2 8.2 10 10m5.8-1.8L14 10m-5.8 5.8L10 14m5.8 1.8L14 14"/><rect x="9.5" y="9.5" width="5" height="5" rx="1.2"/></g>',
    "pano": '<g fill="none" stroke="currentColor" stroke-width="1.6"><ellipse cx="12" cy="12" rx="9.5" ry="4"/><path d="M12 2.5a9.5 9.5 0 0 1 0 19M12 2.5a9.5 9.5 0 0 0 0 19M2.5 12h19"/></g>',
}


def icon(name, size=20, cls="icon"):
    return (f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" '
            f'fill="currentColor" aria-hidden="true" focusable="false">{ICONS[name]}</svg>')


# --------------------------------------------------------------------------- images

class Ctx:
    def __init__(self, content, media_base="", asset_base="assets/", preview=False, versions=None):
        self.c = content
        self.media_base = media_base
        self.asset_base = asset_base
        self.preview = preview
        self.versions = versions or {}
        self.used_media = set()

    def media(self, path):
        if not path:
            return ""
        self.used_media.add(path)
        return self.media_base + path

    def asset(self, name):
        v = self.versions.get(name)
        return f"{self.asset_base}{name}" + (f"?v={v}" if v else "")

    def link(self, value):
        if value in (self.c.get("links") or {}):
            return self.c["links"][value]
        return value

    def media_ok(self, url):
        """A link into the media library only counts if the file is really there."""
        if not url.startswith("media/"):
            return True
        return (ROOT / "content" / url).is_file()

    def href(self, url):
        if url.startswith("media/"):
            return self.media(url)
        return url

    def dp(self, path):
        """data-path attribute used by the editor to jump to the right field."""
        return f' data-path="{esc(path)}"' if self.preview else ""


def img(ctx, path, alt, cls="", lazy=True, sizes=None, extra=""):
    if not path:
        return ""
    dims = image_size(ROOT / "content" / path)
    wh = f' width="{dims[0]}" height="{dims[1]}"' if dims else ""
    loading = ' loading="lazy" decoding="async"' if lazy else ' decoding="async" fetchpriority="high"'
    c = f' class="{cls}"' if cls else ""
    s = f' sizes="{sizes}"' if sizes else ""
    return f'<img src="{esc(ctx.media(path))}" alt="{esc(alt)}"{wh}{loading}{c}{s}{extra}>'


# --------------------------------------------------------------------------- sections

def sec_open(ctx, sec, i, cls=""):
    return (f'<section id="{esc(sec["id"])}" class="section {cls} sec-{esc(sec["type"])}"'
            f'{ctx.dp(f"sections.{i}")}>')


def heading(ctx, sec, i, tag="h2", cls="section-title"):
    t = sec.get("title")
    return f'<{tag} class="{cls} reveal"{ctx.dp(f"sections.{i}.title")}>{inline(t)}</{tag}>' if t else ""


# --------------------------------------------------------------------------- hidden items
# Any list item can be hidden without deleting it. Text-only items are stored either as a
# plain string or as {"text": ..., "hidden": true}. Numbers (FAQ, Top 10) count only what's shown.

def shown(items):
    """(original_index, item) for every item that isn't hidden. The original index keeps the
    editor's click-to-edit pointing at the right field."""
    return [(j, it) for j, it in enumerate(items or [])
            if not (isinstance(it, dict) and it.get("hidden"))]


def text_of(it):
    return it.get("text", "") if isinstance(it, dict) else (it or "")


def r_hero(ctx, sec, i):
    b = ctx.c["business"]
    logo = b["logo"]
    phone = b.get("phone", "")
    call = ""
    if sec.get("showCallButton", True) and phone:
        call = (f'<a class="btn btn-ghost" href="tel:{esc(tel_href(phone))}">{icon("phone")}'
                f'<span>Call {esc(phone)}</span></a>')
    logo_img = (f'<img src="{esc(ctx.media(logo["src"]))}" alt="{esc(logo.get("alt", b["name"]))}" '
                f'width="{int(logo.get("width", 763))}" height="{int(logo.get("height", 478))}" '
                f'decoding="async" fetchpriority="high" class="logo-img">')
    return f"""{sec_open(ctx, sec, i, "hero")}
  <div class="hero-bg" aria-hidden="true"></div>
  <div class="container hero-grid">
    <div class="hero-copy">
      <p class="eyebrow reveal"{ctx.dp(f"sections.{i}.eyebrow")}>{inline(sec.get("eyebrow"))}</p>
      <h1 class="hero-title reveal"{ctx.dp(f"sections.{i}.title")}>{inline(sec.get("title"))}</h1>
      <p class="hero-cred reveal"{ctx.dp("business.credential")}><span>{esc(b.get("credential"))}</span><span class="dot" aria-hidden="true"></span><span>{esc(b.get("owner"))}</span></p>
      <div class="hero-lead reveal"{ctx.dp(f"sections.{i}.lead")}>{paras(sec.get("lead"))}</div>
      <div class="hero-actions reveal">
        <a class="btn btn-primary" href="#contact">{esc(sec.get("primaryButton") or "Request a Quote")}</a>
        {call}
      </div>
      {hours_pill(ctx)}
    </div>
    <div class="hero-logo reveal" data-hero-logo>
      <div class="logo-card"{ctx.dp("business.logo")}>{logo_img}</div>
    </div>
  </div>
</section>"""


def r_trust(ctx, sec, i):
    cards = []
    for j, it in shown(sec.get("items")):
        link = ctx.link(it.get("link", ""))
        inner = (f'<div class="trust-img">{img(ctx, it.get("image"), it.get("label", ""))}</div>'
                 f'<div class="trust-text"><p class="trust-label">{esc(it.get("label"))}</p>'
                 + (f'<p class="trust-note">{inline(it.get("note"))}</p>' if it.get("note") else "")
                 + "</div>")
        dp = ctx.dp(f"sections.{i}.items.{j}")
        if link and SAFE_HREF.match(link):
            cards.append(f'<a class="trust-card reveal" href="{esc(link)}" target="_blank" rel="noopener noreferrer"{dp}>{inner}</a>')
        else:
            cards.append(f'<div class="trust-card reveal"{dp}>{inner}</div>')
    return f"""{sec_open(ctx, sec, i, "trust")}
  <div class="container"><div class="trust-grid">{''.join(cards)}</div></div>
</section>"""


def r_about(ctx, sec, i):
    photo = img(ctx, sec.get("photo"), sec.get("photoAlt", ""), "about-photo")
    if photo and _crop(sec.get("photoCrop")):
        photo = f'<div class="photo-crop">{photo}</div>'
    return f"""{sec_open(ctx, sec, i)}
  <div class="container about-grid">
    <figure class="about-figure reveal"{ctx.dp(f"sections.{i}.photo")}>{photo}</figure>
    <div class="about-copy">
      <p class="kicker reveal">About</p>
      {heading(ctx, sec, i)}
      <div class="prose reveal"{ctx.dp(f"sections.{i}.body")}>{paras(sec.get("body"))}</div>
    </div>
  </div>
</section>"""


def r_text(ctx, sec, i):
    return f"""{sec_open(ctx, sec, i, "band")}
  <div class="container narrow">
    {heading(ctx, sec, i)}
    <div class="prose reveal"{ctx.dp(f"sections.{i}.body")}>{paras(sec.get("body"))}</div>
  </div>
</section>"""


def r_services(ctx, sec, i):
    items = "".join(
        f'<li class="svc reveal"{ctx.dp(f"sections.{i}.items.{j}")}>{icon("check", 18)}<span>{inline(text_of(s))}</span></li>'
        for j, s in shown(sec.get("items")))
    hl = "".join(
        f'<li{ctx.dp(f"sections.{i}.highlights.{j}")}>{icon("check", 18)}<span>{inline(text_of(s))}</span></li>'
        for j, s in shown(sec.get("highlights")))
    highlights = ""
    if hl:
        highlights = f"""<aside class="highlights reveal">
      <h3{ctx.dp(f"sections.{i}.highlightsTitle")}>{inline(sec.get("highlightsTitle"))}</h3>
      <ul>{hl}</ul>
    </aside>"""
    return f"""{sec_open(ctx, sec, i)}
  <div class="container">
    <p class="kicker reveal">What we inspect</p>
    {heading(ctx, sec, i)}
    <div class="prose lead-prose reveal"{ctx.dp(f"sections.{i}.intro")}>{paras(sec.get("intro"))}</div>
    <div class="svc-layout">
      <ul class="svc-grid">{items}</ul>
      {highlights}
    </div>
  </div>
</section>"""


def r_pricing(ctx, sec, i):
    rows = "".join(
        f'<li class="price-card reveal"{ctx.dp(f"sections.{i}.rows.{j}")}>'
        f'<span class="price-name">{inline(r.get("name"))}</span>'
        f'<span class="price-amt">{esc(r.get("price"))}</span></li>'
        for j, r in shown(sec.get("rows")))
    note = f'<p class="price-note reveal"{ctx.dp(f"sections.{i}.note")}>{inline(sec.get("note"))}</p>' if sec.get("note") else ""
    return f"""{sec_open(ctx, sec, i, "band")}
  <div class="container">
    <p class="kicker reveal">Pricing</p>
    {heading(ctx, sec, i)}
    <ul class="price-grid">{rows}</ul>
    {note}
    <div class="center reveal"><a class="btn btn-primary" href="#contact">Request a Quote</a></div>
  </div>
</section>"""


def r_feature(ctx, sec, i):
    media = img(ctx, sec.get("image"), sec.get("imageAlt", ""), "feature-img") if sec.get("image") else ""
    if not media:
        if "drone" in sec["id"]:
            media = f'<div class="feature-art" aria-hidden="true">{icon("drone", 160, "feature-icon")}</div>'
        else:
            media = ('<div class="feature-art pano-art" aria-hidden="true">'
                     '<svg class="orbit" viewBox="0 0 200 200" width="200" height="200" focusable="false">'
                     '<ellipse cx="100" cy="100" rx="88" ry="30" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="6 9" opacity=".55"/>'
                     '<path d="M30 118a88 30 0 0 0 140 0" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>'
                     '<path d="m160 106 12 12-16 6" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
                     '</svg><span class="pano-text">360°</span></div>')
    kicker = f'<p class="kicker kicker-red reveal"{ctx.dp(f"sections.{i}.kicker")}>{esc(sec["kicker"])}</p>' if sec.get("kicker") else ""
    link = sec.get("imageLink", "")
    if link and sec.get("image") and ctx.media_ok(link):
        attrs = _href_attrs(ctx.href(link))
        if attrs:
            media = f'<a class="feature-link" {attrs}>{media}</a>'
    btns = []
    for n, (tk, uk) in enumerate((("buttonText", "buttonUrl"), ("button2Text", "button2Url"))):
        url, text = sec.get(uk, ""), sec.get(tk, "")
        if not (text and url and ctx.media_ok(url)):
            continue
        attrs = _href_attrs(ctx.href(url))
        if not attrs:
            continue
        ico = icon("doc", 16) if url.lower().endswith(".pdf") else icon("external", 16)
        cls = "btn btn-primary" if n == 0 and sec.get("button2Text") else "btn btn-outline"
        btns.append(f'<a class="{cls}" {attrs}{ctx.dp(f"sections.{i}.{uk}")}>{esc(text)} {ico}</a>')
    btn = f'<div class="feature-btns reveal">{"".join(btns)}</div>' if btns else ""
    flip = " flip" if i % 2 else ""
    return f"""{sec_open(ctx, sec, i)}
  <div class="container feature-grid{flip}">
    <figure class="feature-media reveal"{ctx.dp(f"sections.{i}.image")}>{media}</figure>
    <div class="feature-copy">
      {kicker}
      {heading(ctx, sec, i)}
      <div class="prose reveal"{ctx.dp(f"sections.{i}.body")}>{paras(sec.get("body"))}</div>
      {btn}
    </div>
  </div>
</section>"""


def r_reviews(ctx, sec, i):
    cards = []
    for j, r in shown(sec.get("items")):
        # Verbatim: escape only. No formatting, no trimming, no smart quotes.
        cards.append(
            f'<figure class="review reveal"{ctx.dp(f"sections.{i}.items.{j}")}>'
            f'{icon("quote", 34, "review-mark")}'
            f'<blockquote class="review-text" data-verbatim>"{esc(r.get("quote", ""))}"</blockquote>'
            f'<figcaption class="review-name" data-verbatim-name>{esc(r.get("name", ""))}</figcaption>'
            f"</figure>")
    g = ctx.link("googleReviews")
    more = ""
    if g and sec.get("linkText"):
        more = f'<div class="center reveal"><a class="btn btn-outline" href="{esc(g)}" target="_blank" rel="noopener noreferrer">{esc(sec["linkText"])} {icon("external", 16)}</a></div>'
    return f"""{sec_open(ctx, sec, i, "band reviews-band")}
  <div class="container">
    <p class="kicker reveal">What clients say</p>
    {heading(ctx, sec, i)}
    <div class="review-grid">{''.join(cards)}</div>
    {more}
  </div>
</section>"""


def r_list(ctx, sec, i):
    tag = "ol" if sec.get("numbered") else "ul"
    items = "".join(
        f'<li class="reveal"{ctx.dp(f"sections.{i}.items.{j}")}><span class="num" aria-hidden="true">{n:02d}</span><span>{inline(text_of(s))}</span></li>'
        for n, (j, s) in enumerate(shown(sec.get("items")), 1))
    return f"""{sec_open(ctx, sec, i)}
  <div class="container">
    {heading(ctx, sec, i)}
    <div class="prose lead-prose reveal"{ctx.dp(f"sections.{i}.intro")}>{paras(sec.get("intro"))}</div>
    <{tag} class="defect-list">{items}</{tag}>
  </div>
</section>"""


def r_faq(ctx, sec, i):
    items = "".join(
        f'<details class="faq-item reveal"{ctx.dp(f"sections.{i}.items.{j}")}>'
        f'<summary><span class="faq-n">{n}.</span><span class="faq-q">{inline(it.get("q"))}</span><span class="faq-toggle" aria-hidden="true"></span></summary>'
        f'<div class="faq-a">{paras(it.get("a"))}</div></details>'
        for n, (j, it) in enumerate(shown(sec.get("items")), 1))
    return f"""{sec_open(ctx, sec, i, "band")}
  <div class="container narrow">
    <p class="kicker reveal">FAQ</p>
    {heading(ctx, sec, i)}
    <div class="prose lead-prose reveal"{ctx.dp(f"sections.{i}.intro")}>{paras(sec.get("intro"))}</div>
    <div class="faq-list">{items}</div>
  </div>
</section>"""


def r_badges(ctx, sec, i):
    feat = ""
    for j, f in shown(sec.get("featured")):
        inner = img(ctx, f.get("image"), f.get("alt", ""), "featured-badge")
        link = f.get("link", "")
        if link and _href_attrs(link):
            inner = f'<a {_href_attrs(link)}>{inner}</a>'
        feat += f'<figure class="featured reveal"{ctx.dp(f"sections.{i}.featured.{j}")}>{inner}<figcaption>{esc(f.get("alt"))}</figcaption></figure>'
    tiles = "".join(
        f'<li class="badge-tile"{ctx.dp(f"sections.{i}.items.{j}")}>{img(ctx, b.get("image"), b.get("alt", ""))}</li>'
        for j, b in shown(sec.get("items")))
    count = len(shown(sec.get("items")))
    more = f'<button class="btn btn-outline badge-more" type="button" data-badge-more hidden>Show all {count} certifications</button>' if count > 12 else ""
    return f"""{sec_open(ctx, sec, i)}
  <div class="container">
    <p class="kicker reveal">Credentials</p>
    {heading(ctx, sec, i)}
    {f'<div class="prose lead-prose reveal">{paras(sec.get("intro"))}</div>' if sec.get("intro") else ""}
    <div class="badges-layout">
      {f'<div class="featured-col">{feat}</div>' if feat else ""}
      <div class="badge-wrap reveal"><ul class="badge-grid" data-badge-grid>{tiles}</ul>{more}</div>
    </div>
  </div>
</section>"""


def r_gallery(ctx, sec, i):
    items = [(j, g) for j, g in shown(sec.get("items")) if g.get("image")]
    if not items and not ctx.preview:
        return ""
    if not items:
        tiles = '<p class="empty-note">No photos yet. Add some in the editor and this section will appear on the website.</p>'
    else:
        tiles = "<ul class=\"gallery-grid\">" + "".join(
            f'<li class="reveal"{ctx.dp(f"sections.{i}.items.{j}")}>'
            f'<a href="{esc(ctx.media(g["image"]))}" data-lightbox data-caption="{esc(g.get("caption", ""))}">'
            f'{img(ctx, g["image"], g.get("caption") or "Inspection photo")}</a>'
            + (f'<p class="gallery-cap">{esc(g["caption"])}</p>' if g.get("caption") else "")
            + "</li>" for j, g in items) + "</ul>"
    return f"""{sec_open(ctx, sec, i, "band")}
  <div class="container">
    {heading(ctx, sec, i)}
    {f'<div class="prose lead-prose reveal">{paras(sec.get("intro"))}</div>' if sec.get("intro") else ""}
    {tiles}
  </div>
</section>"""


def r_links(ctx, sec, i):
    groups = []
    for j, g in shown(sec.get("groups")):
        lis = []
        for k, l in shown(g.get("links")):
            attrs = _href_attrs(l.get("url", ""))
            text = esc(l.get("text"))
            a = f"<a {attrs}>{text}</a>" if attrs else text
            note = f' <span class="link-note">{esc(l["note"])}</span>' if l.get("note") else ""
            lis.append(f'<li{ctx.dp(f"sections.{i}.groups.{j}.links.{k}")}>{a}{note}</li>')
        groups.append(
            f'<details class="link-group reveal" open{ctx.dp(f"sections.{i}.groups.{j}")}><summary>{esc(g.get("title"))}</summary>'
            f'<ul>{"".join(lis)}</ul></details>')
    return f"""{sec_open(ctx, sec, i)}
  <div class="container">
    {heading(ctx, sec, i)}
    <div class="link-groups">{''.join(groups)}</div>
  </div>
</section>"""


def r_contact(ctx, sec, i):
    b = ctx.c["business"]
    phone, email = b.get("phone", ""), b.get("email", "")
    social = "".join(
        f'<a class="social" href="{esc(s["url"])}" target="_blank" rel="noopener noreferrer">'
        f'{icon(SOCIAL_ICONS.get(s.get("name", "").lower(), "external"), 18)} {esc(s.get("name"))}</a>'
        for s in visible_social(ctx.c))
    return f"""{sec_open(ctx, sec, i, "contact")}
  <div class="container contact-grid">
    <div>
      <p class="kicker kicker-light reveal">Get in touch</p>
      {heading(ctx, sec, i)}
      <div class="prose reveal"{ctx.dp(f"sections.{i}.body")}>{paras(sec.get("body"))}</div>
      <p class="contact-meta reveal"><strong>{esc(b.get("owner"))}</strong><br>{esc(b.get("credential"))}<br>{esc(b.get("serviceArea"))}</p>
      <div class="reveal">{social}</div>
    </div>
    <div class="contact-actions">
      {hours_card(ctx)}
      <a class="contact-btn reveal" href="tel:{esc(tel_href(phone))}">{icon("phone", 26)}<span><small>Call</small>{esc(phone)}</span></a>
      <a class="contact-btn reveal" href="sms:{esc(tel_href(phone))}">{icon("text", 26)}<span><small>Text</small>{esc(phone)}</span></a>
      <a class="contact-btn reveal" href="mailto:{esc(email)}">{icon("mail", 26)}<span><small>Email</small>{esc(email)}</span></a>
    </div>
  </div>
</section>"""


SOCIAL_ICONS = {"facebook": "facebook", "twitter": "x", "x": "x", "linkedin": "linkedin"}


def visible_social(content):
    return [s for s in content.get("social", []) if s.get("show") and s.get("url", "").startswith("http")]


# --------------------------------------------------------------------------- hours

DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _schedule(content):
    h = content.get("hours") or {}
    out = []
    for i in range(7):
        try:
            d = h["schedule"][i]
        except (KeyError, IndexError, TypeError):
            d = {"open": False}
        ok = bool(d.get("open")) and HHMM.match(str(d.get("from", ""))) and HHMM.match(str(d.get("to", "")))
        out.append((d["from"], d["to"]) if ok else None)
    return out


def _ampm(hhmm):
    hh, mm = map(int, hhmm.split(":"))
    return f"{(hh % 12) or 12}:{mm:02d} {'AM' if hh < 12 else 'PM'}"


def hours_summary(content):
    h = content.get("hours") or {}
    sched = _schedule(content)
    zone = h.get("zoneName") or "Central Time"
    days_open = [s for s in sched if s]
    if not days_open:
        return "Please call or email to schedule."
    if len(days_open) == 7 and len(set(days_open)) == 1:
        f, t = days_open[0]
        return f"Open every day, {_ampm(f)} to {_ampm(t)} {zone}"
    return f"Hours vary by day ({zone})"


def hours_attrs(content):
    h = content.get("hours") or {}
    sched = ",".join(f"{s[0]}-{s[1]}" if s else "" for s in _schedule(content))
    return (f' data-hours data-tz="{esc(h.get("timezone") or "America/Chicago")}" data-sched="{esc(sched)}"'
            f' data-zone="{esc(h.get("zoneName") or "Central Time")}"'
            f' data-open-text="{esc(h.get("openText") or "Open now")}" data-closed-text="{esc(h.get("closedText") or "Closed right now")}"')


def hours_pill(ctx):
    h = ctx.c.get("hours") or {}
    if not h.get("show"):
        return ""
    return (f'<p class="hours-pill reveal"{hours_attrs(ctx.c)}{ctx.dp("hours")}>'
            f'<span class="hours-dot" aria-hidden="true"></span>'
            f'<span class="hours-text" data-hours-status>{esc(hours_summary(ctx.c))}</span></p>')


def hours_card(ctx):
    h = ctx.c.get("hours") or {}
    if not h.get("show"):
        return ""
    rows = "".join(
        f'<li data-day="{i}"><span>{DAYS[i]}</span><span>{f"{_ampm(s[0])} to {_ampm(s[1])}" if s else "Closed"}</span></li>'
        for i, s in enumerate(_schedule(ctx.c)))
    zone = esc(h.get("zoneName") or "Central Time")
    return f"""<div class="hours-card reveal"{hours_attrs(ctx.c)}{ctx.dp("hours")}>
        <div class="hours-head"><span class="hours-dot" aria-hidden="true"></span><strong data-hours-status>{esc(hours_summary(ctx.c))}</strong></div>
        <p class="hours-next" data-hours-next></p>
        <div class="clocks">
          <div class="clock" data-clock="visitor"><small>Your time</small><b>--:--</b><span></span></div>
          <div class="clock" data-clock="business"><small>Our time (Pensacola)</small><b>--:--</b><span></span></div>
        </div>
        <details class="hours-week"><summary>Hours of operation ({zone})</summary><ul>{rows}</ul></details>
      </div>"""


RENDERERS = {
    "hero": r_hero, "trust": r_trust, "about": r_about, "text": r_text, "services": r_services,
    "pricing": r_pricing, "feature": r_feature, "reviews": r_reviews, "list": r_list, "faq": r_faq,
    "badges": r_badges, "gallery": r_gallery, "links": r_links, "contact": r_contact,
}


# --------------------------------------------------------------------------- page

def _jsonld(content):
    b = content["business"]
    site = (b.get("siteUrl") or "").rstrip("/")
    data = {
        "@context": "https://schema.org",
        "@type": "HomeAndConstructionBusiness",
        "name": b.get("name"),
        "url": site + "/" if site else None,
        "telephone": b.get("phone"),
        "email": b.get("email"),
        "founder": {"@type": "Person", "name": b.get("owner")},
        "areaServed": "Pensacola, Florida and surrounding areas",
        "address": {"@type": "PostalAddress", "addressLocality": b.get("city"), "addressRegion": b.get("region"), "addressCountry": "US"},
        "logo": f"{site}/{b['logo']['src']}" if site else None,
        "sameAs": [s["url"] for s in visible_social(content)] + [u for u in [(content.get("links") or {}).get("bbb")] if u],
    }
    data = {k: v for k, v in data.items() if v}
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def stats_attrs(content, preview=False):
    st = content.get("stats") or {}
    ep = str(st.get("endpoint") or "")
    if preview or not st.get("enabled") or not (ep.startswith("/") or ep.startswith("https://")):
        return ""
    dnt = ' data-stats-dnt="1"' if st.get("respectPrivacySignals", True) else ""
    return f' data-stats="{esc(ep)}"{dnt}'


def footer_tags(content):
    labels = []
    for sec in content["sections"]:
        if sec.get("type") == "trust" and sec.get("enabled", True):
            labels += [esc(it["label"]) for _, it in shown(sec.get("items")) if it.get("label")]
    return f'<p class="footer-tags">{" · ".join(labels)}</p>' if labels else ""


def nav_links(content, ctx):
    out = []
    for sec in content["sections"]:
        if not sec.get("enabled", True) or not sec.get("nav"):
            continue
        if sec["type"] == "gallery" and not any(g.get("image") for _, g in shown(sec.get("items"))) and not ctx.preview:
            continue
        out.append(f'<li><a href="#{esc(sec["id"])}" data-nav="{esc(sec["id"])}">{esc(sec["nav"])}</a></li>')
    return "".join(out)


def render_page(content, media_base="", asset_base="assets/", preview=False, versions=None, extra_head="", extra_body=""):
    _FOUNDED.set(parse_founded(content.get("business", {}).get("founded")))
    ctx = Ctx(content, media_base, asset_base, preview, versions)
    b = content["business"]
    seo = {k: tokens_plain(v) for k, v in content.get("seo", {}).items()}
    theme = content.get("theme", {})
    body = []
    for i, sec in enumerate(content["sections"]):
        if not sec.get("enabled", True):
            continue
        fn = RENDERERS.get(sec.get("type"))
        if fn:
            body.append(fn(ctx, sec, i))
    year = _dt.date.today().year
    site = (b.get("siteUrl") or "").rstrip("/")
    logo = b["logo"]
    phone, email = b.get("phone", ""), b.get("email", "")
    mode = theme.get("mode", "auto")
    anim = "" if theme.get("animations", True) else " no-anim"
    layout = " layout-mobile" if theme.get("layout") == "mobile" else ""
    canonical = f'<link rel="canonical" href="{esc(site)}/">' if site else ""
    og_img = f'<meta property="og:image" content="{esc(site)}/{esc(logo["src"])}">' if site else ""
    fav = b.get("favicon")
    fav_tag = f'<link rel="icon" href="{esc(ctx.media(fav))}">' if fav else ""

    return f"""<!doctype html>
<html lang="en" data-theme-default="{esc(mode)}" class="no-js{anim}{layout}"{stats_attrs(content, preview)}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(seo.get("title") or b["name"])}</title>
<meta name="description" content="{esc(seo.get("description", ""))}">
<meta name="keywords" content="{esc(seo.get("keywords", ""))}">
<meta name="theme-color" content="{esc(theme.get("navy", "#1b3a8c"))}">
<meta name="format-detection" content="telephone=no">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(seo.get("title") or b["name"])}">
<meta property="og:description" content="{esc(seo.get("description", ""))}">
{og_img}
{canonical}
{fav_tag}
<link rel="preload" href="{esc(ctx.asset("fonts/oswald-latin.woff2"))}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{esc(ctx.asset("theme.css"))}">
<link rel="stylesheet" href="{esc(ctx.asset("site.css"))}">
<link rel="stylesheet" href="{esc(ctx.asset("mobile-layout.css"))}">
<script src="{esc(ctx.asset("site.js"))}" defer></script>
<script type="application/ld+json">{_jsonld(content)}</script>
{extra_head}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="ptr" aria-hidden="true"><span class="ptr-icon">{icon("refresh", 22)}</span></div>
<header class="site-header" data-header>
  <div class="container header-row">
    <a class="brand" href="#home" aria-label="{esc(b["name"])} home">
      <span class="brand-logo"><img src="{esc(ctx.media(logo["src"]))}" alt="" width="{int(logo.get("width", 763))}" height="{int(logo.get("height", 478))}" decoding="async"></span>
      <span class="brand-name">{esc(b["name"])}</span>
    </a>
    <nav class="site-nav" id="site-nav" aria-label="Main">
      <ul>{nav_links(content, ctx)}</ul>
      <a class="nav-call" href="tel:{esc(tel_href(phone))}">{icon("phone", 18)}<span>{esc(phone)}</span></a>
    </nav>
    <button class="icon-btn theme-btn" type="button" data-theme-toggle aria-label="Switch light or dark mode">{icon("moon", 20, "icon i-moon")}{icon("sun", 20, "icon i-sun")}</button>
    <button class="icon-btn menu-btn" type="button" data-menu aria-controls="site-nav" aria-expanded="false" aria-label="Open menu">{icon("menu", 24, "icon i-menu")}{icon("close", 24, "icon i-close")}</button>
  </div>
</header>
<main id="main">
{chr(10).join(body)}
</main>
<footer class="site-footer">
  <div class="container footer-row">
    <div class="footer-brand">
      <span class="footer-logo"><img src="{esc(ctx.media(logo["src"]))}" alt="{esc(logo.get("alt", b["name"]))}" width="{int(logo.get("width", 763))}" height="{int(logo.get("height", 478))}" loading="lazy" decoding="async"></span>
    </div>
    <div class="footer-info">
      <p><strong>{esc(b["name"])}</strong><br>{esc(b.get("serviceArea"))}<br>{esc(b.get("credential"))}</p>
      <p><a href="tel:{esc(tel_href(phone))}">{esc(phone)}</a> · <a href="mailto:{esc(email)}">{esc(email)}</a></p>
      {footer_tags(content)}
    </div>
  </div>
  <div class="container footer-copy"><p>All Content © {year} {esc(b["name"])}</p></div>
</footer>
<div class="callbar" data-callbar>
  <a href="tel:{esc(tel_href(phone))}">{icon("phone", 20)}<span>Call</span></a>
  <a href="sms:{esc(tel_href(phone))}">{icon("text", 20)}<span>Text</span></a>
  <a href="mailto:{esc(email)}">{icon("mail", 20)}<span>Email</span></a>
</div>
<button class="to-top" type="button" data-to-top aria-label="Back to top">{icon("up", 22)}</button>
<div class="lightbox" data-lightbox-root hidden><button class="lb-close" type="button" aria-label="Close photo">{icon("close", 26)}</button><figure><img alt=""><figcaption></figcaption></figure></div>
{extra_body}
</body>
</html>
""", ctx.used_media


def render_404(content, versions=None):
    b = content["business"]
    logo = b["logo"]
    v = versions or {}
    q = lambda n: f"/assets/{n}" + (f"?v={v[n]}" if v.get(n) else "")
    return f"""<!doctype html>
<html lang="en" class="no-js">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found | {esc(b["name"])}</title>
<meta name="robots" content="noindex">
<link rel="stylesheet" href="{q("theme.css")}"><link rel="stylesheet" href="{q("site.css")}"></head>
<body class="page-404"><main class="container narrow center nf">
<div class="logo-card nf-logo"><img class="logo-img" src="/{esc(logo["src"])}" alt="{esc(logo.get("alt"))}" width="{int(logo.get("width", 763))}" height="{int(logo.get("height", 478))}"></div>
<h1 class="section-title">This page moved</h1>
<p>Everything now lives on one page.</p>
<p><a class="btn btn-primary" href="/">Go to the home page</a></p>
<p><a href="tel:{esc(tel_href(b.get("phone")))}">{esc(b.get("phone"))}</a> · <a href="mailto:{esc(b.get("email"))}">{esc(b.get("email"))}</a></p>
</main></body></html>
"""


MOBILE_QUERIES = ("(max-width: 1100px)", "(max-width: 1020px)", "(max-width: 860px)", "(max-width: 760px)")
MOBILE_COLUMN = 520


def _media_blocks(css, query):
    """Yield the inside of every '@media <query> { ... }' block."""
    start = 0
    head = f"@media {query}"
    while True:
        i = css.find(head, start)
        if i < 0:
            return
        j = css.index("{", i) + 1
        depth, k = 1, j
        while depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        yield css[j:k - 1]
        start = k


def _prefix(selector):
    s = selector.strip()
    if s.startswith(":root"):
        return "html.layout-mobile" + s[len(":root"):]
    if s.startswith("html"):
        return "html.layout-mobile" + s[len("html"):]
    if s.startswith(".js "):
        return "html.layout-mobile.js " + s[4:]
    if s.startswith("body"):
        return "html.layout-mobile " + s
    return "html.layout-mobile " + s


def render_mobile_layout_css(site_css):
    """The phone layout, usable on any screen size when <html class="layout-mobile">.

    Built from the phone/tablet @media rules in site.css so the two can never drift apart."""
    out = ["/* Generated from site.css by sitekit/render.py. Do not edit by hand. */"]
    for q in MOBILE_QUERIES:
        for block in _media_blocks(site_css, q):
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
                sels = ", ".join(_prefix(x) for x in m.group(1).split(",") if x.strip())
                out.append(f"{sels} {{{m.group(2)}}}")
    w = MOBILE_COLUMN
    out.append(f"""
/* Phone layout on a big screen: the page is one centered phone-width column. */
@media (min-width: {w + 1}px) {{
  html.layout-mobile {{ background: #0b1430 radial-gradient(1200px 700px at 50% -10%, var(--navy), #0b1430 70%) fixed; }}
  html.layout-mobile body {{ max-width: {w}px; margin: 0 auto; min-height: 100vh; box-shadow: 0 0 0 1px rgba(255,255,255,.08), 0 40px 120px rgba(0,0,0,.45); }}
  html.layout-mobile .site-nav {{ left: 50%; right: auto; width: {w}px; transform: translateX(-50%) translateY(-12px); }}
  html.layout-mobile .site-nav.open {{ transform: translateX(-50%); }}
  html.layout-mobile .callbar {{ left: 50%; right: auto; width: {w}px; transform: translateX(-50%); }}
  html.layout-mobile .to-top {{ right: calc(50vw - {w // 2}px + 18px); }}
}}""")
    return "\n".join(out) + "\n"


def _crop(c):
    """A crop box {x, y, w, h} in the photo's own pixels. Display-only: the file is never changed."""
    try:
        x, y, w, h = (float(c[k]) for k in ("x", "y", "w", "h"))
    except (TypeError, KeyError, ValueError):
        return None
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        return None
    return x, y, w, h


def render_theme_css(content):
    t = content.get("theme", {})
    hexok = lambda v, d: v if isinstance(v, str) and re.match(r"^#[0-9a-fA-F]{6}$", v) else d
    navy = hexok(t.get("navy"), "#1b3a8c")
    red = hexok(t.get("red"), "#d3333a")
    css = f""":root {{
  --navy: {navy};
  --red: {red};
}}
"""
    for sec in content.get("sections", []):
        if sec.get("type") != "about" or not sec.get("photo"):
            continue
        box = _crop(sec.get("photoCrop"))
        dims = image_size(ROOT / "content" / sec["photo"])
        if not box or not dims:
            continue
        x, y, w, h = box
        W, _H = dims
        css += (f"#{sec['id']} .photo-crop {{ aspect-ratio: {w:g} / {h:g}; }}\n"
                f"#{sec['id']} .photo-crop .about-photo {{ width: {W / w * 100:.4f}%; max-width: none; "
                f"margin-left: {-x / w * 100:.4f}%; margin-top: {-y / w * 100:.4f}%; aspect-ratio: auto; }}\n")
    return css
