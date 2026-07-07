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
import mysql.connector
from mysql.connector import errors as mysql_errors

from scraper.tables.base import query
from scraper.types.eTypes import database
from scraper.config import config

# Only these tables may be interpolated into SQL (defence against injection
# via scraped data flowing into table/column positions).
ALLOWED_TABLES = {
    "atlas", "f95_zone", "updates", "dlsite", "dlsite_circle",
    "lewdcorner", "sxs", "test", "lc_review_queue",
}

_conn = None  # the one shared connection for this process; see _connect().


def _check_table(table):
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Refusing to use non-whitelisted table name: {table!r}")
    return table


def _new_connection():
    return mysql.connector.connect(
        user=config.db_user(),
        password=config.db_password(),
        host=config.host(),
        database=config.database(),
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
    cols = list(values.keys())
    col_sql = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    params = [int(v) if isinstance(v, bool) else v for v in values.values()]
    return _run(
        f"INSERT INTO atlas ({col_sql}) VALUES ({placeholders})",
        params, commit=True,
    )


def updateAtlasById(atlas_id, values, db_type=None):
    """Update an existing atlas row in place, located by its atlas_id.

    Used for threads we already have (resolved via f95_id). Updating by the
    primary key keeps atlas_id stable across re-scrapes.
    """
    if not values:
        return
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


def relinkLewdcornerAtlasId(lc_id, new_atlas_id, db_type=None):
    """Point an existing lewdcorner row at the correct atlas_id. Used by the
    reconciler when fixing an already-mis-linked LC row."""
    _run(
        "UPDATE lewdcorner SET atlas_id = %s WHERE lc_id = %s",
        (int(new_atlas_id), int(lc_id)), commit=True,
    )


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


def findDlsiteMaker(table, circle_id, db_type=None):
    _check_table(table)
    row = _run(
        f"SELECT name FROM {table} WHERE circle_id = %s LIMIT 1",
        (circle_id,), fetch="one",
    )
    return row[0] if row else 0


def downloadBase(db_type, table, start_time):
    _check_table(table)
    return _run(
        f"SELECT * FROM {table} WHERE last_record_update > %s ORDER BY atlas_id",
        (start_time,), fetch="all", dict_cursor=True,
    )
