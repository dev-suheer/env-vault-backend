import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.api.routes.projects import project_out, visible_project
from app.api.routes.workspaces import ACTIVE, DELETED, add_audit, can_view, page_count, workspace_payload
from app.core.security import to_ms, utcnow
from app.models.content import EnvFile, Project, Variable
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.content import EnvDetail, EnvIn, EnvOut, EnvPage, ImportIn, ProjectEnvPage, VariableIn, VariableOut

router = APIRouter(tags=["envs"])
MISSING = "No env file with that id."
KINDS = {"Development", "Staging", "Production"}


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=MISSING) from None


def env_options():
    return (
        selectinload(EnvFile.owner),
        selectinload(EnvFile.variables),
        selectinload(EnvFile.project).selectinload(Project.owner),
        selectinload(EnvFile.workspace).selectinload(Workspace.owner),
        selectinload(EnvFile.workspace).selectinload(Workspace.members).selectinload(WorkspaceMember.user),
    )


def can_view_env(user: User, env: EnvFile) -> bool:
    if env.status != ACTIVE or (env.project is not None and env.project.status != ACTIVE):
        return False
    if env.workspace is None:
        return env.owner_id == user.id
    if env.workspace.status != ACTIVE:
        return False
    return can_view(user, env.workspace)


def can_edit_env(user: User, env: EnvFile) -> bool:
    if not can_view_env(user, env):
        return False
    if env.workspace is None:
        return env.owner_id == user.id
    if user.role == "admin" or env.owner_id == user.id or env.workspace.owner_id == user.id:
        return True
    return any(member.user_id == user.id and member.status == ACTIVE and member.access == "edit" for member in env.workspace.members)


def env_out(env: EnvFile) -> EnvOut:
    variables = sorted((item for item in env.variables if item.status == ACTIVE), key=lambda item: item.key)
    return EnvOut(
        id=str(env.id),
        name=env.name,
        desc=env.description,
        env=env.env_kind,
        vars=[VariableOut(id=str(item.id), k=item.key, v=item.value) for item in variables],
        updated=to_ms(env.updated_at) or 0,
        status=env.status,
        owner_id=str(env.owner_id),
        owner_email=env.owner.email,
        owner_name=env.owner.name,
        workspace_id=str(env.workspace_id) if env.workspace_id else None,
        project_id=str(env.project_id) if env.project_id else None,
    )


async def env_detail(db: Db, env: EnvFile) -> EnvDetail:
    return EnvDetail(
        **env_out(env).model_dump(),
        workspace=await workspace_payload(db, env.workspace) if env.workspace is not None else None,
        project=project_out(env.project) if env.project is not None else None,
    )


async def visible_env(db: Db, user: User, env_id: str) -> EnvFile:
    env = await db.scalar(select(EnvFile).where(EnvFile.id == parse_id(env_id)).options(*env_options()))
    if env is None or not can_view_env(user, env):
        raise HTTPException(status_code=404, detail=MISSING)
    return env


def clean_env(body: EnvIn) -> tuple[str, str, str]:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if body.env not in KINDS:
        raise HTTPException(status_code=400, detail="Choose Development, Staging, or Production.")
    return name, body.desc.strip(), body.env


def page(items: list[EnvOut], page_number: int, limit: int, total_records: int) -> EnvPage:
    return EnvPage(
        data=items,
        current_page=page_number,
        total_pages=page_count(total_records, limit),
        total_records=total_records,
        limit=limit,
    )


async def list_envs(db: Db, filters: list, page_number: int, limit: int) -> EnvPage:
    total_records = await db.scalar(select(func.count()).select_from(EnvFile).where(*filters)) or 0
    envs = await db.scalars(
        select(EnvFile)
        .where(*filters)
        .options(*env_options())
        .order_by(EnvFile.updated_at.desc())
        .offset((page_number - 1) * limit)
        .limit(limit)
    )
    return page([env_out(env) for env in envs], page_number, limit, total_records)


def keyword_filter(filters: list, keyword: str | None) -> None:
    term = (keyword or "").strip()
    if not term:
        return
    like = f"%{term}%"
    filters.append(or_(EnvFile.name.ilike(like), EnvFile.description.ilike(like)))


@router.get("/envs", response_model=EnvPage)
async def list_personal_envs(
    user: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(description="Match name or description")] = None,
    env: Annotated[str | None, Query(description="Development, Staging, or Production")] = None,
) -> EnvPage:
    filters = [EnvFile.owner_id == user.id, EnvFile.workspace_id.is_(None), EnvFile.status == ACTIVE]
    if env is not None:
        if env not in KINDS:
            raise HTTPException(status_code=400, detail="Choose Development, Staging, or Production.")
        filters.append(EnvFile.env_kind == env)
    keyword_filter(filters, keyword)
    return await list_envs(db, filters, page, limit)


@router.post("/envs", response_model=EnvDetail, status_code=201)
async def create_personal_env(body: EnvIn, user: CurrentUser, db: Db) -> EnvDetail:
    if user.role != "dev":
        raise HTTPException(status_code=403, detail="Only a dev can create a personal env.")
    name, description, kind = clean_env(body)
    env = EnvFile(
        name=name,
        description=description,
        env_kind=kind,
        owner_id=user.id,
        workspace_id=None,
        project_id=None,
        status=ACTIVE,
        updated_at=utcnow(),
    )
    db.add(env)
    await db.flush()
    return await env_detail(db, await visible_env(db, user, str(env.id)))


@router.get("/projects/{project_id}/envs", response_model=ProjectEnvPage)
async def list_project_envs(
    project_id: str,
    user: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(description="Match name or description")] = None,
    env: Annotated[str | None, Query()] = None,
) -> ProjectEnvPage:
    project = await visible_project(db, user, project_id)
    filters = [EnvFile.project_id == project.id, EnvFile.status == ACTIVE]
    if env is not None:
        if env not in KINDS:
            raise HTTPException(status_code=400, detail="Choose Development, Staging, or Production.")
        filters.append(EnvFile.env_kind == env)
    keyword_filter(filters, keyword)
    listed = await list_envs(db, filters, page, limit)
    return ProjectEnvPage(
        workspace=await workspace_payload(db, project.workspace),
        project=project_out(project),
        data=listed.data,
        current_page=listed.current_page,
        total_pages=listed.total_pages,
        total_records=listed.total_records,
        limit=listed.limit,
    )


@router.post("/projects/{project_id}/envs", response_model=EnvDetail, status_code=201)
async def create_project_env(project_id: str, body: EnvIn, user: CurrentUser, db: Db) -> EnvDetail:
    project = await visible_project(db, user, project_id)
    if not can_view(user, project.workspace):
        raise HTTPException(status_code=404, detail="No project with that id.")
    name, description, kind = clean_env(body)
    env = EnvFile(
        name=name,
        description=description,
        env_kind=kind,
        owner_id=user.id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        status=ACTIVE,
        updated_at=utcnow(),
    )
    db.add(env)
    await db.flush()
    detail = f"Added a {kind} env in {project.name}."
    if description:
        detail = f'{detail} Description: "{description}".'
    add_audit(db, project.workspace_id, user, "Created env", name, detail)
    return await env_detail(db, await visible_env(db, user, str(env.id)))


@router.get("/envs/{env_id}", response_model=EnvDetail)
async def get_env(env_id: str, user: CurrentUser, db: Db) -> EnvDetail:
    return await env_detail(db, await visible_env(db, user, env_id))


@router.patch("/envs/{env_id}", response_model=EnvOut)
async def update_env(env_id: str, body: EnvIn, user: CurrentUser, db: Db) -> EnvOut:
    env = await visible_env(db, user, env_id)
    if not can_edit_env(user, env):
        raise HTTPException(status_code=403, detail="You cannot edit this env.")
    name, description, kind = clean_env(body)
    detail = describe_env_changes(env, name, description, kind)
    env.name = name
    env.description = description
    env.env_kind = kind
    env.updated_at = utcnow()
    if detail and env.workspace_id:
        project_name = env.project.name if env.project else ""
        suffix = f" Project: {project_name}." if project_name else ""
        add_audit(db, env.workspace_id, user, "Updated env", name, f"{detail}.{suffix}")
    await db.flush()
    return env_out(env)


@router.delete("/envs/{env_id}", status_code=204)
async def delete_env(env_id: str, user: CurrentUser, db: Db) -> None:
    env = await visible_env(db, user, env_id)
    if not can_edit_env(user, env):
        raise HTTPException(status_code=403, detail="You cannot edit this env.")
    if env.workspace_id:
        count = sum(1 for item in env.variables if item.status == ACTIVE)
        project_name = env.project.name if env.project else ""
        where = f" from {project_name}" if project_name else ""
        add_audit(
            db,
            env.workspace_id,
            user,
            "Deleted env",
            env.name,
            f"Removed {count} variable{'' if count == 1 else 's'}{where}.",
        )
    env.status = DELETED


@router.post("/envs/{env_id}/variables", response_model=EnvOut)
async def upsert_variable(env_id: str, body: VariableIn, user: CurrentUser, db: Db) -> EnvOut:
    env = await editable_env(db, user, env_id)
    key = clean_key(body.k)
    existed = any(item.key == key and item.status == ACTIVE for item in env.variables)
    unchanged = any(item.key == key and item.status == ACTIVE and item.value == body.v for item in env.variables)
    set_variable(env, key, body.v)
    if env.workspace_id and not unchanged:
        project_name = env.project.name if env.project else ""
        where = f" in {project_name}" if project_name else ""
        add_audit(db, env.workspace_id, user, "Updated variable" if existed else "Added variable", env.name, f"{'Updated' if existed else 'Added'} key {key}{where}.")
    await db.flush()
    return env_out(env)


@router.delete("/envs/{env_id}/variables/{key}", response_model=EnvOut)
async def remove_variable(env_id: str, key: str, user: CurrentUser, db: Db) -> EnvOut:
    env = await editable_env(db, user, env_id)
    cleaned = clean_key(key)
    existed = any(item.key == cleaned and item.status == ACTIVE for item in env.variables)
    set_variable(env, cleaned, None)
    if existed and env.workspace_id:
        project_name = env.project.name if env.project else ""
        where = f" from {project_name}" if project_name else ""
        add_audit(db, env.workspace_id, user, "Removed variable", env.name, f"Removed key {cleaned}{where}.")
    await db.flush()
    return env_out(env)


@router.post("/envs/{env_id}/variables/import", response_model=EnvOut)
async def import_variables(env_id: str, body: ImportIn, user: CurrentUser, db: Db) -> EnvOut:
    env = await editable_env(db, user, env_id)
    if not body.pairs:
        raise HTTPException(status_code=400, detail="Import at least one variable.")
    keys = [clean_key(pair.k) for pair in body.pairs]
    for pair, key in zip(body.pairs, keys, strict=True):
        set_variable(env, key, pair.v)
    if env.workspace_id:
        project_name = env.project.name if env.project else ""
        where = f" into {project_name}" if project_name else ""
        add_audit(
            db,
            env.workspace_id,
            user,
            "Imported variables",
            env.name,
            f"Imported {len(keys)} key{'' if len(keys) == 1 else 's'}{where}: {key_list(keys)}.",
        )
    await db.flush()
    return env_out(env)


async def editable_env(db: Db, user: User, env_id: str) -> EnvFile:
    env = await visible_env(db, user, env_id)
    if not can_edit_env(user, env):
        raise HTTPException(status_code=403, detail="You cannot edit this env.")
    return env


def clean_key(key: str) -> str:
    cleaned = key.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Variable key is required.")
    return cleaned


def set_variable(env: EnvFile, key: str, value: str | None) -> None:
    existing = next((item for item in env.variables if item.key == key), None)
    if value is None:
        if existing is not None and existing.status == ACTIVE:
            existing.status = DELETED
            env.updated_at = utcnow()
        return
    if existing is None:
        env.variables.append(Variable(key=key, value=value, status=ACTIVE))
    else:
        existing.value = value
        existing.status = ACTIVE
    env.updated_at = utcnow()


def describe_env_changes(env: EnvFile, name: str, description: str, kind: str) -> str:
    from app.api.routes.workspaces import describe_changes

    return describe_changes([("Name", env.name, name), ("Description", env.description, description), ("Environment", env.env_kind, kind)])


def key_list(keys: list[str]) -> str:
    shown = keys[:8]
    extra = len(keys) - len(shown)
    if not shown:
        return "none"
    if extra:
        return f"{', '.join(shown)} and {extra} more"
    return ", ".join(shown)
