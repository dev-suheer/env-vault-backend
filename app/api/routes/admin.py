from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.api.routes import admin_users, dashboard

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
router.include_router(admin_users.router)
router.include_router(dashboard.router)
