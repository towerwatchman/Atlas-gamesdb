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
    "lewdcorner", "sxs", "test",
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
        query.createSxsTable(db_type),
    ):
        _run(stmt, commit=True)


def DeleteTables(db_type=None):
    for t in ("atlas", "test", "f95_zone"):
        _run(query.deleteTable(_check_table(t)), commit=True)


# ---------------------------------------------------------------- reads

def getLastUpdate(db_type, f95_id):
    row = _run(
        "SELECT last_thread_comment FROM f95_zone WHERE f95_id = %s LIMIT 1",
        (f95_id,), fetch="one",
    )
    return row[0] if row and row[0] is not None else 0


def getLastUpdatesBulk(f95_ids, db_type=None):
    """Batch version of getLastUpdate: one round trip for a whole page of
    items instead of one round trip per item. Returns
    {f95_id: (last_thread_comment, thread_updated)}. Ids with no row are
    simply absent, so the caller should default missing keys to (0, None).

    thread_updated is included specifically so a row whose stored
    last_thread_comment already happens to be >= the feed's current `ts`
    (true for plenty of legacy rows written before the feed-based ts logic
    existed) isn't treated as permanently "up to date" while its
    thread_updated sits NULL forever -- the caller should force a refresh
    when thread_updated is missing, regardless of the ts comparison."""
    ids = [str(i) for i in f95_ids if i is not None]
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    rows = _run(
        f"SELECT f95_id, last_thread_comment, thread_updated FROM f95_zone "
        f"WHERE f95_id IN ({placeholders})",
        ids, fetch="all",
    ) or []
    return {
        str(f95_id): (last_thread_comment or 0, thread_updated or 0)
        for f95_id, last_thread_comment, thread_updated in rows
    }


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
