import time
import datetime

class epoch:
    def __init__(self) -> None:
        pass

    def ConvertToUnixTime(s):

        try:
            ut = time.mktime(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timetuple())
            return ut
        except:
            return 0