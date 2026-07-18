from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.health.probes import PendingProbe, ReadinessProbe
from app.infrastructure.runtime import RuntimeResources


def pending_readiness_probes() -> tuple[ReadinessProbe, ...]:
    return (
        PendingProbe(name="database", detail="Application startup is pending."),
        PendingProbe(name="redis", detail="Application startup is pending."),
    )


def create_app(
    settings: Settings | None = None,
    readiness_probes: Sequence[ReadinessProbe] | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    injected_probes = tuple(readiness_probes) if readiness_probes is not None else None
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if injected_probes is not None:
            app.state.readiness_probes = injected_probes
            yield
            return

        runtime = RuntimeResources.create(resolved_settings)
        app.state.runtime = runtime
        app.state.readiness_probes = runtime.readiness_probes
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.9.0",
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.state.settings = resolved_settings
    app.state.runtime = None
    app.state.readiness_probes = injected_probes or pending_readiness_probes()
    app.include_router(api_router, prefix=resolved_settings.api_v1_prefix)
    return app


app = create_app()
