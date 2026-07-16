import json
import os


DEFAULT_RP_COMMANDS_PATH = 'rp_commands.json'
DEFAULT_CHAT_RP_COMMANDS_PATH = 'rp_chat_commands.json'


def load_rp_commands(path=DEFAULT_RP_COMMANDS_PATH):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    if isinstance(data, dict) and 'commands' in data:
        return data['commands']
    return data


def _ensure_json_file(path):
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({}, handle, ensure_ascii=False, indent=2)
            handle.write('\n')


def load_chat_rp_commands(path=DEFAULT_CHAT_RP_COMMANDS_PATH):
    _ensure_json_file(path)
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return data
    return {}


def save_chat_rp_commands(chat_commands, path=DEFAULT_CHAT_RP_COMMANDS_PATH):
    _ensure_json_file(path)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(chat_commands, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    return chat_commands


def save_rp_commands(commands, path=DEFAULT_RP_COMMANDS_PATH, chat_commands=None, chat_path=DEFAULT_CHAT_RP_COMMANDS_PATH):
    payload = {'commands': commands}
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    if chat_commands is not None:
        save_chat_rp_commands(chat_commands, chat_path)
    return payload


def parse_rp_command_creation(text):
    if not text:
        return None

    normalized = text.strip()
    if not normalized.lower().startswith('+рпк') and not normalized.lower().startswith('.rpcreate'):
        return None

    payload = normalized[4:].strip() if normalized.lower().startswith('+рпк') else normalized[9:].strip()
    if not payload:
        return None

    parts = [part.strip() for part in payload.split('|')]
    if len(parts) < 4:
        return None

    command_name = parts[0].lower()
    request = parts[1]
    accept = parts[2]
    reject = parts[3]
    description = parts[4].strip() if len(parts) > 4 else ''
    random_parts = []
    if len(parts) > 5:
        random_parts = [item.strip() for item in parts[5].split(',') if item.strip()]

    if not command_name or not request or not accept or not reject:
        return None

    return command_name, request, accept, reject, description, random_parts


def parse_rp_command_delete(text):
    if not text:
        return None

    normalized = text.strip()
    if not normalized.lower().startswith('-рпк') and not normalized.lower().startswith('.rpdelete'):
        return None

    payload = normalized[4:].strip() if normalized.lower().startswith('-рпк') else normalized[9:].strip()
    command_name = payload.lower()
    if not command_name:
        return None
    return command_name
