from fastapi import APIRouter

from app.chat_service import is_chat_model
from app.deps import LLMDep, SettingsDep
from app.schemas import ModelList

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=ModelList)
async def list_models(llm: LLMDep, settings: SettingsDep, refresh: bool = False) -> ModelList:
    """Chat-capable models installed in Ollama (embedding-only models are hidden)."""
    models = [m for m in await llm.list_models(refresh=refresh) if is_chat_model(m)]
    names = {m.name for m in models}
    default: str | None
    if settings.default_model and settings.default_model in names:
        default = settings.default_model
    else:
        default = models[0].name if models else None
    return ModelList(models=models, default=default)
