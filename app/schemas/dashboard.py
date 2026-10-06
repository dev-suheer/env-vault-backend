from pydantic import BaseModel, ConfigDict, Field


class DayPoint(BaseModel):
    key: str
    label: str
    title: str
    value: int


class AccessSlice(BaseModel):
    label: str
    value: int
    color: str


class RankedWorkspace(BaseModel):
    id: str
    name: str
    projects: int
    envs: int
    members: int
    editors: int


class RecentChange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    workspace_id: str = Field(serialization_alias="workspaceId")
    href: str
    action: str
    subject: str
    detail: str
    who: str
    at: int


class DashboardOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspaces: int
    projects: int
    shared_envs: int = Field(serialization_alias="sharedEnvs")
    personal_envs: int = Field(serialization_alias="personalEnvs")
    users: int
    pms: int
    devs: int
    pending_invites: int = Field(serialization_alias="pendingInvites")
    week_activity: int = Field(serialization_alias="weekActivity")
    editors: int
    days: list[DayPoint]
    access: list[AccessSlice]
    ranked: list[RankedWorkspace]
    recent: list[RecentChange]
