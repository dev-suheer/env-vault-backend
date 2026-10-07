import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.core.security import to_ms, utcnow
from app.models.content import Project
from app.models.user import User
from app.models.workspace import AuditLog, Workspace, WorkspaceMember
from app.schemas.workspace import AuditOut, AuditPage, MemberOut, WorkspaceIn, WorkspaceOut, WorkspacePage

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

ACTIVE = "active"
DELETED = "deleted"
MISSING = "No workspace with that id."


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=MISSING) from None


def workspace_out(workspace: Workspace, project_count: int = 0) -> WorkspaceOut:
    members = sorted((member for member in workspace.members if member.status == ACTIVE), key=lambda member: member.user.email)
    return WorkspaceOut(
        id=str(workspace.id),
        name=workspace.name,
        desc=workspace.description,
        status=workspace.status,
        owner_id=str(workspace.owner_id),
        owner_email=workspace.owner.email,
        owner_name=workspace.owner.name,
        members=[
            MemberOut(id=str(member.user.id), email=member.user.email, name=member.user.name, access=member.access)
            for member in members
        ],
        project_count=project_count,
        created=to_ms(workspace.created_at) or 0,
    )


async def workspace_payload(db: Db, workspace: Workspace) -> WorkspaceOut:
    counts = await project_counts(db, [workspace.id])
    return workspace_out(workspace, counts.get(workspace.id, 0))


async def project_counts(db: Db, workspace_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not workspace_ids:
        return {}
    rows = await db.execute(
        select(Project.workspace_id, func.count())
        .where(Project.workspace_id.in_(workspace_ids), Project.status == ACTIVE)
        .group_by(Project.workspace_id)
    )
    return {workspace_id: count for workspace_id, count in rows.all()}


def audit_out(entry: AuditLog) -> AuditOut:
    return AuditOut(
        id=str(entry.id),
        workspace_id=str(entry.workspace_id),
        at=to_ms(entry.created_at) or 0,
        actor_id=str(entry.actor_id),
        actor_name=entry.actor.name,
        actor_email=entry.actor.email,
        action=entry.action,
        subject=entry.subject,
        detail=entry.detail,
    )


def describe_changes(fields: list[tuple[str, str, str]]) -> str:
    parts: list[str] = []
    for label, previous, current in fields:
        if previous == current:
            continue
        if not previous:
            parts.append(f'{label} set to "{current}"')
        elif not current:
            parts.append(f'{label} cleared (was "{previous}")')
        else:
            parts.append(f'{label} changed from "{previous}" to "{current}"')
    return ". ".join(parts)


def add_audit(db: Db, workspace_id: uuid.UUID, actor: User, action: str, subject: str, detail: str) -> None:
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_id=actor.id,
            action=action,
            subject=subject,
            detail=detail,
            created_at=utcnow(),
        )
    )


def can_view(user: User, workspace: Workspace) -> bool:
    if workspace.status != ACTIVE:
        return False
    if user.role == "admin" or workspace.owner_id == user.id:
        return True
    return any(member.user_id == user.id and member.status == ACTIVE for member in workspace.members)


def can_manage(user: User, workspace: Workspace) -> bool:
    return workspace.status == ACTIVE and (user.role == "admin" or workspace.owner_id == user.id)


async def load_workspace(db: Db, workspace_id: uuid.UUID) -> Workspace | None:
    return await db.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id)
        .options(
            selectinload(Workspace.owner),
            selectinload(Workspace.members).selectinload(WorkspaceMember.user),
        )
    )


async def visible_workspace(db: Db, user: User, workspace_id: str) -> Workspace:
    workspace = await load_workspace(db, parse_id(workspace_id))
    if workspace is None or not can_view(user, workspace):
        raise HTTPException(status_code=404, detail=MISSING)
    return workspace


def page_count(total: int, limit: int) -> int:
    if total == 0:
        return 0
    return (total + limit - 1) // limit


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(body: WorkspaceIn, user: CurrentUser, db: Db) -> WorkspaceOut:
    if user.role != "pm":
        raise HTTPException(status_code=403, detail="Only a project manager can create a workspace.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    description = body.desc.strip()
    workspace = Workspace(name=name, description=description, owner_id=user.id, status=ACTIVE, created_at=utcnow())
    db.add(workspace)
    await db.flush()
    add_audit(
        db,
        workspace.id,
        user,
        "Created workspace",
        name,
        f'Description: "{description}".' if description else "No description.",
    )
    loaded = await load_workspace(db, workspace.id)
    if loaded is None:
        raise HTTPException(status_code=404, detail=MISSING)
    counts = await project_counts(db, [loaded.id])
    return workspace_out(loaded, counts.get(loaded.id, 0))


@router.get("", response_model=WorkspacePage)
async def list_workspaces(
    user: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(description="Match name or description")] = None,
) -> WorkspacePage:
    filters = [Workspace.status == ACTIVE]
    if user.role != "admin":
        member_of = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id, WorkspaceMember.status == ACTIVE)
        filters.append(or_(Workspace.owner_id == user.id, Workspace.id.in_(member_of)))
    term = (keyword or "").strip()
    if term:
        like = f"%{term}%"
        filters.append(or_(Workspace.name.ilike(like), Workspace.description.ilike(like)))

    count_stmt = select(func.count()).select_from(Workspace).where(*filters)
    list_stmt = (
        select(Workspace)
        .where(*filters)
        .options(selectinload(Workspace.owner), selectinload(Workspace.members).selectinload(WorkspaceMember.user))
        .order_by(Workspace.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    total_records = await db.scalar(count_stmt) or 0
    workspaces = list(await db.scalars(list_stmt))
    counts = await project_counts(db, [workspace.id for workspace in workspaces])
    return WorkspacePage(
        data=[workspace_out(workspace, counts.get(workspace.id, 0)) for workspace in workspaces],
        current_page=page,
        total_pages=page_count(total_records, limit),
        total_records=total_records,
        limit=limit,
    )


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(workspace_id: str, user: CurrentUser, db: Db) -> WorkspaceOut:
    workspace = await visible_workspace(db, user, workspace_id)
    counts = await project_counts(db, [workspace.id])
    return workspace_out(workspace, counts.get(workspace.id, 0))


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(workspace_id: str, body: WorkspaceIn, user: CurrentUser, db: Db) -> WorkspaceOut:
    workspace = await visible_workspace(db, user, workspace_id)
    if not can_manage(user, workspace):
        raise HTTPException(status_code=403, detail="You cannot change this workspace.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    description = body.desc.strip()
    detail = describe_changes([("Name", workspace.name, name), ("Description", workspace.description, description)])
    workspace.name = name
    workspace.description = description
    if detail:
        add_audit(db, workspace.id, user, "Updated workspace", name, f"{detail}.")
    await db.flush()
    counts = await project_counts(db, [workspace.id])
    return workspace_out(workspace, counts.get(workspace.id, 0))


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, user: CurrentUser, db: Db) -> None:
    workspace = await visible_workspace(db, user, workspace_id)
    if not can_manage(user, workspace):
        raise HTTPException(status_code=403, detail="You cannot change this workspace.")
    add_audit(db, workspace.id, user, "Deleted workspace", workspace.name, "Marked the workspace as deleted.")
    from app.models.content import EnvFile, Notification, Project

    await db.execute(update(Project).where(Project.workspace_id == workspace.id, Project.status == ACTIVE).values(status=DELETED))
    await db.execute(update(EnvFile).where(EnvFile.workspace_id == workspace.id, EnvFile.status == ACTIVE).values(status=DELETED))
    await db.execute(update(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.status == ACTIVE).values(status=DELETED))
    await db.execute(update(Notification).where(Notification.workspace_id == workspace.id, Notification.status == ACTIVE).values(status=DELETED))
    workspace.status = DELETED


@router.get("/{workspace_id}/audit", response_model=AuditPage)
async def list_audit(
    workspace_id: str,
    user: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(description="Match action, subject, or detail")] = None,
) -> AuditPage:
    workspace = await visible_workspace(db, user, workspace_id)
    filters = [AuditLog.workspace_id == workspace.id]
    term = (keyword or "").strip()
    if term:
        like = f"%{term}%"
        filters.append(or_(AuditLog.action.ilike(like), AuditLog.subject.ilike(like), AuditLog.detail.ilike(like)))
    total_records = await db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    entries = await db.scalars(
        select(AuditLog)
        .where(*filters)
        .options(selectinload(AuditLog.actor))
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return AuditPage(
        data=[audit_out(entry) for entry in entries],
        current_page=page,
        total_pages=page_count(total_records, limit),
        total_records=total_records,
        limit=limit,
    )
