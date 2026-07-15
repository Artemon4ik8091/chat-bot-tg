import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rp_command_utils import parse_rp_command_creation, load_rp_commands, save_rp_commands


class RpCommandUtilsTests(unittest.TestCase):
    def test_parse_rp_command_creation(self):
        spec = ".rpcreate почесать | {sender} хочет почесать | {sender} почесал {target} | {target} увернулся | Нежно"
        result = parse_rp_command_creation(spec)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "почесать")
        self.assertEqual(result[1], "{sender} хочет почесать")
        self.assertEqual(result[2], "{sender} почесал {target}")
        self.assertEqual(result[3], "{target} увернулся")
        self.assertEqual(result[4], "Нежно")

    def test_parse_rp_command_creation_with_inline_random_parts(self):
        spec = "+рпк ударить | {sender} хочет ударить | {sender} ударил {target} {random_part} | {target} увернулся | Ударить с размахом | в глаз, в челюсть, в живот"
        result = parse_rp_command_creation(spec)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ударить")
        self.assertEqual(result[1], "{sender} хочет ударить")
        self.assertEqual(result[2], "{sender} ударил {target} {random_part}")
        self.assertEqual(result[3], "{target} увернулся")
        self.assertEqual(result[4], "Ударить с размахом")
        self.assertEqual(result[5], ["в глаз", "в челюсть", "в живот"])

    def test_parse_rp_command_creation_requires_separator(self):
        self.assertIsNone(parse_rp_command_creation(".rpcreate почесать"))

    def test_save_and_load_rp_commands(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as handle:
            path = handle.name

        try:
            commands = {"погладить": {"request": "x", "accept": "y", "reject": "z"}}
            save_rp_commands(commands, path)
            loaded = load_rp_commands(path)
            self.assertEqual(loaded, commands)
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
