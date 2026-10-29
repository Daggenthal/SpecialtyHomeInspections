"""Publish the built site.

Targets (set in editor/config.json -> "deploy.targets"):
  folder      copy dist/ into a folder a local web server serves (the Pi + Cloudflare Tunnel setup)
  cloudflare  upload dist/ to Cloudflare with wrangler (Workers static assets)
  hetzner     upload dist/ to Hetzner Webhosting over SFTP with rclone (see sitekit/hetzner.py)
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

from .paths import DEPLOY_DIR, DIST, EDITOR_SECRETS, ROOT


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


def _redact(text, secrets):
    for v in secrets.values():
        if v and len(v) > 6:
            text = text.replace(v, "••••")
    return re.sub(r"(?i)(api[_-]?token[\"'=: ]+)\S+", r"\1••••", text)


def deploy_folder(dest, dist=DIST):
    """Swap the new site into place in one step so visitors never see half a site."""
    dest = Path(dest).expanduser()
    if not dest.parent.is_dir():
        return False, f"The folder {dest.parent} doesn't exist."
    tmp = dest.with_name(dest.name + ".incoming")
    old = dest.with_name(dest.name + ".previous")
    try:
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(dist, tmp)
        if old.exists():
            shutil.rmtree(old)
        if dest.exists():
            dest.rename(old)
        tmp.rename(dest)
    except OSError as e:
        return False, f"Couldn't copy the site into {dest}: {e}"
    return True, f"Copied to {dest} (the previous version is kept in {old.name})."


def deploy_cloudflare(dist=DIST, timeout=300):
    secrets = read_secrets()
    token, account = secrets.get("CLOUDFLARE_API_TOKEN"), secrets.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        return False, "Cloudflare isn't set up yet (missing API token or account ID in editor/secrets.env)."
    npx = shutil.which("npx")
    if not npx:
        return False, "Node.js isn't installed on this computer, so Cloudflare publishing can't run."
    if not (Path(dist) / "index.html").is_file():
        return False, "There's no built website to upload."
    env = dict(os.environ, CLOUDFLARE_API_TOKEN=token, CLOUDFLARE_ACCOUNT_ID=account,
               WRANGLER_SEND_METRICS="false", CI="1", NO_COLOR="1")
    cmd = [npx, "--yes", "wrangler@4", "deploy", "--config", str(DEPLOY_DIR / "wrangler.jsonc")]
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Cloudflare took too long to answer. Check the internet connection and try again."
    log = _redact((r.stdout or "") + "\n" + (r.stderr or ""), secrets).strip()
    tail = "\n".join(log.splitlines()[-25:])
    if r.returncode != 0:
        return False, "Cloudflare upload failed:\n" + tail
    return True, "Uploaded to Cloudflare.\n" + tail


def publish(targets, folder=None, cfg=None):
    results = []
    for t in targets:
        if t == "folder":
            if not folder:
                results.append(("folder", False, "No folder is configured."))
                continue
            ok, msg = deploy_folder(folder)
        elif t == "cloudflare":
            ok, msg = deploy_cloudflare()
        elif t == "hetzner":
            from .hetzner import deploy_sftp
            ok, msg = deploy_sftp(cfg or {})
        else:
            ok, msg = False, f"Unknown publish target “{t}”."
        results.append((t, ok, msg))
    return results
