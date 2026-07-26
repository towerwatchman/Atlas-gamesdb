"""
Load/save ``deploy.json`` -- the connection details and the two file mappings.

Values come from three layers, later ones winning:

    1. DEFAULTS below
    2. deploy.json  (next to the exe / at the project root, git-ignored)
    3. .env         (and real environment variables, which beat the .env file)

Putting the connection details in ``.env`` is the recommended setup: it's the
file you already keep per-machine and out of git, and it means the SFTP password
never gets written into deploy.json. Anything set there is treated as read-only
by the Settings tab, which shows the effective value and says where it came
from -- editing a field that .env is going to override would silently do
nothing, which is exactly the trap worth closing.
"""
import copy
import json
import os

from atlas_tools.runner import app_root

FILENAME = "deploy.json"

# .env / environment variable  ->  path within the settings dict.
# Names are chosen to say what they are rather than to match the JSON keys.
ENV_MAP = {
    "SFTP_HOST":        ("connection", "host"),
    "SFTP_PORT":        ("connection", "port"),
    "SFTP_USER":        ("connection", "user"),
    "SFTP_PASSWORD":    ("connection", "password"),
    "SFTP_KEY_PATH":    ("connection", "key_path"),
    "SFTP_AUTH":        ("connection", "auth"),
    # The two deploy destinations, named after what they hold.
    "SCRAPER_DIR":      ("targets", "python", "remote"),
    "ADMIN_SERVER_DIR": ("targets", "node", "remote"),
}

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


def env_path(data=None):
    """Which .env file the deploy settings are read from.

    Precedence: the ``env_file`` setting, then ATLAS_ENV_FILE, then a .env
    sitting next to the app -- the same order scraper.config uses, so the GUI
    and the tasks it launches always agree on which file is in play.
    """
    raw = ""
    if data:
        raw = (data.get("env_file") or "").strip()
    raw = raw or os.environ.get("ATLAS_ENV_FILE", "") or ""
    raw = raw.strip()
    if not raw:
        return os.path.join(app_root(), ".env")
    raw = os.path.expanduser(raw)
    if not os.path.isabs(raw):
        raw = os.path.join(app_root(), raw)
    return os.path.abspath(raw)


def _parse_env_file(file_path):
    """Read KEY=VALUE pairs from a .env file.

    Hand-rolled rather than requiring python-dotenv, so the Deploy tab still
    works if only the scraper's dependencies are installed. Handles the subset
    that matters: comments, blank lines, `export ` prefixes, and quoted values.
    """
    values = {}
    if not file_path or not os.path.isfile(file_path):
        return values
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def env_values(data=None):
    """Effective deploy-related env values: real environment beats the file."""
    from_file = _parse_env_file(env_path(data))
    out = {}
    for name in ENV_MAP:
        # A real environment variable wins, matching normal dotenv semantics.
        value = os.environ.get(name)
        if value is None or value == "":
            value = from_file.get(name)
        if value is not None and str(value).strip() != "":
            out[name] = str(value).strip()
    return out


def _set_path(data, keys, value):
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def apply_env(data):
    """Overlay env values onto `data`. Returns {dotted.path: ENV_VAR_NAME}."""
    found = env_values(data)
    sources = {}
    for name, keys in ENV_MAP.items():
        if name not in found:
            continue
        value = found[name]
        if keys[-1] == "port":
            try:
                value = int(value)
            except ValueError:
                continue
        _set_path(data, list(keys), value)
        sources[".".join(keys)] = name

    # Convenience: a password in .env with no key path clearly means password
    # auth, so don't also make the user set SFTP_AUTH.
    if "connection.password" in sources and "connection.auth" not in sources:
        if not (found.get("SFTP_KEY_PATH") or "").strip():
            data.setdefault("connection", {})["auth"] = "password"
            sources["connection.auth"] = "SFTP_PASSWORD"
    return sources


def env_sources(data=None):
    """Which settings paths are currently controlled by the environment.

    Builds a throwaway skeleton rather than deep-copying the caller's dict: the
    GUI's live settings can contain Tk widget references, and copy.deepcopy of a
    Tcl object raises.
    """
    probe = {"env_file": (data or {}).get("env_file", ""),
             "connection": {}, "options": {}, "targets": {}}
    for key in ("python", "node"):
        probe["targets"][key] = {}
    return apply_env(probe)


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
    """Merged settings: DEFAULTS, then deploy.json, then .env / environment."""
    p = path()
    data = copy.deepcopy(DEFAULTS)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = _merge(data, json.load(f))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"could not read {p}: {exc}") from exc
    apply_env(data)
    return data


def save(data, env_controlled=None):
    """Write deploy.json.

    Values that .env supplies are blanked rather than written out. Otherwise the
    SFTP password would be copied into a second file, and a stale value in
    deploy.json would sit there looking authoritative while .env quietly
    overrode it on every load.
    """
    out = copy.deepcopy(data)
    for dotted in (env_controlled if env_controlled is not None
                   else env_sources(data)):
        keys = dotted.split(".")
        node = out
        for key in keys[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict) and keys[-1] in node:
            node[keys[-1]] = 22 if keys[-1] == "port" else ""

    p = path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
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
