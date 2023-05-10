import os
import sqlite3 as sl
import requests
import mysql.connector
from pathlib import Path
from tables.base import *

dbName = "data.db"

# LOCAL DB MANIPULATION
def DeleteLocalDatabase():
     if(Path((dbName)).is_file() == True):
        print("Deleting Database")
        os.remove(dbName)

def CreateLocalDatabase():
    if(Path((dbName)).is_file() == False):
        print("Creating Database")
        con = sl.connect(dbName)
        with con:           
            con.execute(atlasTable())
            con.execute(f95Table())
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
        user='u902432006_dbreader', 
        password='1Z#y!*Ki+',
        host='atlas-gamesdb.com',
        database='u902432006_games'
    )

    print("Creating Remote Database")
    con = cnx.cursor()
    with con:
        con.execute(atlasTable())
        con.execute(f95Table())
    cnx.close()

#-- Dynamic Functions --

def UpdatetableDynamic(table, values, local):
    if local == True:
        con = sl.connect(dbName)      
        cursor = con.cursor()

    columns = ', '.join(values.keys())
    placeholders = ', '.join('?' * len(values))
    sql = 'INSERT OR REPLACE INTO ' + table + ' ({}) VALUES ({})'.format(columns, placeholders)
    values = [int(x) if isinstance(x, bool) else x for x in values.values()]
    cursor.execute(sql, values)
    con.commit()
    cursor.close()