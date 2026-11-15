import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from chat_member_utils import (
    mark_chat_member_left,
    mark_chat_member_returned,
)


class ChatMemberRetentionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE chat_members (
                chat_id TEXT,
                user_id TEXT,
                first_seen_at TEXT NOT NULL,
                left_at TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE user_data (
                chat_id TEXT,
                user_id TEXT,
                date TEXT,
                message_count INTEGER,
                last_activity TEXT,
                PRIMARY KEY (chat_id, user_id, date)
            )
        ''')
        self.cursor.execute(
            '''INSERT INTO chat_members (chat_id, user_id, first_seen_at)
               VALUES ('100', '200', '2026-11-01 10:00:00')'''
        )
        self.cursor.execute(
            '''INSERT INTO user_data (chat_id, user_id, date, message_count, last_activity)
               VALUES ('100', '200', '2026-11-01', 42, '2026-11-01 10:00:00')'''
        )

    def tearDown(self):
        self.conn.close()

    def test_stats_are_retained_indefinitely_then_restored_on_return(self):
        left_at_str = '2026-10-01 12:00:00'
        self.assertTrue(mark_chat_member_left(self.cursor, '100', '200', left_at_str))
        self.assertFalse(mark_chat_member_left(
            self.cursor,
            '100',
            '200',
            '2026-10-01 13:00:00'
        ))

        # Leaving the member marked as departed for more than a week does not purge their stats.
        self.cursor.execute('SELECT message_count FROM user_data')
        self.assertEqual(self.cursor.fetchone(), (42,))
        self.cursor.execute('SELECT left_at FROM chat_members')
        self.assertEqual(self.cursor.fetchone(), (left_at_str,))

        mark_chat_member_returned(
            self.cursor,
            '100',
            '200',
            '2026-11-16 12:00:00'
        )
        self.cursor.execute('SELECT first_seen_at, left_at FROM chat_members')
        self.assertEqual(
            self.cursor.fetchone(),
            ('2026-11-01 10:00:00', None)
        )
        self.cursor.execute('SELECT message_count FROM user_data')
        self.assertEqual(self.cursor.fetchone(), (42,))


if __name__ == '__main__':
    unittest.main()
