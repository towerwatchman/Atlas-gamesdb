"""
Single entry point for both the window and the headless task runner.

    AtlasTools.exe                              -> open the GUI
    AtlasTools.exe --child <task_id> [args...]  -> run one task, headless
    AtlasTools.exe --list                       -> print every task id

    python -m atlas_tools                       -> same, from a checkout
"""
import sys


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    if argv and argv[0] == "--list":
        from atlas_tools.registry import GROUPS, TASKS
        for group in GROUPS:
            print(f"\n{group}")
            for task in TASKS:
                if task.group == group:
                    print(f"  {task.id:<30} {task.label}")
        return 0

    if argv and argv[0] == "--child":
        from atlas_tools.child import main as child_main
        return child_main(argv[1:])

    from atlas_tools.gui import launch
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
