"""
Load/save ``deploy.json`` -- the connection details and the two file mappings.

The file lives next to the exe (or at the project root from a checkout) and is
git-ignored, because it holds a host, a username and possibly a password. A
committed ``deploy/deploy.example.json`` documents the same shape.
"""
import copy
import json
import os

from atlas_tools.runner import app_root

FILENAME = "deploy.json"

DEFAULTS = {
    # Blank = use the .env sitting next to the app.
    "env_file": "",
    "connection": {
        "host": "",
        "port": 22,
        "user": "root",
        # "key" or "password"
        "auth": "key",
        "key_path": "~/.ssh/id_ed25519",
        "password": "",
    },
    "options": {
        # Skip files whose size and mtime already match the server.
        "skip_unchanged": True,
        # Upload to a temp name and rename into place, so a half-written file is
        # never visible to a running process.
        "atomic": True,
    },
    "targets": {
        "python": {
            "label": "Python scraper",
            "enabled": True,
            "local": ".",
            "remote": "/opt/atlas-scraper",
            "include": [
                "api.py",
                "backup.py",
                "f95_refresh_worker.py",
                "requirements.txt",
                ".env.example",
                "scraper/**/*.py",
                "tools/**/*.py",
            ],
            "exclude": [
                "**/__pycache__/**",
                "**/*.pyc",
                "scraper/fixtures/**",
                "atlas_tools/**",
                "build/**",
            ],
            "env_files": [".env"],
            "post_commands": [],
        },
        "node": {
            "label": "Node admin server",
            "enabled": True,
            "local": "server/admin",
            "remote": "/opt/atlas/server/admin",
            "include": [
                "package.json",
                "sql/**/*.sql",
                "server/package.json",
                "server/src/**",
                "web/package.json",
                "web/index.html",
                "web/vite.config.js",
                "web/src/**",
                "web/public/**",
            ],
            "exclude": [
                "**/node_modules/**",
                "server/public/assets/**",
                "**/.env",
            ],
            "env_files": ["server/.env"],
            # Run in order after a successful upload. Comment out what you
            # don't want; `npm run build` regenerates server/public from web/src
            # ON THE SERVER, which is why the built assets aren't uploaded.
            "post_commands": [
                "cd /opt/atlas/server/admin && npm install",
                "cd /opt/atlas/server/admin && npm run build",
                "pm2 restart atlas",
            ],
        },
    },
}


def path():
    return os.path.join(app_root(), FILENAME)


def _merge(base, override):
    """Recursive dict merge so a partial deploy.json still gets new defaults."""
    out = copy.deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def load():
    p = path()
    if not os.path.exists(p):
        return copy.deepcopy(DEFAULTS)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return _merge(DEFAULTS, json.load(f))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"could not read {p}: {exc}") from exc


def save(data):
    p = path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, p)
    return p


def resolved_env_file(data):
    """Absolute path of the .env the tasks should load, or None for the default."""
    raw = (data.get("env_file") or "").strip()
    if not raw:
        return None
    raw = os.path.expanduser(raw)
    if not os.path.isabs(raw):
        raw = os.path.join(app_root(), raw)
    return os.path.abspath(raw)
