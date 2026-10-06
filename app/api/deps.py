from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import hash_token, utcnow
from app.models.user import AuthSession, User

bearer = HTTPBearer(auto_error=False)

Db = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: Db,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in again.")
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(credentials.credentials)))
    if session is None or session.expires_at <= utcnow():
        if session is not None:
            await db.delete(session)
        raise HTTPException(status_code=401, detail="Sign in again.")
    user = await db.scalar(select(User).where(User.id == session.user_id).options(selectinload(User.logins)))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in again.")
    if not user.status:
        raise HTTPException(status_code=403, detail="This account is inactive. Ask an admin to activate it.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can edit users.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
