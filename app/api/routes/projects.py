import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.api.routes.workspaces import (
    ACTIVE,
    DELETED,
    add_audit,
    can_manage,
    can_view,
    describe_changes,
    page_count,
    visible_workspace,
)
from app.core.security import to_ms, utcnow
from app.models.content import EnvFile, Project
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.content import ProjectIn, ProjectOut, ProjectPage

router = APIRouter(tags=["projects"])
MISSING = "No project with that id."


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=MISSING) from None


def project_options():
    return (
        selectinload(Project.owner),
        selectinload(Project.workspace).selectinload(Workspace.owner),
        selectinload(Project.workspace).selectinload(Workspace.members).selectinload(WorkspaceMember.user),
    )


def project_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=str(project.id),
        workspace_id=str(project.workspace_id),
        name=project.name,
        desc=project.description,
        status=project.status,
        owner_id=str(project.owner_id),
        owner_email=project.owner.email,
        owner_name=project.owner.name,
        created=to_ms(project.created_at) or 0,
    )


async def visible_project(db: Db, user: User, project_id: str) -> Project:
    project = await db.scalar(select(Project).where(Project.id == parse_id(project_id)).options(*project_options()))
    if project is None or project.status != ACTIVE or not can_view(user, project.workspace):
        raise HTTPException(status_code=404, detail=MISSING)
    return project


@router.get("/workspaces/{workspace_id}/projects", response_model=ProjectPage)
async def list_projects(
    workspace_id: str,
    user: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(description="Match name or description")] = None,
) -> ProjectPage:
    workspace = await visible_workspace(db, user, workspace_id)
    filters = [Project.workspace_id == workspace.id, Project.status == ACTIVE]
    term = (keyword or "").strip()
    if term:
        like = f"%{term}%"
        filters.append(or_(Project.name.ilike(like), Project.description.ilike(like)))
    total_records = await db.scalar(select(func.count()).select_from(Project).where(*filters)) or 0
    projects = await db.scalars(
        select(Project)
        .where(*filters)
        .options(selectinload(Project.owner))
        .order_by(Project.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return ProjectPage(
        data=[project_out(project) for project in projects],
        current_page=page,
        total_pages=page_count(total_records, limit),
        total_records=total_records,
        limit=limit,
    )


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectOut, status_code=201)
async def create_project(workspace_id: str, body: ProjectIn, user: CurrentUser, db: Db) -> ProjectOut:
    workspace = await visible_workspace(db, user, workspace_id)
    if not can_manage(user, workspace):
        raise HTTPException(status_code=403, detail="You cannot change this workspace.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    description = body.desc.strip()
    project = Project(
        workspace_id=workspace.id,
        name=name,
        description=description,
        owner_id=user.id,
        status=ACTIVE,
        created_at=utcnow(),
    )
    db.add(project)
    await db.flush()
    add_audit(db, workspace.id, user, "Created project", name, f'Description: "{description}".' if description else "No description.")
    loaded = await visible_project(db, user, str(project.id))
    return project_out(loaded)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, user: CurrentUser, db: Db) -> ProjectOut:
    return project_out(await visible_project(db, user, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectIn, user: CurrentUser, db: Db) -> ProjectOut:
    project = await visible_project(db, user, project_id)
    if not can_manage(user, project.workspace):
        raise HTTPException(status_code=403, detail="You cannot change this workspace.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    description = body.desc.strip()
    detail = describe_changes([("Name", project.name, name), ("Description", project.description, description)])
    project.name = name
    project.description = description
    if detail:
        add_audit(db, project.workspace_id, user, "Updated project", name, f"{detail}.")
    await db.flush()
    return project_out(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, user: CurrentUser, db: Db) -> None:
    project = await visible_project(db, user, project_id)
    if not can_manage(user, project.workspace):
        raise HTTPException(status_code=403, detail="You cannot change this workspace.")
    env_count = await db.scalar(
        select(func.count()).select_from(EnvFile).where(EnvFile.project_id == project.id, EnvFile.status == ACTIVE)
    ) or 0
    add_audit(
        db,
        project.workspace_id,
        user,
        "Deleted project",
        project.name,
        f"Removed the project and {env_count} env file{'' if env_count == 1 else 's'} inside it.",
    )
    await db.execute(update(EnvFile).where(EnvFile.project_id == project.id, EnvFile.status == ACTIVE).values(status=DELETED))
    project.status = DELETED
