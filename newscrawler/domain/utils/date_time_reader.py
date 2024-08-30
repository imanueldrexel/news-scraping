from dateutil import parser
from datetime import datetime, date, timedelta, timezone


class DateTimeReader:
    def __init__(self, default_year=date.today().year):
        self.century = 2000
        self.default_year = default_year
        self.gmt_offset = timezone(timedelta(hours=0))

    @staticmethod
    def convert_date(text: str):
        dt = parser.parse(text)
        gmt_plus_7 = timezone(timedelta(hours=7))

        # If the parsed date doesn't have timezone info, set it to GMT+7
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=gmt_plus_7)
        else:
            # Convert to GMT+7 if it already has timezone info
            dt = dt.astimezone(gmt_plus_7)

        return dt

    @staticmethod
    def get_time_now():
        return datetime.now().replace(tzinfo=timezone(timedelta(hours=0)))
