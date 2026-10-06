import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User
from app.models.workspace import Workspace


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("status IN ('active', 'deleted')", name="projects_status_check"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship()
    owner: Mapped[User] = relationship()


class EnvFile(Base):
    __tablename__ = "env_files"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'deleted')", name="env_files_status_check"),
        CheckConstraint("env_kind IN ('Development', 'Staging', 'Production')", name="env_files_kind_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    env_kind: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship()
    workspace: Mapped[Workspace | None] = relationship()
    project: Mapped[Project | None] = relationship()
    variables: Mapped[list["Variable"]] = relationship(back_populates="env_file")


class Variable(Base):
    __tablename__ = "variables"
    __table_args__ = (
        UniqueConstraint("env_id", "key", name="variables_env_key_unique"),
        CheckConstraint("status IN ('active', 'deleted')", name="variables_status_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    env_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("env_files.id"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")

    env_file: Mapped[EnvFile] = relationship(back_populates="variables")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("kind IN ('invite', 'info')", name="notifications_kind_check"),
        CheckConstraint("status IN ('active', 'deleted')", name="notifications_status_check"),
        CheckConstraint(
            "invite_status IS NULL OR invite_status IN ('pending', 'accepted', 'declined')",
            name="notifications_invite_status_check",
        ),
        CheckConstraint("access IS NULL OR access IN ('view', 'edit')", name="notifications_access_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    invite_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    access: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    to_user: Mapped[User] = relationship(foreign_keys=[to_user_id])
    from_user: Mapped[User | None] = relationship(foreign_keys=[from_user_id])
    workspace: Mapped[Workspace | None] = relationship()
