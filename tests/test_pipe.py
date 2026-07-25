"""
Tests for the parent/child output protocol.

The regression these exist for: a tool that prints WITHOUT a trailing newline
and then calls input() used to wedge the whole app. The sentinel landed
mid-line, the parent never recognised it as a prompt, so it never wrote an
answer, so the child blocked on stdin forever with the GUI showing nothing.

    python tests/test_pipe.py
"""
import os
import subprocess
import sys
import textwrap
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from atlas_tools.protocol import PROMPT_PREFIX
from atlas_tools.runner import process_chunk

TIMEOUT = 30


# ------------------------------------------------------- pure pump behaviour
def _drain(chunks):
    """Feed chunks through process_chunk, return (events, leftover)."""
    buf = ""
    events = []
    for chunk in chunks:
        new, buf = process_chunk(buf, chunk)
        events.extend(new)
    return events, buf


def test_plain_lines():
    events, left = _drain(["hello\nworld\n"])
    assert events == [("out", "hello\n"), ("out", "world\n")], events
    assert left == ""


def test_crlf_is_normalised():
    events, _ = _drain(["hello\r\n"])
    assert events == [("out", "hello\n")], events


def test_ansi_is_stripped():
    events, _ = _drain(["\x1b[1mbold\x1b[0m\n"])
    assert events == [("out", "bold\n")], events


def test_prompt_on_its_own_line():
    events, _ = _drain([PROMPT_PREFIX + "  choose > \n"])
    assert events == [("prompt", "  choose > ")], events


def test_prompt_after_partial_line_is_still_detected():
    """The original deadlock: output with end='' immediately before a prompt."""
    events, _ = _drain(["[3/40] " + PROMPT_PREFIX + "y/N ? \n"])
    kinds = [k for k, _ in events]
    assert "prompt" in kinds, events
    assert ("out", "[3/40] ") in events, events


def test_sentinel_split_across_chunks():
    """A chunk boundary landing inside the sentinel must not leak it as output."""
    whole = PROMPT_PREFIX + "answer me\n"
    for cut in range(1, len(whole)):
        events, left = _drain([whole[:cut], whole[cut:]])
        prompts = [p for k, p in events if k == "prompt"]
        assert prompts == ["answer me"], (cut, events)
        # The sentinel must never appear in displayed output.
        for kind, payload in events:
            if kind == "out":
                assert PROMPT_PREFIX not in payload, (cut, events)
        assert left == ""


def test_partial_line_is_shown_immediately():
    """A tool printing a progress prefix shouldn't look frozen."""
    events, left = _drain(["[1/9] "])
    assert events == [("out", "[1/9] ")], events
    assert left == ""


def test_partial_sentinel_is_held_back():
    events, left = _drain([PROMPT_PREFIX[:4]])
    assert events == [], events
    assert left == PROMPT_PREFIX[:4]


def test_output_then_prompt_then_output():
    events, _ = _drain([
        "starting\n",
        PROMPT_PREFIX + "name? \n",
        "done\n",
    ])
    assert events == [
        ("out", "starting\n"),
        ("prompt", "name? "),
        ("out", "done\n"),
    ], events


def test_byte_at_a_time_delivery():
    """Worst-case chunking: one character per read."""
    stream = "a\n" + PROMPT_PREFIX + "q? \n" + "b\n"
    events, left = _drain(list(stream))
    prompts = [p for k, p in events if k == "prompt"]
    out = "".join(p for k, p in events if k == "out")
    assert prompts == ["q? "], events
    assert "a" in out and "b" in out
    assert PROMPT_PREFIX not in out
    assert left == ""


# ------------------------------------------------- real child, real subprocess
FAKE_TASK = '''
import sys

def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    print("args:", argv)
    # Deliberately no trailing newline before the prompt -- the regression.
    print("progress... ", end="")
    name = input("  your name > ")
    print("hello", name)
    ok = input("    proceed? [y/N] ")
    print("got", ok)
    return 7
'''

SHIM = '''
import sys
from atlas_tools import registry
from atlas_tools.registry import Task
registry.BY_ID["faketask"] = Task(
    id="faketask", label="fake", group="test", module="faketask")
from atlas_tools.child import main
raise SystemExit(main(sys.argv[1:]))
'''


def test_real_child_relays_input_and_returns_exit_code():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tmp = tempfile.mkdtemp()
    proc = None
    try:
        with open(os.path.join(tmp, "faketask.py"), "w") as f:
            f.write(textwrap.dedent(FAKE_TASK))
        shim = os.path.join(tmp, "shim.py")
        with open(shim, "w") as f:
            f.write(textwrap.dedent(SHIM))

        env = os.environ.copy()
        env["PYTHONPATH"] = root + os.pathsep + tmp
        env["PYTHONUNBUFFERED"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-u", shim, "faketask", "--flag", "v"],
            cwd=root, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)

        answers = iter(["Braden", "y"])
        prompts = []
        out = []
        buf = ""

        # Read using exactly the parent's own logic.
        import threading
        done = threading.Event()

        def reader():
            nonlocal buf
            try:
                while True:
                    chunk = proc.stdout.read(1)
                    if not chunk:
                        break
                    events, buf = process_chunk(
                        buf, chunk.decode("utf-8", errors="replace"))
                    for kind, payload in events:
                        if kind == "prompt":
                            prompts.append(payload)
                            try:
                                proc.stdin.write((next(answers) + "\n").encode())
                                proc.stdin.flush()
                            except StopIteration:
                                proc.stdin.close()
                        else:
                            out.append(payload)
            finally:
                done.set()

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        done.wait(TIMEOUT)
        if not done.is_set():
            proc.kill()
            raise AssertionError(
                f"child deadlocked. prompts={prompts} out={''.join(out)!r}")

        code = proc.wait(timeout=TIMEOUT)
        text = "".join(out)

        assert code == 7, (code, text)
        assert "args: ['--flag', 'v']" in text, text
        assert "progress..." in text, text
        assert "hello Braden" in text, text
        assert "got y" in text, text
        assert len(prompts) == 2, prompts
        assert "your name" in prompts[0], prompts
        assert "[y/N]" in prompts[1], prompts
        assert PROMPT_PREFIX not in text
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def test_child_exits_cleanly_when_stdin_closes():
    """Pressing Stop closes stdin; an open input() must not hang or traceback."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tmp = tempfile.mkdtemp()
    proc = None
    try:
        with open(os.path.join(tmp, "faketask.py"), "w") as f:
            f.write(textwrap.dedent('''
                def main(argv=None):
                    print("before")
                    x = input("ask > ")
                    print("never", x)
                    return 0
            '''))
        shim = os.path.join(tmp, "shim.py")
        with open(shim, "w") as f:
            f.write(textwrap.dedent(SHIM))

        env = os.environ.copy()
        env["PYTHONPATH"] = root + os.pathsep + tmp
        env["PYTHONUNBUFFERED"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-u", shim, "faketask"],
            cwd=root, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)

        proc.stdin.close()          # what TaskRun.stop() does first
        # Read directly rather than via communicate(), which would try to close
        # the already-closed stdin and raise.
        stdout = proc.stdout.read()
        code = proc.wait(timeout=TIMEOUT)
        text = stdout.decode("utf-8", errors="replace")

        assert code == 130, (code, text)
        assert "Stopped." in text, text
        assert "never" not in text, text
        assert "Traceback" not in text, text
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
