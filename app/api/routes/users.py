import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.api.routes.auth import user_out
from app.core.security import MIN_PASSWORD, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import PasswordIn, ProfileIn, UserOut

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
    if "image" in body.model_fields_set:
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


async def find_user(db: Db, user_id: str) -> User:
    try:
        parsed = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No account with that id.") from None
    user = await db.scalar(select(User).where(User.id == parsed).options(selectinload(User.logins)))
    if user is None:
        raise HTTPException(status_code=404, detail="No account with that id.")
    return user
