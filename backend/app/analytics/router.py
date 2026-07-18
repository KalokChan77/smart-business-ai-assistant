from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.analytics.dependencies import get_analytics_service
from app.analytics.schemas import (
    AIRunMetricsResponse,
    AnalyticsOverviewResponse,
    AnalyticsPeriodQuery,
    CategoryDistributionResponse,
    ConsultationTrendResponse,
    SatisfactionResponse,
)
from app.analytics.service import AnalyticsService
from app.auth.dependencies import require_any_role
from app.auth.principal import Principal

router = APIRouter(prefix="/analytics", tags=["analytics"])
AnalyticsPrincipal = Annotated[
    Principal,
    Depends(require_any_role("admin", "decision_maker")),
]
AnalyticsServiceDependency = Annotated[
    AnalyticsService,
    Depends(get_analytics_service),
]
AnalyticsPeriod = Annotated[AnalyticsPeriodQuery, Query()]


@router.get(
    "/overview",
    response_model=AnalyticsOverviewResponse,
    summary="查询当前租户统计总览",
)
async def get_analytics_overview(
    principal: AnalyticsPrincipal,
    service: AnalyticsServiceDependency,
    period: AnalyticsPeriod,
) -> AnalyticsOverviewResponse:
    return await service.overview(principal, period)


@router.get(
    "/consultations",
    response_model=ConsultationTrendResponse,
    summary="查询当前租户咨询量趋势",
)
async def get_consultation_trend(
    principal: AnalyticsPrincipal,
    service: AnalyticsServiceDependency,
    period: AnalyticsPeriod,
) -> ConsultationTrendResponse:
    return await service.consultations(principal, period)


@router.get(
    "/categories",
    response_model=CategoryDistributionResponse,
    summary="查询当前租户问题分类分布",
)
async def get_category_distribution(
    principal: AnalyticsPrincipal,
    service: AnalyticsServiceDependency,
    period: AnalyticsPeriod,
) -> CategoryDistributionResponse:
    return await service.categories(principal, period)


@router.get(
    "/satisfaction",
    response_model=SatisfactionResponse,
    summary="查询当前租户满意度统计",
)
async def get_satisfaction_metrics(
    principal: AnalyticsPrincipal,
    service: AnalyticsServiceDependency,
    period: AnalyticsPeriod,
) -> SatisfactionResponse:
    return await service.satisfaction(principal, period)


@router.get(
    "/ai-runs",
    response_model=AIRunMetricsResponse,
    summary="查询当前租户 AI Run 统计",
)
async def get_ai_run_metrics(
    principal: AnalyticsPrincipal,
    service: AnalyticsServiceDependency,
    period: AnalyticsPeriod,
) -> AIRunMetricsResponse:
    return await service.ai_runs(principal, period)
