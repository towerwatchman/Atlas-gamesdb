"""
Parent side: spawn a task as a child process and pump its output onto a queue
the GUI can drain from the Tk main thread.

Events pushed onto ``TaskRun.events`` are ``(kind, payload)`` tuples:

    ("out",    text)   -- output to append to the log verbatim
    ("prompt", text)   -- the child is blocked on input(); show the prompt bar
    ("exit",   code)   -- the process finished
"""
import os
import queue
import re
import subprocess
import sys
import threading

from atlas_tools.protocol import PROMPT_PREFIX

# Tools colour their output with ANSI escapes, which a Tk text widget would
# render as literal gibberish.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Hide the console window that would otherwise flash up for every child on
# Windows. Harmless no-op elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def strip_ansi(text):
    return _ANSI.sub("", text)


def app_root():
    """Folder the app treats as the project root (see scraper.config.app_root)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def process_chunk(buf, chunk):
    """Turn accumulated child output into events. Pure, so it can be tested.

    Returns ``(events, remaining_buf)``. Three cases have to be handled or the
    app wedges, and all three have happened:

      1. The sentinel is searched for anywhere in the stream, not only at a line
         start. The child tries to put it on its own line, but a missed prompt
         means the child blocks on stdin forever with nothing on screen.
      2. A sentinel that has arrived but whose terminating newline has not must
         be held in the buffer -- never flushed to the display as text.
      3. A read boundary can land *inside* the sentinel, so a trailing fragment
         that could still grow into one is held back too.
    """
    events = []
    buf += chunk

    # 1. Complete prompts: sentinel present AND its newline has arrived.
    while True:
        idx = buf.find(PROMPT_PREFIX)
        if idx == -1:
            break
        start = idx + len(PROMPT_PREFIX)
        nl = buf.find("\n", start)
        if nl == -1:
            break                      # incomplete -- handled below
        events.extend(_emit_lines(buf[:idx]))
        events.append(("prompt", strip_ansi(buf[start:nl].rstrip("\r"))))
        buf = buf[nl + 1:]

    # 2. A sentinel still waiting for its newline: emit only what precedes it.
    idx = buf.find(PROMPT_PREFIX)
    if idx != -1:
        events.extend(_emit_lines(buf[:idx]))
        return events, buf[idx:]

    # 3. No sentinel in play -- emit complete lines.
    while "\n" in buf:
        line, buf = buf.split("\n", 1)
        events.append(("out", strip_ansi(line.rstrip("\r")) + "\n"))

    # A trailing fragment with no newline is real output written with end="";
    # show it now rather than making the user think the task has frozen.
    if buf and not _could_become_sentinel(buf):
        events.append(("out", strip_ansi(buf)))
        buf = ""

    return events, buf


def _emit_lines(text):
    """Emit `text` as out-events, splitting on newlines but keeping partials."""
    if not text:
        return []
    events = []
    while "\n" in text:
        line, text = text.split("\n", 1)
        events.append(("out", strip_ansi(line.rstrip("\r")) + "\n"))
    if text:
        events.append(("out", strip_ansi(text)))
    return events


def _could_become_sentinel(buf):
    """True if buf ends with a partial PROMPT_PREFIX we should wait on."""
    for i in range(1, min(len(buf), len(PROMPT_PREFIX)) + 1):
        if buf[-i:] == PROMPT_PREFIX[:i]:
            return True
    return False


def child_command(task_id, argv):
    """Build the command line that runs one task headlessly.

    Frozen, ``sys.executable`` IS our own exe, so we re-invoke ourselves with
    --child. From a source checkout we go through the interpreter and -m.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--child", task_id] + list(argv)
    return [sys.executable, "-u", "-m", "atlas_tools", "--child", task_id] + list(argv)


class TaskRun:
    """One running task. Not reusable -- make a new one per run."""

    def __init__(self, task_id, argv, env_file=None):
        self.task_id = task_id
        self.argv = list(argv)
        self.events = queue.Queue()
        self.proc = None
        self._reader = None
        self._stopping = False
        self._env_file = env_file

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # So a source checkout can import `api`, `scraper`, `tools`, ...
        root = app_root()
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        if self._env_file:
            env["ATLAS_ENV_FILE"] = self._env_file

        cmd = child_command(self.task_id, self.argv)
        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd=root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                bufsize=0,
                creationflags=_NO_WINDOW,
            )
        except Exception as exc:
            self.events.put(("out", f"failed to start task: {exc}\n"))
            self.events.put(("exit", 1))
            return

        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def send_line(self, text):
        """Answer an open input() prompt."""
        if not self.running or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write((text + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def stop(self):
        """Terminate the child, escalating to kill if it ignores us."""
        if not self.running:
            return
        self._stopping = True
        # Closing stdin first turns any open input() into EOFError, which every
        # interactive tool here already handles as a clean "Interrupted." exit.
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass

        def _escalate():
            try:
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

        threading.Thread(target=_escalate, daemon=True).start()

    # -- output pump -------------------------------------------------------
    def _pump(self):
        """Read the child's output, split out prompt sentinels, post events."""
        buf = ""
        stream = self.proc.stdout
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                events, buf = process_chunk(
                    buf, chunk.decode("utf-8", errors="replace"))
                for event in events:
                    self.events.put(event)
        except Exception as exc:
            self.events.put(("out", f"\n[output pump stopped: {exc}]\n"))
        finally:
            if buf:
                self.events.put(("out", strip_ansi(buf)))
            code = self.proc.wait()
            if self._stopping:
                self.events.put(("out", "\n[stopped by user]\n"))
            self.events.put(("exit", code))
