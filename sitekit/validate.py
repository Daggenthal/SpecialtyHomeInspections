"""Checks run before every save and every publish.

errors   -> block the save/publish (something would break or a protected item changed)
warnings -> shown to the editor, publish needs an explicit "publish anyway"
"""
import hashlib
import re

from .paths import ROOT

MAX_STRING = 20000
SAFE_URL = re.compile(r"^(https?://|mailto:|tel:|sms:|#|media/|/)[^\s<>\"']*$", re.I)
DISCOUNT_WORD = re.compile(r"discount", re.I)
AMOUNT = re.compile(r"\$\s?\d|\d+\s?%|\d+\s?percent|\d+\s?dollars", re.I)
SECTION_TYPES = {
    "hero", "trust", "about", "text", "services", "pricing", "feature", "reviews",
    "list", "faq", "badges", "gallery", "links", "contact",
}


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}.{i}")
    else:
        yield path, obj


TYPE_NAMES = {
    "hero": "Top of page", "trust": "Trust badges", "about": "About", "text": "Text block", "services": "Services",
    "pricing": "Prices", "feature": "Picture and text", "reviews": "Reviews", "list": "List",
    "faq": "Questions and answers", "badges": "Certifications", "gallery": "Photo gallery", "links": "Links",
    "contact": "Contact",
}


def friendly(path, content):
    """Turn 'sections.9.items.6.a' into something John can find in the editor."""
    m = re.match(r"sections\.(\d+)(?:\.(.*))?", path)
    if not m:
        return path
    try:
        sec = content["sections"][int(m.group(1))]
        title = (sec.get("title") or TYPE_NAMES.get(sec.get("type")) or sec.get("id") or "").replace("**", "")
    except (IndexError, KeyError, TypeError):
        return path
    rest = m.group(2) or ""
    im = re.match(r"items\.(\d+)", rest)
    where = f" (item {int(im.group(1)) + 1})" if im else ""
    return f"“{title}” section{where}"


def _approved(content, path):
    node = content
    for key in path.split(".")[:-1]:
        node = node[int(key)] if isinstance(node, list) else node.get(key)
        if isinstance(node, dict) and node.get("allowAmount") is True:
            return True
    return False


def validate(content, check_media=True):
    errors, warnings = [], []

    if not isinstance(content, dict) or not isinstance(content.get("sections"), list):
        return ["The content file is damaged (no sections list)."], []
    biz = content.get("business") or {}
    for key in ("name", "phone", "email"):
        if not str(biz.get(key, "")).strip():
            errors.append(f"Business {key} can't be empty.")

    for path, value in _walk(content):
        if isinstance(value, str):
            if len(value) > MAX_STRING:
                errors.append(f"Text at {friendly(path, content)} is too long.")
            leaf = path.rsplit(".", 1)[-1]
            if leaf in ("url", "link", "buttonUrl", "button2Url", "imageLink") and value and value not in ("bbb",):
                if not SAFE_URL.match(value):
                    errors.append(f"The link “{value[:80]}” in {friendly(path, content)} isn't a normal web, email or phone link.")
            if leaf in ("image", "photo", "src") and value and not value.startswith("media/"):
                errors.append(f"Image path “{value[:80]}” in {friendly(path, content)} must point into the media library.")

    # Discount guard: keep dollar/percent amounts away from discount wording,
    # unless that exact item was approved on purpose ("allowAmount": true).
    for path, value in _walk(content):
        if _approved(content, path):
            continue
        if isinstance(value, str) and DISCOUNT_WORD.search(value) and AMOUNT.search(value):
            warnings.append(
                f"{friendly(path, content)} mentions a discount together with an amount. "
                "We keep discount amounts off the website so nobody can quote it back to claim one. "
                "Remove the amount, or choose “Publish anyway”."
            )

    founded = biz.get("founded")
    if founded:
        try:
            import datetime as _dt
            if _dt.date.fromisoformat(str(founded)) > _dt.date.today():
                errors.append("The business start date is in the future.")
        except ValueError:
            errors.append("The business start date isn't a real date.")
    if not founded and any("{years}" in str(v) or "{since}" in str(v) for _, v in _walk(content)):
        warnings.append("Some text uses {years} or {since}, but no business start date is set in Business info.")

    hours = content.get("hours") or {}
    sched = hours.get("schedule") or []
    if hours.get("show"):
        if len(sched) != 7:
            errors.append("The hours of operation need all seven days (Sunday to Saturday).")
        for d in sched:
            if d.get("open"):
                for k in ("from", "to"):
                    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(d.get(k, ""))):
                        errors.append(f"{d.get('day', 'A day')}: the {'opening' if k == 'from' else 'closing'} time is missing.")
        if not any(d.get("open") for d in sched):
            warnings.append("Every day is set to closed, so the website will always say closed.")
    if (content.get("theme") or {}).get("layout", "responsive") not in ("responsive", "mobile"):
        errors.append("Unknown page layout.")

    ids = set()
    for i, sec in enumerate(content["sections"]):
        if not isinstance(sec, dict):
            errors.append(f"Section {i + 1} is damaged.")
            continue
        if sec.get("type") not in SECTION_TYPES:
            errors.append(f"Section {i + 1} has an unknown type “{sec.get('type')}”.")
        sid = sec.get("id")
        if not sid or not re.match(r"^[a-z0-9-]+$", str(sid)):
            errors.append(f"Section {i + 1} needs a simple id (lowercase letters, numbers, dashes).")
        elif sid in ids:
            errors.append(f"Two sections share the id “{sid}”.")
        ids.add(sid)

        if sec.get("type") == "reviews":
            for j, r in enumerate(sec.get("items", [])):
                if r.get("locked"):
                    if sha256_text(r.get("quote", "")) != r.get("quoteSha256") or sha256_text(r.get("name", "")) != r.get("nameSha256"):
                        errors.append(
                            f"Review {j + 1} (“{r.get('name', '')}”) is locked as a word-for-word copy of the original, "
                            "but its text no longer matches. Undo the change, or unlock the review first on purpose."
                        )

    if check_media:
        logo = biz.get("logo") or {}
        lp = ROOT / "content" / logo.get("src", "")
        if lp.is_file():
            if logo.get("sha256") and sha256_file(lp) != logo["sha256"]:
                errors.append("The logo file has been changed. The logo must stay exactly as it is.")
        else:
            warnings.append("The logo file is missing. Run tools/import_old_site.py once to bring it over.")
        missing = []
        for path, value in _walk(content):
            leaf = path.rsplit(".", 1)[-1]
            if leaf in ("image", "photo", "src") and isinstance(value, str) and value.startswith("media/"):
                if not (ROOT / "content" / value).is_file():
                    missing.append((value, friendly(path, content)))
        for path, value in _walk(content):
            leaf = path.rsplit(".", 1)[-1]
            if leaf in ("url", "link", "buttonUrl", "button2Url", "imageLink") and isinstance(value, str) \
                    and value.startswith("media/") and not (ROOT / "content" / value).is_file():
                warnings.append(f"The file {value} (linked in {friendly(path, content)}) isn't here yet, so that "
                                "link is hidden on the website until it's added.")
        if len(missing) > 3:
            warnings.append(f"{len(missing)} pictures are missing (for example {missing[0][0]}). "
                            "On a new setup, run tools/import_old_site.py once.")
        else:
            warnings.extend(f"Missing picture {v} (used in {where})." for v, where in missing)

    return errors, sorted(set(warnings), key=warnings.index)
