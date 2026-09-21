"""Auth request/response schemas."""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    device_name: str | None = Field(default=None, max_length=255)


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    key_prefix: str
    api_key: str
