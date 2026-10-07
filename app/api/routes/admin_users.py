from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser, Db
from app.api.routes.auth import user_out
from app.api.routes.envs import ACTIVE, keyword_filter, list_envs
from app.api.routes.users import find_user
from app.models.content import EnvFile
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.auth import AdminUserIn, UserOut, UserPage, UserWorkspaceOut, UserWorkspacePage
from app.schemas.content import EnvPage

router = APIRouter(prefix="/users", tags=["admin"])


@router.get("", response_model=UserPage)
async def list_users(
    admin: AdminUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    role: Annotated[str | None, Query()] = None,
    status: Annotated[bool | None, Query(description="true for active accounts, false for inactive")] = None,
    keyword: Annotated[str | None, Query(description="Match name or email")] = None,
) -> UserPage:
    if role is not None and role not in {"pm", "dev"}:
        raise HTTPException(status_code=400, detail="Choose a valid role.")
    filters = [User.role != "admin"]
    if role is not None:
        filters.append(User.role == role)
    if status is not None:
        filters.append(User.status.is_(status))
    term = (keyword or "").strip()
    if term:
        like = f"%{term}%"
        filters.append(or_(User.name.ilike(like), User.email.ilike(like)))

    count_filters = [User.role != "admin"]
    if status is not None:
        count_filters.append(User.status.is_(status))
    if term:
        like = f"%{term}%"
        count_filters.append(or_(User.name.ilike(like), User.email.ilike(like)))
    grouped = select(User.role, func.count()).select_from(User).group_by(User.role)
    if count_filters:
        grouped = grouped.where(*count_filters)
    by_role = {role_name: count for role_name, count in (await db.execute(grouped)).all()}
    project_managers = by_role.get("pm", 0)
    devs = by_role.get("dev", 0)

    count_stmt = select(func.count()).select_from(User)
    list_stmt = select(User).options(selectinload(User.logins)).order_by(User.created_at.desc().nulls_last(), User.email)
    if filters:
        count_stmt = count_stmt.where(*filters)
        list_stmt = list_stmt.where(*filters)
    total_records = await db.scalar(count_stmt) or 0
    total_pages = (total_records + limit - 1) // limit if total_records else 0
    users = await db.scalars(list_stmt.offset((page - 1) * limit).limit(limit))
    return UserPage(
        data=[user_out(user) for user in users],
        current_page=page,
        total_pages=total_pages,
        total_records=total_records,
        limit=limit,
        counts={"all": project_managers + devs, "project_managers": project_managers, "devs": devs},
    )


@router.get("/{user_id}/workspaces", response_model=UserWorkspacePage)
async def list_user_workspaces(
    user_id: str,
    admin: AdminUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(description="Match workspace name")] = None,
) -> UserWorkspacePage:
    user = await find_user(db, user_id)
    member_of = select(WorkspaceMember.workspace_id).where(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.status == "active",
    )
    filters = [Workspace.status == "active", or_(Workspace.owner_id == user.id, Workspace.id.in_(member_of))]
    term = (keyword or "").strip()
    if term:
        filters.append(Workspace.name.ilike(f"%{term}%"))
    total_records = await db.scalar(select(func.count()).select_from(Workspace).where(*filters)) or 0
    total_pages = (total_records + limit - 1) // limit if total_records else 0
    rows = await db.scalars(
        select(Workspace)
        .where(*filters)
        .options(selectinload(Workspace.members))
        .order_by(Workspace.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    data = []
    for workspace in rows:
        active_members = [member for member in workspace.members if member.status == "active"]
        membership = next((member for member in active_members if member.user_id == user.id), None)
        if workspace.owner_id == user.id:
            access = "owner"
        elif membership is not None and membership.access == "edit":
            access = "edit"
        else:
            access = "view"
        data.append(
            UserWorkspaceOut(
                id=str(workspace.id),
                name=workspace.name,
                access=access,
                members=len(active_members) + 1,
            )
        )
    return UserWorkspacePage(
        data=data,
        current_page=page,
        total_pages=total_pages,
        total_records=total_records,
        limit=limit,
    )


@router.get("/{user_id}/envs", response_model=EnvPage)
async def list_user_envs(
    user_id: str,
    admin: AdminUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query()] = None,
) -> EnvPage:
    owner = await find_user(db, user_id)
    if owner.role == "admin":
        raise HTTPException(status_code=404, detail="No account with that id.")
    filters = [EnvFile.owner_id == owner.id, EnvFile.status == ACTIVE]
    keyword_filter(filters, keyword)
    return await list_envs(db, filters, page, limit)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: str, admin: AdminUser, db: Db) -> UserOut:
    return user_out(await find_user(db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: AdminUserIn, admin: AdminUser, db: Db) -> UserOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if body.role not in {"admin", "pm", "dev"}:
        raise HTTPException(status_code=400, detail="Choose a valid role.")
    user = await find_user(db, user_id)
    if body.role == "admin" and user.role != "admin":
        raise HTTPException(status_code=400, detail="There is only one admin account.")
    if admin.email == user.email and body.role != user.role:
        raise HTTPException(status_code=400, detail="You cannot change your own role.")
    if admin.email == user.email and not body.status:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    user.name = name
    user.role = body.role
    user.status = body.status
    await db.flush()
    return user_out(user)
