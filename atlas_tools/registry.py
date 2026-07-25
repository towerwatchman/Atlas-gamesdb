"""
The single source of truth for "what can this app run".

Every tool in the repo is described here once: which module holds its
``main(argv)``, what arguments it takes, and whether it is destructive or
interactive. The GUI builds its forms from this list, and the headless child
runner resolves ``--task <id>`` through it, so adding a new tool is a one-entry
change and never needs a GUI edit.

To add a tool:
    1. give it a ``main(argv=None)`` that returns an int (or None for success)
    2. append a ``Task(...)`` below
"""
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Tuple

# --- parameter kinds --------------------------------------------------------
FLAG = "flag"        # bool -> emits `arg` when True
TEXT = "text"        # free string
INT = "int"
FLOAT = "float"
CHOICE = "choice"    # dropdown, one of `choices`
FILE = "file"        # string + a Browse... button
DIR = "dir"          # string + a Browse folder... button


@dataclass
class Param:
    key: str
    label: str
    kind: str = FLAG
    default: Any = None
    choices: Optional[Sequence[str]] = None
    arg: Optional[str] = None        # CLI flag, e.g. "--limit". None = positional
    help: str = ""
    # Only show/emit this param when another param has one of these values.
    # e.g. only_when=("cmd", ["fuzzy", "defer"])
    only_when: Optional[Tuple[str, Sequence[str]]] = None
    # For CHOICE params whose value IS the flag (e.g. "--once" / "--drain"),
    # map the label the user picks to the argv fragment it produces.
    value_map: Optional[dict] = None

    @property
    def positional(self) -> bool:
        return self.arg is None


@dataclass
class Task:
    id: str
    label: str
    group: str
    module: str                       # dotted path holding main(argv=None)
    help: str = ""
    params: List[Param] = field(default_factory=list)
    # Destructive tasks get a type-to-confirm dialog before they run.
    danger: bool = False
    danger_note: str = ""
    # Interactive tasks prompt with input(); the GUI shows its prompt bar.
    interactive: bool = False
    # Long-running tasks the user is expected to stop manually.
    long_running: bool = False
    # Optional custom argv builder: fn(values: dict) -> list[str]
    build_argv: Optional[Callable[[dict], List[str]]] = None


# ---------------------------------------------------------------------------
# api.py keeps its historical 8-positional true/false CLI so that whatever
# cron/systemd entry already calls it does not need touching. Rather than make
# a human remember the slot order, the GUI offers the documented run modes and
# expands them here.
# ---------------------------------------------------------------------------
API_MODES = {
    #                    f95   full  dls   pkg   lc    lcful new   ts
    "Incremental (default)": (True, False, False, True, False, False, False, False),
    "Full re-crawl":         (True, True,  False, True, False, False, False, False),
    "New-only sweep":        (True, False, False, True, False, False, True,  False),
    "Ts-only sweep":         (True, False, False, True, False, False, False, True),
    "Package only":          (False, False, False, True, False, False, False, False),
    "F95 + LewdCorner":      (True, False, False, True, True,  False, False, False),
    "LewdCorner only":       (False, False, False, True, True,  False, False, False),
    "DLsite only":           (False, False, True,  True, False, False, False, False),
}

_API_SLOTS = [
    "f95_enable", "f95_full", "dlsite_enable", "create_package",
    "lc_enable", "lc_full", "f95_new_only", "f95_ts_only",
]


def _build_api_argv(values: dict) -> List[str]:
    mode = values.get("mode") or "Incremental (default)"
    if mode == "Custom (use the checkboxes)":
        flags = [bool(values.get(k)) for k in _API_SLOTS]
    else:
        flags = list(API_MODES[mode])
    return ["true" if f else "false" for f in flags]


API_TASK = Task(
    id="api",
    label="Scrape + build package",
    group="Production",
    module="api",
    help=(
        "The main scrape entry point the server runs on a schedule. Pick a run "
        "mode, or choose Custom to set the eight positional flags yourself. "
        "The generated command line is shown before it runs."
    ),
    long_running=True,
    build_argv=_build_api_argv,
    params=[
        Param("mode", "Run mode", CHOICE,
              default="Incremental (default)",
              choices=list(API_MODES) + ["Custom (use the checkboxes)"],
              help="Expands to the documented positional flag combination."),
        Param("f95_enable", "Scrape F95", FLAG, default=True,
              only_when=("mode", ["Custom (use the checkboxes)"])),
        Param("f95_full", "F95 full re-crawl (re-fetch every detail page)", FLAG,
              default=False, only_when=("mode", ["Custom (use the checkboxes)"])),
        Param("dlsite_enable", "Scrape DLsite", FLAG, default=False,
              only_when=("mode", ["Custom (use the checkboxes)"])),
        Param("create_package", "Build package afterwards", FLAG, default=True,
              only_when=("mode", ["Custom (use the checkboxes)"])),
        Param("lc_enable", "Scrape LewdCorner", FLAG, default=False,
              only_when=("mode", ["Custom (use the checkboxes)"])),
        Param("lc_full", "LewdCorner: walk every feed page", FLAG, default=False,
              only_when=("mode", ["Custom (use the checkboxes)"])),
        Param("f95_new_only", "F95 new-only sweep", FLAG, default=False,
              only_when=("mode", ["Custom (use the checkboxes)"])),
        Param("f95_ts_only", "F95 ts-only sweep (never opens a detail page)", FLAG,
              default=False, only_when=("mode", ["Custom (use the checkboxes)"])),
    ],
)


TASKS: List[Task] = [
    API_TASK,

    Task(
        id="backup",
        label="Rebuild master package",
        group="Production",
        module="backup",
        help=("Truncates the updates table and rebuilds a full master package "
              "(start_time=0, so every row exports). Clients will re-download "
              "a full base package after this."),
        danger=True,
        danger_note="This TRUNCATES the `updates` table before rebuilding.",
        long_running=True,
    ),

    Task(
        id="refresh_worker",
        label="F95 refresh-queue worker",
        group="Production",
        module="f95_refresh_worker",
        help=("Consumes f95_refresh_queue, one game every REFRESH_INTERVAL "
              "seconds. Daemon mode runs until you press Stop."),
        long_running=True,
        params=[
            Param("mode", "Mode", CHOICE, default="Daemon (run until stopped)",
                  choices=["Daemon (run until stopped)",
                           "Once (single item, then exit)",
                           "Drain (everything pending, then exit)"],
                  value_map={"Daemon (run until stopped)": None,
                             "Once (single item, then exit)": "--once",
                             "Drain (everything pending, then exit)": "--drain"}),
        ],
    ),

    # --- refresh -----------------------------------------------------------
    Task(
        id="refresh_game",
        label="Refresh specific game(s) by F95 id",
        group="Refresh",
        module="tools.refresh.refresh_game",
        help=("Full single-game re-scan: rewrites tags, downloads, screens, "
              "overview, prefixes and external ids. Same code path the queue "
              "worker uses."),
        params=[
            Param("ids", "F95 thread id(s)", TEXT, default="",
                  help="One or more numeric ids, separated by spaces."),
        ],
    ),

    Task(
        id="refresh_missing_tags",
        label="Refresh all games missing tags",
        group="Refresh",
        module="tools.refresh.refresh_missing_tags",
        help=("Finds every f95_zone row with an empty tags column and does a "
              "full refresh of each. Paced by F95_DELAY_MIN/MAX, so this is "
              "intentionally slow."),
        long_running=True,
        params=[
            Param("dry_run", "Dry run (list only, fetch nothing)", FLAG,
                  default=True, arg="--dry-run"),
            Param("limit", "Limit", INT, default="", arg="--limit",
                  help="Only process the first N games. Blank = all."),
        ],
    ),

    # --- diagnostics (read-only) -------------------------------------------
    Task(
        id="check_thread_updates",
        label="Check unset thread_updated counts",
        group="Diagnostics (read-only)",
        module="tools.diagnostics.check_thread_updates",
        help=("How many f95_zone rows still have thread_updated NULL/0. A high "
              "fraction explains an incremental run that never early-stops."),
    ),

    Task(
        id="find_duplicates",
        label="Find duplicate games",
        group="Diagnostics (read-only)",
        module="tools.diagnostics.find_duplicates",
        help="Never writes. Only SELECTs. Use reconcile to actually resolve.",
        params=[
            Param("scope", "Scope", CHOICE, default="all", arg="--scope",
                  choices=["all", "f95", "lc", "cross"]),
            Param("fuzzy_floor", "Fuzzy floor", FLOAT, default="0.90",
                  arg="--fuzzy-floor",
                  help="Similarity threshold for the fuzzy detector."),
            Param("no_fuzzy", "Exact matches only (skip fuzzy)", FLAG,
                  default=False, arg="--no-fuzzy"),
            Param("csv_path", "Also dump to CSV", FILE, default="", arg="--csv"),
        ],
    ),

    Task(
        id="diagnose_manual_links",
        label="Diagnose one game's external_ids export",
        group="Diagnostics (read-only)",
        module="tools.diagnostics.diagnose_manual_links",
        help=("Shows stored external_ids, every atlas_manual_links row, and the "
              "post-overlay result a client would receive."),
        params=[
            Param("atlas_id", "atlas_id", INT, default="",
                  help="Required."),
        ],
    ),

    Task(
        id="verify_package",
        label="Verify a package on disk",
        group="Diagnostics (read-only)",
        module="tools.diagnostics.verify_package",
        help=("Reads the newest base .update (LZ4) and prints the external_ids "
              "actually written for one atlas_id."),
        params=[
            Param("atlas_id", "atlas_id", INT, default="", help="Required."),
            Param("pkg_dir", "Package dir override", DIR, default="",
                  help="Blank = whatever PACKAGE_DIR resolves to."),
        ],
    ),

    # --- backfill (dry run unless --apply) ---------------------------------
    Task(
        id="backfill_atlas_export",
        label="Backfill stale atlas export timestamps",
        group="Backfill",
        module="tools.backfill.backfill_atlas_export",
        help=("Bumps atlas.last_record_update on rows behind a linked f95/lc "
              "source row. Dry run unless Apply is ticked. Safe to re-run."),
        params=[
            Param("apply", "Apply (without this it only counts)", FLAG,
                  default=False, arg="--apply"),
            Param("all_linked", "Also bump every dlsite/sxs-linked row", FLAG,
                  default=False, arg="--all-linked"),
        ],
    ),

    Task(
        id="backfill_lc_atlas_export",
        label="Backfill LewdCorner atlas timestamps",
        group="Backfill",
        module="tools.backfill.backfill_lc_atlas_export",
        help=('Fixes games showing as "LewdCorner #<lc_id>" on the client. '
              "Dry run unless Apply is ticked."),
        params=[
            Param("apply", "Apply (without this it only counts)", FLAG,
                  default=False, arg="--apply"),
            Param("stale_only", "Only rows actually at risk (stale)", FLAG,
                  default=False, arg="--stale-only"),
        ],
    ),

    Task(
        id="backfill_manual_links_export",
        label="Backfill manual-link export timestamps",
        group="Backfill",
        module="tools.backfill.backfill_manual_links_export",
        help=("Re-exports every atlas row that has admin manual links, so the "
              "next delta package carries them. Dry run unless Apply."),
        params=[
            Param("apply", "Apply (without this it only counts)", FLAG,
                  default=False, arg="--apply"),
        ],
    ),

    # --- maintenance -------------------------------------------------------
    Task(
        id="cleanup_version_titles",
        label='Delete titles corrupted with " - Version:"',
        group="Maintenance",
        module="tools.maintenance.cleanup_version_titles",
        help=("Deletes atlas rows (and their lewdcorner row) whose title was "
              "corrupted by the old LC title-parsing bug. Never deletes a row "
              "another source still references. Dry run unless Apply."),
        danger=True,
        danger_note="With Apply ticked this DELETES atlas and lewdcorner rows.",
        params=[
            Param("apply", "Apply (actually delete)", FLAG, default=False,
                  arg="--apply"),
        ],
    ),

    Task(
        id="import_f95_csv",
        label="Import F95 games from CSV",
        group="Maintenance",
        module="tools.maintenance.import_f95_csv",
        help=("Inserts new atlas/f95_zone rows from a CSV export. Never "
              "modifies existing rows. Sequel-looking matches are asked about "
              "one at a time unless you pick an auto mode."),
        interactive=True,
        params=[
            Param("csv_path", "CSV file", FILE, default="", help="Required."),
            Param("threshold", "Match threshold", FLOAT, default="0.70",
                  arg="--threshold",
                  help="Above this, a row is treated as a probable duplicate."),
            Param("sequel_mode", "Sequel handling", CHOICE,
                  default="Prompt for each",
                  choices=["Prompt for each", "Auto-create as new",
                           "Skip as duplicates"],
                  value_map={"Prompt for each": None,
                             "Auto-create as new": "--approve-sequels",
                             "Skip as duplicates": "--skip-sequels"}),
            Param("dry_run", "Dry run", FLAG, default=True, arg="--dry-run"),
            Param("limit", "Limit rows", INT, default="", arg="--limit"),
        ],
    ),

    Task(
        id="reconcile_lc",
        label="Reconcile LewdCorner <-> atlas",
        group="Maintenance",
        module="tools.maintenance.reconcile_lc",
        help=("cleanup: fix existing mis-linked rows.  fuzzy: review fuzzy "
              "candidates.  queue: work lc_review_queue.  defer: bulk-park "
              "high-scoring matches without prompting."),
        interactive=True,
        danger=True,
        danger_note=("cleanup and queue can delete orphaned atlas rows (each "
                     "one asks first); defer deletes rows in bulk."),
        params=[
            Param("cmd", "Subcommand", CHOICE, default="cleanup",
                  choices=["cleanup", "fuzzy", "queue", "defer"]),
            Param("fuzzy_floor", "Floor", FLOAT, default="0.55", arg="--floor",
                  only_when=("cmd", ["fuzzy"])),
            Param("fuzzy_auto", "Auto-accept at/above", FLOAT, default="",
                  arg="--auto", only_when=("cmd", ["fuzzy"]),
                  help="Blank = always ask."),
            Param("kind", "Queue kind", CHOICE, default="(all)", arg="--kind",
                  choices=["(all)", "multi", "fuzzy"],
                  only_when=("cmd", ["queue"]),
                  value_map={"(all)": None, "multi": "multi", "fuzzy": "fuzzy"}),
            Param("threshold", "Threshold", FLOAT, default="0.8",
                  arg="--threshold", only_when=("cmd", ["defer"])),
            Param("defer_floor", "Floor", FLOAT, default="0.55", arg="--floor",
                  only_when=("cmd", ["defer"])),
            Param("defer_dry", "Dry run", FLAG, default=True, arg="--dry-run",
                  only_when=("cmd", ["defer"])),
        ],
    ),
]

BY_ID = {t.id: t for t in TASKS}

GROUPS: List[str] = []
for _t in TASKS:
    if _t.group not in GROUPS:
        GROUPS.append(_t.group)


def visible(param: Param, values: dict) -> bool:
    """Whether a param applies given the currently selected values."""
    if param.only_when is None:
        return True
    other, allowed = param.only_when
    return values.get(other) in allowed


def build_argv(task: Task, values: dict) -> List[str]:
    """Turn a dict of form values into the argv list the tool expects."""
    if task.build_argv is not None:
        return task.build_argv(values)

    positional: List[str] = []
    flags: List[str] = []

    for p in task.params:
        if not visible(p, values):
            continue
        raw = values.get(p.key)

        if p.kind == FLAG:
            if raw:
                flags.append(p.arg or p.key)
            continue

        # value_map lets a dropdown pick produce a bare flag or nothing at all
        if p.value_map is not None:
            mapped = p.value_map.get(raw, None)
            if mapped is None:
                continue
            if p.arg:
                flags.extend([p.arg, str(mapped)])
            else:
                flags.append(str(mapped))
            continue

        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue

        if p.positional:
            # "ids" style fields can carry several whitespace-separated values
            positional.extend(text.split())
        else:
            flags.extend([p.arg, text])

    return positional + flags


def preview(task: Task, values: dict) -> str:
    """Human-readable equivalent command line, shown in the GUI."""
    argv = build_argv(task, values)
    if task.module in ("api", "backup", "f95_refresh_worker"):
        script = f"{task.module}.py"
    else:
        script = task.module.replace(".", "/") + ".py"
    return " ".join(["python", script] + argv)
