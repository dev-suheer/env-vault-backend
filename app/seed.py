import asyncio

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User

DEMO_PASSWORD = "demo1234"
DEMO_USERS = (
    ("admin@gmail.com", "Admin", "admin"),
    ("pm@gmail.com", "Project Manager", "pm"),
    ("dev1@gmail.com", "Dev One", "dev"),
    ("dev2@gmail.com", "Dev Two", "dev"),
)


async def seed() -> None:
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        if count:
            return
        for email, name, role in DEMO_USERS:
            session.add(
                User(
                    email=email,
                    name=name,
                    role=role,
                    password_hash=hash_password(DEMO_PASSWORD),
                    phone="",
                    image=None,
                    status=True,
                    created_at=None,
                )
            )
        await session.commit()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
