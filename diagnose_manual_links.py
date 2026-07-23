"""
Diagnose what the export would produce for one atlas row's external_ids.

Given an atlas_id, prints:
  1. the raw atlas.external_ids as stored,
  2. every row in atlas_manual_links for it,
  3. the external_ids AFTER the export-time manual-link overlay (exactly what a
     client would receive from backup.py / the daily package).

If step 2 is empty, the ids were never written to atlas_manual_links -- so no
export can surface them. That points at the admin write path, not the export.

Usage:
    python diagnose_manual_links.py <atlas_id>
"""
import json
import sys

from scraper.types.eTypes import database
from scraper.utils.db import _run, _merge_manual_links_into_external_ids


def main():
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print("usage: python diagnose_manual_links.py <atlas_id>")
        return
    atlas_id = int(sys.argv[1])
    db_type = database.REMOTE

    row = _run(
        "SELECT atlas_id, title, external_ids, last_record_update "
        "FROM atlas WHERE atlas_id = %s",
        (atlas_id,), fetch="one", dict_cursor=True,
    )
    if not row:
        print(f"No atlas row #{atlas_id}.")
        return

    print(f"atlas_id       : {row['atlas_id']}")
    print(f"title          : {row.get('title')}")
    print(f"last_record_update: {row.get('last_record_update')}")
    print(f"stored external_ids: {row.get('external_ids')}")
    print()

    links = _run(
        "SELECT link_id, kind, ext_id, url, added_by, added_at "
        "FROM atlas_manual_links WHERE atlas_id = %s ORDER BY link_id",
        (atlas_id,), fetch="all", dict_cursor=True,
    ) or []
    print(f"atlas_manual_links rows: {len(links)}")
    for l in links:
        print(f"  #{l['link_id']}  kind={l['kind']!r}  ext_id={l['ext_id']!r}  "
              f"url={l['url']!r}  by={l['added_by']}")
    if not links:
        print("  (none) -> nothing to overlay. The ids were never written to "
              "atlas_manual_links; check the admin add-link path.")
    print()

    # Run the exact overlay the export uses, on a copy of this row.
    merged = _merge_manual_links_into_external_ids([dict(row)])
    print("external_ids AFTER overlay (what the client receives):")
    try:
        parsed = json.loads(merged[0].get("external_ids") or "{}")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        steam_ids = parsed.get("steam_appids") or (
            [parsed["steam_appid"]] if parsed.get("steam_appid") else [])
        print()
        print(f"steam ids the client will see: {steam_ids}")
    except (ValueError, TypeError) as e:
        print("  could not parse merged external_ids:", e)
        print("  raw:", merged[0].get("external_ids"))


if __name__ == "__main__":
    main()
