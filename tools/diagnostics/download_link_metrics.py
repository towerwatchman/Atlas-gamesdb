#!/usr/bin/env python3
"""Metrics over the stored download links in f95_zone.

Answers two questions that are currently being decided on a five-row sample:

  1. Which file hosts should get plugins first?
     Not by link count - by COVERAGE. A host that appears twice on every
     thread is worth less than one that is the only option on a few hundred.
     What matters is how many games have at least one supported host, so
     this reports incremental coverage as hosts are added in greedy order.

  2. What is the real vocabulary of the `group` field?
     The platform/kind classifier has to be written against this, and so far
     it has only been seen on a handful of threads ("Win", "All", "Others",
     "", "Win/Linux", "Mac", "Android"). Guessing at the rest is how an
     "Update Only" patch ends up queued as a full game and overwrites a
     working install.

Read-only. Opens one connection, runs SELECTs, exits.

Usage:
    python tools/diagnostics/download_link_metrics.py
    python tools/diagnostics/download_link_metrics.py --top 30
    python tools/diagnostics/download_link_metrics.py --json metrics.json
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scraper.utils.db import _new_connection  # noqa: E402

# Columns holding the same JSON link structure.
LINK_COLUMNS = ("downloads", "patches", "extras", "translations")


def load_rows(connection, table="f95_zone"):
    columns = ", ".join(LINK_COLUMNS)
    cursor = connection.cursor()
    cursor.execute(f"SELECT f95_id, {columns} FROM {table}")
    rows = cursor.fetchall()
    cursor.close()
    return rows


def parse_links(raw):
    """The column is JSON text. Tolerate null, empty and malformed."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def normalise_host(host, url=""):
    """Host is inconsistent in the data - some carry a tld, some do not
    ('mega.nz' vs 'mixdrop', 'pixeldrain.com' vs 'uploadhaven'). Fold to a
    bare second-level name so counts are not split across spellings."""
    value = (host or "").strip().lower()
    if not value and url:
        try:
            from urllib.parse import urlparse
            value = urlparse(url).netloc.lower()
        except Exception:  # noqa: BLE001
            value = ""
    value = value.removeprefix("www.")
    # Masked urls put the destination host in the path, so the stored host is
    # already the real one; just strip the tld for grouping.
    parts = value.split(".")
    return parts[0] if parts and parts[0] else value or "(unknown)"


def greedy_coverage(games_by_host, total_games, limit=12):
    """Order hosts by how many NEW games each one adds.

    This is the number that should drive plugin priority. Raw link counts
    overstate hosts that appear alongside everything else.
    """
    remaining = {game for games in games_by_host.values() for game in games}
    covered = set()
    order = []
    pool = dict(games_by_host)
    while pool and len(order) < limit:
        best_host, best_new = None, set()
        for host, games in pool.items():
            new = games - covered
            if len(new) > len(best_new):
                best_host, best_new = host, new
        if not best_host or not best_new:
            break
        covered |= best_new
        order.append({
            "host": best_host,
            "new_games": len(best_new),
            "cumulative": len(covered),
            "cumulative_pct": round(100 * len(covered) / total_games, 1) if total_games else 0.0,
        })
        pool.pop(best_host)
    return order, len(remaining)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=20, help="rows per table")
    parser.add_argument("--table", default="f95_zone", help="source table")
    parser.add_argument("--json", metavar="PATH", help="also write raw metrics as json")
    args = parser.parse_args()

    connection = _new_connection()
    try:
        rows = load_rows(connection, args.table)
    finally:
        connection.close()

    print(f"Scanned {len(rows)} rows from {args.table}\n")

    host_links = Counter()
    host_games = defaultdict(set)
    group_counts = Counter()
    group_by_host = defaultdict(Counter)
    type_counts = Counter()
    masked_by_host = defaultdict(lambda: [0, 0])  # [masked, unmasked]
    bucket_counts = Counter()
    games_with_downloads = set()
    label_counts = Counter()

    for row in rows:
        f95_id = row[0]
        for column_index, column in enumerate(LINK_COLUMNS, start=1):
            links = parse_links(row[column_index])
            if links:
                bucket_counts[column] += len(links)
            if column != "downloads":
                continue
            if links:
                games_with_downloads.add(f95_id)
            for link in links:
                if not isinstance(link, dict):
                    continue
                host = normalise_host(link.get("host"), link.get("url", ""))
                host_links[host] += 1
                host_games[host].add(f95_id)
                group = (link.get("group") or "").strip()
                group_counts[group or "(empty)"] += 1
                group_by_host[host][group or "(empty)"] += 1
                type_counts[(link.get("type") or "(none)")] += 1
                label_counts[(link.get("label") or "(none)").strip().upper()] += 1
                masked_by_host[host][0 if link.get("masked") else 1] += 1

    total_games = len(games_with_downloads)
    print(f"Games with at least one download link: {total_games}")
    print(f"Total download links: {sum(host_links.values())}")
    print(f"Links per bucket: " + ", ".join(
        f"{name}={bucket_counts.get(name, 0)}" for name in LINK_COLUMNS) + "\n")

    print("=" * 72)
    print("HOSTS BY GAME COVERAGE")
    print("=" * 72)
    print(f"{'host':<20}{'games':>8}{'% games':>9}{'links':>8}{'masked':>9}{'open':>7}")
    for host, games in sorted(host_games.items(), key=lambda kv: -len(kv[1]))[: args.top]:
        masked, unmasked = masked_by_host[host]
        pct = 100 * len(games) / total_games if total_games else 0
        print(f"{host:<20}{len(games):>8}{pct:>8.1f}%{host_links[host]:>8}"
              f"{masked:>9}{unmasked:>7}")

    print()
    print("=" * 72)
    print("PLUGIN PRIORITY - incremental coverage, greedy order")
    print("=" * 72)
    print("Each row is the host that adds the most games not already covered.")
    print("This is the order that reaches usable coverage with fewest plugins.\n")
    order, _ = greedy_coverage(host_games, total_games)
    print(f"{'#':<4}{'host':<20}{'new games':>11}{'cumulative':>12}{'% of all':>10}")
    for index, entry in enumerate(order, start=1):
        print(f"{index:<4}{entry['host']:<20}{entry['new_games']:>11}"
              f"{entry['cumulative']:>12}{entry['cumulative_pct']:>9.1f}%")

    print()
    print("=" * 72)
    print("GROUP VOCABULARY - drives the platform/kind classifier")
    print("=" * 72)
    for group, count in group_counts.most_common(args.top * 2):
        print(f"  {count:>7}  {group}")
    if len(group_counts) > args.top * 2:
        print(f"  ... and {len(group_counts) - args.top * 2} more distinct values")
    print(f"\n  {len(group_counts)} distinct group values total")

    print()
    print("=" * 72)
    print("LABEL VOCABULARY")
    print("=" * 72)
    for label, count in label_counts.most_common(args.top):
        print(f"  {count:>7}  {label}")

    print()
    print("=" * 72)
    print("TYPE FIELD")
    print("=" * 72)
    for value, count in type_counts.most_common():
        print(f"  {count:>7}  {value}")

    if args.json:
        payload = {
            "total_games": total_games,
            "host_links": dict(host_links),
            "host_games": {host: len(games) for host, games in host_games.items()},
            "greedy_order": order,
            "groups": dict(group_counts),
            "labels": dict(label_counts),
            "types": dict(type_counts),
            "buckets": dict(bucket_counts),
            "masked_by_host": {host: {"masked": counts[0], "unmasked": counts[1]}
                               for host, counts in masked_by_host.items()},
        }
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        print(f"\nRaw metrics written to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
