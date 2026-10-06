import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()

SESSION_TTL = timedelta(days=14)
RESET_TTL = timedelta(minutes=10)
LOGIN_HISTORY = timedelta(days=400)
MIN_PASSWORD = 6


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def issue_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def reset_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def to_ms(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp() * 1000)


def utcnow() -> datetime:
    return datetime.now(UTC)


def device_label(agent: str) -> str:
    if not agent:
        return "Unknown device"
    if re.search(r"Edg/", agent):
        browser = "Edge"
    elif re.search(r"Chrome/", agent):
        browser = "Chrome"
    elif re.search(r"Firefox/", agent):
        browser = "Firefox"
    elif re.search(r"Safari/", agent):
        browser = "Safari"
    else:
        browser = "Browser"
    if re.search(r"iPhone|iPad", agent):
        os_name = "iOS"
    elif re.search(r"Android", agent):
        os_name = "Android"
    elif re.search(r"Mac OS X", agent):
        os_name = "macOS"
    elif re.search(r"Windows", agent):
        os_name = "Windows"
    elif re.search(r"Linux", agent):
        os_name = "Linux"
    else:
        os_name = "Unknown OS"
    return f"{browser} on {os_name}"
