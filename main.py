import telebot
import os
import json
import random

from telebot import types,util

####### CREATE DB IF NOT EXIST

if not os.path.exists('db.json'):
    db = {'token': 'None'}
    js = json.dumps(db, indent=2)
    with open('db.json', 'w') as outfile:
        outfile.write(js)

    print('Input token in "None" (db.json)')
    exit()

if not os.path.exists('users.json'):
        users = {}
        js = json.dumps(users, indent=2)
        with open('users.json', 'w') as outfile:
                outfile.write(js)

if not os.path.exists('la.json'):
        la = {}
        js = json.dumps(la, indent=2)
        with open('la.json', 'w') as outfile:
                outfile.write(js)
############WORK WITH DBs##########

def read_db():
    with open('db.json', 'r') as openfile:
        db = json.load(openfile)
        return db
def write_db(db):
    js = json.dumps(db, indent=2)
    with open('db.json', 'w') as outfile:
        outfile.write(js)

def catch_error(message, e, err_type = None):
    if not err_type:
        global log_stream, known_errs
        e = str(e)

def read_users():
    global users
    with open('users.json', 'r') as openfile:
        users = json.load(openfile)
def write_users():
    global users
    js = json.dumps(users, indent=2)
    with open('users.json', 'w') as outfile:
        outfile.write(js)

# LA - Low Admin.
# Admin permissions in bot without admin rights.
def read_la():
    with open('la.json', 'r') as openfile:
        la = json.load(openfile)
    return la
def write_la(la):
    js = json.dumps(la, indent=2)
    with open('la.json', 'w') as outfile:
        outfile.write(js)

####################FAST HASH#################
from xxhash import xxh32

# Generate fast hash
def sha(text):
    text = str(text)
    return xxh32(text).hexdigest()

##################FUNCTIONS########

def get_admins(message):
    try:
        if bot.get_chat(message.chat.id).type == 'private':
            return []
        else:
            admins = bot.get_chat_administrators(chat_id=message.chat.id)
            true_admins = []
            for i in admins:
                if i.status == 'creator' or i.can_restrict_members == True:
                    true_admins.append(i.user.id)
        return true_admins
    except Exception as e:
        catch_error(message, e)
        return None

# Fix for anon admins, all anon (not premium) users == admins
def is_anon(message):
    if message.from_user.username ==  'Channel_Bot' or message.from_user.username == 'GroupAnonymousBot':
        if message.from_user.is_premium == None:
            return True
    else:
        return False

# Return id from db/chat of user
def get_target(message):
    try:
        global users

        spl = message.text.split()
        if ( len(spl) > 1 and spl[1][0] == '@' ) or ( len(spl) > 2  and spl[2][0] == '@' ):
            for i in spl:
                if i[0] == '@':
                    username = i[1:]
                    break
            read_users()
            if sha(username) in users:
                return users[sha(username)]
            else:
                return None
        else:
            target = message.reply_to_message.from_user.id
            if target not in get_admins(message):
                return target
            else:
                return None
    except:
        return None

def get_name(message):
    try:
        text = message.text.split()

        # If message with @username
        if len(text) > 1 and text[1][0] == '@':
            return text[1]
        if len(text) > 2 and text[2][0] == '@':
            return text[2]
        # Reply to message
        else:
            return telebot.util.user_link(message.reply_to_message.from_user)
    except Exception as e:
        catch_error(message, e)

# Get time for '/mute'
# [time, time_in_sec, format]
def get_time(message):
    formats = {'s':[1, 'секунд(ы)'], 'm':[60, 'минут(ы)'], 'h': [3600,'час(а)'], 'd': [86400,'день/дня']}
    text = message.text.split()[1:] ; time = None

    # Find format in text
    for i in text:
        if time:
            break
        for f in list(formats.keys()):
            if f in i:
                try:
                    time = [i[:-1], int(i[:-1]) * formats[i[-1]][0] , formats[i[-1]][1] ]
                    break
                except:
                    pass

    return time

def have_rights(message, set_la = False):
    la = read_la()
    if message.from_user.id in get_admins(message):
        return True
    elif is_anon(message):
        return True
    elif str(message.chat.id) in la and not set_la:
        if str(message.from_user.username) in la[str(message.chat.id)]:
            return True
    else:
        bot.reply_to(message, 'Да кто ты такой, чтобы я тебя слушался??')

def key_by_value(dictionary, key):
    for i in dictionary:
        if dictionary[i] == key:
            return i
    return None

def analytic(message):
    global users
    read_users()

    if key_by_value(users, message.from_user.id) == message.from_user.username:
        pass
    elif message.from_user.username == 'None':
        pass
    else:
        users[sha(message.from_user.username)] = message.from_user.id
        write_users()


#############TOKEN INIT#####


db = read_db()
read_users()
bot = telebot.TeleBot(db['token'])

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, "Привет, я недо-ирис. Форк на Python.")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if message.text == 'bot?':
        username = message.from_user.first_name          #Получаем имя юзера
        bot.reply_to(message, f'Hello. I see you, {username}')

    if message.text.upper() == 'ПИНГ':bot.reply_to(message, f'ПОНГ')

    if message.text.upper() == 'КИНГ': bot.reply_to(message, f'КОНГ')

    if message.text.upper() == 'БОТ': bot.reply_to(message, f'✅ На месте')

    if message.text.upper() == 'КТО Я':
        username = message.from_user.first_name          #Получаем имя юзера
        bot.reply_to(message, f"Ты {username}!")

    if message.text.upper().startswith("РАНДОМ "):
        msg = message.text.upper()
        msg = msg.replace("РАНДОМ ", "")
        min = ""
        max = ""
        for item in msg:
            if item != " ":
                min += item
            else:
                break
        max = msg.replace(f"{min} ", "")
        max, min = int(max), int(min)
        try:
            if max < min:
                bot.reply_to(message, f"Первое число должно быть меньше второго!")
            if max == min:
                bot.reply_to(message, f"Да ты гений.")
            else:
                result = random.randint(min, max)
                bot.reply_to(message, f"Случайное число из диапазона [{min}..{max}] выпало на {result}")
        except:
            return 0
    if message.text.upper().startswith('МУТ'):
        try:
            if have_rights(message):
                target = get_target(message)
                time = get_time(message)
                if target:
                    if time:
                        bot.restrict_chat_member(message.chat.id, target, until_date = message.date + time[1])
                        answer = f'Я заклеил ему рот на {time[0]} {time[2]}. Маловато как по мне, ну ладно.'
                    else:
                        bot.restrict_chat_member(message.chat.id, target, until_date = message.date)
                        answer = f'Я заклеил ему рот.'
                    try:
                        bot.reply_to(message, answer, parse_mode='HTML')
                    except:
                        bot.reply_to(message, answer)
                else:
                    catch_error(message, 'None', 'no_user')
        except Exception as e:
            catch_error(message, e)


    if message.text.upper().startswith('РАЗМУТ'):
        try:
            if have_rights(message):
                target = get_target(message)
                if target:
                    bot.restrict_chat_member(message.chat.id, target, can_send_messages=True
                    , can_send_other_messages = True, can_send_polls = True
                    , can_add_web_page_previews = True, until_date = message.date)
                    bot.reply_to(message, f'''Ладно, так и быть, пусть он говорит.
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "КИК":
        try:
            if have_rights(message):
                target = get_target(message)
                if target:
                    bot.ban_chat_member(message.chat.id, target)
                    bot.unban_chat_member(message.chat.id, target)

                    bot.reply_to(message, f'''Этот плохиш был изгнан с сие великой группы.
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "БАН":
        try:
            if have_rights(message):
                target = get_target(message)
                if target:
                    bot.ban_chat_member(message.chat.id, target)
                    bot.reply_to(message, f'''Этот плохиш был изгнан с сие великой группы и не имеет права прощения!
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "РАЗБАН":
        try:
            if have_rights(message):
                target = get_target(message)
                if target:
                    bot.unban_chat_member(message.chat.id, target)
                    bot.reply_to(message, f'''Ладно, может право на прощение он и имеет.. Но только единожды! Наверное..
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '-ЧАТ':
        try:
            if have_rights(message):
                bot.set_chat_permissions(message.chat.id, telebot.types.ChatPermissions(can_send_messages=False, can_send_other_messages = False, can_send_polls = False))
                bot.reply_to(message, 'Крч вы достали админов господа.. и меня тоже. Закрываем чат..)')
            else:
                bot.reply_to(message, f'А, ещё.. <tg-spoiler>ПОПЛАЧЬ)))))</tg-spoiler>', parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '+ЧАТ':
        try:
            if have_rights(message):
                bot.set_chat_permissions(message.chat.id, telebot.types.ChatPermissions(can_send_messages=True, can_send_other_messages = True, can_send_polls = True))
                bot.reply_to(message, 'Ладно, мне надоела тишина. Открываю чат..')
        except Exception as e:
            catch_error(message, e)

bot.polling(none_stop=True)