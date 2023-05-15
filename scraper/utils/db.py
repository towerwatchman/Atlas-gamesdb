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
            host=config.host(),
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


def CreateDatabase(type):
    # Local
    if type == database.LOCAL:
        if Path((dbName)).is_file() == False:
            print("Creating Local Database")
        else:
            print("Local Database Exist")
        con = sl.connect(dbName)
        with con:
            con.execute(query.createAtlasTable(database.LOCAL))
            con.execute(query.createF95Table(database.LOCAL))
    # Remote
    elif type == database.REMOTE:
        cnx = mysql.connector.connect(
            user=config.user_readdonly(),
            password=config.password_readonly(),
            host=config.host(),
            database=config.database(),
        )
        print("Creating Remote Database")
        con = cnx.cursor()
        with con:
            con.execute(query.createAtlasTable(database.REMOTE))
            con.execute(query.createF95Table(database.REMOTE))
        cnx.close()


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
            host=config.host(),
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
