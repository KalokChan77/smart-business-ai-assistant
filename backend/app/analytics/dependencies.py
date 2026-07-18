from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.repository import SQLAlchemyAnalyticsRepository
from app.analytics.service import AnalyticsService
from app.db.dependencies import get_db_session


def get_analytics_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SQLAlchemyAnalyticsRepository:
    return SQLAlchemyAnalyticsRepository(session)


def get_analytics_service(
    repository: Annotated[
        SQLAlchemyAnalyticsRepository,
        Depends(get_analytics_repository),
    ],
) -> AnalyticsService:
    return AnalyticsService(repository)
