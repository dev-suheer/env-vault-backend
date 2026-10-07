from pydantic import BaseModel, ConfigDict, Field

from app.schemas.workspace import WorkspaceOut


class ProjectOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    workspace_id: str = Field(serialization_alias="workspaceId")
    name: str
    desc: str
    status: str
    owner_id: str = Field(serialization_alias="ownerId")
    owner_email: str = Field(serialization_alias="ownerEmail")
    owner_name: str = Field(serialization_alias="ownerName")
    created: int


class ProjectPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace: WorkspaceOut
    data: list[ProjectOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int


class ProjectIn(BaseModel):
    name: str
    desc: str = ""


class VariableOut(BaseModel):
    id: str
    k: str
    v: str


class VariableIn(BaseModel):
    k: str
    v: str = ""


class ImportIn(BaseModel):
    pairs: list[VariableIn]


class EnvOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    desc: str
    env: str
    vars: list[VariableOut]
    updated: int
    status: str
    owner_id: str = Field(serialization_alias="ownerId")
    owner_email: str = Field(serialization_alias="ownerEmail")
    owner_name: str = Field(serialization_alias="ownerName")
    workspace_id: str | None = Field(serialization_alias="workspaceId")
    project_id: str | None = Field(serialization_alias="projectId")


class EnvDetail(EnvOut):
    workspace: WorkspaceOut | None = None
    project: ProjectOut | None = None


class EnvPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[EnvOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int


class ProjectEnvPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace: WorkspaceOut
    project: ProjectOut
    data: list[EnvOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int


class EnvIn(BaseModel):
    name: str
    desc: str = ""
    env: str


class NotificationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    status: str | None = None
    read: bool
    at: int
    text: str | None = None
    access: str | None = None
    to_user_id: str = Field(serialization_alias="toUserId")
    to_email: str = Field(serialization_alias="toEmail")
    from_user_id: str | None = Field(default=None, serialization_alias="fromUserId")
    from_email: str | None = Field(default=None, serialization_alias="fromEmail")
    workspace_id: str | None = Field(default=None, serialization_alias="workspaceId")
    workspace_name: str | None = Field(default=None, serialization_alias="workspaceName")


class NotificationPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[NotificationOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int


class InviteIn(BaseModel):
    email: str
    access: str


class RespondIn(BaseModel):
    accept: bool


class InviteResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    workspace_id: str | None = Field(default=None, serialization_alias="workspaceId")
    name: str | None = None


class AccessIn(BaseModel):
    access: str
