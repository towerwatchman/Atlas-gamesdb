# AtlasTools — the Windows desktop app

One window that runs every tool in this repo, so you don't have to remember
which script takes which flags. It is a *testing and operations* front end; the
server still runs the plain Python scripts on a schedule.

```
python -m atlas_tools                      # from a source checkout
AtlasTools.exe                             # once built
```

## Building the exe

From the project root, on Windows:

```
build\build_exe.bat
```

That installs dependencies, runs the tests, builds, and copies `.env` and
`deploy.json` next to the exe. Output:

```
dist\AtlasTools\AtlasTools.exe        <- run this
dist\AtlasTools\_internal\...         <- required, don't delete
dist\AtlasTools\.env                  <- edit this one, not the repo's
dist\AtlasTools\deploy.json
```

**Copy the whole `AtlasTools` folder**, not just the .exe.

### Why a folder and not a single file

The app runs each tool by re-invoking its own exe with `--child`. A one-file
PyInstaller build re-extracts the entire bundle to a temp folder on *every*
invocation, so each task run would stall for several seconds before printing
anything. One-folder starts instantly. If you want the single file anyway, set
`ONEFILE = True` at the top of `build/atlas_tools.spec`.

### Where the exe looks for `.env`

Next to itself — not inside the bundle, and not in whatever folder you happened
to launch from. This is what `scraper.config.app_root()` does: under PyInstaller
it returns the exe's directory, otherwise the project root. Relative paths in
`.env` (like `F95_COOKIE_FILE=f95_cookies.json`) resolve against the same place,
so the session cookie is reused between runs instead of being recreated
wherever your shell's working directory happened to be.

Point it somewhere else with the `.env file` box on the Settings tab, or the
`ATLAS_ENV_FILE` environment variable.

## The Run tab

Pick a tool on the left, fill in the form, press Run. The green line above the
buttons is the exact equivalent command line — useful for copying to the server:

```
python api.py true false false true false false false false
```

`api.py`'s eight positional `true`/`false` flags are unchanged, so anything on
the server that already calls it keeps working. The Run-mode dropdown just
expands the documented combinations for you:

| Run mode | Expands to |
| --- | --- |
| Incremental (default) | `true false false true false false false false` |
| Full re-crawl | `true true false true false false false false` |
| New-only sweep | `true false false true false false true false` |
| Ts-only sweep | `true false false true false false false true` |
| Package only | `false false false true false false false false` |
| F95 + LewdCorner | `true false false true true false false false` |
| Custom | whatever you tick |

### Answering prompts

`reconcile_lc` and `import_f95_csv` ask questions. When a tool blocks on input,
a prompt bar appears under the log; type an answer and press Enter. `[y/N]`
prompts also get Yes/No buttons.

This works because tasks run as a real child process and the app relays
`input()` over its stdin. The relevant consequence: **Stop actually stops
things**, including the refresh worker daemon and a multi-hour full re-crawl. A
thread-based design could not do that.

### Destructive tools

`backup`, `cleanup_version_titles --apply`, `reconcile_lc defer` (without dry
run) and anything with Apply ticked ask you to type a confirmation word first.
The backfill and cleanup tools default to dry run.

## Running a task without the GUI

Same code path, no window:

```
AtlasTools.exe --child find_duplicates --scope f95 --fuzzy-floor 0.85
AtlasTools.exe --list
python -m atlas_tools --child refresh_game 12345 67890
```

The exit code is the tool's return value, so this is usable from a batch file
or Task Scheduler.

## Adding a new tool

1. Give it a `main(argv=None)` that returns an int (or `None` for success).
2. Add one `Task(...)` to `atlas_tools/registry.py`.

That's it — the GUI builds its form from the registry, and
`build/atlas_tools.spec` derives PyInstaller's hidden-imports list from the same
place, so a new tool can't be silently missing from the build.

## Tests

```
python tests\test_atlas_tools.py     # argv building, deploy globbing (18)
python tests\test_pipe.py            # parent/child protocol (12)
python tests\test_gui_smoke.py       # builds the real window (6)
python -m pytest tests\test_f95_detail.py   # the original parser tests (11)
python tests\test_deploy_live.py     # real SFTP; skips unless configured
```

`test_pipe.py` is the one that matters most. It exists because of a bug worth
remembering: a tool that printed with `end=""` and then called `input()` used to
wedge the whole app — the prompt sentinel landed mid-line, the parent never
recognised it, so it never sent an answer and the child blocked on stdin for
ever. `refresh_missing_tags.py` prints exactly like that.
