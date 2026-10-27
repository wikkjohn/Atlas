"""FastAPI application factory."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router, v1_router
from app.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import CORRELATION_HEADER, CorrelationIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description=(
            "Synthetic enterprise banking simulation and AI testing platform. "
            "All data is synthetic; no real banking systems are connected."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Correlation middleware is added first so CORS wraps it and error responses still
    # carry CORS headers.
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[CORRELATION_HEADER],
    )
    register_error_handlers(app)
    app.include_router(api_router)
    app.include_router(v1_router)

    logging.getLogger("atlas").info(
        "application created",
        extra={"environment": settings.environment, "version": __version__},
    )
    return app


app = create_app()
