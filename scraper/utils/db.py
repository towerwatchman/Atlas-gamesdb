"""
Database access layer. MySQL only -- there is no SQLite/local fallback.

Connection handling: a single connection is opened once and reused for the
whole process, instead of opening a fresh connection per query. Reconnecting
to a remote MySQL host (TCP + auth handshake) on every single SELECT/INSERT
has real, noticeable latency, and it was the actual cause of multi-second
per-listing-page delays -- a page of ~90 items does at least one query per
item (more for ones that get written), so that overhead was being paid
hundreds of times per page. _run() below reconnects automatically, but only
when a query actually fails because the connection had genuinely dropped.

Refactor notes vs the original:
  * One _run() helper instead of ~13 copies of the connect/cursor/close block.
  * Parameterised queries everywhere (no string-built WHERE clauses).
  * Table names are whitelisted before being interpolated.
  * Credentials come from the environment via config (no plaintext here).
"""
import json
import re
import time

import mysql.connector
from mysql.connector import errors as mysql_errors

from scraper.tables.base import query
from scraper.types.eTypes import database
from scraper.config import config

# Only these tables may be interpolated into SQL (defence against injection
# via scraped data flowing into table/column positions).
ALLOWED_TABLES = {
    "atlas", "f95_zone", "updates", "dlsite", "dlsite_circle",
    "lewdcorner", "sxs", "test", "lc_review_queue", "f95_refresh_queue",
}

_conn = None  # the one shared connection for this process; see _connect().


def _check_table(table):
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Refusing to use non-whitelisted table name: {table!r}")
    return table


def _new_connection():
    # autocommit=True is load-bearing, not a style choice: without it, every
    # read-only _run() call (fetch="one"/"all", commit=False -- the default,
    # and most call sites) leaves its transaction open indefinitely, since
    # nothing ever commits it. That's invisible for a short-lived script like
    # api.py, which exits and drops the connection soon after. It is NOT
    # invisible for a long-running daemon (f95_refresh_worker.py / atlas-worker)
    # that polls the DB every few seconds forever: the first read-only poll
    # after startup opens a transaction that then never closes, holding a
    # metadata lock on every table it has ever read from until the process
    # exits or happens to run a commit=True write.
    #
    # Confirmed directly: with an idle worker running, `ALTER TABLE
    # f95_refresh_queue ADD COLUMN ...` (migration 009) hung indefinitely --
    # information_schema.INNODB_TRX showed the worker's connection sitting in
    # a RUNNING transaction with trx_query=NULL, i.e. blocked on nothing,
    # holding the lock the ALTER needed simply because it had never committed.
    # Once that connection closed, the exact same ALTER completed instantly.
    return mysql.connector.connect(
        user=config.db_user(),
        password=config.db_password(),
        host=config.host(),
        database=config.database(),
        autocommit=True,
    )


def _connect(db_type=None):
    """Return (connection, "%s"). db_type is accepted-but-ignored for
    call-site compatibility. Opens a connection on first use only; after
    that, _run() reuses it and only reconnects if a query actually fails."""
    global _conn
    if _conn is None:
        _conn = _new_connection()
    return _conn, "%s"


def _run(sql, params=(), commit=False, fetch=None, dict_cursor=False):
    """Execute one statement on the shared connection. Reconnects and
    retries exactly once if the connection had genuinely dropped (e.g. an
    idle timeout during a long-running scrape) -- not on every call.

    fetch="one" always fully drains the cursor (via fetchall(), taking just
    the first row) rather than calling fetchone() and stopping there. A
    bare fetchone() on a query that returns more than one row leaves the
    rest sitting unread on the connection, and Connector/Python refuses to
    run the NEXT query on that connection until those are drained -- it
    raises "Unread result found" on whatever runs next, which can look like
    an unrelated, random failure several calls later. Every "one row"
    call site should also have its own LIMIT 1 for clarity/efficiency, but
    this makes the unread-results class of bug impossible even if one is
    missing.
    """
    global _conn
    for attempt in (1, 2):
        con, _ = _connect()
        try:
            cur = con.cursor(dictionary=True) if dict_cursor else con.cursor()
            cur.execute(sql, params)
            if commit:
                con.commit()
            if fetch == "one":
                all_rows = cur.fetchall()
                result = all_rows[0] if all_rows else None
            elif fetch == "all":
                result = cur.fetchall()
            elif commit:
                result = cur.lastrowid
            else:
                result = None
            cur.close()
            return result
        except mysql_errors.OperationalError:
            # Connection actually dropped -- drop it and let the next loop
            # iteration open a fresh one and retry once.
            try:
                con.close()
            except Exception:
                pass
            _conn = None
            if attempt == 2:
                raise


# ---------------------------------------------------------------- writes

def UpdatetableDynamic(table, values, db_type=None):
    """Upsert a dict of column->value into `table`."""
    _check_table(table)
    if not values:
        return
    # Any atlas write must bump its export timestamp (see
    # _ensure_atlas_export_timestamp). Covers callers that upsert the atlas table
    # directly (e.g. the dlsite agent) without stamping it themselves.
    if table == "atlas":
        values = _ensure_atlas_export_timestamp(dict(values))
    cols = list(values.keys())
    col_sql = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    params = [int(v) if isinstance(v, bool) else v for v in values.values()]
    updates = ", ".join(f"{c}=VALUES({c})" for c in cols)
    sql = (
        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {updates}"
    )
    _run(sql, params, commit=True)


def insertAtlas(values, db_type=None):
    """Insert a brand-new atlas row and return its generated atlas_id.

    Used for threads we have never seen before. Plain INSERT (no REPLACE) so
    the AUTO_INCREMENT atlas_id is assigned once and never churns.
    """
    if not values:
        raise ValueError("insertAtlas called with empty values")
    values = _ensure_atlas_export_timestamp(dict(values))
    cols = list(values.keys())
    col_sql = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    params = [int(v) if isinstance(v, bool) else v for v in values.values()]
    return _run(
        f"INSERT INTO atlas ({col_sql}) VALUES ({placeholders})",
        params, commit=True,
    )


def _ensure_atlas_export_timestamp(values):
    """Guarantee an atlas row carries a fresh last_record_update so the delta
    packager (WHERE last_record_update > start_time) actually exports it.

    The single most common data-sync bug in this codebase: a source (F95, Steam,
    dlsite, LewdCorner) writes or links an atlas row without bumping this
    timestamp, so the row silently falls out of the client's incremental update
    and the new/changed data never reaches users. Stamping it here, at the shared
    db layer, means EVERY atlas insert/update/upsert exports regardless of which
    caller wrote it -- no caller has to remember.

    An explicitly-provided value is preserved (migrations/backfills may set a
    specific timestamp on purpose); only a missing/blank one is filled.
    """
    if values is None:
        return values
    existing = values.get("last_record_update")
    if existing is None or existing == "" or existing == 0:
        values["last_record_update"] = int(time.time())
    return values


# Columns an admin lock may never cover. `last_record_update` is export
# bookkeeping the delta packager depends on -- if a lock could freeze it, the
# row would drop out of every future package and its changes would never reach
# clients. atlas_id is the key.
_UNLOCKABLE_ATLAS_COLUMNS = {"atlas_id", "last_record_update"}


def getLockedAtlasFields(atlas_id, db_type=None):
    """Column names on this atlas row that an admin has locked.

    Locks are set in the admin portal: editing a field there marks it as
    human-owned. Returns a set; an empty set for rows with no locks, and for a
    database that predates migration 008 (the column simply won't exist, which
    is caught rather than raised so an un-migrated deploy still scrapes).
    """
    try:
        rows = _run(
            "SELECT locked_fields FROM atlas WHERE atlas_id = %s",
            (atlas_id,), fetch="one")
    except mysql_errors.ProgrammingError as exc:
        # 1054 = unknown column: the database predates migration 008. Treat that
        # as "no locks" so an un-migrated deploy still scrapes.
        #
        # Deliberately NOT a bare `except Exception`. If a connection drops or
        # the query fails for any other reason, swallowing it here would report
        # "no locks" and the crawl would go on to overwrite every admin edit on
        # the row -- exactly the bug this function exists to prevent. Better to
        # fail loudly; the UPDATE that follows would have failed anyway.
        if getattr(exc, "errno", None) == 1054:
            return set()
        raise
    if not rows:
        return set()
    raw = rows[0] if isinstance(rows, (list, tuple)) else rows
    if isinstance(raw, dict):
        raw = raw.get("locked_fields")
    if not raw:
        return set()
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(f) for f in parsed} - _UNLOCKABLE_ATLAS_COLUMNS

def updateAtlasById(atlas_id, values, db_type=None):
    """Update an existing atlas row in place by its atlas_id.

    Unlike UpdatetableDynamic (which upserts on a natural key), this targets a
    known primary-key row and only writes the provided columns. The atlas_id
    itself is never part of the SET clause. Bumps last_record_update via
    _ensure_atlas_export_timestamp so the change is picked up by the delta
    packager.
    """
    if not values:
        return
    values = _ensure_atlas_export_timestamp(dict(values))

    # Drop anything an admin has claimed. Without this the crawl overwrites
    # human edits every time the thread is re-scraped -- the reason a corrected
    # version number would silently revert to whatever the thread title says.
    locked = getLockedAtlasFields(atlas_id, db_type)
    if locked:
        skipped = [c for c in values if c in locked]
        for c in skipped:
            values.pop(c, None)
        if skipped:
            print(f"  atlas {atlas_id}: keeping admin values for "
                  f"{', '.join(sorted(skipped))}")

    cols = [c for c in values.keys() if c != "atlas_id"]
    if not cols:
        return
    set_sql = ", ".join(f"{c} = %s" for c in cols)
    params = [int(values[c]) if isinstance(values[c], bool) else values[c]
              for c in cols]
    params.append(atlas_id)
    _run(f"UPDATE atlas SET {set_sql} WHERE atlas_id = %s", params, commit=True)


def TruncateUpdatesTable(db_type=None):
    _run("DELETE FROM updates", commit=True)


# ---------------------------------------------------------------- schema

def CreateDatabase(db_type=None):
    for stmt in (
        query.createAtlasTable(db_type),
        query.createF95Table(db_type),
        query.createUpdateTable(db_type),
        query.createDlsiteCircleTable(db_type),
        query.createDlsiteTable(db_type),
        query.createLewdcornereTable(db_type),
        query.createLcReviewQueueTable(db_type),
        query.createF95RefreshQueueTable(db_type),
        query.createSxsTable(db_type),
    ):
        _run(stmt, commit=True)
    _ensure_indexes()


def _ensure_indexes():
    """Create helpful indexes if missing. The match path (both the reconciler
    and every normal scrape) filters atlas by id_name; without an index that's
    a full table scan per lookup, which is what made the reconciler appear to
    hang on a large atlas table. Guarded so re-running is a no-op and an
    already-existing index (or a MySQL build that lacks IF NOT EXISTS on
    CREATE INDEX) doesn't raise."""
    idx = [
        ("idx_atlas_id_name", "CREATE INDEX idx_atlas_id_name ON atlas (id_name)"),
    ]
    for name, ddl in idx:
        try:
            _run(ddl, commit=True)
        except Exception:
            # Index already exists (error 1061) or similar -- safe to ignore.
            pass


def DeleteTables(db_type=None):
    for t in ("atlas", "test", "f95_zone"):
        _run(query.deleteTable(_check_table(t)), commit=True)


# ---------------------------------------------------------------- reads

def getLastUpdate(db_type, f95_id):
    """Returns the stored thread_updated for this f95_id, or 0 if unseen/
    unset. thread_updated -- not last_thread_comment -- is the freshness
    comparison field: last_thread_comment (raw forum reply activity) was
    producing too many false positives, since a thread can get new replies
    without the game itself actually updating."""
    row = _run(
        "SELECT thread_updated FROM f95_zone WHERE f95_id = %s LIMIT 1",
        (f95_id,), fetch="one",
    )
    return row[0] if row and row[0] is not None else 0


def getLastUpdatesBulk(f95_ids, db_type=None):
    """Batch version of getLastUpdate: one round trip for a whole page of
    items instead of one round trip per item. Returns
    {f95_id: thread_updated}; ids with no row (or a NULL value) are simply
    absent, so the caller should default missing keys to 0."""
    ids = [str(i) for i in f95_ids if i is not None]
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    rows = _run(
        f"SELECT f95_id, thread_updated FROM f95_zone "
        f"WHERE f95_id IN ({placeholders})",
        ids, fetch="all",
    ) or []
    return {str(f95_id): (thread_updated or 0) for f95_id, thread_updated in rows}


def getLcThreadUpdated(lc_id, db_type=None):
    """LewdCorner equivalent of getLastUpdate: stored thread_updated for
    this lc_id, or 0 if unseen/unset."""
    row = _run(
        "SELECT thread_updated FROM lewdcorner WHERE lc_id = %s LIMIT 1",
        (lc_id,), fetch="one",
    )
    return row[0] if row and row[0] is not None else 0


def getLcThreadUpdatesBulk(lc_ids, db_type=None):
    """Batch version of getLcThreadUpdated -- one round trip for a whole
    page instead of one per item. Returns {lc_id: thread_updated}; ids with
    no row are simply absent, so the caller should default missing keys
    to 0."""
    ids = [str(i) for i in lc_ids if i is not None]
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    rows = _run(
        f"SELECT lc_id, thread_updated FROM lewdcorner "
        f"WHERE lc_id IN ({placeholders})",
        ids, fetch="all",
    ) or []
    return {str(lc_id): (thread_updated or 0) for lc_id, thread_updated in rows}


def getAtlasIdByF95Id(f95_id, db_type=None):
    """Return the atlas_id already linked to this f95 thread, or 0 if unseen.

    This is the canonical way to find an existing f95 game: the thread's
    f95_id is stable, unlike the title-derived id_name.
    """
    row = _run(
        "SELECT atlas_id FROM f95_zone WHERE f95_id = %s LIMIT 1",
        (f95_id,), fetch="one",
    )
    return row[0] if row else 0


def atlasOwnedByOtherSource(atlas_id, db_type=None):
    """True if this atlas row is referenced by a NON-lewdcorner source table
    (f95_zone, dlsite, sxs). Used so the LewdCorner agent never overwrites the
    atlas fields of a game that another source created/owns -- it only links a
    lewdcorner row to it."""
    for tbl in ("f95_zone", "dlsite", "sxs"):
        try:
            row = _run(
                f"SELECT 1 FROM {tbl} WHERE atlas_id = %s LIMIT 1",
                (atlas_id,), fetch="one",
            )
            if row:
                return True
        except Exception:
            # Table may not exist on a partial dev DB; ignore and continue.
            pass
    return False


def getLcSiteUrl(lc_id, db_type=None):
    """The stored thread URL for this lc_id, or None if unseen. Needed by a
    single-thread refresh (queue worker / manual rescan), which has only an
    lc_id to work from -- no fresh listing-feed item carrying a `link`."""
    row = _run(
        "SELECT site_url FROM lewdcorner WHERE lc_id = %s LIMIT 1",
        (lc_id,), fetch="one",
    )
    return row[0] if row and row[0] else None


def getAtlasIdByLcId(lc_id, db_type=None):
    """Return the atlas_id already linked to this LewdCorner thread, or 0 if
    unseen. The LewdCorner thread id (lc_id) is stable, so this is the
    canonical way to find a row we've scraped before and update it in place
    rather than inserting a duplicate."""
    row = _run(
        "SELECT atlas_id FROM lewdcorner WHERE lc_id = %s LIMIT 1",
        (lc_id,), fetch="one",
    )
    return row[0] if row else 0


def findIdByTitle(table, id_name, db_type=None):
    _check_table(table)
    row = _run(
        f"SELECT atlas_id FROM {table} WHERE id_name = %s LIMIT 1",
        (id_name,), fetch="one",
    )
    return row[0] if row else 0


# ---------------------------------------------------------------- matching

def getLcOnlyAtlasRows(db_type=None):
    """Return atlas rows that are referenced by a lewdcorner row but NOT by
    any authoritative source (f95_zone/dlsite/sxs). These are the LC-only
    games -- the ones that were inserted as brand-new atlas rows because no
    exact id_name match was found at scrape time, when in fact the game very
    likely already exists in atlas under an F95-backed row with a slightly
    different title/creator spelling.

    Returns dicts with the atlas fields we need to fuzzy-match, plus the
    owning lc_id.
    """
    return _run(
        """
        SELECT a.atlas_id, a.title, a.creator, a.developer, a.short_name,
               a.id_name, a.version, a.engine, a.status, l.lc_id
        FROM atlas a
        JOIN lewdcorner l ON l.atlas_id = a.atlas_id
        WHERE a.atlas_id NOT IN (SELECT atlas_id FROM f95_zone)
          AND a.atlas_id NOT IN (SELECT atlas_id FROM dlsite)
          AND a.atlas_id NOT IN (SELECT atlas_id FROM sxs)
        ORDER BY a.atlas_id
        """,
        fetch="all", dict_cursor=True,
    ) or []


def getF95BackedAtlasRows(db_type=None):
    """Return all atlas rows that ARE backed by F95 (the source of truth),
    with the f95_id, for use as the fuzzy-match candidate pool. Pulled once
    and matched in Python so we avoid a per-row LIKE query."""
    return _run(
        """
        SELECT a.atlas_id, a.title, a.creator, a.developer, a.short_name,
               a.id_name, a.version, a.engine, a.status, f.f95_id
        FROM atlas a
        JOIN f95_zone f ON f.atlas_id = a.atlas_id
        ORDER BY a.atlas_id
        """,
        fetch="all", dict_cursor=True,
    ) or []


def findAtlasIdsByIdName(id_name, db_type=None):
    """Return ALL atlas_ids whose id_name matches exactly (no LIMIT 1).

    This is the honest version of findIdByTitle: the old single-row lookup
    silently linked to whichever row MySQL returned first when an LC game's
    computed id_name collided with more than one atlas row. Callers use the
    length of this list to decide: 0 -> new, 1 -> link, >1 -> ambiguous
    (route to the review queue).
    """
    rows = _run(
        "SELECT atlas_id FROM atlas WHERE id_name = %s ORDER BY atlas_id",
        (id_name,), fetch="all",
    ) or []
    return [r[0] for r in rows]


def findFuzzyAtlasCandidates(short_name, creator, db_type=None, limit=25):
    """Best-effort fuzzy candidate lookup for an LC game that had NO exact
    id_name match. Site formatting differs (spacing, punctuation, creator
    aliases), so an exact id_name miss doesn't mean the game is absent from
    atlas -- it may just be spelled differently.

    Strategy (cheap, index-friendly-ish, no extensions required):
      * match on short_name prefix (title with all non-alnum stripped), OR
      * match on creator prefix,
    then let the human judge. Returns a list of atlas_id ints. Ordering puts
    rows that share BOTH signals first.
    """
    sn = (short_name or "").strip()
    cr = (creator or "").strip().upper()
    if not sn and not cr:
        return []
    # A short prefix keeps this from matching half the table on very short
    # names; 4 chars (or the whole thing if shorter) is a reasonable floor.
    sn_pref = sn[:max(4, min(len(sn), 8))]
    rows = _run(
        """
        SELECT atlas_id,
               (short_name LIKE %s) AS sn_hit,
               (UPPER(creator) LIKE %s) AS cr_hit
        FROM atlas
        WHERE short_name LIKE %s OR UPPER(creator) LIKE %s
        ORDER BY (short_name LIKE %s) + (UPPER(creator) LIKE %s) DESC, atlas_id
        LIMIT %s
        """,
        (f"{sn_pref}%", f"{cr}%",
         f"{sn_pref}%", f"{cr}%",
         f"{sn_pref}%", f"{cr}%", int(limit)),
        fetch="all",
    ) or []
    return [r[0] for r in rows]


def getAtlasRowsByIds(atlas_ids, db_type=None):
    """Fetch full atlas rows for a list of atlas_ids, as dicts, so the
    reconciler can show the human the candidates side by side."""
    ids = [int(i) for i in atlas_ids if i is not None]
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    return _run(
        f"SELECT * FROM atlas WHERE atlas_id IN ({placeholders})",
        ids, fetch="all", dict_cursor=True,
    ) or []


def getAtlasSourceOwners(atlas_id, db_type=None):
    """Return the list of source tables that reference this atlas_id
    (e.g. ['f95_zone'] or ['f95_zone', 'lewdcorner']). Used both to show the
    human where a candidate came from and to guard deletion -- an atlas row
    still owned by another source must never be deleted."""
    owners = []
    for tbl in ("f95_zone", "dlsite", "sxs", "lewdcorner"):
        try:
            row = _run(
                f"SELECT 1 FROM {tbl} WHERE atlas_id = %s LIMIT 1",
                (atlas_id,), fetch="one",
            )
            if row:
                owners.append(tbl)
        except Exception:
            pass
    return owners


def getAtlasSourceIds(atlas_id, db_type=None):
    """Return the actual source-thread ids referencing this atlas_id, as a
    dict e.g. {'f95_id': 12345, 'lc_id': 23056}. Only sources that actually
    reference the row are included. Used to show the reviewer exactly which
    F95 and LewdCorner threads are attached to each candidate atlas row."""
    id_cols = {
        "f95_zone": "f95_id",
        "dlsite": "dlsite_id",
        "sxs": "sxs_id",
        "lewdcorner": "lc_id",
    }
    out = {}
    for tbl, id_col in id_cols.items():
        try:
            rows = _run(
                f"SELECT {id_col} FROM {tbl} WHERE atlas_id = %s",
                (atlas_id,), fetch="all",
            ) or []
            if rows:
                vals = [r[0] for r in rows]
                # atlas_id is UNIQUE in each source table, so normally one id;
                # keep a list just in case and collapse to a scalar when single.
                out[id_col] = vals[0] if len(vals) == 1 else vals
        except Exception:
            pass
    return out


def deleteAtlasById(atlas_id, db_type=None):
    """Delete an orphaned atlas row by id. The caller is responsible for
    confirming it's safe (no remaining source references)."""
    _run("DELETE FROM atlas WHERE atlas_id = %s", (atlas_id,), commit=True)


def touchAtlasRecord(atlas_id, db_type=None, now=None):
    """Bump an atlas row's last_record_update to `now` (default: current epoch).

    The daily/base packager exports every table with
    `WHERE last_record_update > start_time`. When a lewdcorner row is newly
    linked or relinked to an atlas_id WITHOUT the atlas row itself being
    rewritten, the lewdcorner row exports (fresh timestamp) but the atlas row
    carrying the *title* does not (stale timestamp). The client then receives an
    LC record pointing at an atlas_id it has no atlas_data row for, and falls
    back to displaying "LewdCorner #<lc_id>".

    Touching the atlas row here forces the title-bearing atlas row to ride along
    in the next export so the client can resolve the real title.
    """
    if atlas_id is None:
        return
    if now is None:
        now = int(time.time())
    _run(
        "UPDATE atlas SET last_record_update = %s WHERE atlas_id = %s",
        (int(now), int(atlas_id)), commit=True,
    )


def relinkLewdcornerAtlasId(lc_id, new_atlas_id, db_type=None):
    """Point an existing lewdcorner row at the correct atlas_id. Used by the
    reconciler when fixing an already-mis-linked LC row."""
    _run(
        "UPDATE lewdcorner SET atlas_id = %s WHERE lc_id = %s",
        (int(new_atlas_id), int(lc_id)), commit=True,
    )
    # Ensure the (title-bearing) atlas row re-exports so the client can resolve
    # the title for this newly-linked LC game. See touchAtlasRecord.
    touchAtlasRecord(new_atlas_id, db_type)


def getLcIdByAtlasId(atlas_id, db_type=None):
    """Return the lc_id of the lewdcorner row currently pointing at this
    atlas_id, or None. lewdcorner.atlas_id is UNIQUE, so there's at most one.
    Used to detect the case where the F95 game we want to relink to ALREADY
    has a (correct) LewdCorner row -- meaning the row we're processing is a
    duplicate LC thread for the same game, not a fixable mis-link."""
    row = _run(
        "SELECT lc_id FROM lewdcorner WHERE atlas_id = %s LIMIT 1",
        (int(atlas_id),), fetch="one",
    )
    return row[0] if row else None


def deleteLewdcornerByLcId(lc_id, db_type=None):
    """Delete a lewdcorner row by lc_id. Used to drop a duplicate LC thread
    whose game is already linked to the target atlas row by another LC row."""
    _run("DELETE FROM lewdcorner WHERE lc_id = %s",
         (int(lc_id),), commit=True)


def getLewdcornerRowByLcId(lc_id, db_type=None):
    """Return the full lewdcorner row (all columns) as a dict, or None.
    Used by the reconciler's `defer` pass to rebuild the lc_payload that the
    review queue needs so the game can be recreated/relinked later without
    re-scraping."""
    return _run(
        "SELECT * FROM lewdcorner WHERE lc_id = %s LIMIT 1",
        (int(lc_id),), fetch="one", dict_cursor=True,
    )


# ---------------------------------------------------- review queue (LC)

def enqueueLcReview(row, db_type=None):
    """Upsert one ambiguous LC item into lc_review_queue (keyed by lc_id, so
    a re-scrape refreshes the same pending row instead of duplicating it).
    `row` is a dict of column->value; first_seen is preserved on update."""
    if not row:
        return
    cols = list(row.keys())
    col_sql = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    params = list(row.values())
    # Never let first_seen get overwritten by a later sighting.
    updates = ", ".join(
        f"{c}=VALUES({c})" for c in cols if c != "first_seen"
    )
    sql = (
        f"INSERT INTO lc_review_queue ({col_sql}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {updates}"
    )
    _run(sql, params, commit=True)


def getLcReviewQueue(match_kind=None, db_type=None):
    """Return pending review rows as dicts, oldest first. Optional filter by
    match_kind ('multi' or 'fuzzy')."""
    if match_kind:
        return _run(
            "SELECT * FROM lc_review_queue WHERE match_kind = %s "
            "ORDER BY first_seen, lc_id",
            (match_kind,), fetch="all", dict_cursor=True,
        ) or []
    return _run(
        "SELECT * FROM lc_review_queue ORDER BY first_seen, lc_id",
        fetch="all", dict_cursor=True,
    ) or []


def isLcInReviewQueue(lc_id, db_type=None):
    row = _run(
        "SELECT 1 FROM lc_review_queue WHERE lc_id = %s LIMIT 1",
        (lc_id,), fetch="one",
    )
    return bool(row)


def dequeueLcReview(lc_id, db_type=None):
    """Remove a review row once it's been resolved (or dismissed)."""
    _run("DELETE FROM lc_review_queue WHERE lc_id = %s",
         (int(lc_id),), commit=True)


# -------------------------------------------------- tag backfill (req #2)

def getF95IdsMissingTags(db_type=None):
    """Return the f95_id of every f95_zone row whose tags column is empty
    (NULL or blank string). These are exactly the games that landed with
    only listing-level data and never got their game/thread page tags -- the
    backfill target for refresh_missing_tags.py. Ordered oldest-touched
    first so a long backfill makes steady forward progress."""
    rows = _run(
        """
        SELECT f95_id FROM f95_zone
        WHERE f95_id IS NOT NULL
          AND (tags IS NULL OR TRIM(tags) = '')
        ORDER BY last_record_update IS NULL DESC, last_record_update, f95_id
        """,
        fetch="all",
    ) or []
    return [r[0] for r in rows]


# -------------------------------------------------- refresh queue (req #4)
#
# A tiny work queue the Node admin server writes into (enqueue an item to be
# re-scraped) and the Python worker (atlas-worker / f95_refresh_worker.py)
# drains, one item every ~10s. Status lifecycle:
#   pending -> processing -> done | error
# The worker claims exactly one pending row at a time (oldest first),
# dispatches it to the right agent by `source`, then marks it done/error.
# Kept deliberately simple: one worker, so no locking beyond the status flip.
#
# Originally F95-only (hence the table/column names and the F95-suffixed
# function names below, kept for compatibility). `source` distinguishes which
# agent a row belongs to: 'f95' -> f95.refresh_one, 'lc' -> lewdcorner.refresh_one.
# getNextPendingRefresh / markRefreshProcessing / markRefreshResult never
# actually depended on the source (SELECT * / UPDATE by queue_id), so those
# three are plain renames with the old name kept as an alias. enqueue is the
# one that DOES need to change: the "is this already queued" dedup check has
# to be scoped by (source, id) together, not just id, or a numeric lc_id that
# happens to equal a pending f95_id would be reported as already-queued
# against the wrong source.

def getNextPendingRefresh(db_type=None):
    """Return the oldest still-pending refresh queue row as a dict, or None.
    'Oldest' = lowest priority number first, then earliest requested_at, so
    a caller can bump urgent items by giving them a lower priority. Rows from
    every source are eligible; the caller (the worker) reads row['source'] to
    decide which agent handles it."""
    return _run(
        """
        SELECT * FROM f95_refresh_queue
        WHERE status = 'pending'
        ORDER BY priority, requested_at, queue_id
        LIMIT 1
        """,
        fetch="one", dict_cursor=True,
    )


def markRefreshProcessing(queue_id, db_type=None):
    """Flip a claimed row pending -> processing, stamping started_at. Returns
    True if this call was the one that claimed it (affected a row), so even
    if two workers ever raced, only one proceeds."""
    now = int(time.time())
    _run(
        """
        UPDATE f95_refresh_queue
        SET status = 'processing', started_at = %s, attempts = attempts + 1
        WHERE queue_id = %s AND status = 'pending'
        """,
        (now, queue_id), commit=True,
    )
    # _run returns lastrowid for commits, not rowcount, so re-read to confirm.
    row = _run(
        "SELECT status FROM f95_refresh_queue WHERE queue_id = %s LIMIT 1",
        (queue_id,), fetch="one",
    )
    return bool(row and row[0] == "processing")


def markRefreshResult(queue_id, ok, error=None, db_type=None):
    """Mark a processed row done (ok=True) or error (ok=False, with an
    optional message), stamping finished_at."""
    now = int(time.time())
    last_error = None if ok else (error or "unknown error")[:1000]
    _run(
        """
        UPDATE f95_refresh_queue
        SET status = %s, finished_at = %s, last_error = %s
        WHERE queue_id = %s
        """,
        ("done" if ok else "error", now, last_error, queue_id),
        commit=True,
    )


def enqueueRefresh(source, item_id, requested_by="python", priority=100,
                    db_type=None):
    """Insert a pending refresh request for `item_id` under `source` ('f95' or
    'lc'). If an unfinished request for the same (source, item_id) already
    exists, this leaves it alone and returns its id -- scoped by source so an
    lc_id and an f95_id that happen to share a numeric value can't collide."""
    existing = _run(
        """
        SELECT queue_id FROM f95_refresh_queue
        WHERE source = %s AND f95_id = %s AND status IN ('pending', 'processing')
        ORDER BY queue_id LIMIT 1
        """,
        (source, str(item_id)), fetch="one",
    )
    if existing:
        return existing[0]
    now = int(time.time())
    return _run(
        """
        INSERT INTO f95_refresh_queue
            (f95_id, source, status, priority, requested_by, requested_at, attempts)
        VALUES (%s, %s, 'pending', %s, %s, %s, 0)
        """,
        (str(item_id), source, int(priority), requested_by, now), commit=True,
    )


def enqueueF95Refresh(f95_id, requested_by="python", priority=100,
                      db_type=None):
    """Insert a pending F95 refresh request (used by CLI helpers; the Node
    server has its own insert). Thin wrapper over enqueueRefresh -- kept under
    its original name since tools/maintenance/repair_external_ids.py and its
    test already call it by this name."""
    return enqueueRefresh("f95", f95_id, requested_by, priority, db_type)


def enqueueLcRefresh(lc_id, requested_by="python", priority=100, db_type=None):
    """Insert a pending LewdCorner refresh request. Symmetry with
    enqueueF95Refresh, for CLI helpers / future admin-server use."""
    return enqueueRefresh("lc", lc_id, requested_by, priority, db_type)


# Old names, kept as aliases: these three never depended on 'f95' specifically,
# they just predate a second source existing. f95_refresh_worker.py has been
# updated to call the new names directly; anything else still using these
# keeps working unchanged.
getNextPendingF95Refresh = getNextPendingRefresh
markF95RefreshProcessing = markRefreshProcessing
markF95RefreshResult = markRefreshResult


def findDlsiteMaker(table, circle_id, db_type=None):
    _check_table(table)
    row = _run(
        f"SELECT name FROM {table} WHERE circle_id = %s LIMIT 1",
        (circle_id,), fetch="one",
    )
    return row[0] if row else 0


def downloadBase(db_type, table, start_time):
    """Export rows for a table.

    start_time > 0  -> the delta: rows changed since then.
    start_time <= 0 -> EVERYTHING, including rows whose last_record_update is 0
                       or NULL.

    That second case used to be `WHERE last_record_update > 0`, which silently
    excluded any row that had never had its export timestamp set -- from a FULL
    package. Those rows (and anything hanging off them, such as admin manual
    links) simply never reached a client, and nothing ever brought them back
    because a full rebuild was exactly the thing that skipped them.
    """
    _check_table(table)
    if start_time and start_time > 0:
        return _run(
            f"SELECT * FROM {table} WHERE last_record_update > %s ORDER BY atlas_id",
            (start_time,), fetch="all", dict_cursor=True,
        )
    return _run(
        f"SELECT * FROM {table} ORDER BY atlas_id",
        (), fetch="all", dict_cursor=True,
    )


# Manual links may be stored with an id, a url, or both -- the admin UI accepts
# any of the three. Every kind therefore has to be read from BOTH columns and
# the missing half derived, or links silently vanish from the export: a Steam
# link added as a url had no ext_id and was dropped, and an itch link added as
# an id had no url and was dropped.
_STORE_ID_FROM_URL = {
    "steam": re.compile(r"store\.steampowered\.com/(?:app|widget)/(\d+)", re.I),
    "gog": re.compile(r"gog\.com/(?:[\w-]+/)?game/([\w-]+)", re.I),
}
_STORE_URL_FROM_ID = {
    "steam": lambda i: f"https://store.steampowered.com/app/{i}/",
    "gog": lambda i: f"https://www.gog.com/game/{i}",
}

# Where the scraper's own value for the same platform lives, so a manual link
# that duplicates it is recognised instead of being listed twice.
_SCRAPED_ID_KEYS = {
    "steam": ("steam_appid", "steam_id"),
    "gog": ("gog_id", "gog_appid"),
}
_SCRAPED_URL_KEYS = {
    "itch": ("itch_url",),
}

# Store kinds export as an id set plus a backward-compatible scalar.
_STORE_OUTPUT = {
    "steam": ("steam_appid", "steam_appids"),
    "gog": ("gog_id", "gog_ids"),
}


def _itch_url_from_id(value):
    """An itch id may be a bare slug or already a host."""
    v = str(value or "").strip().strip("/")
    if not v:
        return None
    if "." in v:
        return v if v.startswith("http") else f"https://{v}"
    return f"https://{v}.itch.io"


def _norm_url(value):
    """Normalise a url for equality: scheme, www. and trailing / are noise.

    Without this the scraper's "caribdis.itch.io" and a manual
    "https://caribdis.itch.io" are two different strings and the same page ends
    up exported twice.
    """
    v = str(value or "").strip().lower()
    if not v:
        return ""
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^www\.", "", v)
    return v.rstrip("/")


def _dedupe(seq, key=None):
    """Order-preserving de-duplication, optionally on a normalised key."""
    seen = set()
    out = []
    for value in seq:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        marker = key(text) if key else text
        if not marker or marker in seen:
            continue
        seen.add(marker)
        out.append(text)
    return out


def _merge_manual_links_into_external_ids(atlas_rows):
    """Overlay admin-approved manual links (atlas_manual_links) onto each atlas
    row's external_ids blob, at EXPORT time only -- the stored atlas.external_ids
    column is never modified, so a re-scrape can't clobber manual links (that is
    the whole reason atlas_manual_links exists as a separate, scraper-untouched
    table).

    The client resolves Steam/GOG ids from external_ids, but the historic shape
    (`{"steam_appid": "123"}`) holds only ONE id per store. Manual linking allows
    several (e.g. multiple Steam season appids under one atlas), so array-valued
    fields are added alongside the scalar ones:

        {
          "steam_appid":  "111",                       # primary, backward compat
          "steam_appids": ["111","222","333"],         # full deduped set
          "gog_id":       "...",
          "gog_ids":      [...],
          "itch": [...urls...], "custom": [...urls...]  # non-store links as urls
        }

    Three rules, each of which was previously broken:

      * EVERY link is exported. A link may carry an id, a url, or both; the
        missing half is derived where the platform allows it. Reading only one
        column silently dropped Steam links added as a url and itch links added
        as an id.
      * A manual link that duplicates something already present appears ONCE.
        Comparison is on a normalised url (scheme/www./trailing-slash stripped),
        so the scraper's "caribdis.itch.io" and a manual
        "https://caribdis.itch.io" are recognised as the same page.
      * An unrecognised kind is exported under its own key rather than dropped,
        so adding a link kind can't silently lose data here.
    """
    if not atlas_rows:
        return atlas_rows

    atlas_ids = [r.get("atlas_id") for r in atlas_rows if r.get("atlas_id") is not None]
    if not atlas_ids:
        return atlas_rows

    placeholders = ", ".join(["%s"] * len(atlas_ids))
    links = _run(
        f"SELECT atlas_id, kind, ext_id, url FROM atlas_manual_links "
        f"WHERE atlas_id IN ({placeholders}) ORDER BY link_id",
        tuple(atlas_ids), fetch="all", dict_cursor=True,
    ) or []

    # Normalise the key to int so a type mismatch between the atlas row's
    # atlas_id and the manual-links atlas_id (int vs str from different
    # queries/drivers) can't cause a silent miss where NO ids get added.
    def _aid_key(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return str(v).strip()

    by_atlas = {}
    for link in links:
        by_atlas.setdefault(_aid_key(link["atlas_id"]), []).append(link)

    if not by_atlas:
        return atlas_rows

    for row in atlas_rows:
        manual = by_atlas.get(_aid_key(row.get("atlas_id")))
        if not manual:
            continue

        raw = row.get("external_ids")
        ext = {}
        if raw:
            try:
                ext = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (ValueError, TypeError):
                ext = {}
        if not isinstance(ext, dict):
            ext = {}

        # Group by kind, resolving each link to (id, url) with whichever half
        # can be derived from the other.
        grouped = {}
        for link in manual:
            kind = str(link.get("kind") or "").strip().lower()
            if not kind:
                continue
            ext_id = str(link.get("ext_id") or "").strip() or None
            url = str(link.get("url") or "").strip() or None

            if not ext_id and url and kind in _STORE_ID_FROM_URL:
                found = _STORE_ID_FROM_URL[kind].search(url)
                if found:
                    ext_id = found.group(1)
            if not url and ext_id:
                if kind in _STORE_URL_FROM_ID:
                    url = _STORE_URL_FROM_ID[kind](ext_id)
                elif kind == "itch":
                    url = _itch_url_from_id(ext_id)

            if not ext_id and not url:
                continue
            grouped.setdefault(kind, []).append({"id": ext_id, "url": url})

        for kind, entries in grouped.items():
            if kind in _STORE_OUTPUT:
                scalar_key, list_key = _STORE_OUTPUT[kind]
                scraped = [ext.get(k) for k in _SCRAPED_ID_KEYS.get(kind, ())]
                # Manual first: an admin id is an override of the scraped one.
                ids = _dedupe([e["id"] for e in entries if e["id"]]
                              + list(ext.get(list_key) or [])
                              + scraped)
                if ids:
                    ext[list_key] = ids
                    ext[scalar_key] = ids[0]
                # A store link with no resolvable id (an unusual url shape) is
                # still worth shipping as a url rather than being discarded.
                urls_only = [e["url"] for e in entries if e["url"] and not e["id"]]
                if urls_only:
                    ext[f"{kind}_urls"] = _dedupe(
                        list(ext.get(f"{kind}_urls") or []) + urls_only, key=_norm_url)
                continue

            # url-shaped kinds (itch, custom, and anything added later)
            existing = list(ext.get(kind) or [])
            scraped_urls = [ext.get(k) for k in _SCRAPED_URL_KEYS.get(kind, ())]
            merged = _dedupe(
                existing + [e["url"] for e in entries if e["url"]] + scraped_urls,
                key=_norm_url)
            if merged:
                ext[kind] = merged

        row["external_ids"] = json.dumps(ext, ensure_ascii=False)

    return atlas_rows


def downloadManualLinks(db_type=None):
    """Every admin manual link, for the archival backup.

    The backup dumps the raw atlas table deliberately -- with the export overlay
    baked in, a restore would write merged values back into atlas.external_ids
    and destroy the separation that keeps manual links safe from the scraper.
    But that meant the backup contained no manual links at all, so a restore
    silently lost every admin-added id. Dumping the table alongside keeps the
    snapshot raw AND complete.
    """
    return _run(
        "SELECT * FROM atlas_manual_links ORDER BY atlas_id, link_id",
        (), fetch="all", dict_cursor=True,
    ) or []

def downloadAtlasBase(db_type, start_time):
    """Atlas export rows with admin manual links overlaid into external_ids.
    Use this instead of downloadBase(..., 'atlas', ...) so manual links always
    ship. See _merge_manual_links_into_external_ids.

    Besides the normal timestamp-delta rows, this UNIONS in any atlas row that
    has manual links, regardless of its last_record_update. That makes manual
    links self-healing: even if a link was added without bumping the atlas
    timestamp (older data, or a missed touch), the row still exports with its
    links overlaid, so the client always sees them. Full exports (start_time=0)
    already include everything, so the union is a no-op there.
    """
    rows = downloadBase(db_type, "atlas", start_time)

    if start_time and start_time > 0:
        seen = {r.get("atlas_id") for r in rows}
        manual_rows = _run(
            """
            SELECT a.* FROM atlas a
             WHERE (a.last_record_update <= %s OR a.last_record_update IS NULL)
               AND EXISTS (SELECT 1 FROM atlas_manual_links m
                            WHERE m.atlas_id = a.atlas_id)
            """,
            (start_time,), fetch="all", dict_cursor=True,
        ) or []
        for r in manual_rows:
            if r.get("atlas_id") not in seen:
                rows.append(r)

    return _merge_manual_links_into_external_ids(rows)
