import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from awards_utils import (
    add_global_user_award,
    add_user_award,
    get_global_user_awards,
    get_user_awards,
)


class AwardsUtilsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE chat_user_awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                award TEXT NOT NULL,
                award_key TEXT NOT NULL,
                UNIQUE (chat_id, user_id, award_key)
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE global_user_awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                award TEXT NOT NULL,
                award_key TEXT NOT NULL,
                UNIQUE (user_id, award_key)
            )
        ''')

    def tearDown(self):
        self.conn.close()

    def test_awards_are_unique_per_user_and_chat_case_insensitively(self):
        self.assertTrue(add_user_award(self.cursor, -1001, 42, 'Золотая звезда'))
        self.assertFalse(add_user_award(self.cursor, -1001, 42, '  золотая звезда  '))
        self.assertTrue(add_user_award(self.cursor, -1001, 43, 'Золотая звезда'))
        self.assertTrue(add_user_award(self.cursor, -1002, 42, 'Золотая звезда'))
        self.assertEqual(get_user_awards(self.cursor, -1001, 42), ['Золотая звезда'])

    def test_awards_are_returned_in_grant_order(self):
        add_user_award(self.cursor, -1001, 42, 'Первая')
        add_user_award(self.cursor, -1001, 42, 'Вторая')

        self.assertEqual(
            get_user_awards(self.cursor, -1001, 42),
            ['Первая', 'Вторая']
        )

    def test_empty_award_is_rejected(self):
        with self.assertRaises(ValueError):
            add_user_award(self.cursor, -1001, 42, '  ')

    def test_global_awards_are_shared_across_chats_and_unique(self):
        self.assertTrue(add_global_user_award(self.cursor, 42, 'Звезда чата'))
        self.assertFalse(add_global_user_award(self.cursor, 42, ' звезда чата '))
        self.assertEqual(get_global_user_awards(self.cursor, 42), ['Звезда чата'])
        self.assertEqual(get_user_awards(self.cursor, -1001, 42), [])


if __name__ == '__main__':
    unittest.main()
