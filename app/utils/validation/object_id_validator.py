import re


def is_valid_object_id(value: str) -> bool:
    if not value or not isinstance(value, str):
        return False
    return bool(re.match(r'^[0-9a-fA-F]{24}$', value.strip()))

