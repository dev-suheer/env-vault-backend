from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.database import database_ready

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db", response_model=None)
async def health_db() -> JSONResponse | dict[str, str]:
    if await database_ready():
        return {"status": "ok"}
    return JSONResponse(status_code=503, content={"status": "unavailable"})
