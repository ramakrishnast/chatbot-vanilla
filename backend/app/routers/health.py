import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.deps import LLMDep, SessionmakerDep

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(sessionmaker: SessionmakerDep, llm: LLMDep) -> JSONResponse:
    """Readiness: Postgres and Ollama are both reachable."""
    checks = {"database": False, "ollama": False}
    try:
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        log.warning("readiness: database unavailable", extra={"error": str(exc)})
    checks["ollama"] = await llm.ping()
    ok = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "unavailable", "checks": checks},
        status_code=200 if ok else 503,
    )
