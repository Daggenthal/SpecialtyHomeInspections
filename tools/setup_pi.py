#!/usr/bin/env python3
"""Set up (or repair) everything on the Raspberry Pi in one go.

    python3 tools/setup_pi.py            check every step, fix what's missing, then test it all
    python3 tools/setup_pi.py --check    only check, change nothing

Safe to run as often as you like. Every step first checks whether it's already done
and skips it if so. If a step fails, the steps that don't depend on it still run, and the
summary at the end says exactly what to do. Fix that one thing and run it again; nothing
gets redone or re-copied.

Steps that need you (konsoleH, Tailscale sign-in, the editor password) ask on screen.
Things only you can do at Hetzner or the registrar are in the README, "Setup checklist".
A log of every run is kept in data/setup.log.
"""
import argparse
import datetime as _dt
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sitekit import hetzner  # noqa: E402
from sitekit.paths import EDITOR_CONFIG  # noqa: E402

LOG = ROOT / "data" / "setup.log"
TS_NETS = ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]
UNITS = {  # file -> what to enable (None = started by its timer)
    "specialty-editor.service": "specialty-editor.service",
    "specialty-backup.service": None,
    "specialty-backup.timer": "specialty-backup.timer",
    "specialty-health.service": None,
    "specialty-health.timer": "specialty-health.timer",
}
CHECK_ONLY = False
OPTIONAL = {"notify"}   # nice to have; doesn't count as unfinished
TTY = sys.stdin.isatty()


# --------------------------------------------------------------------------- helpers

def log(text):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{_dt.datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")


def run(cmd, sudo=False, check=False, capture=True, timeout=600, input_text=None):
    if sudo and os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    log("$ " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout, input=input_text)
    if capture:
        log((r.stdout or "")[-2000:] + (r.stderr or "")[-2000:])
    if check and r.returncode != 0:
        raise RuntimeError(((r.stderr or r.stdout or "").strip().splitlines() or ["failed"])[-1])
    return r


def load_cfg():
    try:
        return json.loads(EDITOR_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cfg(cfg):
    EDITOR_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(EDITOR_CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, indent=2) + "\n")


def ask(prompt, default=""):
    if not TTY:
        return default
    v = input(f"   {prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return v or default


def yes(prompt, default=True):
    if not TTY:
        return default
    v = input(f"   {prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not v else v.startswith("y")


def has_systemd():
    return Path("/run/systemd/system").is_dir() and shutil.which("systemctl")


def ts_status():
    if not shutil.which("tailscale"):
        return None
    r = run(["tailscale", "status", "--json"])
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def ts_name():
    st = ts_status() or {}
    return ((st.get("Self") or {}).get("DNSName") or "").rstrip(".").lower()


def on_own_drive(path: Path):
    """True if path is on a different drive than / (so backups don't wear out the SD card)."""
    try:
        return os.stat(path).st_dev != os.stat("/").st_dev
    except OSError:
        return False


# --------------------------------------------------------------------------- steps
# Each step: (key, title, check() -> (ok, detail), fix() or None, needs=[keys], hint)

def c_python():
    v = sys.version_info
    return v >= (3, 11), f"Python {v.major}.{v.minor}"


def c_packages():
    missing = [t for t in ("rclone", "ssh-keygen", "ssh-keyscan", "curl") if not shutil.which(t)]
    return not missing, ("all there" if not missing else "missing: " + ", ".join(missing))


def f_packages():
    run(["apt-get", "update", "-q"], sudo=True, timeout=900)
    run(["apt-get", "install", "-y", "-q", "rclone", "openssh-client", "curl"], sudo=True, check=True, timeout=900)


def c_media():
    r = run([sys.executable, "tools/import_old_site.py", "--check"])
    last = [l for l in r.stdout.splitlines() if "verified" in l]
    return r.returncode == 0, (last[0].strip() if last else "not checked")


def f_media():
    r = run([sys.executable, "tools/import_old_site.py"], timeout=900)
    if r.returncode != 0:
        raise RuntimeError("couldn't download every original picture. If the old site is already gone, copy "
                           "content/media/ over from the Mac (or restore a backup) and run this again")


def c_tests():
    r = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], timeout=600)
    tail = (r.stderr or "").strip().splitlines()
    return r.returncode == 0, (tail[-1] if tail else "")


def c_tailscale():
    st = ts_status()
    if st is None:
        return False, "not installed"
    if st.get("BackendState") != "Running":
        return False, f"installed, state: {st.get('BackendState')} (needs signing in)"
    return True, f"running as {ts_name()}"


def f_tailscale():
    if not shutil.which("tailscale"):
        script = urllib.request.urlopen("https://tailscale.com/install.sh", timeout=60).read().decode()
        run(["sh", "-s"], sudo=True, check=True, input_text=script, timeout=900)
    print("   Tailscale will print a sign-in link. Open it, approve the Pi, and come back.")
    run(["tailscale", "up"], sudo=True, capture=False, timeout=900)


def c_password():
    return bool(load_cfg().get("password_hash")), "set" if load_cfg().get("password_hash") else "no editor password yet"


def f_password():
    if not TTY:
        raise RuntimeError("run this in a terminal so it can ask for the password")
    run([sys.executable, "editor/server.py", "password"], capture=False, check=True)


def c_editor_net():
    cfg = load_cfg()
    name = ts_name()
    probs = []
    if cfg.get("bind", "127.0.0.1") in ("127.0.0.1", "::1", "localhost"):
        probs.append("only listens on the Pi itself")
    if not set(TS_NETS) <= set(cfg.get("extra_networks") or []):
        probs.append("Tailscale addresses not allowed")
    if name and name not in (cfg.get("allowed_hosts") or []):
        probs.append(f"{name} not an allowed name")
    return not probs, ("home network + Tailscale" if not probs else "; ".join(probs))


def f_editor_net():
    cfg = load_cfg()
    cfg["bind"] = "0.0.0.0"
    cfg["extra_networks"] = sorted(set(cfg.get("extra_networks") or []) | set(TS_NETS))
    name = ts_name()
    if name:
        cfg["allowed_hosts"] = sorted(set(cfg.get("allowed_hosts") or []) | {name, name.split(".")[0]})
    save_cfg(cfg)


def c_hetzner():
    cfg = load_cfg()
    if not hetzner.configured(cfg):
        return False, "not set up (server name, user, key)"
    if not Path(hetzner.settings(cfg)["known_hosts"]).is_file():
        return False, "server fingerprint missing"
    ok, log_ = hetzner.check_connection(cfg, timeout=45)
    if not ok:
        return False, "login failed: " + (log_.strip().splitlines() or ["?"])[-1][-160:]
    if "hetzner" not in (cfg.get("deploy") or {}).get("targets", []):
        return False, "connected, but Publish doesn't upload to Hetzner yet"
    return True, f"logged in to {hetzner.settings(cfg)['host']}"


def f_hetzner():
    cfg = load_cfg()
    if hetzner.configured(cfg) and Path(hetzner.settings(cfg)["known_hosts"]).is_file():
        ok, _ = hetzner.check_connection(cfg, timeout=45)
        if ok:  # only the publish target was missing
            cfg.setdefault("deploy", {})
            cfg["deploy"]["targets"] = sorted(set(cfg["deploy"].get("targets", [])) | {"hetzner"})
            save_cfg(cfg)
            return
    if not TTY:
        raise RuntimeError("run this in a terminal; it needs the konsoleH details")
    run([sys.executable, "tools/hetzner_setup.py"], capture=False)


def uses_cloudflare(cfg=None):
    targets = ((cfg or load_cfg()).get("deploy") or {}).get("targets", [])
    return "cloudflare" in targets or "hetzner" not in targets


def node_major():
    node = shutil.which("node")
    if not node:
        return 0
    r = run([node, "--version"])
    try:
        return int((r.stdout or "v0").strip().lstrip("v").split(".")[0])
    except ValueError:
        return 0


def c_publish():
    """Cloudflare (the current setup) or Hetzner (the older plan), whichever Publish uses."""
    cfg = load_cfg()
    if not uses_cloudflare(cfg):
        return c_hetzner()
    major = node_major()
    if major < 22:
        return False, f"Node.js 22 or newer needed for Cloudflare uploads (found {major or 'none'})"
    if not (ROOT / "node_modules" / ".bin" / "wrangler").is_file():
        return False, "Cloudflare's upload tool isn't installed yet (npm ci)"
    from sitekit import cloudflare
    if not cloudflare.credentials_info()["ready"]:
        return False, "Cloudflare isn't connected yet"
    return True, "publishing to Cloudflare"


def f_publish():
    cfg = load_cfg()
    if not uses_cloudflare(cfg):
        return f_hetzner()
    if node_major() < 22:
        # NodeSource's official packages; Raspberry Pi OS's own nodejs is too old for wrangler
        script = ROOT / "data" / "nodesource_setup.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        run(["curl", "-fsSL", "https://deb.nodesource.com/setup_22.x", "-o", str(script)], check=True, timeout=120)
        run(["bash", str(script)], sudo=True, check=True, timeout=900)
        run(["apt-get", "install", "-y", "-q", "nodejs"], sudo=True, check=True, timeout=900)
    if not (ROOT / "node_modules" / ".bin" / "wrangler").is_file():
        run(["npm", "ci", "--no-audit", "--no-fund"], check=True, timeout=900)
    from sitekit import cloudflare
    if not cloudflare.credentials_info()["ready"]:
        raise RuntimeError("open the editor and press Publish to website; it asks for the two Cloudflare details")


def backup_dir():
    return Path((load_cfg().get("backup") or {}).get("local_dir") or "").expanduser()


def c_backup_dir():
    d = backup_dir()
    if not str(d) or str(d) == ".":
        return False, "no backup folder chosen"
    if not d.is_dir():
        return False, f"{d} doesn't exist (is the M.2 mounted?)"
    if not os.access(d, os.W_OK):
        return False, f"{d} isn't writable"
    if not on_own_drive(d):
        root = run(["findmnt", "-n", "-o", "SOURCE", "/"]).stdout.strip()
        if "mmcblk" in root:
            return False, f"{d} is on the SD card ({root}); put it on the M.2"
        return True, f"{d} (same drive as the system, {root or '?'}; Hetzner holds the off-site copy)"
    return True, str(d)


def f_backup_dir():
    mounts = []
    r = run(["findmnt", "-rn", "-o", "TARGET,SOURCE"])
    for line in r.stdout.splitlines():
        t, _, src = line.partition(" ")
        if t.startswith(("/mnt", "/media", "/srv", "/data")) and src.startswith("/dev/"):
            mounts.append(t)
    guess = str(backup_dir()) if str(backup_dir()) not in ("", ".") else \
        (f"{mounts[0]}/backups/specialty-site" if mounts else "")
    if mounts:
        print("   Drives found: " + ", ".join(mounts))
    d = ask("Folder for backups on the M.2", guess)
    if not d:
        raise RuntimeError("no M.2 drive mounted yet. Mount it (README, \"Backups\") and run this again")
    d = Path(d).expanduser()
    if not d.is_dir():
        try:
            d.mkdir(parents=True)
        except PermissionError:
            run(["mkdir", "-p", str(d)], sudo=True, check=True)
            run(["chown", "-R", f"{getpass.getuser()}:", str(d)], sudo=True, check=True)
    cfg = load_cfg()
    cfg["backup"] = dict(cfg.get("backup") or {}, local_dir=str(d))
    save_cfg(cfg)


def unit_text(name):
    user = getpass.getuser()
    text = (ROOT / "deploy" / name).read_text(encoding="utf-8")
    text = text.replace("/home/REPLACE_WITH_YOUR_USER/specialty-site", str(ROOT))
    text = text.replace("REPLACE_WITH_YOUR_USER", user)
    text = text.replace("/usr/bin/python3", sys.executable)
    return text


def c_services():
    if not has_systemd():
        return False, "systemd not available on this machine"
    stale = [n for n in UNITS if not Path(f"/etc/systemd/system/{n}").is_file()
             or Path(f"/etc/systemd/system/{n}").read_text(encoding="utf-8") != unit_text(n)]
    if stale:
        return False, "not installed or out of date: " + ", ".join(stale)
    inactive = [u for u in UNITS.values() if u and run(["systemctl", "is-active", u]).stdout.strip() != "active"]
    if inactive:
        return False, "not running: " + ", ".join(inactive)
    return True, "editor running, backup + health timers on"


def f_services():
    if not has_systemd():
        raise RuntimeError("this needs systemd (Raspberry Pi OS has it)")
    for n in UNITS:
        tmp = ROOT / "data" / f".{n}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(unit_text(n), encoding="utf-8")
        run(["install", "-m", "644", str(tmp), f"/etc/systemd/system/{n}"], sudo=True, check=True)
        tmp.unlink()
    run(["systemctl", "daemon-reload"], sudo=True, check=True)
    for u in filter(None, UNITS.values()):
        run(["systemctl", "enable", u], sudo=True, check=True)
        run(["systemctl", "restart", u], sudo=True, check=True)


def c_editor_up():
    port = int(load_cfg().get("port", 8787))
    for _ in range(10):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=3) as r:
                if r.status == 200:
                    name = ts_name()
                    return True, f"http://{name or 'localhost'}:{port}/"
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    return False, f"nothing answers on port {port} (journalctl -u specialty-editor)"


def c_notify():
    url = (load_cfg().get("notify") or {}).get("ntfy")
    return bool(url), (url.split("/")[2] + "/…" if url else "phone alerts not set up (optional, recommended)")


def f_notify():
    import secrets
    if not TTY or not yes("Set up phone alerts with ntfy (free, no account)?", True):
        raise RuntimeError("skipped; run again to set it up")
    topic = f"shi-{secrets.token_urlsafe(12).replace('_', '').replace('-', '').lower()}"
    url = ask("ntfy address", f"https://ntfy.sh/{topic}")
    cfg = load_cfg()
    cfg["notify"] = {"ntfy": url}
    save_cfg(cfg)
    print(f"   In the ntfy phone app, subscribe to: {url.rsplit('/', 1)[-1]}  (server {url.rsplit('/', 1)[0]})")
    run([sys.executable, "tools/healthcheck.py", "--test-notify"])
    yes("Did the test notification arrive?", True)


def c_backup_run():
    mark = backup_dir() / ".last-ok"
    if not mark.is_file():
        return False, "no backup yet"
    return True, f"last good backup {_dt.datetime.fromtimestamp(mark.stat().st_mtime):%Y-%m-%d %H:%M}"


def f_backup_run():
    r = run([sys.executable, "tools/backup.py"], timeout=1800)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr).strip().splitlines()[-1])


def c_kit():
    z = ROOT / "dist-windows" / "Website-Editor-Setup.zip"
    name = ts_name()
    if not z.is_file():
        return False, "not made yet"
    import zipfile
    body = zipfile.ZipFile(z).read("Website Editor Setup/install.ps1").decode("utf-8", "replace")
    return (name in body), (f"dist-windows/{z.name}" if name in body else "made for a different address")


def f_kit():
    name = ts_name()
    port = int(load_cfg().get("port", 8787))
    run([sys.executable, "tools/make_windows_kit.py", f"http://{name}:{port}/"], check=True)


def c_health():
    r = run([sys.executable, "tools/healthcheck.py"], timeout=300)
    print("\n".join("      " + l for l in r.stdout.splitlines()))
    fails = [l for l in r.stdout.splitlines() if l.startswith("❌")]
    return not fails, ("everything passed" if not fails else f"{len(fails)} problem(s), see above")


STEPS = [
    ("python", "Python 3.11 or newer", c_python, None, [], "Update Raspberry Pi OS (sudo apt full-upgrade)."),
    ("packages", "rclone, ssh tools, curl", c_packages, f_packages, [], "sudo apt install rclone openssh-client curl"),
    ("media", "Original pictures, byte-for-byte", c_media, f_media, ["python"],
     "Copy content/media/ from the Mac, or restore a backup."),
    ("tests", "Tests pass", c_tests, None, ["media"], "Run python3 -m unittest discover -s tests -v to see which."),
    ("tailscale", "Tailscale connected", c_tailscale, f_tailscale, [], "sudo tailscale up, then open the link it prints."),
    ("password", "Editor password", c_password, f_password, ["python"], "python3 editor/server.py password"),
    ("editornet", "Editor reachable at home + Tailscale only", c_editor_net, f_editor_net, ["tailscale", "password"],
     "Run this again after Tailscale is connected."),
    ("publish", "Publishing (Cloudflare)", c_publish, f_publish, ["packages"],
     "Open the editor > Website setup. It walks through Cloudflare, the domain and the email."),
    ("backupdir", "Backup folder on the M.2", c_backup_dir, f_backup_dir, [], "Mount the M.2 (README, \"Backups\")."),
    ("services", "Editor + nightly backup + daily health check start on boot", c_services, f_services,
     ["editornet", "tests"], "sudo systemctl status specialty-editor"),
    ("editorup", "Editor answers", c_editor_up, None, ["services"], "journalctl -u specialty-editor -n 50"),
    ("notify", "Phone alerts (ntfy)", c_notify, f_notify, [], "python3 tools/healthcheck.py --test-notify"),
    ("backup", "First backup", c_backup_run, f_backup_run, ["backupdir"],
     "python3 tools/backup.py shows the error."),
    ("kit", "Dad's Windows icon installer", c_kit, f_kit, ["tailscale", "editorup"],
     "python3 tools/make_windows_kit.py http://<pi's tailscale name>:8787/"),
    ("health", "Live site health check", c_health, None, ["publish"],
     "Fix what it lists; the editor's Website setup covers Cloudflare, the domain and the email."),
]


def main():
    global CHECK_ONLY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only check, change nothing")
    ap.add_argument("--only", metavar="STEP", help="run one step: " + ", ".join(k for k, *_ in STEPS))
    a = ap.parse_args()
    CHECK_ONLY = a.check
    os.chdir(ROOT)
    log(f"=== setup_pi.py {'--check' if a.check else ''} as {getpass.getuser()}")
    print(f"\nSpecialty Home Inspections: Pi setup {'(check only)' if a.check else ''}\n")

    status = {}
    for key, title, check, fix, needs, hint in STEPS:
        if a.only and key != a.only:
            continue
        blocked = [n for n in needs if status.get(n, ("ok",))[0] not in ("ok",)]
        if blocked:
            status[key] = ("wait", f"waiting on: {', '.join(blocked)}", hint)
            print(f"⏸  {title}: waiting on {', '.join(blocked)}")
            continue
        print(f"…  {title}", flush=True)
        try:
            ok, detail = check()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"check failed: {e}"
        if not ok and fix and not CHECK_ONLY:
            print(f"   fixing: {detail}", flush=True)
            try:
                fix()
                ok, detail = check()
            except KeyboardInterrupt:
                print()
                ok, detail = False, "stopped by you"
            except Exception as e:  # noqa: BLE001
                ok, detail = False, str(e)
        status[key] = ("ok" if ok else "fail", detail, hint)
        print(f"{'✅' if ok else '❌'} {title}: {detail}")
        log(f"{key}: {'ok' if ok else 'FAIL'} {detail}")

    print("\nSummary\n-------")
    todo = 0
    for key, title, *_ in STEPS:
        if key not in status:
            continue
        st, detail, hint = status[key]
        if st == "fail" and key in OPTIONAL:
            print(f"⚠️  {title} (optional)\n     {detail}\n     Next: {hint}")
            continue
        mark = {"ok": "✅", "fail": "❌", "wait": "⏸ "}[st]
        print(f"{mark} {title}")
        if st != "ok":
            todo += 1
            print(f"     {detail}\n     Next: {hint}")
    print("\nAll done. Nothing left to do." if not todo else
          f"\n{todo} step(s) left. Fix the first ❌ and run  python3 tools/setup_pi.py  again; finished steps are skipped.")
    print(f"Log: {LOG.relative_to(ROOT)}")
    sys.exit(0 if not todo else 1)


if __name__ == "__main__":
    main()
