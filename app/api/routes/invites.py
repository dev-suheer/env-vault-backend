import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.api.routes.workspaces import ACTIVE, DELETED, add_audit, can_manage, load_workspace, page_count, visible_workspace
from app.core.security import to_ms, utcnow
from app.models.content import Notification
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.schemas.content import AccessIn, InviteIn, InviteResult, NotificationOut, NotificationPage, RespondIn

router = APIRouter(tags=["invites"])
MISSING = "No invite with that id."


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=MISSING) from None


def note_options():
    return (
        selectinload(Notification.to_user),
        selectinload(Notification.from_user),
        selectinload(Notification.workspace),
    )


def note_out(note: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(note.id),
        kind=note.kind,
        status=note.invite_status,
        read=note.read,
        at=to_ms(note.created_at) or 0,
        text=note.text,
        access=note.access,
        to_user_id=str(note.to_user_id),
        to_email=note.to_user.email,
        from_user_id=str(note.from_user_id) if note.from_user_id else None,
        from_email=note.from_user.email if note.from_user else None,
        workspace_id=str(note.workspace_id) if note.workspace_id else None,
        workspace_name=note.workspace.name if note.workspace else None,
    )


def active_membership(workspace_members: list[WorkspaceMember], user_id: uuid.UUID) -> WorkspaceMember | None:
    return next((member for member in workspace_members if member.user_id == user_id and member.status == ACTIVE), None)


@router.post("/workspaces/{workspace_id}/invites", response_model=NotificationOut, status_code=201)
async def invite(workspace_id: str, body: InviteIn, user: CurrentUser, db: Db) -> NotificationOut:
    workspace = await visible_workspace(db, user, workspace_id)
    if not can_manage(user, workspace):
        raise HTTPException(status_code=403, detail="You cannot invite from here")
    if body.access not in {"view", "edit"}:
        raise HTTPException(status_code=400, detail="Choose view or edit access.")
    email = body.email.strip().lower()
    target = await db.scalar(select(User).where(User.email == email))
    if target is None:
        raise HTTPException(status_code=400, detail="No account with that email")
    if target.role != "dev":
        raise HTTPException(status_code=400, detail="Only Dev accounts can be invited")
    if not target.status:
        raise HTTPException(status_code=400, detail="That account is inactive")
    if active_membership(workspace.members, target.id):
        raise HTTPException(status_code=400, detail="Already in this workspace")
    pending = await db.scalar(
        select(Notification.id).where(
            Notification.kind == "invite",
            Notification.workspace_id == workspace.id,
            Notification.to_user_id == target.id,
            Notification.invite_status == "pending",
            Notification.status == ACTIVE,
        )
    )
    if pending:
        raise HTTPException(status_code=400, detail="Invite already sent")
    note = Notification(
        kind="invite",
        status=ACTIVE,
        invite_status="pending",
        access=body.access,
        to_user_id=target.id,
        from_user_id=user.id,
        workspace_id=workspace.id,
        read=False,
        created_at=utcnow(),
    )
    db.add(note)
    add_audit(db, workspace.id, user, "Invited member", target.name, f"Invited {email} with {body.access} access.")
    await db.flush()
    loaded = await db.scalar(select(Notification).where(Notification.id == note.id).options(*note_options()))
    if loaded is None:
        raise HTTPException(status_code=404, detail=MISSING)
    return note_out(loaded)


@router.delete("/invites/{invite_id}", status_code=204)
async def cancel_invite(invite_id: str, user: CurrentUser, db: Db) -> None:
    note = await db.scalar(select(Notification).where(Notification.id == parse_id(invite_id)).options(*note_options()))
    if note is None or note.kind != "invite" or note.status != ACTIVE or note.invite_status != "pending":
        raise HTTPException(status_code=404, detail=MISSING)
    workspace = await load_workspace(db, note.workspace_id) if note.workspace_id else None
    if workspace is None or not can_manage(user, workspace):
        raise HTTPException(status_code=403, detail="You cannot invite from here")
    note.status = DELETED
    add_audit(
        db,
        workspace.id,
        user,
        "Cancelled invite",
        note.to_user.name,
        f"Cancelled a pending {note.access or 'view'} invite to {note.to_user.email}.",
    )


@router.post("/invites/{invite_id}/respond", response_model=InviteResult)
async def respond_invite(invite_id: str, body: RespondIn, user: CurrentUser, db: Db) -> InviteResult:
    note = await db.scalar(select(Notification).where(Notification.id == parse_id(invite_id)).options(*note_options()))
    if note is None or note.kind != "invite" or note.status != ACTIVE or note.to_user_id != user.id or note.invite_status != "pending":
        raise HTTPException(status_code=404, detail=MISSING)
    workspace = await load_workspace(db, note.workspace_id) if note.workspace_id else None
    if workspace is None or workspace.status != ACTIVE:
        note.invite_status = "declined"
        return InviteResult(status="missing")
    note.invite_status = "accepted" if body.accept else "declined"
    if body.accept:
        membership = next((member for member in workspace.members if member.user_id == user.id), None)
        if membership is None:
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, access=note.access or "view", status=ACTIVE))
        else:
            membership.status = ACTIVE
            membership.access = note.access or "view"
    access_label = "edit" if note.access == "edit" else "view"
    db.add(
        Notification(
            kind="info",
            status=ACTIVE,
            to_user_id=note.from_user_id or workspace.owner_id,
            text=f"{user.name} {'accepted' if body.accept else 'declined'} your invite to {workspace.name}",
            read=False,
            created_at=utcnow(),
        )
    )
    add_audit(
        db,
        workspace.id,
        user,
        "Joined workspace" if body.accept else "Declined invite",
        user.name,
        f"Accepted the invite with {access_label} access." if body.accept else f"Declined the invite ({access_label} access).",
    )
    if not body.accept:
        return InviteResult(status="declined")
    return InviteResult(status="joined", workspace_id=str(workspace.id), name=workspace.name)


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(workspace_id: str, user_id: str, user: CurrentUser, db: Db) -> None:
    workspace = await visible_workspace(db, user, workspace_id)
    if not can_manage(user, workspace):
        raise HTTPException(status_code=403, detail="You cannot change this workspace.")
    try:
        member_id = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No account with that email.") from None
    membership = active_membership(workspace.members, member_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="That person is not in this workspace.")
    membership.status = DELETED
    person = membership.user
    db.add(
        Notification(
            kind="info",
            status=ACTIVE,
            to_user_id=person.id,
            text=f"You were removed from {workspace.name}",
            read=False,
            created_at=utcnow(),
        )
    )
    add_audit(db, workspace.id, user, "Removed member", person.name, f"Removed {person.email} from the workspace.")


@router.patch("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
async def set_access(workspace_id: str, user_id: str, body: AccessIn, user: CurrentUser, db: Db) -> None:
    workspace = await visible_workspace(db, user, workspace_id)
    if not can_manage(user, workspace):
        raise HTTPException(status_code=403, detail="You cannot change this workspace.")
    if body.access not in {"view", "edit"}:
        raise HTTPException(status_code=400, detail="Choose view or edit access.")
    try:
        member_id = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="That person is not in this workspace.") from None
    membership = active_membership(workspace.members, member_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="That person is not in this workspace.")
    previous = "edit" if membership.access == "edit" else "view"
    if previous == body.access:
        return
    membership.access = body.access
    add_audit(
        db,
        workspace.id,
        user,
        "Changed access",
        membership.user.name,
        f"Access for {membership.user.email} changed from {previous} to {body.access}.",
    )


@router.get("/notifications", response_model=NotificationPage)
async def list_notifications(
    user: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(description="Match invite workspace or info text")] = None,
) -> NotificationPage:
    filters = [Notification.to_user_id == user.id, Notification.status == ACTIVE]
    term = (keyword or "").strip()
    if term:
        like = f"%{term}%"
        filters.append(or_(Notification.text.ilike(like), Notification.invite_status.ilike(like)))
    total_records = await db.scalar(select(func.count()).select_from(Notification).where(*filters)) or 0
    notes = await db.scalars(
        select(Notification)
        .where(*filters)
        .options(*note_options())
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return NotificationPage(
        data=[note_out(note) for note in notes],
        current_page=page,
        total_pages=page_count(total_records, limit),
        total_records=total_records,
        limit=limit,
    )


@router.post("/notifications/read", status_code=204)
async def mark_read(user: CurrentUser, db: Db) -> None:
    notes = await db.scalars(
        select(Notification).where(
            Notification.to_user_id == user.id,
            Notification.kind == "info",
            Notification.status == ACTIVE,
            Notification.read.is_(False),
        )
    )
    for note in notes:
        note.read = True
