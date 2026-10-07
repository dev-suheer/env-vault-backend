from fastapi import APIRouter

from app.api.routes import admin, auth, envs, health, invites, projects, users, workspaces

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(workspaces.router)
api_router.include_router(projects.router)
api_router.include_router(envs.router)
api_router.include_router(invites.router)
api_router.include_router(admin.router)
