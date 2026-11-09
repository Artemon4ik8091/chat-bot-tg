import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from criminal_code_utils import (
    CRIMINAL_CODE_ARTICLES,
    CRIMINAL_CODE_EDITION,
    format_criminal_code_messages,
    format_criminal_code_punishments,
    get_random_criminal_code_article,
    load_criminal_code_articles,
)
from rp_command_utils import load_rp_commands


class CriminalCodeUtilsTests(unittest.TestCase):
    def test_catalog_contains_all_article_titles(self):
        project_dir = os.path.dirname(os.path.dirname(__file__))
        articles_path = os.path.join(project_dir, "criminal_code_articles.json")
        articles = load_criminal_code_articles(articles_path)

        self.assertEqual(len(articles), 535)
        self.assertEqual(sum(len(article["punishments"]) for article in articles), 1085)
        self.assertEqual(len({article["number"] for article in articles}), len(articles))
        self.assertEqual(articles[0]["number"], "1")
        self.assertEqual(articles[-1]["number"], "361")
        article_105 = next(article for article in articles if article["number"] == "105")
        self.assertEqual(article_105["title"], "Убийство")
        punishments_105 = format_criminal_code_punishments(article_105)
        self.assertTrue(any("часть" in item.lower() and "шести до пятнадцати лет" in item for item in punishments_105))
        self.assertTrue(any("часть" in item.lower() and "смертной казнью" in item for item in punishments_105))
        self.assertEqual(CRIMINAL_CODE_EDITION, "09.04.2026")

        article_228_1 = next(article for article in articles if article["number"] == "228.1")
        self.assertEqual([item["part"] for item in article_228_1["punishments"]], ["1", "2", "3", "4", "5"])

    def test_articles_without_separate_sanction_are_explained(self):
        article_1 = next(article for article in CRIMINAL_CODE_ARTICLES if article["number"] == "1")
        repealed_article = next(article for article in CRIMINAL_CODE_ARTICLES if article["number"] == "129")

        self.assertIn("общие нормы", format_criminal_code_punishments(article_1)[0])
        self.assertIn("утратила силу", format_criminal_code_punishments(repealed_article)[0])

    def test_random_article_comes_from_full_catalog(self):
        article = get_random_criminal_code_article()

        self.assertIn(article, CRIMINAL_CODE_ARTICLES)

    def test_long_part_sanctions_are_split_for_telegram(self):
        article_204 = next(article for article in CRIMINAL_CODE_ARTICLES if article["number"] == "204")
        parts = format_criminal_code_punishments(article_204)
        messages = format_criminal_code_messages("⚖️ Статья 204 УК РФ", parts)

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 4000 for message in messages))
        self.assertTrue(all("<blockquote expandable>" in message for message in messages))
        self.assertTrue(all(message.endswith("</blockquote>") for message in messages))
        self.assertIn("Часть 1:", messages[0])

    def test_my_article_is_not_an_rp_command(self):
        project_dir = os.path.dirname(os.path.dirname(__file__))
        commands_path = os.path.join(project_dir, "rp_commands.json")

        self.assertNotIn("моя статья", load_rp_commands(commands_path))


if __name__ == "__main__":
    unittest.main()
