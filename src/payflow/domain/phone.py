import re

_SEPARATORS = re.compile(r"[\s\-()]")
_E164 = re.compile(r"\+[1-9]\d{9,14}")


def normalize_phone(raw: str) -> str:
    """Normalize to E.164. Local Kazakh numbers (8 7xx ...) become +7 7xx ..."""
    phone = _SEPARATORS.sub("", raw)
    if len(phone) == 11 and phone.startswith("8"):
        phone = f"+7{phone[1:]}"
    elif not phone.startswith("+"):
        phone = f"+{phone}"
    if not _E164.fullmatch(phone):
        raise ValueError("expected an international number such as +77011234567")
    return phone
