"""Сервис безопасности: хэширование паролей и генерация/проверка JWT.

Токены привязываются к fingerprint браузера (thumbmarkjs): в payload вшивается
SHA-256 хэш fingerprint. Проверка совпадения выполняется при авторизации/рефреше.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import Settings
from app.schemas.auth import TokenPair

# Ключи payload
_CLAIM_TYPE = "type"
_CLAIM_FINGERPRINT = "fp"
_CLAIM_JTI = "jti"
_CLAIM_SUB = "sub"

_TYPE_ACCESS = "access"
_TYPE_REFRESH = "refresh"


class SecurityService:
    """Криптографические операции: пароли (bcrypt) и JWT с привязкой к fingerprint."""

    def __init__(self, settings: Settings) -> None:
        self._jwt_settings = settings.jwt

    def hash_password(self, password: str) -> str:
        """Хэшировать пароль (bcrypt)."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Проверить пароль против bcrypt-хэша."""
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    def hash_fingerprint(self, fingerprint: str) -> str:
        """SHA-256 хэш клиентского fingerprint (в БД/токены хранится только хэш)."""
        return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()

    def create_token_pair(self, user_id: str, fingerprint: str) -> TokenPair:
        """Создать пару access (15 мин) / refresh (7 дней) токенов для пользователя."""
        fingerprint_hash = self.hash_fingerprint(fingerprint)
        return TokenPair(
            access_token=self._create_token(
                token_type=_TYPE_ACCESS,
                subject=user_id,
                fingerprint_hash=fingerprint_hash,
                expires_delta=timedelta(minutes=self._jwt_settings.access_token_expire_minutes),
            ),
            refresh_token=self._create_token(
                token_type=_TYPE_REFRESH,
                subject=user_id,
                fingerprint_hash=fingerprint_hash,
                expires_delta=timedelta(days=self._jwt_settings.refresh_token_expire_days),
            ),
        )

    def decode_token(self, token: str, *, expected_type: str) -> dict[str, Any]:
        """Декодировать и проверить JWT.

        Поднимает jwt.PyJWTError при невалидной подписи/истёкшем сроке
        и ValueError при несовпадении типа токена.
        """
        payload = jwt.decode(token, self._jwt_settings.secret_key, algorithms=[self._jwt_settings.algorithm])
        if payload.get(_CLAIM_TYPE) != expected_type:
            raise ValueError(f"Ожидался токен типа {expected_type!r}")
        return payload

    def _create_token(
        self, *, token_type: str, subject: str, fingerprint_hash: str, expires_delta: timedelta
    ) -> str:
        """Сформировать подписанный JWT с привязкой к fingerprint."""
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            _CLAIM_SUB: subject,
            _CLAIM_TYPE: token_type,
            _CLAIM_FINGERPRINT: fingerprint_hash,
            _CLAIM_JTI: str(uuid.uuid4()),
            "iat": now,
            "exp": now + expires_delta,
        }
        return jwt.encode(payload, self._jwt_settings.secret_key, algorithm=self._jwt_settings.algorithm)
