import unittest

from datetime import datetime

from weeklymonthly import is_weekly, is_monthly


class Testis_weekly(unittest.TestCase):
    def test_monday_is_weekly_day(self):
        self.assertTrue(
            is_weekly(
                datetime(year=2015, month=7, day=19),
                datetime(year=2015, month=7, day=20),
            )
        )

    def test_more_than_seven_days(self):
        self.assertTrue(
            is_weekly(
                datetime(year=2015, month=7, day=14),
                datetime(year=2015, month=7, day=22),
            )
        )

    def test_borderline_seven_days(self):
        self.assertTrue(
            is_weekly(
                datetime(year=2015, month=7, day=13),
                datetime(year=2015, month=7, day=20),
            )
        )

    def test_inside_week_is_not_weekly(self):
        self.assertFalse(
            is_weekly(
                datetime(year=2015, month=7, day=20),
                datetime(year=2015, month=7, day=26),
            )
        )

    def test_inside_week_is_not_weekly(self):
        self.assertFalse(
            is_weekly(
                datetime(year=2015, month=7, day=20),
                datetime(year=2015, month=7, day=21),
            )
        )


class Testis_monthly(unittest.TestCase):
    def test_simple(self):
        self.assertTrue(
            is_monthly(
                datetime(year=2015, month=6, day=30),
                datetime(year=2015, month=7, day=1),
            )
        )

    def test_inside_month(self):
        self.assertFalse(
            is_monthly(
                datetime(year=2015, month=7, day=1),
                datetime(year=2015, month=7, day=2),
            )
        )

    def test_inside_month_2(self):
        self.assertFalse(
            is_monthly(
                datetime(year=2015, month=7, day=3),
                datetime(year=2015, month=7, day=2),
            )
        )
