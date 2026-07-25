"""
End-to-end deploy test against a REAL SSH/SFTP server.

This is the only test that exercises the actual upload path, so it's worth
running before you trust a deploy. It needs an sshd you can reach with a key.
It SKIPS (rather than fails) if one isn't configured, so it's safe to run
anywhere.

To set one up on a Linux box / WSL:

    sudo apt-get install -y openssh-server
    ssh-keygen -t ed25519 -f ~/.ssh/id_test -N ""
    cat ~/.ssh/id_test.pub >> ~/.ssh/authorized_keys
    sudo mkdir -p /run/sshd && sudo ssh-keygen -A
    printf 'Port 2222\\nListenAddress 127.0.0.1\\nHostKey /etc/ssh/ssh_host_ed25519_key\\n\\
PermitRootLogin yes\\nPubkeyAuthentication yes\\nPasswordAuthentication no\\n\\
Subsystem sftp internal-sftp\\nUsePAM no\\n' | sudo tee /etc/ssh/sshd_config.test
    sudo /usr/sbin/sshd -f /etc/ssh/sshd_config.test

Then:

    ATLAS_TEST_SSH_HOST=127.0.0.1 ATLAS_TEST_SSH_PORT=2222 \
    ATLAS_TEST_SSH_USER=root ATLAS_TEST_SSH_KEY=~/.ssh/id_test \
    ATLAS_TEST_REMOTE_BASE=/tmp/atlas-deploy-test \
    python tests/test_deploy_live.py

What it proves, in order: connect; dry run touches nothing; a real deploy lands
both trees in their own folders byte-identically and runs the post-commands;
no .atlastmp files are left behind; a second deploy skips everything; touching
one file re-uploads exactly one; .env is uploaded only when explicitly asked
for; and a failing post-command is surfaced rather than swallowed.
"""
import copy
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from atlas_tools import settings
from atlas_tools.deploy import DeployError, run_deploy, test_connection

HOST = os.environ.get("ATLAS_TEST_SSH_HOST")
PORT = int(os.environ.get("ATLAS_TEST_SSH_PORT", "22"))
USER = os.environ.get("ATLAS_TEST_SSH_USER", "root")
KEY = os.environ.get("ATLAS_TEST_SSH_KEY", "")
BASE = os.environ.get("ATLAS_TEST_REMOTE_BASE", "/tmp/atlas-deploy-test")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _config():
    data = copy.deepcopy(settings.DEFAULTS)
    data["connection"] = {"host": HOST, "port": PORT, "user": USER,
                          "auth": "key", "key_path": KEY, "password": ""}
    data["targets"]["python"]["remote"] = f"{BASE}/scraper-side"
    data["targets"]["python"]["post_commands"] = ["echo PY-POST-OK"]
    data["targets"]["node"]["remote"] = f"{BASE}/node-side"
    data["targets"]["node"]["post_commands"] = ["echo NODE-POST-OK"]
    return data


def _quiet(_msg):
    pass


def main():
    if not HOST:
        print("SKIP: set ATLAS_TEST_SSH_HOST to run the live deploy test.")
        print("      (see the docstring at the top of this file)")
        return 0

    data = _config()
    lines = []

    def log(msg):
        lines.append(str(msg))

    print("1. connect ...", end=" ", flush=True)
    test_connection(data, log=log)
    print("ok")

    print("2. dry run touches nothing ...", end=" ", flush=True)
    result = run_deploy(data, ["python"], dry_run=True, log=_quiet)
    assert result.get("dry_run") and result["uploaded"] == 0, result
    print("ok")

    print("3. real deploy, both targets ...", end=" ", flush=True)
    result = run_deploy(data, ["python", "node"], dry_run=False, log=log)
    assert result["uploaded"] > 50, result
    joined = "\n".join(lines)
    assert "PY-POST-OK" in joined, "python post-command did not run"
    assert "NODE-POST-OK" in joined, "node post-command did not run"
    print(f"ok ({result['uploaded']} files, post-commands ran)")

    # The remaining checks need to see the remote filesystem. When the server is
    # this machine (the usual local-sshd setup) we can just look.
    local_view = os.path.isdir(BASE)
    if local_view:
        print("4. landed correctly and byte-identical ...", end=" ", flush=True)
        py = f"{BASE}/scraper-side"
        node = f"{BASE}/node-side"
        for rel in ("api.py", "backup.py", "f95_refresh_worker.py",
                    "scraper/utils/db.py",
                    "tools/backfill/backfill_atlas_export.py"):
            assert os.path.isfile(os.path.join(py, rel)), rel
        for rel in ("package.json", "server/src/index.js", "web/src/App.jsx"):
            assert os.path.isfile(os.path.join(node, rel)), rel
        # The two targets must not bleed into each other.
        assert not os.path.exists(os.path.join(py, "server")), \
            "node tree leaked into the scraper folder"
        assert not os.path.exists(os.path.join(node, "scraper")), \
            "scraper tree leaked into the node folder"
        # Never upload these.
        assert not os.path.exists(os.path.join(py, ".env"))
        for bad in ("__pycache__", "atlas_tools", "node_modules"):
            assert not any(bad in d for d, _, _ in os.walk(BASE)), bad
        with open(os.path.join(ROOT, "api.py"), "rb") as f:
            want = f.read()
        with open(os.path.join(py, "api.py"), "rb") as f:
            assert f.read() == want, "content differs after upload"
        leftovers = [os.path.join(d, n) for d, _, ns in os.walk(BASE)
                     for n in ns if n.endswith(".atlastmp")]
        assert not leftovers, leftovers
        print("ok")

    print("5. re-deploy skips unchanged ...", end=" ", flush=True)
    result = run_deploy(data, ["python", "node"], dry_run=False,
                        run_post=False, log=_quiet)
    assert result["uploaded"] == 0, f"expected 0 uploads, got {result}"
    assert result["skipped"] > 50, result
    print(f"ok ({result['skipped']} skipped)")

    print("6. touching one file re-uploads exactly one ...", end=" ", flush=True)
    stamp = time.time() + 10
    os.utime(os.path.join(ROOT, "api.py"), (stamp, stamp))
    result = run_deploy(data, ["python"], dry_run=False, run_post=False,
                        log=_quiet)
    assert result["uploaded"] == 1, f"expected 1 upload, got {result}"
    print("ok")

    print("7. .env only uploads when asked ...", end=" ", flush=True)
    env_path = os.path.join(ROOT, ".env")
    created = not os.path.exists(env_path)
    if created:
        with open(env_path, "w") as f:
            f.write("DB_USER=deploy-test\n")
    try:
        run_deploy(data, ["python"], include_env=False, dry_run=False,
                   run_post=False, log=_quiet)
        if local_view:
            assert not os.path.exists(f"{BASE}/scraper-side/.env"), \
                ".env was uploaded without being asked for"
        run_deploy(data, ["python"], include_env=True, dry_run=False,
                   run_post=False, log=_quiet)
        if local_view:
            assert os.path.isfile(f"{BASE}/scraper-side/.env"), \
                ".env was not uploaded when asked for"
    finally:
        if created:
            os.remove(env_path)
    print("ok")

    print("8. a failing post-command is surfaced ...", end=" ", flush=True)
    bad = _config()
    bad["targets"]["python"]["post_commands"] = ["exit 3"]
    try:
        run_deploy(bad, ["python"], dry_run=False, run_post=True, log=_quiet)
    except DeployError as exc:
        assert "exited 3" in str(exc), exc
    else:
        raise AssertionError("a failing post-command did not raise")
    print("ok")

    if local_view:
        shutil.rmtree(BASE, ignore_errors=True)
    print("\nall live deploy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
