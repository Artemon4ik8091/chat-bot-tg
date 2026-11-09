import json
import os
import random


DEFAULT_CRIMINAL_CODE_ARTICLES_PATH = os.path.join(
    os.path.dirname(__file__),
    "criminal_code_articles.json",
)


def load_criminal_code_catalog(path=DEFAULT_CRIMINAL_CODE_ARTICLES_PATH):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    articles = data.get("articles") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("edition"), str)
        or not data["edition"]
        or not isinstance(articles, list)
        or not articles
    ):
        raise ValueError(f"Invalid Criminal Code article catalog in {path}")

    numbers = set()
    for article in articles:
        if (
            not isinstance(article, dict)
            or not isinstance(article.get("number"), str)
            or not article["number"]
            or not isinstance(article.get("title"), str)
            or not article["title"]
            or not isinstance(article.get("punishments"), list)
        ):
            raise ValueError(f"Invalid article entry in {path}: {article!r}")
        if article["number"] in numbers:
            raise ValueError(f"Duplicate Criminal Code article number in {path}: {article['number']}")
        numbers.add(article["number"])
        for punishment in article["punishments"]:
            if (
                not isinstance(punishment, dict)
                or (punishment.get("part") is not None and not isinstance(punishment["part"], str))
                or not isinstance(punishment.get("text"), str)
                or not punishment["text"]
            ):
                raise ValueError(f"Invalid punishment entry for article {article['number']} in {path}")

    return data


def load_criminal_code_articles(path=DEFAULT_CRIMINAL_CODE_ARTICLES_PATH):
    return load_criminal_code_catalog(path)["articles"]


CRIMINAL_CODE_CATALOG = load_criminal_code_catalog()
CRIMINAL_CODE_ARTICLES = CRIMINAL_CODE_CATALOG["articles"]
CRIMINAL_CODE_EDITION = CRIMINAL_CODE_CATALOG["edition"]


def get_random_criminal_code_article():
    return random.choice(CRIMINAL_CODE_ARTICLES)


def format_criminal_code_punishments(article):
    if article["punishments"]:
        return [
            f"{'Часть ' + punishment['part'] if punishment['part'] else 'Статья целиком'}: "
            f"{punishment['text']}"
            for punishment in article["punishments"]
        ]
    if article["title"].casefold() == "утратила силу":
        return ["Статья утратила силу; наказание по ней больше не применяется."]
    return ["Отдельная санкция в этой статье не указана: она содержит общие нормы УК РФ."]


def split_criminal_code_message(lines, max_length=4000):
    messages = []
    current_message = ""
    for line in lines:
        if len(line) > max_length:
            raise ValueError("A criminal-code message line exceeds the Telegram message limit")
        candidate = f"{current_message}\n{line}" if current_message else line
        if len(candidate) > max_length:
            messages.append(current_message)
            current_message = line
        else:
            current_message = candidate
    if current_message:
        messages.append(current_message)
    return messages
