#!/usr/bin/env python3
"""Daily backups of everything that can't be rebuilt.

    python3 tools/backup.py             make today's backup, copy it to Hetzner, remove old ones
    python3 tools/backup.py --list      show the backups on this Pi and on Hetzner
    python3 tools/backup.py --restore FILE   put a backup back (stop the editor first)

Two archives per run:
  specialty-YYYY-MM-DD-full.tar.gz   on the Pi only (M.2). Everything, including the editor's
                                     password hash, the Hetzner key and other private settings.
  specialty-YYYY-MM-DD.tar.gz        on the Pi AND on Hetzner (in ~/backups, outside public_html).
                                     The site's content, pictures, edit history and visit counts.
                                     No passwords or keys ever leave the Pi.

The site itself (dist/) isn't backed up: it's rebuilt from the content in seconds.
If nothing changed since the last backup, no new one is made.

Settings in editor/config.json (all optional):
  "backup": {"local_dir": "/mnt/m2/backups/specialty-site", "remote_dir": "backups",
             "keep_daily": 30, "keep_monthly": 24, "offsite": true}
"""
import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sitekit import hetzner  # noqa: E402
from sitekit.paths import EDITOR_CONFIG  # noqa: E402

DEFAULTS = {"local_dir": str(Path.home() / "backups" / "specialty-site"), "remote_dir": "backups",
            "keep_daily": 30, "keep_monthly": 24, "offsite": True}
SITE_PARTS = ["content/site.json", "content/.published.json", "content/media", "content/history",
              "data/stats.sqlite", "data/remote-hits.json"]
PRIVATE_PARTS = ["editor/config.json", "editor/secrets.env", "editor/keys", "editor/google-service-account.json"]
NAME = re.compile(r"^specialty-(\d{4}-\d{2}-\d{2})(-full)?\.tar\.gz$")


def load_cfg():
    try:
        return json.loads(EDITOR_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def settings(cfg):
    s = dict(DEFAULTS)
    s.update((cfg.get("backup") or {}))
    return s


def _files(parts):
    for part in parts:
        p = ROOT / part
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.name != ".DS_Store" and "__pycache__" not in f.parts:
                    yield f


def fingerprint(parts):
    h = hashlib.sha256()
    for f in _files(parts):
        st = f.stat()
        h.update(f"{f.relative_to(ROOT).as_posix()}|{st.st_size}|{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def make_archive(dest: Path, parts):
    """Write a .tar.gz of the parts. The stats database is copied with SQLite's own backup
    so a visit being saved at that moment can't leave a broken copy."""
    tmp = dest.with_suffix(".partial")
    with tempfile.TemporaryDirectory() as td, tarfile.open(tmp, "w:gz") as tar:
        for f in _files(parts):
            rel = f.relative_to(ROOT).as_posix()
            if f.suffix == ".sqlite":
                snap = Path(td) / f.name
                src, out = sqlite3.connect(f), sqlite3.connect(snap)
                with out:
                    src.backup(out)
                src.close()
                out.close()
                tar.add(snap, arcname=rel)
            else:
                tar.add(f, arcname=rel)
    tmp.replace(dest)
    dest.chmod(0o600)
    return dest


def to_keep(names, keep_daily, keep_monthly):
    """Newest keep_daily backups, plus the first backup of each of the last keep_monthly months."""
    dated = sorted({NAME.match(n).group(1) for n in names if NAME.match(n)}, reverse=True)
    keep = set(dated[:keep_daily])
    months = {}
    for d in sorted(dated):
        months.setdefault(d[:7], d)
    keep.update(sorted(months.values(), reverse=True)[:keep_monthly])
    return keep


def prune_local(folder: Path, s):
    names = [p.name for p in folder.glob("specialty-*.tar.gz")]
    keep = to_keep(names, int(s["keep_daily"]), int(s["keep_monthly"]))
    gone = [n for n in names if NAME.match(n) and NAME.match(n).group(1) not in keep]
    for n in gone:
        (folder / n).unlink(missing_ok=True)
    return gone


def remote_list(cfg, s):
    hz = hetzner.settings(cfg)
    code, log = hetzner._run(hz, ["lsf", f"hetzner:{s['remote_dir'].strip('/')}", "--files-only"], 120)
    return [l.strip() for l in log.splitlines() if NAME.match(l.strip())] if code == 0 else []


def offsite(cfg, s, archive: Path):
    hz = hetzner.settings(cfg)
    remote = f"hetzner:{s['remote_dir'].strip('/')}"
    code, log = hetzner._run(hz, ["copyto", str(archive), f"{remote}/{archive.name}"], 900)
    if code != 0:
        return False, log
    names = remote_list(cfg, s)
    keep = to_keep(names, int(s["keep_daily"]), int(s["keep_monthly"]))
    for n in names:
        if NAME.match(n).group(1) not in keep:
            hetzner._run(hz, ["deletefile", f"{remote}/{n}"], 120)
    return True, ""


def cmd_backup(cfg, s):
    folder = Path(s["local_dir"]).expanduser()
    if not folder.parent.is_dir():
        sys.exit(f"Backup folder {folder} can't be made: {folder.parent} doesn't exist. Is the M.2 drive mounted?")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = folder / ".last-fingerprint"
    fp = fingerprint(SITE_PARTS + PRIVATE_PARTS)
    if stamp.is_file() and stamp.read_text().strip() == fp:
        print("Nothing changed since the last backup.")
        (folder / ".last-ok").write_text(_dt.datetime.now().isoformat(timespec="seconds"))
        return 0
    day = _dt.date.today().isoformat()
    site = make_archive(folder / f"specialty-{day}.tar.gz", SITE_PARTS)
    full = make_archive(folder / f"specialty-{day}-full.tar.gz", SITE_PARTS + PRIVATE_PARTS)
    print(f"Saved {full.name} ({full.stat().st_size // 1024} KB) and {site.name} in {folder}")
    rc = 0
    if s.get("offsite") and hetzner.configured(cfg):
        ok, log = offsite(cfg, s, site)
        print("Copied to Hetzner." if ok else "Couldn't copy to Hetzner (the Pi copy is fine):\n" + log[-800:])
        rc = 0 if ok else 2
    elif s.get("offsite"):
        print("Hetzner isn't set up yet, so this backup is on the Pi only.")
    gone = prune_local(folder, s)
    if gone:
        print(f"Removed {len(gone)} old backup file(s).")
    if rc == 0:  # if Hetzner failed, try again tomorrow even if nothing changes
        stamp.write_text(fp)
        (folder / ".last-ok").write_text(_dt.datetime.now().isoformat(timespec="seconds"))  # read by healthcheck.py
    return rc


def cmd_list(cfg, s):
    folder = Path(s["local_dir"]).expanduser()
    print(f"On this Pi ({folder}):")
    for p in sorted(folder.glob("specialty-*.tar.gz")):
        print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    if hetzner.configured(cfg):
        print(f"On Hetzner (~/{s['remote_dir']}):")
        for n in sorted(remote_list(cfg, s)):
            print("  " + n)


def safe_members(tar):
    for m in tar.getmembers():
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
            raise SystemExit(f"Refusing to restore: unexpected entry {m.name}")
        if not (m.name.startswith(("content/", "data/", "editor/"))):
            raise SystemExit(f"Refusing to restore: unexpected entry {m.name}")
        yield m


def cmd_restore(path):
    src = Path(path).expanduser()
    if not src.is_file():
        sys.exit(f"No such file: {src}")
    keep = ROOT / f"before-restore-{_dt.datetime.now():%Y%m%d-%H%M%S}"
    with tarfile.open(src, "r:gz") as tar:
        members = list(safe_members(tar))
        tops = sorted({"/".join(Path(m.name).parts[:2]) for m in members if len(Path(m.name).parts) >= 2})
        for t in tops:
            cur = ROOT / t
            if cur.exists():
                (keep / t).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cur), str(keep / t))
        tar.extractall(ROOT, members=members, filter="data") if sys.version_info >= (3, 12) else \
            tar.extractall(ROOT, members=members)
    print(f"Restored {src.name}. What was there before is in {keep.name}/ (delete it once you're happy).")
    print("Start the editor again, check the preview, then press Publish.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--restore", metavar="FILE")
    a = ap.parse_args()
    cfg = load_cfg()
    s = settings(cfg)
    if a.restore:
        return cmd_restore(a.restore)
    if a.list:
        return cmd_list(cfg, s)
    sys.exit(cmd_backup(cfg, s))


if __name__ == "__main__":
    main()
