
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
        host='atlas-gamesdb.com',
        database='u902432006_games'
    )
    
    sql = "SELECT MAX(last_db_update) FROM f95zone_data"
    mycursor = mydb.cursor()
    mycursor.execute(sql)
    return (mycursor.fetchone())[0]


def UpdateLocalF95Table(f95_id, short_name, category, engine, banner_url, title, status, version,
    developer,site_url, overview, last_thread_update, last_release, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, preview_urls, last_record_update,
    thread_publish_date,last_thread_comment):
    con = sl.connect(dbName)
    cursor = con.cursor()
    sql = """INSERT OR REPLACE INTO f95zone_data
    (f95_id, short_name, category, engine, banner_url, title, status, version,
    developer,site_url, overview, last_thread_update, last_release, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, preview_urls, last_record_update,
    thread_publish_date,last_thread_comment)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);"""
    parameters = (f95_id, short_name, category, engine, banner_url, title, status, version,
    developer,site_url, overview, last_thread_update, last_release, censored, language, translations,
    length, vndb, genre, voice, os, views, likes, tags, rating, preview_urls, last_record_update,
    thread_publish_date,last_thread_comment)
    cursor.execute(sql,parameters)
    con.commit()
    cursor.close()