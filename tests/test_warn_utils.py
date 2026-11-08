from datetime import datetime, timedelta
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from warn_utils import (
    add_warn,
    cleanup_expired_warns,
    format_duration,
    get_chat_warn_settings,
    get_user_warn_count,
    get_user_warns,
    init_warn_tables,
    parse_duration_string,
    remove_warn,
    set_chat_max_warns,
    set_chat_warn_duration,
)


class WarnUtilsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.cursor = self.conn.cursor()
        init_warn_tables(self.cursor)

    def tearDown(self):
        self.conn.close()

    def test_settings_defaults_and_updates(self):
        # Default settings
        s1 = get_chat_warn_settings(self.cursor, '-1001')
        self.assertEqual(s1['max_warns'], 3)
        self.assertEqual(s1['warn_duration'], 86400)

        # Update chat 1 limit to 5
        set_chat_max_warns(self.cursor, '-1001', 5)
        s1 = get_chat_warn_settings(self.cursor, '-1001')
        self.assertEqual(s1['max_warns'], 5)

        # Check chat 2 is still default
        s2 = get_chat_warn_settings(self.cursor, '-1002')
        self.assertEqual(s2['max_warns'], 3)

        # Update chat 2 duration
        set_chat_warn_duration(self.cursor, '-1002', 3600)
        s2 = get_chat_warn_settings(self.cursor, '-1002')
        self.assertEqual(s2['max_warns'], 3)
        self.assertEqual(s2['warn_duration'], 3600)

    def test_warns_isolation_between_chats(self):
        # Add warn to user 999 in chat A
        add_warn(self.cursor, '-1001', '999')
        # Check user 999 has 1 warn in chat A and 0 in chat B
        self.assertEqual(get_user_warn_count(self.cursor, '-1001', '999'), 1)
        self.assertEqual(get_user_warn_count(self.cursor, '-1002', '999'), 0)

    def test_timed_warn_automatic_expiration(self):
        t0 = datetime(2026, 11, 8, 12, 0, 0)
        # Add warn for 3600 seconds (1 hour)
        count, max_warns, dur, exp = add_warn(self.cursor, '-1001', '100', duration_seconds=3600, now_dt=t0)
        self.assertEqual(count, 1)
        self.assertEqual(exp, '2026-11-08 13:00:00')

        # Check at 12:30 (still active)
        t_active = datetime(2026, 11, 8, 12, 30, 0)
        self.assertEqual(get_user_warn_count(self.cursor, '-1001', '100', now_dt=t_active), 1)

        # Check at 13:05 (expired!)
        t_expired = datetime(2026, 11, 8, 13, 5, 0)
        self.assertEqual(get_user_warn_count(self.cursor, '-1001', '100', now_dt=t_expired), 0)
        self.assertEqual(get_user_warns(self.cursor, '-1001', '100', now_dt=t_expired), [])

    def test_remove_warn(self):
        add_warn(self.cursor, '-1001', '200')
        add_warn(self.cursor, '-1001', '200')
        self.assertEqual(get_user_warn_count(self.cursor, '-1001', '200'), 2)

        ok, rem, max_w = remove_warn(self.cursor, '-1001', '200')
        self.assertTrue(ok)
        self.assertEqual(rem, 1)

        ok, rem, max_w = remove_warn(self.cursor, '-1001', '200')
        self.assertTrue(ok)
        self.assertEqual(rem, 0)

        ok, rem, max_w = remove_warn(self.cursor, '-1001', '200')
        self.assertFalse(ok)
        self.assertEqual(rem, 0)

    def test_parse_duration_string(self):
        self.assertEqual(parse_duration_string('24h'), 86400)
        self.assertEqual(parse_duration_string('2d'), 172800)
        self.assertEqual(parse_duration_string('30m'), 1800)
        self.assertEqual(parse_duration_string('60s'), 60)
        self.assertEqual(parse_duration_string('0'), 0)
        self.assertEqual(parse_duration_string('навсегда'), 0)
        self.assertEqual(parse_duration_string('бессрочно'), 0)
        self.assertEqual(parse_duration_string('invalid'), None)

    def test_format_duration(self):
        self.assertEqual(format_duration(86400), '1 дн.')
        self.assertEqual(format_duration(3600), '1 ч.')
        self.assertEqual(format_duration(1800), '30 мин.')
        self.assertEqual(format_duration(0), 'бессрочно')
        self.assertEqual(format_duration(None), 'бессрочно')


if __name__ == '__main__':
    unittest.main()
