import time
import datetime
import calendar


class epoch:
    def __init__(self) -> None:
        pass

    def ConvertToUnixTime(s):
        try:
            ut = time.mktime(
                datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timetuple()
            )
            return ut
        except:
            try:
                ut = calendar.timegm(
                    datetime.datetime.strptime(s, "%Y-%m-%d").timetuple()
                )
                return ut
            except:
                return 0
