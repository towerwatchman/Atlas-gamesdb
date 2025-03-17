import os
import sqlite3 as sl
import requests
import mysql.connector
from pathlib import Path
from scraper.tables.base import *
from scraper.types.eTypes import *
from scraper.config import *

dbName = "data.db"


# LOCAL DB MANIPULATION
def DeleteLocalDatabase():
    if Path((dbName)).is_file() == True:
        print("Deleting Database")
        os.remove(dbName)


def TruncateLocalF95Table():
    
    con = sl.connect(dbName)
    cursor = con.cursor()
    sql = """DELETE FROM f95zone_data"""
    cursor.execute(sql)
    con.commit()
    cursor.close()

def TruncateLocalUpdatesTable(type):
    if type == database.LOCAL:
        con = sl.connect(dbName)
        cursor = con.cursor()

    elif type == database.REMOTE:
        con = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        cursor = con.cursor(prepared=True)

    query = "DELETE FROM updates"

    cursor.execute(query)  
    con.commit()
    cursor.close()
    con.close()

# -- Dynamic Functions --


def UpdatetableDynamic(table, values, type):
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" * len(values))
    sql = ""
    data = ""

    if type == database.LOCAL:
        con = sl.connect(dbName)
        cursor = con.cursor()
        sql = (
            "INSERT OR REPLACE INTO "
            + table
            + " ({}) VALUES ({})".format(columns, placeholders)
        )
    elif type == database.REMOTE:
        con = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        cursor = con.cursor(prepared=True)
        sql = (
            "INSERT INTO "
            + table
            + " ({}) VALUES ({}) ON DUPLICATE KEY UPDATE ".format(columns, placeholders)
        )
        for id, value in enumerate(values):
            data += value + "=VALUES(" + value + ")"
            if id + 1 < len(values):
                data += ","

        # print(data)

        # values = [int(x) if isinstance(x, bool) else x for x in values: x]
    values = [int(x) if isinstance(x, bool) else x for x in values.values()]
    # print(sql)
    sql = sql + data
    # print(sql)
    # print(values)
    cursor.execute(sql, values)
    con.commit()
    cursor.close()
    con.close()


def CreateDatabase(type):
    # Local
    if type == database.LOCAL:
        if Path((dbName)).is_file() == False:
            print("Creating Local Database")
        else:
            print("Local Database Exist")
        con = sl.connect(dbName)
        with con:
            # con.execute(query.createIdSequence(database.LOCAL))
            con.execute(query.createAtlasTable(database.LOCAL))
            con.execute(query.createF95Table(database.LOCAL))
            con.execute(query.createUpdateTable(database.LOCAL))
            con.execute(query.createDlsiteCircleTable(database.LOCAL))
            con.execute(query.createDlsiteTable(database.LOCAL))
            con.execute(query.createLewdcornereTable(database.REMOTE))
            con.execute(query.createSxsTable(database.REMOTE))
        con.close()
    # Remote
    elif type == database.REMOTE:
        cnx = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        print("Creating Remote Database")
        con = cnx.cursor()
        with con:
            # con.execute(query.createIdSequence(database.REMOTE))
            con.execute(query.createAtlasTable(database.REMOTE))
            con.execute(query.createF95Table(database.REMOTE))
            con.execute(query.createUpdateTable(database.REMOTE))
            con.execute(query.createDlsiteCircleTable(database.REMOTE))
            con.execute(query.createDlsiteTable(database.REMOTE))
            con.execute(query.createLewdcornereTable(database.REMOTE))
            con.execute(query.createSxsTable(database.REMOTE))

        con.close()


def getLastUsedId(type):
    if type == database.LOCAL:
        con = sl.connect(dbName)
        cursor = con.cursor()

    elif type == database.REMOTE:
        con = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        cursor = con.cursor(prepared=True)

    query = "SELECT id FROM id_sequence"

    cursor.execute(query)
    id = cursor.fetchone()
    # cursor.close()
    if id == None:
        id = 0
    else:
        id = id[0]
    return id

def getLastUpdate(type, id):
    if type == database.LOCAL:
        con = sl.connect(dbName)
        cursor = con.cursor()

    elif type == database.REMOTE:
        con = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        cursor = con.cursor(prepared=True)

    query = "SELECT last_thread_comment FROM f95_zone where f95_id = " + id

    cursor.execute(query)
    last_update = cursor.fetchone()
    cursor.close()
    con.close()
    if last_update == None:
        last_update = 0
    else:
        last_update = last_update[0]
    return last_update


def DeleteTables(type):
    # Local
    if type == database.LOCAL:
        if Path((dbName)).is_file() == True:
            print("Deleting Local Tables")
            con = sl.connect(dbName)
            with con:
                con.execute(query.deleteTable("atlas"))
                con.execute(query.deleteTable("test"))
                con.execute(query.deleteTable("f95_zone_data"))
    if type == database.REMOTE:
        cnx = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        print("Deleting Remote Tables")
        con = cnx.cursor()
        with con:
            con.execute(query.deleteTable("atlas"))
            con.execute(query.deleteTable("test"))
            con.execute(query.deleteTable("f95_zone_data"))
        cnx.close()


def DeleteDatabase(type):
    # Local
    if type == database.LOCAL:
        if Path((dbName)).is_file() == True:
            print("Deleting Local Database")
            os.remove(dbName)


def findIdByTitle(table, id_name, type):
    if type == database.LOCAL:
        con = sl.connect(dbName)
        con.row_factory = sl.Row
        cursor = con.cursor()

    elif type == database.REMOTE:
        con = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        cursor = con.cursor(prepared=True)

    query = "SELECT atlas_id FROM " + table + ' WHERE id_name = "' + id_name + '"'

    cursor.execute(query)
    id = cursor.fetchone()
    # cursor.close()
    if id == None:
        return 0
    else:
        return id[0]


def findDlsiteMaker(table, id, type):
    if type == database.LOCAL:
        con = sl.connect(dbName)
        con.row_factory = sl.Row
        cursor = con.cursor()

    elif type == database.REMOTE:
        con = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        cursor = con.cursor(prepared=True)

    query = "SELECT name FROM " + table + ' WHERE circle_id = "' + id + '"'

    cursor.execute(query)
    id = cursor.fetchone()
    # cursor.close()
    if id == None:
        return 0
    else:
        return id[0]


def downloadBase(type, table, start_time):
    if type == database.LOCAL:
        con = sl.connect(dbName)
        con.row_factory = dict_factory
        cursor = con.cursor()

    elif type == database.REMOTE:
        con = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(database.REMOTE),
            database=config.database(),
        )
        cursor = con.cursor(dictionary=True)

    query = "SELECT * FROM " + table + " WHERE last_record_update > " + str(start_time) + " ORDER BY atlas_id"

    cursor.execute(query)
    data = cursor.fetchall()
    cursor.close()
    con.close()
    return data


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
