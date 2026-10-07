from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: str
    name: str
    role: str
    phone: str
    image: str | None
    status: bool
    created: int | None
    last_login: int | None = Field(serialization_alias="lastLogin")
    last_device: str | None = Field(serialization_alias="lastDevice")
    logins: list[int]


class UserCounts(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    all: int
    project_managers: int = Field(serialization_alias="projectManagers")
    devs: int


class UserPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[UserOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int
    counts: UserCounts


class UserWorkspaceOut(BaseModel):
    id: str
    name: str
    access: str
    members: int


class UserWorkspacePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[UserWorkspaceOut]
    current_page: int = Field(serialization_alias="currentPage")
    total_pages: int = Field(serialization_alias="totalPages")
    total_records: int = Field(serialization_alias="totalRecords")
    limit: int


class AuthOut(BaseModel):
    token: str
    user: UserOut


class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    phone: str
    role: str


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    name: str
    phone: str = ""
    image: str | None = None


class PasswordIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current: str
    new_password: str = Field(alias="next")


class AdminUserIn(BaseModel):
    name: str
    role: str
    status: bool


class ForgotIn(BaseModel):
    email: str


class ForgotOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    code: str
    expires_at: int = Field(serialization_alias="expiresAt")


class VerifyResetIn(BaseModel):
    email: str
    code: str


class VerifyResetOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reset_token: str = Field(serialization_alias="resetToken")


class FinishResetIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reset_token: str = Field(alias="resetToken")
    password: str
