import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from migrations import (
    MIGRATIONS,
    column_exists,
    get_migration_status,
    run_migrations,
    table_exists,
)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_bot.db')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_migrations_fresh_db(self):
        # Fresh database with no tables
        applied = run_migrations(self.db_path, make_backup=False)
        self.assertEqual(len(applied), len(MIGRATIONS))

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check tables exist
        expected_tables = [
            'users', 'low_admins', 'warns', 'chats', 'user_profiles',
            'user_data', 'rp_requests', 'marriages', 'marriage_requests',
            'chat_warn_settings', 'chat_warns', 'schema_migrations'
        ]
        for tbl in expected_tables:
            self.assertTrue(table_exists(cursor, tbl), f"Table {tbl} should exist")

        # Check columns exist
        self.assertTrue(column_exists(cursor, 'rp_requests', 'sender_first_name'))
        self.assertTrue(column_exists(cursor, 'user_data', 'last_mentioned_target'))
        conn.close()

    def test_idempotent_runs(self):
        applied1 = run_migrations(self.db_path, make_backup=False)
        self.assertEqual(len(applied1), len(MIGRATIONS))

        # Second run should apply 0 migrations
        applied2 = run_migrations(self.db_path, make_backup=False)
        self.assertEqual(applied2, [])

    def test_upgrade_legacy_database_preserves_data(self):
        # Simulate an old DB version without sender_first_name and without last_mentioned_target
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE user_data (
                chat_id TEXT,
                user_id TEXT,
                date TEXT,
                message_count INTEGER,
                last_activity TEXT,
                PRIMARY KEY (chat_id, user_id, date)
            )
        ''')
        cursor.execute('''
            CREATE TABLE rp_requests (
                request_id TEXT PRIMARY KEY,
                chat_id TEXT,
                sender_id INTEGER,
                target_id INTEGER,
                command TEXT,
                phrase TEXT,
                created_at TEXT
            )
        ''')
        # Insert test data into legacy tables
        cursor.execute("INSERT INTO user_data VALUES ('100', '200', '2026-11-08', 42, 'active')")
        cursor.execute("INSERT INTO rp_requests VALUES ('req1', '100', 200, 300, 'обнять', 'привет', '2026-11-08')")
        conn.commit()
        conn.close()

        # Run migrations on legacy DB
        applied = run_migrations(self.db_path, make_backup=True)
        self.assertTrue(len(applied) > 0)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Verify new columns added
        self.assertTrue(column_exists(cursor, 'user_data', 'last_mentioned_target'))
        self.assertTrue(column_exists(cursor, 'rp_requests', 'sender_first_name'))

        # Verify old data is completely preserved
        cursor.execute("SELECT chat_id, user_id, message_count FROM user_data WHERE chat_id='100'")
        row = cursor.fetchone()
        self.assertEqual(row, ('100', '200', 42))

        cursor.execute("SELECT request_id, command FROM rp_requests WHERE request_id='req1'")
        row_rp = cursor.fetchone()
        self.assertEqual(row_rp, ('req1', 'обнять'))
        conn.close()

    def test_migration_status(self):
        status1 = get_migration_status(self.db_path)
        self.assertFalse(status1['db_exists'])
        self.assertEqual(len(status1['pending']), len(MIGRATIONS))

        run_migrations(self.db_path, make_backup=False)

        status2 = get_migration_status(self.db_path)
        self.assertTrue(status2['db_exists'])
        self.assertEqual(len(status2['applied']), len(MIGRATIONS))
        self.assertEqual(status2['pending'], [])


if __name__ == '__main__':
    unittest.main()
