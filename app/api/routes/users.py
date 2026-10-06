from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser, CurrentUser, Db
from app.api.routes.auth import user_out
from app.core.security import MIN_PASSWORD, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import AdminUserIn, PasswordIn, ProfileIn, UserOut, UserPage

router = APIRouter(prefix="/users", tags=["users"])

MAX_IMAGE = 500_000


@router.get("/me", response_model=UserOut)
async def my_profile(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.patch("/me", response_model=UserOut)
async def update_profile(body: ProfileIn, user: CurrentUser, db: Db) -> UserOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if body.image is not None and (not body.image.startswith("data:image/") or len(body.image) > MAX_IMAGE):
        raise HTTPException(status_code=400, detail="Use a smaller profile photo.")
    user.name = name
    user.phone = body.phone.strip()
    user.image = body.image
    await db.flush()
    return user_out(user)


@router.post("/me/password", status_code=204)
async def change_password(body: PasswordIn, user: CurrentUser) -> None:
    if not verify_password(body.current, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is not correct.")
    if len(body.new_password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail="Use a password with at least 6 characters.")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from the current one.")
    user.password_hash = hash_password(body.new_password)


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
    if role is not None and role not in {"admin", "pm", "dev"}:
        raise HTTPException(status_code=400, detail="Choose a valid role.")
    filters = []
    if role is not None:
        filters.append(User.role == role)
    if status is not None:
        filters.append(User.status.is_(status))
    term = (keyword or "").strip()
    if term:
        like = f"%{term}%"
        filters.append(or_(User.name.ilike(like), User.email.ilike(like)))

    count_stmt = select(func.count()).select_from(User)
    list_stmt = select(User).options(selectinload(User.logins)).order_by(User.email)
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
    )


@router.get("/{email}", response_model=UserOut)
async def get_user(email: str, admin: AdminUser, db: Db) -> UserOut:
    user = await find_user(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="No account with that email.")
    return user_out(user)


@router.patch("/{email}", response_model=UserOut)
async def update_user(email: str, body: AdminUserIn, admin: AdminUser, db: Db) -> UserOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if body.role not in {"admin", "pm", "dev"}:
        raise HTTPException(status_code=400, detail="Choose a valid role.")
    user = await find_user(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="No account with that email.")
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


async def find_user(db: Db, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.strip().lower()).options(selectinload(User.logins)))
