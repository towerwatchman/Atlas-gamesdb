"""
Verify that the most recent package on disk actually contains the manual-link
overlay for a given atlas_id -- i.e. that backup.py emitted steam_appids into
the .update file the client downloads.

Resolves the package directory the same way the app does (config.package_dir(),
honoring PACKAGE_DIR / PACKAGE_DIR_REMOTE), so it always looks where backup.py
wrote. Reads the newest base .update (LZ4), finds the atlas row, and prints its
external_ids.

Usage:
    python verify_package.py <atlas_id>
    python verify_package.py <atlas_id> /explicit/package/dir   # override
"""
import glob
import json
import os
import sys

import lz4.frame

try:
    from scraper.config import config
    _DEFAULT_DIR = config.package_dir()
except Exception:
    _DEFAULT_DIR = os.environ.get("PACKAGE_DIR") or os.environ.get(
        "PACKAGE_DIR_REMOTE", "/var/www/html/packages")


def main():
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print("usage: python verify_package.py <atlas_id> [package_dir]")
        return
    atlas_id = int(sys.argv[1])
    pkg_dir = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_DIR

    print(f"package dir : {pkg_dir}")
    if not os.path.isdir(pkg_dir):
        print("  ERROR: that directory does not exist. Set PACKAGE_DIR or pass "
              "the path as the 2nd arg.")
        return

    # backup.py writes the base package as <epoch>.update at the top level; the
    # daily backup goes under backup/. Look at top-level .update files first.
    candidates = sorted(
        glob.glob(os.path.join(pkg_dir, "*.update")),
        key=os.path.getmtime, reverse=True,
    )
    if not candidates:
        # Fall back to a recursive search in case of a different layout.
        candidates = sorted(
            glob.glob(os.path.join(pkg_dir, "**", "*.update"), recursive=True),
            key=os.path.getmtime, reverse=True,
        )
    if not candidates:
        print("  ERROR: no .update files found. Did backup.py run and write "
              "here? Check PACKAGE_DIR / PACKAGE_DIR_REMOTE.")
        return

    newest = candidates[0]
    print(f"newest file : {newest}")
    try:
        data = json.loads(lz4.frame.decompress(open(newest, "rb").read()))
    except Exception as e:
        print("  ERROR decompressing/parsing:", e)
        return

    print(f"is_full flag: {data.get('full')}")
    atlas_rows = data.get("atlas") or []
    print(f"atlas rows in package: {len(atlas_rows)}")

    row = next((r for r in atlas_rows if int(r.get("atlas_id", -1)) == atlas_id), None)
    if not row:
        print(f"  atlas_id {atlas_id} NOT in this package. If this was a delta "
              f"(is_full=0), the row may not have changed since start_time; run "
              f"backup.py for a full export, or bump the row.")
        return

    ext_raw = row.get("external_ids")
    print(f"\nexternal_ids in package for atlas_id {atlas_id}:")
    try:
        parsed = json.loads(ext_raw) if isinstance(ext_raw, str) else ext_raw
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        steam = parsed.get("steam_appids") or (
            [parsed["steam_appid"]] if parsed.get("steam_appid") else [])
        print(f"\nsteam ids the client will receive: {steam}")
        print("RESULT:", "OK - multiple ids present" if len(steam) > 1
              else ("single id only" if steam else "NO steam ids"))
    except Exception as e:
        print("  could not parse:", e, "\n  raw:", ext_raw)


if __name__ == "__main__":
    main()
