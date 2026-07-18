from dataclasses import dataclass

from redis.asyncio import Redis

from app.cache.client import create_redis_client
from app.core.config import Settings
from app.db.session import Database
from app.health.probes import PendingProbe, ReadinessProbe
from app.infrastructure.probes import DatabaseProbe, RedisProbe


@dataclass(slots=True)
class RuntimeResources:
    database: Database | None
    redis: Redis | None
    readiness_probes: tuple[ReadinessProbe, ...]

    @classmethod
    def create(cls, settings: Settings) -> "RuntimeResources":
        probes: list[ReadinessProbe] = []

        database = None
        if settings.database_url is None:
            probes.append(
                PendingProbe(
                    name="database",
                    detail="DATABASE_URL is not configured.",
                )
            )
        else:
            database = Database.create(
                settings.database_url.get_secret_value(),
                echo=settings.database_echo,
            )
            probes.append(DatabaseProbe(database.engine))

        redis = None
        if settings.redis_url is None:
            probes.append(
                PendingProbe(
                    name="redis",
                    detail="REDIS_URL is not configured.",
                )
            )
        else:
            redis = create_redis_client(settings.redis_url.get_secret_value())
            probes.append(RedisProbe(redis))

        return cls(
            database=database,
            redis=redis,
            readiness_probes=tuple(probes),
        )

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
        if self.database is not None:
            await self.database.close()
