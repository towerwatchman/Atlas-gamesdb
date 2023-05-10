
def atlasTable():
    query = """
            CREATE TABLE games (
                id INT NOT NULL UNIQUE PRIMARY KEY,
                title TINYTEXT NOT NULL, 
                short_name TINYTEXT NOT NULL,
                original_name TINYTEXT,
                category TINYTEXT,
                engine TINYTEXT,
                status TINYTEXT,
                version TINYTEXT NOT NULL,
                developer TINYTEXT,
                creator TINYTEXT,
                overview LONGTEXT,
                censored TINYTEXT,
                language TINYTEXT,
                translations TINYTEXT,
                genre TINYTEXT,
                voice TINYTEXT,
                os TINYTEXT,
                release_date DATE,
                length TINYTEXT,
                banner LONGTEXT,
                banner_wide LONGTEXT,
                cover LONGTEXT,
                logo LONGTEXT,
                last_update DATETIME
            );
        """
    return query

def f95Table():
   query = """
            CREATE TABLE f95_zone_data (
                f95_id INT NOT NULL UNIQUE PRIMARY KEY,
                id INT NOT NULL,
                banner_url LONGTEXT, 
                site_url LONGTEXT,
                thread_update DATETIME,
                views INT,
                likes TINYTEXT,
                tags LONGTEXT,
                rating TINYTEXT,
                screens LONGTEXT
            );
        """
   return query



def testTable():
    query = """
            CREATE TABLE test (
                id INT NOT NULL UNIQUE PRIMARY KEY,
                name TINYTEXT
            );
        """
    return query

