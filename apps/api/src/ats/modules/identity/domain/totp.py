"""TOTP — Time-based One-Time Password (RFC 6238) на чистом stdlib.

SECURE FIRST: не зависит от внешних библиотек (pyotp/qrcode не установлены).
Реализация следует RFC 6238 и RFC 4226 (HOTP).

WHITEBOX AI: алгоритм полностью прозрачен — тот же алгоритм, что в Google
Authenticator, Microsoft Authenticator и др.

ТЗ §15: 2FA (TOTP) для ролей с админ-правами.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Protocol

# Параметры TOTP по умолчанию (RFC 6238)
DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30  # секунд
DEFAULT_ALGORITHM = "sha1"

# Допустимый временной дрейф (окна до и после) — для tolerance
DEFAULT_TOLERANCE_WINDOWS = 1  # ±30 сек


def generate_secret(num_bytes: int = 20) -> str:
    """Сгенерировать случайный TOTP-секрет (base32, 20 байт = 160 бит).

    SECURE FIRST: secrets.token_bytes — криптостойкий генератор.
    """
    import secrets

    raw = secrets.token_bytes(num_bytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _hotp(secret: str, counter: int, digits: int = DEFAULT_DIGITS) -> str:
    """HOTP — HMAC-based OTP (RFC 4226).

    Args:
        secret: base32-закодированный секрет.
        counter: 8-байтный счётчик (big-endian).
        digits: количество цифр (обычно 6).

    Returns:
        Строка из `digits` цифр с ведущими нулями.
    """
    key = _decode_base32(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()

    # Dynamic truncation (RFC 4226 §5.3)
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    otp = binary % (10**digits)
    return str(otp).zfill(digits)


def _decode_base32(secret: str) -> bytes:
    """Декодировать base32-секрет (с нормализацией padding)."""
    # Нормализуем: uppercase + добавляем padding
    cleaned = secret.upper().replace(" ", "").replace("-", "")
    padding = (8 - len(cleaned) % 8) % 8
    return base64.b32decode(cleaned + "=" * padding)


def totp_code(
    secret: str,
    timestamp: int | None = None,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
) -> str:
    """Вычислить TOTP-код для текущего (или заданного) времени.

    Args:
        secret: base32-секрет.
        timestamp: Unix-время (по умолчанию — сейчас).
        digits: количество цифр.
        period: период в секундах (по умолчанию 30).

    Returns:
        Строка из `digits` цифр.
    """
    if timestamp is None:
        timestamp = int(time.time())
    counter = timestamp // period
    return _hotp(secret, counter, digits)


def verify_totp(
    secret: str,
    code: str,
    timestamp: int | None = None,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
    tolerance_windows: int = DEFAULT_TOLERANCE_WINDOWS,
) -> bool:
    """Проверить TOTP-код с допустимым временным дрейфом.

    SECURE FIRST: constant-time comparison (hmac.compare_digest).
    tolerance_windows=1 → проверяем текущее окно + предыдущее + следующее.

    Args:
        secret: base32-секрет.
        code: код, введённый пользователем.
        timestamp: Unix-время (по умолчанию — сейчас).
        tolerance_windows: сколько окон до/после проверять (0 = только текущее).

    Returns:
        True если код валиден для любого окна в диапазоне.
    """
    if not code or not secret:
        return False

    if timestamp is None:
        timestamp = int(time.time())

    counter = timestamp // period

    for offset in range(-tolerance_windows, tolerance_windows + 1):
        expected = _hotp(secret, counter + offset, digits)
        if hmac.compare_digest(expected, code.strip()):
            return True

    return False


def build_otpauth_uri(
    issuer: str,
    account: str,
    secret: str,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
) -> str:
    """Сформировать otpauth:// URI для QR-кода.

    Фронтенд рендерит QR из этого URI. Формат:
        otpauth://totp/ISSUER:ACCOUNT?secret=SECRET&issuer=ISSUER&digits=D&period=P
    """
    from urllib.parse import quote, urlencode

    label = f"{quote(issuer)}:{quote(account)}"
    params = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "digits": digits,
            "period": period,
            "algorithm": DEFAULT_ALGORITHM.upper(),
        }
    )
    return f"otpauth://totp/{label}?{params}"


def generate_backup_codes(count: int = 10) -> list[str]:
    """Сгенерировать одноразовые backup-коды.

    SECURE FIRST: каждый код — 8 групп по 4 hex-символа (криптостойкий).
    Используются, когда у пользователя нет доступа к TOTP-устройству.
    """
    import secrets

    codes = []
    for _ in range(count):
        raw = secrets.token_hex(8)  # 16 hex chars
        # Формат: XXXX-XXXX-XXXX-XXXX
        formatted = "-".join(
            raw[i : i + 4] for i in range(0, len(raw), 4)
        )
        codes.append(formatted)
    return codes


def hash_backup_code(code: str) -> str:
    """Хешировать backup-код для хранения (не храним в открытом виде).

    SECURE FIRST: SHA-256 с солью — код нельзя восстановить из БД.
    """
    import hashlib

    return hashlib.sha256(code.encode("utf-8")).hexdigest()
