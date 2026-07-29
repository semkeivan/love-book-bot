import hmac
import hashlib
from config import PAYMENT_SECRET


def make_token(user_id: int) -> str:
    """Сгенерировать HMAC-токен для user_id."""
    return hmac.new(
        PAYMENT_SECRET.encode(),
        f"paid:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def verify_token(user_id: int, token: str) -> bool:
    """Проверить токен — защита от подделки."""
    expected = make_token(user_id)
    return hmac.compare_digest(expected, token)
