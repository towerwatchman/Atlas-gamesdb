"""
The tiny line protocol spoken between the GUI (parent) and a task (child).

Tasks run in a real child process rather than a thread. That buys three things
a thread cannot give us:

  * a genuine Stop button -- a Python thread cannot be killed, and several of
    these tools are long-running (the refresh worker is a daemon, a full
    re-crawl runs for hours)
  * crash isolation -- a task that segfaults inside a C extension or calls
    sys.exit() cannot take the window with it
  * no global stdout hijacking, so two things printing at once can't interleave
    into the same buffer

The cost is that ``input()`` no longer has a console to read from. So the child
replaces ``builtins.input`` with a version that writes a sentinel-prefixed line
to stdout and then blocks reading one line from stdin. The parent watches for
that sentinel, shows its prompt bar, and writes the user's answer back to the
child's stdin. From the tool's point of view nothing has changed -- it still
just called ``input()`` and got a string.
"""

# Deliberately built from control characters no tool would ever print.
PROMPT_PREFIX = "\x01ATLAS-PROMPT\x01"
