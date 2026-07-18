from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.health.schemas import DependencyCheck, ProbeStatus


class DatabaseProbe:
    name = "database"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def check(self) -> DependencyCheck:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            return DependencyCheck(
                name=self.name,
                status=ProbeStatus.ERROR,
                detail="PostgreSQL connection check failed.",
            )
        return DependencyCheck(name=self.name, status=ProbeStatus.OK)


class RedisProbe:
    name = "redis"

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def check(self) -> DependencyCheck:
        try:
            is_available = await self._client.ping()
        except Exception:
            is_available = False
        if not is_available:
            return DependencyCheck(
                name=self.name,
                status=ProbeStatus.ERROR,
                detail="Redis connection check failed.",
            )
        return DependencyCheck(name=self.name, status=ProbeStatus.OK)
