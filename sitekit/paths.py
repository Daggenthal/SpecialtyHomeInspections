from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"
CONTENT_FILE = CONTENT_DIR / "site.json"
MEDIA_DIR = CONTENT_DIR / "media"
HISTORY_DIR = CONTENT_DIR / "history"
SITE_ASSETS = ROOT / "site" / "assets"
DIST = ROOT / "dist"
MANIFEST = ROOT / "tools" / "original_manifest.json"
EDITOR_DIR = ROOT / "editor"
EDITOR_CONFIG = EDITOR_DIR / "config.json"
EDITOR_SECRETS = EDITOR_DIR / "secrets.env"
DEPLOY_DIR = ROOT / "deploy"
