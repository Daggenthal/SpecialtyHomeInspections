#!/usr/bin/env python3
"""Look for things that shouldn't go to GitHub, before you commit.

    python3 tools/privacy_check.py

Checks every file git would commit (or, outside a git repo, every file not covered by
.gitignore's main folders) for:
  - private keys, password hashes, API tokens
  - home-folder paths (/Users/name, /home/name, C:\\Users\\name) that reveal a user name
  - email addresses that aren't on the allowed list below
  - IP addresses that aren't examples or private ranges
  - any word listed in .privacy-words (one per line; that file is git-ignored, so the
    words you're hiding are never committed themselves)

Exits 1 if anything is found, so it can run as a git pre-commit hook:
    printf '#!/bin/sh\\nexec python3 tools/privacy_check.py\\n' > .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
"""
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_EMAILS = {
    "specialtyhomeinspections@gmail.com", "john@specialtyhomeinspections.biz",
    "112846802+daggenthal@users.noreply.github.com", "noreply@anthropic.com", "git@github.com",
}
ALLOWED_IPS = {"148.72.8.248"}  # the old GoDaddy server, documented in the README
SKIP_DIRS = {".git", "dist", "dist.tmp", "dist.old", "published", "published.previous", "published.incoming",
             "data", "__pycache__", "dist-windows", "history", ".trash", "keys"}
SKIP_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".woff2", ".pdf", ".sqlite", ".gz", ".zip"}

PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("password hash", re.compile(r"pbkdf2_sha256\$\d+\$")),
    ("API token", re.compile(r"(?i)(api[_-]?token|secret|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{20,}")),
    ("Google key", re.compile(r"\"private_key_id\"\s*:")),
    ("home folder", re.compile(r"(/Users/(?!Shared\b)[A-Za-z0-9._-]+|/home/(?!REPLACE_WITH_YOUR_USER\b|claude\b)[a-z0-9._-]+|"
                               r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+)")),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PRIVATE_NAMES = {"config.json", "secrets.env", "google-service-account.json", ".draft.json", ".published.json",
                 ".privacy-words", ".DS_Store"}
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def files():
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=ROOT, capture_output=True, check=True).stdout
        return [ROOT / p for p in out.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        found = []
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT).parts
            if not p.is_file() or set(rel[:-1]) & SKIP_DIRS or rel[0].startswith("before-restore"):
                continue
            if p.name in PRIVATE_NAMES:
                continue
            found.append(p)
        return found


def main():
    words_file = ROOT / ".privacy-words"
    words = [w.strip() for w in words_file.read_text(encoding="utf-8").splitlines()
             if w.strip() and not w.startswith("#")] if words_file.is_file() else []
    problems = []
    for f in files():
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith("editor/keys/") or rel in ("editor/config.json", "editor/secrets.env"):
            problems.append((rel, 0, "private file is about to be committed"))
            continue
        if f.suffix.lower() in SKIP_SUFFIX or not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if rel == "tools/privacy_check.py":
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for label, rx in PATTERNS:
                if rx.search(line):
                    problems.append((rel, n, label))
            fixture = rel.startswith("tests/")   # made-up test addresses and IPs
            for m in ([] if fixture else EMAIL.findall(line)):
                if m.lower() not in ALLOWED_EMAILS and not m.lower().endswith(("@example.com", "@users.noreply.github.com")):
                    problems.append((rel, n, f"email {m}"))
            for m in ([] if fixture else IPV4.findall(line)):
                try:
                    ip = ipaddress.ip_address(m)
                except ValueError:
                    continue
                if not (ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_reserved
                        or ip in ipaddress.ip_network("100.64.0.0/10") or m in ALLOWED_IPS):
                    problems.append((rel, n, f"public IP {m}"))
            low = line.lower()
            for w in words:
                if w.lower() in low:
                    problems.append((rel, n, "a word from .privacy-words"))
    if problems:
        print("Check these before committing:")
        for rel, n, what in problems:
            print(f"  {rel}:{n}  {what}")
        sys.exit(1)
    print(f"Clean: nothing private found in {len(files())} files.")


if __name__ == "__main__":
    main()
