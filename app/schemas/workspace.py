from pydantic import BaseModel, ConfigDict, Field


class MemberOut(BaseModel):
    id: str
    email: str
    name: str
    access: str


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    desc: str
    status: str
    owner_id: str = Field(serialization_alias="ownerId")
    owner_email: str = Field(serialization_alias="ownerEmail")
    owner_name: str = Field(serialization_alias="ownerName")
    members: list[MemberOut]
    created: int


class WorkspacePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[WorkspaceOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int


class WorkspaceIn(BaseModel):
    name: str
    desc: str = ""


class AuditOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    workspace_id: str = Field(serialization_alias="workspaceId")
    at: int
    actor_id: str = Field(serialization_alias="actorId")
    actor_name: str = Field(serialization_alias="actorName")
    actor_email: str = Field(serialization_alias="actorEmail")
    action: str
    subject: str
    detail: str


class AuditPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[AuditOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int
