import random
import re


def escape_html(text):
    if not text:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def is_shipping_command(text):
    if not text:
        return False
    clean = text.strip().upper()
    return clean in ['ШИППЕРИМ', 'ШИП', 'ШИППЕРИТЬ']


def generate_ship_name(name1, name2):
    def clean_name(n):
        if not n:
            return 'Аноним'
        words = [w for w in n.strip().split() if any(c.isalnum() for c in w)]
        first_word = words[0] if words else n.strip().split()[0]
        cleaned = re.sub(r'[^\w]', '', first_word, flags=re.UNICODE)
        return cleaned if cleaned else 'Аноним'

    c1 = clean_name(name1)
    c2 = clean_name(name2)

    if c1 == 'Аноним' and c2 == 'Аноним':
        return 'Аноним'

    len1 = len(c1)
    len2 = len(c2)

    part1 = c1[:max(1, (len1 + 1) // 2)]
    part2 = c2[len2 // 2:]
    if not part2:
        part2 = c2

    res = (part1 + part2).capitalize()
    if res.lower() in [c1.lower(), c2.lower()] and len(c2) >= 2:
        alt_part2 = c2[:max(2, (len2 + 1) // 2)].lower()
        res = (part1 + alt_part2).capitalize()

    return res


def format_progress_bar(percent, length=10):
    clamped = max(0, min(100, int(percent)))
    filled = round(clamped / 100 * length)
    return "█" * filled + "░" * (length - filled)


def get_ship_comment(percent):
    if percent >= 90:
        return random.choice([
            "Обречены на свадьбу! 💍",
            "Совет да любовь вам! ❤️",
            "Идеальный мэтч! ✨",
            "Горько! 🥂",
        ])
    elif percent >= 70:
        return random.choice([
            "А вы неплохо смотритесь.. 👀",
            "Искры так и летят! 🔥",
            "Между вами точно что-то есть 😉",
            "Горячая парочка! 🥰",
        ])
    elif percent >= 50:
        return random.choice([
            "Стоит присмотреться друг к другу! ✨",
            "А почему бы и нет? 😏",
            "Шансы весьма неплохие 👍",
            "Очень даже гармонично! 💕",
        ])
    elif percent >= 30:
        return random.choice([
            "Пока сойдёт за дружбу 🤝",
            "Шанс есть, пробуйте! ☕",
            "Кому-то пора сделать шаг 👀",
            "Время покажет.. ⏳",
        ])
    elif percent >= 15:
        return random.choice([
            "Тут всё сложно.. ⚡",
            "Придётся постараться 🤷‍♂️",
            "Искры только от замыкания 🔌",
            "Противоположности притягиваются? 🤔",
        ])
    else:
        return random.choice([
            "Купидон промахнулся 🏹",
            "Звёзды явно против 🥶",
            "Лучше остаться врагами 💔",
            "Не судьба 🛑",
        ])


def format_shipping_message(user1_link, user2_link, ship_name, percent, comment=None, extra_notes=None):
    if comment is None:
        comment = get_ship_comment(percent)
    bar = format_progress_bar(percent)
    escaped_ship_name = escape_html(ship_name)
    lines = [
        "💘 <b>Шипперим участников чата!</b>",
        "",
        "Амур натянул тетиву и выбрал пару:",
        f"❤️ {user1_link}  +  {user2_link} ❤️",
        "",
        f"✨ <b>Пейринг:</b> <code>{escaped_ship_name}</code>",
        f"📊 <b>Совместимость:</b> [{bar}] {percent}%",
        f"💬 <i>{comment}</i>",
    ]
    if extra_notes:
        lines.append("")
        lines.extend(extra_notes)
    return "\n".join(lines)


def get_chat_shipping_candidates(cursor, chat_id, current_user_id=None, reply_user_id=None):
    candidates = set()
    cursor.execute('SELECT DISTINCT user_id FROM user_data WHERE chat_id = ?', (str(chat_id),))
    for row in cursor.fetchall():
        try:
            candidates.add(int(row[0]))
        except (ValueError, TypeError):
            continue
    if current_user_id is not None:
        try:
            candidates.add(int(current_user_id))
        except (ValueError, TypeError):
            pass
    if reply_user_id is not None:
        try:
            candidates.add(int(reply_user_id))
        except (ValueError, TypeError):
            pass
    return candidates


def pick_random_pair(candidate_ids, is_valid_member_func):
    candidates = list(candidate_ids)
    random.shuffle(candidates)
    valid_members = []
    for uid in candidates:
        member = is_valid_member_func(uid)
        if member is not None:
            valid_members.append((uid, member))
            if len(valid_members) == 2:
                break
    return valid_members if len(valid_members) == 2 else []
