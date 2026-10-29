#!/usr/bin/env python3
"""One-time setup for publishing to Hetzner Webhosting over SFTP.

    python3 tools/hetzner_setup.py          (ed25519 key)
    python3 tools/hetzner_setup.py --rsa    (RSA 4096 key, if konsoleH refuses the ed25519 one)
    python3 tools/hetzner_setup.py --test   (only check the connection)

What it does:
  1. asks for the SFTP server name and the main FTP user (both shown in konsoleH)
  2. makes a key pair in editor/keys/ (the private key never leaves this computer)
  3. prints the public key in the RFC4716 format konsoleH asks for, for you to paste in
  4. saves the server's fingerprint, so uploads refuse an impostor server
  5. tests the connection and turns on the "hetzner" publish target
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sitekit import hetzner  # noqa: E402
from sitekit.paths import EDITOR_CONFIG  # noqa: E402


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
    v = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return v or default


def need(tool):
    exe = shutil.which(tool)
    if not exe:
        sys.exit(f"'{tool}' isn't installed. See the README section \"Hetzner\" for how to install it.")
    return exe


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rsa", action="store_true", help="make an RSA 4096 key instead of ed25519")
    ap.add_argument("--test", action="store_true", help="only test the saved settings")
    a = ap.parse_args()

    cfg = load_cfg()
    cfg.setdefault("deploy", {})
    saved = dict(hetzner.DEFAULTS, **(cfg["deploy"].get("hetzner") or {}))
    hz = dict(saved)

    if a.test:
        ok, log = hetzner.check_connection(cfg)
        print(("Connected. The server's top folder holds:\n" if ok else "Couldn't connect:\n") + log)
        sys.exit(0 if ok else 1)

    print("\nHetzner publishing setup\n------------------------")
    print("konsoleH > your domain > Access details > FTP shows the server name and the main FTP user.\n")
    hz["host"] = ask("SFTP server name (e.g. www123.your-server.de)", hz["host"])
    hz["user"] = ask("Main FTP user name", hz["user"])
    hz["port"] = int(ask("SFTP port", str(hz["port"] or 22)))
    hz["remote_dir"] = ask("Folder the website lives in", hz["remote_dir"])

    paths = hetzner.settings({"deploy": {"hetzner": hz}})
    key = Path(paths["key_file"])
    key.parent.mkdir(parents=True, exist_ok=True)
    keygen = need("ssh-keygen")
    if not key.is_file():
        kind = ["-t", "rsa", "-b", "4096"] if a.rsa else ["-t", "ed25519"]
        subprocess.run([keygen, *kind, "-N", "", "-C", "website-editor", "-f", str(key)], check=True,
                       stdout=subprocess.DEVNULL)
        print(f"\nMade a new key: {key}  (private, stays on this computer)")
    else:
        print(f"\nUsing the existing key: {key}")
    rfc = subprocess.run([keygen, "-e", "-f", str(key) + ".pub"], check=True, capture_output=True, text=True).stdout
    (key.parent / (key.name + ".rfc4716.pub")).write_text(rfc, encoding="utf-8")
    print("\nPaste ALL of the following into konsoleH > Access details > FTP > SSH keys (the main FTP user):\n")
    print(rfc)

    scan = need("ssh-keyscan")
    r = subprocess.run([scan, "-p", str(hz["port"]), "-T", "15", hz["host"]], capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l and not l.startswith("#")]
    if not lines:
        sys.exit(f"Couldn't reach {hz['host']} on port {hz['port']}. Check the name and try again.")
    kh = Path(paths["known_hosts"])
    kh.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fp = subprocess.run([keygen, "-lf", str(kh)], capture_output=True, text=True).stdout.strip()
    print("Saved the server's fingerprint (uploads will refuse any other server):\n" + fp + "\n")

    cfg["deploy"]["hetzner"] = hz
    targets = [t for t in cfg["deploy"].get("targets", []) if t != "hetzner"]
    cfg["deploy"]["targets"] = targets + ["hetzner"]
    save_cfg(cfg)

    input("After pasting the key into konsoleH and saving it there, press Enter to test... ")
    ok, log = hetzner.check_connection(cfg)
    if not ok:
        print("Couldn't log in yet:\n" + log + "\n\nIf konsoleH rejected the key, run this again with --rsa."
              "\nTest again later with:  python3 tools/hetzner_setup.py --test")
        sys.exit(1)
    folders = {l.strip("/") for l in log.splitlines()}
    print("Connected.")
    if hz["remote_dir"].strip("/").split("/")[0] not in folders:
        print(f"Note: there's no '{hz['remote_dir']}' folder at the top. Folders found: {', '.join(sorted(folders))}")
    print("\nThe editor's Publish button now uploads to Hetzner. Restart the editor to pick this up.")
    if "folder" in targets:
        print("It also still copies to the local folder; remove \"folder\" from deploy.targets in "
              "editor/config.json if you no longer want that.")


if __name__ == "__main__":
    main()
