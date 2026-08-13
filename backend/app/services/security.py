from datetime import datetime, timedelta, timezone
from hashlib import sha256
import base64
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
import jwt
import pyotp

from app.config import settings


password_hasher = PasswordHasher(time_cost=3, memory_cost=19456, parallelism=2)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: int, is_admin: bool) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "admin": is_admin,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(hours=settings.login_session_hours),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> tuple[int, bool]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("アクセストークンではありません。")
    return int(payload["sub"]), payload.get("admin") is True


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    key = sha256(settings.encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(secret: str) -> str:
    return _fernet().decrypt(secret.encode()).decode()


def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def verify_mfa(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
