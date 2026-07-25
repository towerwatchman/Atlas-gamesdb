"""
Child-process side: run one task, headless, with input() relayed over stdin.

This is what the GUI spawns, and it is also perfectly usable by hand:

    python -m atlas_tools --child find_duplicates --scope f95
    AtlasTools.exe --child find_duplicates --scope f95

The exit code is the task's return value (0 on a clean run), so it also works
as the thing a cron entry or a batch file calls.
"""
import importlib
import os
import sys
import traceback

from atlas_tools.protocol import PROMPT_PREFIX


class _LineTracker:
    """stdout proxy that remembers whether we're at the start of a line.

    Needed because tools legitimately print without a trailing newline
    (``print(f"[{n}/{len(ids)}] ", end="")``). If a prompt sentinel were then
    written straight after, it would land mid-line and the parent would read it
    as ordinary output -- leaving the child blocked on stdin forever. So we
    emit a newline first when we aren't at a line start.
    """

    def __init__(self, stream):
        self._stream = stream
        self.at_line_start = True

    def write(self, data):
        written = self._stream.write(data)
        if data:
            self.at_line_start = data.endswith("\n")
        return written

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _unbuffer():
    """Line-buffer stdout/stderr so the GUI sees output as it happens.

    Without this, a pipe gets a 4-8KB block buffer and a slow task looks frozen
    for minutes at a time.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, encoding="utf-8",
                               errors="replace")
        except Exception:
            pass
    sys.stdout = _LineTracker(sys.stdout)


def _install_input_relay():
    """Replace input() with a version that talks to the parent GUI."""
    import builtins

    real_input = builtins.input

    def relayed_input(prompt=""):
        # If we actually have a console (someone ran this by hand in cmd.exe),
        # don't get in the way -- use the normal blocking input.
        if sys.stdin is not None and sys.stdin.isatty():
            return real_input(prompt)

        # Prompts can legitimately contain newlines; collapse them so the
        # sentinel stays a single line on the wire.
        text = str(prompt).replace("\r", " ").replace("\n", " ")
        # Make sure the sentinel begins a line -- see _LineTracker.
        if not getattr(sys.stdout, "at_line_start", True):
            sys.stdout.write("\n")
        sys.stdout.write(PROMPT_PREFIX + text + "\n")
        sys.stdout.flush()

        line = sys.stdin.readline()
        if line == "":
            # Parent closed the pipe (Stop was pressed). The tools all catch
            # EOFError and exit cleanly, which is exactly what we want.
            raise EOFError("input stream closed")
        return line.rstrip("\n").rstrip("\r")

    builtins.input = relayed_input


def run(task_id, argv):
    """Import the task's module and call its main(argv). Returns an exit code."""
    # Imported here so `--child` starts fast and a registry syntax error is
    # reported as a normal traceback rather than an import-time crash.
    from atlas_tools.registry import BY_ID

    task = BY_ID.get(task_id)
    if task is None:
        known = ", ".join(sorted(BY_ID))
        print(f"unknown task id {task_id!r}\nknown ids: {known}", file=sys.stderr)
        return 2

    _unbuffer()
    _install_input_relay()

    try:
        module = importlib.import_module(task.module)
    except Exception:
        print(f"failed to import {task.module}:", file=sys.stderr)
        traceback.print_exc()
        return 1

    entry = getattr(module, "main", None)
    if entry is None:
        print(f"{task.module} has no main()", file=sys.stderr)
        return 1

    print(f"$ {task.module} {' '.join(argv)}".rstrip())
    print("-" * 68)

    try:
        result = entry(list(argv))
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except EOFError:
        # Stop pressed while a prompt was open.
        print("\nStopped.")
        return 130
    except Exception:
        print("\n--- task raised ---", file=sys.stderr)
        traceback.print_exc()
        return 1

    return 0 if result is None else int(result)


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if not argv:
        print("usage: --child <task_id> [args...]", file=sys.stderr)
        return 2
    return run(argv[0], argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
