from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    runtime = request.app.state.runtime
    if runtime.database is None:
        raise RuntimeError("Database is not configured.")

    async with runtime.database.session_factory() as session:
        yield session
