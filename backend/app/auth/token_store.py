from datetime import UTC, datetime
from math import ceil
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError


class TokenStoreUnavailable(RuntimeError):
    """Raised when revocation state cannot be read safely."""


class TokenRevocationStore(Protocol):
    async def revoke(self, jti: str, expires_at: datetime) -> None: ...

    async def consume(self, jti: str, expires_at: datetime) -> bool: ...

    async def is_revoked(self, jti: str) -> bool: ...


class RedisTokenRevocationStore:
    def __init__(self, redis: Redis, *, key_prefix: str = "auth:revoked:") -> None:
        self._redis = redis
        self._key_prefix = key_prefix

    async def revoke(self, jti: str, expires_at: datetime) -> None:
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        ttl_seconds = max(1, ceil(remaining))
        try:
            await self._redis.set(self._key(jti), "1", ex=ttl_seconds)
        except RedisError as exc:
            raise TokenStoreUnavailable("Token revocation store is unavailable.") from exc

    async def consume(self, jti: str, expires_at: datetime) -> bool:
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        ttl_seconds = max(1, ceil(remaining))
        try:
            was_stored = await self._redis.set(
                self._key(jti),
                "1",
                ex=ttl_seconds,
                nx=True,
            )
            return bool(was_stored)
        except RedisError as exc:
            raise TokenStoreUnavailable("Token revocation store is unavailable.") from exc

    async def is_revoked(self, jti: str) -> bool:
        try:
            return bool(await self._redis.exists(self._key(jti)))
        except RedisError as exc:
            raise TokenStoreUnavailable("Token revocation store is unavailable.") from exc

    def _key(self, jti: str) -> str:
        return f"{self._key_prefix}{jti}"
