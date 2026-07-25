"""
Push raw files to the server over SFTP.

Two independent targets ("python" and "node") each map a local folder to a
remote folder with their own include/exclude patterns, so the scraper and the
Node app land in the different places they live in without one deploy
clobbering the other.

Design choices worth knowing:

  * ``.env`` files are NEVER uploaded unless explicitly asked for. They are
    listed separately from the include patterns so a routine code push cannot
    quietly overwrite production credentials with a dev copy.
  * Unchanged files are skipped by comparing size + mtime, and mtime is written
    back after each upload so the comparison keeps working on the next run.
  * Uploads go to ``<name>.atlastmp`` and are then renamed into place, so a
    running Node process never sees a half-written file.
  * Nothing is ever deleted on the server. Removing a file locally leaves the
    stale copy remote; that is the safe default, and the log says so.
"""
import fnmatch
import os
import posixpath
import re
import stat
import time


class DeployError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# glob matching
# ---------------------------------------------------------------------------

def _glob_to_regex(pattern):
    """Translate a glob to a regex, with proper ``**`` handling.

    fnmatch is not usable here because its ``*`` also matches ``/``, which makes
    ``**/__pycache__/**`` and ``web/src/*`` mean the same thing. We need:
        **/   -> zero or more path segments
        **    -> anything, including separators
        *     -> anything except a separator
        ?     -> one character except a separator
    """
    i = 0
    out = ["^"]
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    out.append("$")
    return re.compile("".join(out))


_CACHE = {}


def matches(rel, pattern):
    rx = _CACHE.get(pattern)
    if rx is None:
        rx = _CACHE[pattern] = _glob_to_regex(pattern)
    return rx.match(rel) is not None


def matches_any(rel, patterns):
    return any(matches(rel, p) for p in patterns)


def collect_files(local_root, include, exclude):
    """Return sorted rel-paths (forward slashes) under local_root to upload."""
    local_root = os.path.abspath(local_root)
    if not os.path.isdir(local_root):
        raise DeployError(f"local folder does not exist: {local_root}")

    # A bare folder name in `include` is a convenience for "everything under it".
    expanded = []
    for pat in include:
        if not any(c in pat for c in "*?[") and \
                os.path.isdir(os.path.join(local_root, pat)):
            expanded.append(pat.rstrip("/") + "/**")
        else:
            expanded.append(pat)

    found = []
    for dirpath, dirnames, filenames in os.walk(local_root):
        rel_dir = os.path.relpath(dirpath, local_root).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""

        # Prune excluded directories so we don't walk into node_modules at all.
        keep = []
        for d in dirnames:
            rel_sub = f"{rel_dir}/{d}" if rel_dir else d
            if matches_any(rel_sub + "/x", exclude) or matches_any(rel_sub, exclude):
                continue
            keep.append(d)
        dirnames[:] = keep

        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if not matches_any(rel, expanded):
                continue
            if matches_any(rel, exclude):
                continue
            found.append(rel)

    return sorted(found)


# ---------------------------------------------------------------------------
# ssh / sftp
# ---------------------------------------------------------------------------

def _connect(conn, log):
    try:
        import paramiko
    except ImportError as exc:
        raise DeployError(
            "paramiko is not installed. Run:  pip install paramiko"
        ) from exc

    host = (conn.get("host") or "").strip()
    if not host:
        raise DeployError("No host set. Fill it in on the Settings tab.")
    user = (conn.get("user") or "").strip()
    if not user:
        raise DeployError("No username set.")
    port = int(conn.get("port") or 22)

    client = paramiko.SSHClient()
    try:
        client.load_system_host_keys()
    except Exception:
        pass
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 20,
        "allow_agent": True,
        "look_for_keys": True,
    }

    if conn.get("auth") == "password":
        pwd = conn.get("password") or ""
        if not pwd:
            raise DeployError("Password auth selected but no password set.")
        kwargs["password"] = pwd
        kwargs["look_for_keys"] = False
    else:
        key_path = (conn.get("key_path") or "").strip()
        if key_path:
            key_path = os.path.expanduser(key_path)
            if not os.path.exists(key_path):
                raise DeployError(f"Key file not found: {key_path}")
            kwargs["key_filename"] = key_path

    log(f"connecting to {user}@{host}:{port} ...")
    client.connect(**kwargs)

    transport = client.get_transport()
    if transport is not None:
        key = transport.get_remote_server_key()
        # Printed so a changed server key is at least visible in the log.
        log(f"  host key {key.get_name()} "
            f"sha256:{_fingerprint(key)}")
    log("  connected")
    return client


def _fingerprint(key):
    import base64
    import hashlib
    digest = hashlib.sha256(key.asbytes()).digest()
    return base64.b64encode(digest).decode().rstrip("=")


def _mkdirs(sftp, remote_dir, made, log):
    """mkdir -p over SFTP, remembering what we've already created."""
    if remote_dir in ("", "/", ".") or remote_dir in made:
        return
    parent = posixpath.dirname(remote_dir)
    if parent and parent != remote_dir:
        _mkdirs(sftp, parent, made, log)
    try:
        sftp.stat(remote_dir)
    except IOError:
        try:
            sftp.mkdir(remote_dir)
            log(f"  mkdir {remote_dir}")
        except IOError as exc:
            raise DeployError(f"cannot create {remote_dir}: {exc}") from exc
    made.add(remote_dir)


def _needs_upload(sftp, local_path, remote_path, skip_unchanged):
    if not skip_unchanged:
        return True, "forced"
    try:
        rstat = sftp.stat(remote_path)
    except IOError:
        return True, "new"
    lstat = os.stat(local_path)
    if rstat.st_size != lstat.st_size:
        return True, "size differs"
    # 2s slack absorbs filesystem timestamp granularity differences.
    if int(lstat.st_mtime) > int(rstat.st_mtime) + 2:
        return True, "newer locally"
    return False, "unchanged"


def _put(sftp, local_path, remote_path, atomic):
    if atomic:
        tmp = remote_path + ".atlastmp"
        sftp.put(local_path, tmp)
        try:
            sftp.posix_rename(tmp, remote_path)
        except (AttributeError, IOError):
            # Older servers: remove-then-rename is the best we can do.
            try:
                sftp.remove(remote_path)
            except IOError:
                pass
            sftp.rename(tmp, remote_path)
    else:
        sftp.put(local_path, remote_path)

    st = os.stat(local_path)
    try:
        sftp.utime(remote_path, (st.st_atime, st.st_mtime))
    except IOError:
        pass


# ---------------------------------------------------------------------------
# the deploy itself
# ---------------------------------------------------------------------------

def plan(data, target_keys, include_env):
    """Work out what would be uploaded, without connecting to anything."""
    from atlas_tools.runner import app_root
    root = app_root()
    out = {}
    for key in target_keys:
        target = data["targets"][key]
        local_root = os.path.abspath(os.path.join(root, target.get("local") or "."))
        files = collect_files(local_root, target.get("include") or [],
                             target.get("exclude") or [])
        envs = []
        if include_env:
            for rel in target.get("env_files") or []:
                if os.path.isfile(os.path.join(local_root, rel)):
                    envs.append(rel)
        out[key] = {
            "local_root": local_root,
            "remote_root": (target.get("remote") or "").rstrip("/"),
            "files": files,
            "env_files": envs,
            "missing_env": [
                rel for rel in (target.get("env_files") or [])
                if include_env and not os.path.isfile(os.path.join(local_root, rel))
            ],
            "post_commands": target.get("post_commands") or [],
        }
    return out


def run_deploy(data, target_keys, include_env=False, dry_run=False,
               run_post=True, log=print, should_stop=lambda: False):
    """Upload the selected targets. ``log`` gets one line at a time."""
    plans = plan(data, target_keys, include_env)

    total_files = sum(len(p["files"]) for p in plans.values())
    total_env = sum(len(p["env_files"]) for p in plans.values())

    log("=" * 68)
    log(f"{'DRY RUN -- ' if dry_run else ''}deploy: "
        f"{len(target_keys)} target(s), {total_files} file(s)"
        + (f", {total_env} env file(s)" if total_env else ""))
    log("=" * 68)

    for key, p in plans.items():
        if not p["remote_root"]:
            raise DeployError(
                f"target '{key}' has no remote path set (Settings tab).")
        log("")
        log(f"[{key}] {p['local_root']}")
        log(f"     -> {p['remote_root']}")
        log(f"     {len(p['files'])} file(s) match")
        for rel in p["missing_env"]:
            log(f"     !! env file not found locally, skipping: {rel}")
        if p["env_files"]:
            log(f"     !! WILL OVERWRITE REMOTE ENV: "
                f"{', '.join(p['env_files'])}")

    if dry_run:
        log("")
        for key, p in plans.items():
            log(f"--- [{key}] files ---")
            for rel in p["files"]:
                log(f"    {rel}")
            for rel in p["env_files"]:
                log(f"    {rel}   (env)")
            if run_post and p["post_commands"]:
                log(f"--- [{key}] would then run ---")
                for cmd in p["post_commands"]:
                    log(f"    $ {cmd}")
        log("")
        log("Dry run only -- nothing was uploaded.")
        return {"uploaded": 0, "skipped": 0, "dry_run": True}

    client = _connect(data.get("connection") or {}, log)
    uploaded = skipped = 0
    started = time.time()
    opts = data.get("options") or {}
    skip_unchanged = bool(opts.get("skip_unchanged", True))
    atomic = bool(opts.get("atomic", True))

    try:
        sftp = client.open_sftp()
        made = set()

        for key, p in plans.items():
            log("")
            log(f"=== [{key}] uploading ===")
            _mkdirs(sftp, p["remote_root"], made, log)

            for rel in p["files"] + p["env_files"]:
                if should_stop():
                    log("\n[stopped by user]")
                    return {"uploaded": uploaded, "skipped": skipped,
                            "stopped": True}

                local_path = os.path.join(p["local_root"], rel.replace("/", os.sep))
                remote_path = posixpath.join(p["remote_root"], rel)
                _mkdirs(sftp, posixpath.dirname(remote_path), made, log)

                needed, why = _needs_upload(sftp, local_path, remote_path,
                                            skip_unchanged)
                if not needed:
                    skipped += 1
                    continue
                try:
                    _put(sftp, local_path, remote_path, atomic)
                except IOError as exc:
                    raise DeployError(f"upload failed for {rel}: {exc}") from exc
                uploaded += 1
                log(f"  + {rel}   ({why})")

            log(f"  {uploaded} uploaded, {skipped} unchanged so far")

        sftp.close()

        if run_post:
            for key, p in plans.items():
                if not p["post_commands"]:
                    continue
                log("")
                log(f"=== [{key}] post-deploy commands ===")
                for cmd in p["post_commands"]:
                    if should_stop():
                        log("\n[stopped by user]")
                        return {"uploaded": uploaded, "skipped": skipped,
                                "stopped": True}
                    log(f"$ {cmd}")
                    code = _exec(client, cmd, log)
                    if code != 0:
                        raise DeployError(
                            f"command exited {code}: {cmd}\n"
                            "Nothing was rolled back -- the files are already "
                            "uploaded. Fix the cause and re-run.")
    finally:
        client.close()

    log("")
    log("-" * 68)
    log(f"done in {time.time() - started:.1f}s: "
        f"{uploaded} uploaded, {skipped} unchanged")
    log("Note: files deleted locally are NOT removed on the server.")
    return {"uploaded": uploaded, "skipped": skipped}


def _exec(client, cmd, log):
    """Run one remote command, streaming its output."""
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=False, timeout=None)
    stdin.close()
    channel = stdout.channel
    buf = b""
    while True:
        if channel.recv_ready():
            buf += channel.recv(4096)
        elif channel.recv_stderr_ready():
            buf += channel.recv_stderr(4096)
        elif channel.exit_status_ready() and not channel.recv_ready() \
                and not channel.recv_stderr_ready():
            break
        else:
            time.sleep(0.05)

        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            log("    " + line.decode("utf-8", errors="replace").rstrip("\r"))

    if buf:
        log("    " + buf.decode("utf-8", errors="replace"))
    return channel.recv_exit_status()


def test_connection(data, log=print):
    """Connect, print uname and check both remote folders exist."""
    client = _connect(data.get("connection") or {}, log)
    try:
        _exec(client, "uname -a", log)
        sftp = client.open_sftp()
        for key, target in (data.get("targets") or {}).items():
            remote = (target.get("remote") or "").rstrip("/")
            if not remote:
                log(f"  [{key}] no remote path set")
                continue
            try:
                st = sftp.stat(remote)
                kind = "dir" if stat.S_ISDIR(st.st_mode) else "FILE (expected a dir!)"
                log(f"  [{key}] {remote} -> exists ({kind})")
            except IOError:
                log(f"  [{key}] {remote} -> DOES NOT EXIST "
                    f"(it will be created on first deploy)")
        sftp.close()
    finally:
        client.close()
    log("connection OK")
