import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shipping_utils import (
    escape_html,
    format_progress_bar,
    format_shipping_message,
    generate_ship_name,
    get_chat_shipping_candidates,
    get_ship_comment,
    is_shipping_command,
    pick_random_pair,
)


class ShippingUtilsTests(unittest.TestCase):
    def test_is_shipping_command(self):
        valid = [
            "шипперим",
            "ШИППЕРИМ",
            "Шипперим",
            "  шипперим  ",
            "шип",
            "ШИП",
            "шипперить",
            "ШИППЕРИТЬ",
        ]
        for cmd in valid:
            self.assertTrue(is_shipping_command(cmd), f"Expected True for '{cmd}'")

        invalid = [
            "/шипперим",
            "/шипперим@test_bot",
            ".шипперим",
            "!шипперим",
            "/шип",
            "/шип@test_bot",
            ".шип",
            "!шип",
            "/шипперить",
            "шипперим кого-то",
            "привет",
            "не шипперим",
            "",
            None,
            "123",
            "/start",
            ".хелп",
        ]
        for cmd in invalid:
            self.assertFalse(is_shipping_command(cmd), f"Expected False for '{cmd}'")

    def test_generate_ship_name(self):
        # Basic pairs
        name = generate_ship_name("Иван", "Мария")
        self.assertEqual(name, "Иврия")

        # Clean names with emojis and additional info
        name2 = generate_ship_name("🌟 Саша 🌟", "Вика (админ)")
        self.assertEqual(name2, "Сака")

        # Single letter names
        name3 = generate_ship_name("А", "Б")
        self.assertEqual(name3, "Аб")

        # Fallback for empty or non-alphanumeric
        name4 = generate_ship_name("!!!", "???")
        self.assertEqual(name4, "Аноним")

        # Avoiding collision with identical names
        name5 = generate_ship_name("Саша", "Паша")
        self.assertNotEqual(name5.lower(), "саша")
        self.assertNotEqual(name5.lower(), "паша")

    def test_format_progress_bar(self):
        self.assertEqual(format_progress_bar(0), "░░░░░░░░░░")
        self.assertEqual(format_progress_bar(50), "█████░░░░░")
        self.assertEqual(format_progress_bar(100), "██████████")
        self.assertEqual(format_progress_bar(-10), "░░░░░░░░░░")
        self.assertEqual(format_progress_bar(150), "██████████")

    def test_get_ship_comment(self):
        for percent in [0, 15, 30, 50, 75, 85, 100]:
            comment = get_ship_comment(percent)
            self.assertIsInstance(comment, str)
            self.assertTrue(len(comment) > 0)

    def test_format_shipping_message(self):
        msg = format_shipping_message(
            user1_link='<a href="https://t.me/user1">User 1</a>',
            user2_link='<a href="https://t.me/user2">User 2</a>',
            ship_name="Usus",
            percent=85,
            comment="Отличная пара!",
            extra_notes=["💍 <i>Кстати, эти двое уже состоят в браке!</i>"]
        )
        self.assertIn("Шипперим участников чата!", msg)
        self.assertIn('<a href="https://t.me/user1">User 1</a>', msg)
        self.assertIn('<a href="https://t.me/user2">User 2</a>', msg)
        self.assertIn("Usus", msg)
        self.assertIn("85%", msg)
        self.assertIn("Отличная пара!", msg)
        self.assertIn("Кстати, эти двое уже состоят в браке!", msg)

    def test_get_chat_shipping_candidates(self):
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE user_data (chat_id TEXT, user_id TEXT, date TEXT, message_count INTEGER, last_activity TEXT)")
        cursor.execute("INSERT INTO user_data VALUES ('123', '1001', '2026-11-08', 5, '2026-11-08 12:00:00')")
        cursor.execute("INSERT INTO user_data VALUES ('123', '1002', '2026-11-08', 10, '2026-11-08 12:05:00')")
        cursor.execute("INSERT INTO user_data VALUES ('123', '1001', '2026-11-07', 3, '2026-11-07 12:00:00')")
        cursor.execute("INSERT INTO user_data VALUES ('456', '9999', '2026-11-08', 1, '2026-11-08 12:00:00')")

        candidates = get_chat_shipping_candidates(cursor, '123', current_user_id=1003, reply_user_id=1004)
        self.assertEqual(candidates, {1001, 1002, 1003, 1004})
        conn.close()

    def test_pick_random_pair(self):
        candidates = {1, 2, 3, 4, 5}
        # validator where 1, 2, 3 are valid, 4 and 5 are invalid (None)
        def validator(uid):
            if uid in [1, 2, 3]:
                return f"Member_{uid}"
            return None

        pair = pick_random_pair(candidates, validator)
        self.assertEqual(len(pair), 2)
        uid1, m1 = pair[0]
        uid2, m2 = pair[1]
        self.assertNotEqual(uid1, uid2)
        self.assertIn(uid1, [1, 2, 3])
        self.assertIn(uid2, [1, 2, 3])

        # Test when not enough valid members
        def strictly_one(uid):
            return "Member_1" if uid == 1 else None

        pair_fail = pick_random_pair(candidates, strictly_one)
        self.assertEqual(pair_fail, [])


if __name__ == '__main__':
    unittest.main()
