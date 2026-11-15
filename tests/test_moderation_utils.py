import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from moderation_utils import (
    clear_chat_mute,
    get_active_chat_ban,
    get_chat_ban_history,
    get_chat_mute,
    get_latest_chat_ban,
    has_recent_matching_ban,
    record_ban,
    revoke_latest_chat_ban,
    set_chat_mute,
)


class ModerationUtilsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.cursor = self.conn.cursor()
        self.cursor.executescript('''
            CREATE TABLE chat_ban_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                admin_id INTEGER,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                until_date INTEGER,
                warn_count INTEGER,
                max_warns INTEGER,
                last_warn_created_at TEXT,
                last_warn_expires_at TEXT,
                last_warn_reason TEXT,
                revoked_at TEXT
            );
            CREATE TABLE chat_mutes (
                chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                until_date INTEGER,
                PRIMARY KEY (chat_id, user_id)
            );
        ''')

    def tearDown(self):
        self.conn.close()

    def test_ban_history_preserves_warn_limit_context(self):
        record_ban(
            self.cursor,
            -1001,
            42,
            7,
            'warn_limit',
            '2026-11-15 12:00:00',
            warn_count=3,
            max_warns=3,
            last_warn={
                'created_at': '2026-11-15 11:59:00',
                'expires_at': '2026-11-16 11:59:00',
                'reason': 'flood',
            }
        )

        history = get_chat_ban_history(self.cursor, -1001)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['source'], 'warn_limit')
        self.assertEqual(history[0]['warn_count'], 3)
        self.assertEqual(history[0]['last_warn_created_at'], '2026-11-15 11:59:00')
        self.assertEqual(history[0]['last_warn_reason'], 'flood')
        self.assertEqual(
            get_latest_chat_ban(self.cursor, -1001, 42),
            {
                'source': 'warn_limit',
                'created_at': '2026-11-15 12:00:00',
                'until_date': None,
            }
        )
        self.assertTrue(has_recent_matching_ban(
            self.cursor,
            -1001,
            42,
            None,
            '2026-11-15 12:01:00'
        ))
        self.assertFalse(has_recent_matching_ban(
            self.cursor,
            -1001,
            42,
            1794744000,
            '2026-11-15 12:01:00'
        ))

    def test_active_ban_respects_expiration_and_permanent_bans(self):
        record_ban(self.cursor, -1001, 42, 7, 'manual', '2026-11-15 12:00:00', 2000)
        self.assertEqual(
            get_active_chat_ban(self.cursor, -1001, 42, now_timestamp=1999)['until_date'],
            2000
        )
        self.assertIsNone(get_active_chat_ban(self.cursor, -1001, 42, now_timestamp=2000))

        record_ban(self.cursor, -1001, 43, 7, 'manual', '2026-11-15 12:00:00')
        self.assertIsNone(get_active_chat_ban(self.cursor, -1001, 43, now_timestamp=2000)['until_date'])

    def test_unban_revokes_current_ban_without_deleting_history(self):
        record_ban(self.cursor, -1001, 42, 7, 'manual', '2026-11-15 12:00:00')
        record_ban(self.cursor, -1001, 42, 8, 'manual', '2026-11-15 12:30:00', 3000)
        self.assertTrue(revoke_latest_chat_ban(
            self.cursor, -1001, 42, '2026-11-15 13:00:00'
        ))

        self.assertIsNone(get_active_chat_ban(self.cursor, -1001, 42, now_timestamp=2000))
        self.assertEqual(len(get_chat_ban_history(self.cursor, -1001)), 2)

    def test_mute_state_can_be_updated_and_cleared(self):
        set_chat_mute(self.cursor, -1001, 42, '2026-11-15 12:00:00', 1794744000)
        self.assertEqual(
            get_chat_mute(self.cursor, -1001, 42),
            {'started_at': '2026-11-15 12:00:00', 'until_date': 1794744000}
        )

        set_chat_mute(self.cursor, -1001, 42, '2026-11-15 13:00:00', None)
        self.assertEqual(
            get_chat_mute(self.cursor, -1001, 42),
            {'started_at': '2026-11-15 13:00:00', 'until_date': None}
        )

        clear_chat_mute(self.cursor, -1001, 42)
        self.assertIsNone(get_chat_mute(self.cursor, -1001, 42))


if __name__ == '__main__':
    unittest.main()
