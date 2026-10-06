from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.api.routes.workspaces import ACTIVE
from app.core.security import to_ms
from app.models.content import EnvFile, Notification, Project
from app.models.user import User
from app.models.workspace import AuditLog, Workspace, WorkspaceMember
from app.schemas.dashboard import AccessSlice, DashboardOut, DayPoint, RankedWorkspace, RecentChange

router = APIRouter(tags=["dashboard"])


def start_of_day(moment: datetime) -> datetime:
    current = moment.astimezone(UTC)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(user: CurrentUser, db: Db) -> DashboardOut:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can view the dashboard.")

    workspaces = await db.scalar(select(func.count()).select_from(Workspace).where(Workspace.status == ACTIVE)) or 0
    projects = await db.scalar(select(func.count()).select_from(Project).where(Project.status == ACTIVE)) or 0
    shared_envs = await db.scalar(
        select(func.count()).select_from(EnvFile).where(EnvFile.status == ACTIVE, EnvFile.workspace_id.is_not(None))
    ) or 0
    personal_envs = await db.scalar(
        select(func.count()).select_from(EnvFile).where(EnvFile.status == ACTIVE, EnvFile.workspace_id.is_(None))
    ) or 0
    users = await db.scalar(select(func.count()).select_from(User)) or 0
    pms = await db.scalar(select(func.count()).select_from(User).where(User.role == "pm")) or 0
    devs = await db.scalar(select(func.count()).select_from(User).where(User.role == "dev")) or 0
    pending_invites = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.kind == "invite", Notification.invite_status == "pending", Notification.status == ACTIVE)
    ) or 0

    membership = await db.execute(
        select(WorkspaceMember.access, func.count())
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(Workspace.status == ACTIVE, WorkspaceMember.status == ACTIVE)
        .group_by(WorkspaceMember.access)
    )
    counts = {access: count for access, count in membership.all()}
    editors = counts.get("edit", 0)
    viewers = counts.get("view", 0)

    today = start_of_day(datetime.now(UTC))
    window_start = today - timedelta(days=6)
    stamps = await db.scalars(
        select(AuditLog.created_at)
        .join(Workspace, Workspace.id == AuditLog.workspace_id)
        .where(Workspace.status == ACTIVE, AuditLog.created_at >= window_start)
    )
    buckets = [0] * 7
    for stamp in stamps:
        day = start_of_day(stamp)
        index = (day - window_start).days
        if 0 <= index < 7:
            buckets[index] += 1
    days = []
    for index in range(7):
        day = window_start + timedelta(days=index)
        days.append(
            DayPoint(
                key=str(to_ms(day) or 0),
                label=day.strftime("%b %-d"),
                title=day.strftime("%A, %B %-d"),
                value=buckets[index],
            )
        )

    project_counts = (
        select(Project.workspace_id, func.count().label("projects"))
        .where(Project.status == ACTIVE)
        .group_by(Project.workspace_id)
        .subquery()
    )
    env_counts = (
        select(EnvFile.workspace_id, func.count().label("envs"))
        .where(EnvFile.status == ACTIVE, EnvFile.workspace_id.is_not(None))
        .group_by(EnvFile.workspace_id)
        .subquery()
    )
    member_counts = (
        select(
            WorkspaceMember.workspace_id,
            func.count().label("members"),
            func.count().filter(WorkspaceMember.access == "edit").label("editors"),
        )
        .where(WorkspaceMember.status == ACTIVE)
        .group_by(WorkspaceMember.workspace_id)
        .subquery()
    )
    ranked_rows = await db.execute(
        select(
            Workspace.id,
            Workspace.name,
            func.coalesce(project_counts.c.projects, 0),
            func.coalesce(env_counts.c.envs, 0),
            func.coalesce(member_counts.c.members, 0),
            func.coalesce(member_counts.c.editors, 0),
        )
        .outerjoin(project_counts, project_counts.c.workspace_id == Workspace.id)
        .outerjoin(env_counts, env_counts.c.workspace_id == Workspace.id)
        .outerjoin(member_counts, member_counts.c.workspace_id == Workspace.id)
        .where(Workspace.status == ACTIVE)
        .order_by(func.coalesce(env_counts.c.envs, 0).desc(), func.coalesce(project_counts.c.projects, 0).desc(), Workspace.name)
        .limit(5)
    )
    ranked = [
        RankedWorkspace(id=str(row[0]), name=row[1], projects=row[2], envs=row[3], members=row[4], editors=row[5])
        for row in ranked_rows.all()
    ]

    recent_rows = await db.scalars(
        select(AuditLog)
        .join(Workspace, Workspace.id == AuditLog.workspace_id)
        .where(Workspace.status == ACTIVE)
        .options(selectinload(AuditLog.actor))
        .order_by(AuditLog.created_at.desc())
        .limit(6)
    )
    recent = [
        RecentChange(
            id=str(entry.id),
            workspace_id=str(entry.workspace_id),
            href=f"/workspaces/{entry.workspace_id}?tab=audit",
            action=entry.action,
            subject=entry.subject,
            detail=entry.detail,
            who=entry.actor.name,
            at=to_ms(entry.created_at) or 0,
        )
        for entry in recent_rows
    ]

    return DashboardOut(
        workspaces=workspaces,
        projects=projects,
        shared_envs=shared_envs,
        personal_envs=personal_envs,
        users=users,
        pms=pms,
        devs=devs,
        pending_invites=pending_invites,
        week_activity=sum(buckets),
        editors=editors,
        days=days,
        access=[
            AccessSlice(label="Edit", value=editors, color="#0f9d75"),
            AccessSlice(label="View", value=viewers, color="#8b949e"),
        ],
        ranked=ranked,
        recent=recent,
    )
