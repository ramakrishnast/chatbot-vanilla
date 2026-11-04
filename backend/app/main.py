import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.logging_setup import configure_logging
from app.ollama import LLMClient, OllamaClient, OllamaError
from app.routers import conversations, health, models

log = logging.getLogger("app")

QUIET_PATHS = {"/health", "/ready"}


def create_app(
    settings: Settings | None = None,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own sessionmaker and a fake LLM client."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    engine: AsyncEngine | None = None
    if sessionmaker is None:
        engine = create_engine(settings.database_url)
        sessionmaker = create_sessionmaker(engine)
    llm_client: LLMClient = llm or OllamaClient(settings.ollama_base_url, settings.ollama_timeout)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info(
            "starting",
            extra={"ollama": settings.ollama_base_url, "default_model": settings.default_model},
        )
        yield
        await llm_client.aclose()
        if engine is not None:
            await engine.dispose()
        log.info("stopped")

    app = FastAPI(title="Local Chat", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessionmaker = sessionmaker
    app.state.llm = llm_client

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": request_id})
            raise
        response.headers["X-Request-ID"] = request_id
        level = logging.DEBUG if request.url.path in QUIET_PATHS else logging.INFO
        log.log(
            level,
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    @app.exception_handler(OllamaError)
    async def ollama_unavailable(_: Request, exc: OllamaError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(conversations.router)

    # `make start` serves the built UI from the same origin as the API.
    if settings.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="ui")

    return app


app = create_app()
