import os
import sqlite3 as sl
import requests
import mysql.connector
from pathlib import Path

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
            con.execute("""
                CREATE TABLE f95zone_data (
                    f95_id TEXT NOT NULL UNIQUE PRIMARY KEY,
                    short_name TEXT NOT NULL,
                    other TEXT,
                    engine TEXT,
                    banner_url TEXT,
                    title TEXT NOT NULL,
                    status TEXT,
                    version TEXT NOT NULL,
                    developer TEXT,
                    site_url TEXT,
                    overview TEXT,
                    thread_update DATE,
                    release_date DATE,
                    censored TEXT,
                    language TEXT,
                    translations TEXT,
                    length TEXT,
                    vndb TEXT,
                    genre TEXT,
                    voice TEXT,
                    os TEXT,
                    views TEXT,
                    likes TEXT,
                    tags TEXT,
                    rating TEXT,
                    screens TEXT,
                    last_update TEXT
                );
            """)
    else:
        print("Database Exist")

def UpdateLocalF95Table(f95_id, short_name, other, engine, banner_url, title, status, version, developer,
    site_url, overview, thread_update, release_date, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, screens, last_update):
    con = sl.connect(dbName)
    cursor = con.cursor()
    sql = """INSERT OR REPLACE INTO f95zone_data
    (f95_id, short_name, other, engine, banner_url, title, status, version, developer,
    site_url, overview, thread_update, release_date, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, screens, last_update)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);"""
    parameters = (f95_id, short_name, other, engine, banner_url, title, status, version, developer,
    site_url, overview, thread_update, release_date, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, screens, last_update)
    cursor.execute(sql,parameters)
    con.commit()
    cursor.close()

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
        host='hydrus95.com',
        database='u902432006_vndb'
        )

    print("Creating Remote Database")
    con = cnx.cursor()
    with con:
        con.execute("""
            CREATE TABLE f95zone_data (
                f95_id INT NOT NULL UNIQUE PRIMARY KEY,
                short_name TINYTEXT NOT NULL,
                other TINYTEXT,
                engine TINYTEXT,
                banner_url LONGTEXT,
                title TINYTEXT NOT NULL,
                status TINYTEXT,
                version TINYTEXT NOT NULL,
                developer TINYTEXT,
                site_url LONGTEXT,
                overview LONGTEXT,
                thread_update DATE,
                release_date DATE,
                censored TINYTEXT,
                language TINYTEXT,
                translations TINYTEXT,
                length TINYTEXT,
                vndb TINYTEXT,
                genre TINYTEXT,
                voice TINYTEXT,
                os TINYTEXT,
                views TINYTEXT,
                likes TINYTEXT,
                tags TINYTEXT,
                rating TINYTEXT,
                screens LONGTEXT,
                last_update DATETIME
            );
        """)
    cnx.close()

def UpdateRemoteF95Table(f95_id, short_name, other, engine, banner_url, title, status, version, developer,
    site_url, overview, thread_update, release_date, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, screens, last_update):

    mydb = mysql.connector.connect(
    user='u902432006_dbreader', 
    password='1Z#y!*Ki+',
    host='hydrus95.com',
    database='u902432006_vndb'
    )

    mycursor = mydb.cursor(prepared=True)

    sql = """INSERT INTO f95zone_data
    (f95_id, short_name, other, engine, banner_url, title, status, version, developer,
    site_url, overview, thread_update, release_date, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, screens, last_update)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE
    f95_id = VALUES(f95_id), short_name = VALUES(short_name), other = VALUES(other), engine = VALUES(engine), banner_url = VALUES(banner_url),
    title = VALUES(title), status = VALUES(status), version = VALUES(version), developer = VALUES(developer),
    site_url = VALUES(site_url), overview = VALUES(overview), thread_update = VALUES(thread_update), release_date = VALUES(release_date),
    censored = VALUES(censored), language = VALUES(language), translations = VALUES(translations), length = VALUES(length),
    vndb = VALUES(vndb), genre = VALUES(genre), voice = VALUES(voice), os = VALUES(os), views = VALUES(views), likes = VALUES(likes),
    tags = VALUES(tags), rating = VALUES(rating), screens = VALUES(screens), last_update = VALUES(last_update);"""
    parameters = (f95_id, short_name, other, engine, banner_url, title, status, version, developer,
    site_url, overview, thread_update, release_date, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, screens, last_update)
    mycursor.execute(sql,parameters)
    mydb.commit()
    mydb.close()

def GetLastDbUpdate():
    mydb = mysql.connector.connect(
        user='u902432006_dbreader', 
        password='1Z#y!*Ki+',
        host='hydrus95.com',
        database='u902432006_vndb'
    )
    
    sql = "SELECT MAX(last_db_update) FROM f95zone_data"
    mycursor = mydb.cursor()
    mycursor.execute(sql)
    return (mycursor.fetchone())[0]
