from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db
from app.core.security import (
    LOGIN_HISTORY,
    MIN_PASSWORD,
    RESET_TTL,
    SESSION_TTL,
    device_label,
    hash_password,
    hash_token,
    issue_token,
    reset_code,
    to_ms,
    utcnow,
    verify_password,
)
from app.models.user import AuthSession, LoginEvent, PasswordReset, User
from app.schemas.auth import (
    AuthOut,
    FinishResetIn,
    ForgotIn,
    ForgotOut,
    LoginIn,
    SignupIn,
    UserOut,
    VerifyResetIn,
    VerifyResetOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: User) -> UserOut:
    logins = sorted(event.logged_in_at for event in user.logins)
    return UserOut(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        phone=user.phone,
        image=user.image,
        status=user.status,
        created=to_ms(user.created_at),
        last_login=to_ms(user.last_login_at),
        last_device=user.last_device,
        logins=[to_ms(moment) or 0 for moment in logins],
    )


async def open_session(db: Db, user: User, agent: str) -> str:
    now = utcnow()
    device = device_label(agent)
    user.last_login_at = now
    user.last_device = device
    cutoff = now - LOGIN_HISTORY
    user.logins[:] = [event for event in user.logins if event.logged_in_at >= cutoff]
    user.logins.append(LoginEvent(logged_in_at=now, device=device))
    raw, digest = issue_token()
    db.add(AuthSession(user_id=user.id, token_hash=digest, expires_at=now + SESSION_TTL, created_at=now))
    await db.flush()
    return raw


def normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post("/signup", response_model=AuthOut, status_code=201)
async def signup(body: SignupIn, request: Request, db: Db) -> AuthOut:
    email = normalize_email(body.email)
    if await db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=400, detail="An account with this email already exists. Sign in instead.")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail="Use a password with at least 6 characters.")
    if body.role not in {"pm", "dev"}:
        raise HTTPException(status_code=400, detail="Choose Project Manager or Dev.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    now = utcnow()
    user = User(
        email=email,
        name=name,
        role=body.role,
        password_hash=hash_password(body.password),
        phone="",
        image=None,
        status=True,
        created_at=now,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user, attribute_names=["logins"])
    token = await open_session(db, user, request.headers.get("user-agent", ""))
    return AuthOut(token=token, user=user_out(user))


@router.post("/login", response_model=AuthOut)
async def login(body: LoginIn, request: Request, db: Db) -> AuthOut:
    email = normalize_email(body.email)
    user = await db.scalar(select(User).where(User.email == email).options(selectinload(User.logins)))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    if not user.status:
        raise HTTPException(status_code=403, detail="This account is inactive. Ask an admin to activate it.")
    token = await open_session(db, user, request.headers.get("user-agent", ""))
    return AuthOut(token=token, user=user_out(user))


@router.post("/logout", status_code=204)
async def logout(user: CurrentUser, request: Request, db: Db) -> None:
    header = request.headers.get("authorization", "")
    raw = header.split(" ", 1)[1] if header.lower().startswith("bearer ") else ""
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(raw), AuthSession.user_id == user.id))
    if session is not None:
        await db.delete(session)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.post("/forgot", response_model=ForgotOut)
async def forgot(body: ForgotIn, db: Db) -> ForgotOut:
    email = normalize_email(body.email)
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(status_code=400, detail="No account with that email.")
    if not user.status:
        raise HTTPException(status_code=400, detail="This account is inactive. Ask an admin to activate it.")
    await db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    code = reset_code()
    expires = utcnow() + RESET_TTL
    db.add(PasswordReset(user_id=user.id, code_hash=hash_password(code), expires_at=expires, verified=False, attempts=0))
    return ForgotOut(email=user.email, code=code, expires_at=to_ms(expires) or 0)


@router.post("/forgot/verify", response_model=VerifyResetOut)
async def verify_reset(body: VerifyResetIn, db: Db) -> VerifyResetOut:
    email = normalize_email(body.email)
    user = await db.scalar(select(User).where(User.email == email))
    challenge = None
    if user is not None:
        challenge = await db.scalar(
            select(PasswordReset).where(PasswordReset.user_id == user.id).order_by(PasswordReset.expires_at.desc())
        )
    if challenge is None or challenge.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="Request a new code.")
    if challenge.attempts >= 5:
        raise HTTPException(status_code=400, detail="Too many tries. Request a new code.")
    if not verify_password(body.code.strip(), challenge.code_hash):
        challenge.attempts += 1
        raise HTTPException(status_code=400, detail="That code is not correct.")
    raw, digest = issue_token()
    challenge.verified = True
    challenge.reset_token_hash = digest
    return VerifyResetOut(reset_token=raw)


@router.post("/forgot/reset", status_code=204)
async def finish_reset(body: FinishResetIn, db: Db) -> None:
    challenge = await db.scalar(select(PasswordReset).where(PasswordReset.reset_token_hash == hash_token(body.reset_token)))
    if challenge is None or not challenge.verified or challenge.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="Verify the code before choosing a new password.")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail="Use a password with at least 6 characters.")
    user = await db.get(User, challenge.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="No account with that email.")
    if verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from the current one.")
    user.password_hash = hash_password(body.password)
    await db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
