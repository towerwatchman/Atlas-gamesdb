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


def CreateLocalDatabase():
    if Path((dbName)).is_file() == False:
        print("Creating Database")
        con = sl.connect(dbName)
        # with con:
        #    con.execute(atlasTable(database.LOCAL))
        #    con.execute(f95Table())
    else:
        print("Database Exist")


def TruncateLocalF95Table():
    con = sl.connect(dbName)
    cursor = con.cursor()
    sql = """DELETE FROM f95zone_data"""
    cursor.execute(sql)
    con.commit()
    cursor.close()


# REMOTE DB MANIPULATION


def CreateRemoteDatabase():
    cnx = mysql.connector.connect(
        user="u902432006_dbreader",
        password="1Z#y!*Ki+",
        host="atlas-gamesdb.com",
        database="u902432006_games",
    )

    print("Creating Remote Database")
    con = cnx.cursor()
    # with con:
    #    con.execute(atlasTable())
    #    con.execute(f95Table())
    cnx.close()


# -- Dynamic Functions --


def UpdatetableDynamic(table, values, local):
    if local == True:
        con = sl.connect(dbName)
        cursor = con.cursor()

    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" * len(values))
    sql = (
        "INSERT OR REPLACE INTO "
        + table
        + " ({}) VALUES ({})".format(columns, placeholders)
    )
    values = [int(x) if isinstance(x, bool) else x for x in values.values()]
    cursor.execute(sql, values)
    con.commit()
    cursor.close()


def CreateDatabase(type):
    # Local
    if type == database.LOCAL:
        if Path((dbName)).is_file() == False:
            print("Creating Local Database")
            con = sl.connect(dbName)
            with con:
                con.execute(query.atlasTable(database.LOCAL))
                con.execute(query.f95Table(database.LOCAL))
        else:
            print("Local Database Exist")
    # Remote
    elif type == database.REMOTE:
        cnx = mysql.connector.connect(
            user=config.user_readdonly,
            password=config.password_readonly,
            host=config.host,
            database=config.database,
        )
        print("Creating Remote Database")
        con = cnx.cursor()
        with con:
            con.execute(query.atlasTable(database.REMOTE))
            con.execute(query.f95Table(database.REMOTE))
        cnx.close()
