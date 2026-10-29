"""Publish the built site.

Targets (set in editor/config.json -> "deploy.targets"):
  folder      copy dist/ into a folder a local web server serves (the Pi + Cloudflare Tunnel setup)
  cloudflare  upload dist/ to Cloudflare with wrangler (Workers static assets). Attaches the real
              domain on its own once the domain and email forwarding are on Cloudflare
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


def _wrangler_cmd():
    """The project's own wrangler (npm ci) if it's there, otherwise npx fetches wrangler 4."""
    local = ROOT / "node_modules" / ".bin" / "wrangler"
    if local.is_file():
        return [str(local)], None
    npx = shutil.which("npx")
    if not npx:
        return None, "Node.js isn't installed on this computer, so Cloudflare publishing can't run (see README, \"Node.js on the Pi\")."
    return [npx, "--yes", "wrangler@4"], None


def _node_too_old():
    node = shutil.which("node")
    if not node:
        return "Node.js isn't installed on this computer (see README, \"Node.js on the Pi\")."
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        if int(out.lstrip("v").split(".")[0]) < 22:
            return f"Node.js {out} is too old for Cloudflare's upload tool, it needs 22 or newer (see README, \"Node.js on the Pi\")."
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def _worker_name():
    text = (DEPLOY_DIR / "wrangler.jsonc").read_text(encoding="utf-8")
    m = re.search(r'"name"\s*:\s*"([^"]+)"', text)
    return m.group(1) if m else "specialty-home-inspections"


WWW_WORKER = "specialty-home-inspections-www"


def deploy_cloudflare(dist=DIST, timeout=300):
    from . import cloudflare as cf

    secrets = read_secrets()
    token, account = secrets.get("CLOUDFLARE_API_TOKEN"), secrets.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        return False, "Cloudflare isn't connected yet. Press Publish to website and fill in the two boxes."
    problem = _node_too_old()
    if problem:
        return False, problem
    cmd, problem = _wrangler_cmd()
    if problem:
        return False, problem
    if not (Path(dist) / "index.html").is_file():
        return False, "There's no built website to upload."

    # Put the site on the real address only when it's safe: the domain is on Cloudflare,
    # and email forwarding is on, so John@ keeps working when the old website records go.
    notes = []
    domain = cf.site_domain()
    attach = []
    if domain:
        ds = cf.domain_status(domain)
        if ds["onCloudflare"] and ds["emailRouting"]:
            # the site takes the bare address; www goes to a tiny redirect Worker (deploy/www-redirect)
            if (cf.clear_old_records(domain, [domain], token, account, _worker_name(), notes.append)
                    and cf.clear_old_records(domain, ["www." + domain], token, account, WWW_WORKER, notes.append)):
                attach = [domain]
            else:
                notes.append("Kept the website on its temporary address for now.")
        elif ds["onCloudflare"] is None:
            notes.append("Couldn't check the domain, so the website stays where it was.")
        elif not ds["onCloudflare"]:
            notes.append(f"{domain} isn't on Cloudflare yet, so the website is on its temporary address (Website setup, step 2).")
        else:
            notes.append(f"Email forwarding isn't on yet, so {domain} keeps the old website for now and John@ keeps working (Website setup, step 3).")

    env = dict(os.environ, CLOUDFLARE_API_TOKEN=token, CLOUDFLARE_ACCOUNT_ID=account,
               WRANGLER_SEND_METRICS="false", CI="1", NO_COLOR="1", FORCE_COLOR="0")
    cmd = cmd + ["deploy", "--config", str(DEPLOY_DIR / "wrangler.jsonc")]
    for host in attach:
        cmd += ["--domain", host]
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Cloudflare took too long to answer. Check the internet connection and try again."
    log = _redact((r.stdout or "") + "\n" + (r.stderr or ""), secrets)
    log = re.sub(r"\x1b\[[0-9;]*m", "", log).strip()   # wrangler colors even with NO_COLOR
    tail = "\n".join(log.splitlines()[-25:])
    if r.returncode != 0:
        hint = ""
        low = log.lower()
        if "authentication" in low or "10000" in low:
            hint = "Cloudflare rejected the saved token. Use Website setup > Change to paste a new one.\n"
        elif "already" in low and "dns" in low:
            hint = "An old DNS record is still using the address. Delete it in Cloudflare > DNS, then publish again.\n"
        return False, hint + "Cloudflare upload failed:\n" + tail
    where = [f"https://{h}" for h in attach] or re.findall(r"https://[\w.-]+\.workers\.dev", log)[:1]
    head = "Uploaded to Cloudflare." + (f" Live at {where[0]}" if where else "")
    if attach:
        www = ["--config", str(DEPLOY_DIR / "www-redirect" / "wrangler.jsonc"),
               "--domain", "www." + domain, "--var", f"APEX:{domain}"]
        try:
            w = subprocess.run(cmd[:cmd.index("deploy") + 1] + www, cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=timeout)
            if w.returncode == 0:
                notes.append(f"www.{domain} sends visitors to {domain}.")
            else:
                notes.append(f"The website is live, but the www. redirect didn't upload. It'll be retried on the next publish.")
        except subprocess.TimeoutExpired:
            notes.append("The website is live, but the www. redirect timed out. It'll be retried on the next publish.")
    return True, "\n".join([head] + notes + ["", tail])


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
