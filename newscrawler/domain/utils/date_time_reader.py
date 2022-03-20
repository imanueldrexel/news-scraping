from dateutil import parser
from datetime import datetime, date


class DateTimeReader:
    def __init__(self, default_year=date.today().year):
        self.century = 2000
        self.default_year = default_year

    @staticmethod
    def convert_date(text: str):
        return parser.parse(text)

    @staticmethod
    def get_time_now():
        return datetime.now()
