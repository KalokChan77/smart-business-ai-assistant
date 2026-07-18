from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@dataclass(frozen=True, slots=True)
class Database:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def create(cls, url: str, *, echo: bool = False) -> "Database":
        engine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
        )
        return cls(
            engine=engine,
            session_factory=async_sessionmaker(
                bind=engine,
                expire_on_commit=False,
                autoflush=False,
            ),
        )

    async def close(self) -> None:
        await self.engine.dispose()
