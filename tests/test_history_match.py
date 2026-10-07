import unittest
from playlocal_server import _reservation_row_matches_slot


class ActivityMatchingTests(unittest.TestCase):
    def setUp(self):
        self.slot = {'date': '2026-10-09', 'start': 480, 'end': 540,
                     'courtName': 'West Roxbury High School 2',
                     'facilityName': 'West Roxbury High School'}
        self.row = {'date': '2026-10-09', 'start': '8:00 AM', 'status': 'current',
                    'text': 'West Roxbury High School 2 Fri, Oct 9, 2026 at 8:00am'}

    def test_actual_activity_court_name_matches(self):
        self.assertTrue(_reservation_row_matches_slot(self.row, self.slot))

    def test_other_court_never_advances_queue(self):
        for court in ('1', '3', '20'):
            with self.subTest(court=court):
                row = {**self.row, 'text': f'West Roxbury High School {court}'}
                self.assertFalse(_reservation_row_matches_slot(row, self.slot))

    def test_missing_or_mismatched_date_time_and_canceled_do_not_confirm(self):
        changes = [{'date': ''}, {'date': '2026-10-10'}, {'start': ''},
                   {'start': '9:00 AM'}, {'status': 'cancelled'},
                   {'text': 'West Roxbury High School'}]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(_reservation_row_matches_slot({**self.row, **change}, self.slot))

    def test_short_court_name_uses_same_number_and_venue(self):
        slot = {**self.slot, 'courtName': 'Court 2'}
        self.assertTrue(_reservation_row_matches_slot(self.row, slot))
        self.assertFalse(_reservation_row_matches_slot({**self.row, 'text': 'Other Venue Court 2'}, slot))


if __name__ == '__main__':
    unittest.main()
