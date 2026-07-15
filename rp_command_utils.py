import json
import os


def load_rp_commands(path='rp_commands.json'):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    if isinstance(data, dict) and 'commands' in data:
        return data['commands']
    return data


def save_rp_commands(commands, path='rp_commands.json'):
    payload = {'commands': commands}
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
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
    if not normalized.lower().startswith('.rpdelete'):
        return None

    command_name = normalized[9:].strip().lower()
    if not command_name:
        return None
    return command_name
