"""
Database access layer.

LOCAL  -> SQLite (data.db, Windows dev box)
REMOTE -> MySQL  (server)

Refactor notes vs the original:
  * One _connect() helper instead of ~8 copies of the connect block.
  * Parameterised queries everywhere (no string-built WHERE clauses).
  * Table names are whitelisted before being interpolated.
  * MySQL upsert uses %s placeholders (the old code mixed ? and %s).
  * Credentials come from the environment via config (no plaintext here).
"""
import os
import sqlite3 as sl
from pathlib import Path

import mysql.connector

from scraper.tables.base import query
from scraper.types.eTypes import database
from scraper.config import config

dbName = "data.db"

# Only these tables may be interpolated into SQL (defence against injection
# via scraped data flowing into table/column positions).
ALLOWED_TABLES = {
    "atlas", "f95_zone", "updates", "dlsite", "dlsite_circle",
    "lewdcorner", "sxs", "test",
}


def _check_table(table):
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Refusing to use non-whitelisted table name: {table!r}")
    return table


def _connect(db_type):
    """Return (connection, paramstyle). paramstyle is '?' (sqlite) or '%s' (mysql)."""
    if db_type == database.LOCAL:
        return sl.connect(dbName), "?"
    return (
        mysql.connector.connect(
            user=config.db_user(),
            password=config.db_password(),
            host=config.host(database.REMOTE.value),
            database=config.database(),
        ),
        "%s",
    )


# ---------------------------------------------------------------- writes

def UpdatetableDynamic(table, values, db_type):
    """Upsert a dict of column->value into `table`."""
    _check_table(table)
    if not values:
        return
    con, ph = _connect(db_type)
    try:
        cols = list(values.keys())
        col_sql = ", ".join(cols)
        placeholders = ", ".join([ph] * len(cols))
        params = [int(v) if isinstance(v, bool) else v for v in values.values()]

        if db_type == database.LOCAL:
            sql = f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})"
        else:
            updates = ", ".join(f"{c}=VALUES({c})" for c in cols)
            sql = (
                f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}"
            )
        cur = con.cursor()
        cur.execute(sql, params)
        con.commit()
        cur.close()
    finally:
        con.close()


def TruncateLocalUpdatesTable(db_type):
    con, _ = _connect(db_type)
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM updates")
        con.commit()
        cur.close()
    finally:
        con.close()


# ---------------------------------------------------------------- schema

def CreateDatabase(db_type):
    con, _ = _connect(db_type)
    try:
        cur = con.cursor()
        for stmt in (
            query.createAtlasTable(db_type),
            query.createF95Table(db_type),
            query.createUpdateTable(db_type),
            query.createDlsiteCircleTable(db_type),
            query.createDlsiteTable(db_type),
            query.createLewdcornereTable(db_type),
            query.createSxsTable(db_type),
        ):
            cur.execute(stmt)
        con.commit()
        cur.close()
    finally:
        con.close()


def DeleteTables(db_type):
    con, _ = _connect(db_type)
    try:
        cur = con.cursor()
        for t in ("atlas", "test", "f95_zone"):
            cur.execute(query.deleteTable(_check_table(t)))
        con.commit()
        cur.close()
    finally:
        con.close()


def DeleteDatabase(db_type):
    if db_type == database.LOCAL and Path(dbName).is_file():
        os.remove(dbName)


# ---------------------------------------------------------------- reads

def getLastUpdate(db_type, f95_id):
    con, ph = _connect(db_type)
    try:
        cur = con.cursor()
        cur.execute(
            f"SELECT last_thread_comment FROM f95_zone WHERE f95_id = {ph}",
            (f95_id,),
        )
        row = cur.fetchone()
        cur.close()
        return row[0] if row and row[0] is not None else 0
    finally:
        con.close()


def findIdByTitle(table, id_name, db_type):
    _check_table(table)
    con, ph = _connect(db_type)
    try:
        cur = con.cursor()
        cur.execute(f"SELECT atlas_id FROM {table} WHERE id_name = {ph}", (id_name,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else 0
    finally:
        con.close()


def findDlsiteMaker(table, circle_id, db_type):
    _check_table(table)
    con, ph = _connect(db_type)
    try:
        cur = con.cursor()
        cur.execute(f"SELECT name FROM {table} WHERE circle_id = {ph}", (circle_id,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else 0
    finally:
        con.close()


def downloadBase(db_type, table, start_time):
    _check_table(table)
    con, ph = _connect(db_type)
    try:
        if db_type == database.LOCAL:
            con.row_factory = dict_factory
            cur = con.cursor()
        else:
            cur = con.cursor(dictionary=True)
        cur.execute(
            f"SELECT * FROM {table} WHERE last_record_update > {ph} ORDER BY atlas_id",
            (start_time,),
        )
        data = cur.fetchall()
        cur.close()
        return data
    finally:
        con.close()


def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
