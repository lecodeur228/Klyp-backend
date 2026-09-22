"""Auth request/response schemas."""

from pydantic import BaseModel, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    """Accepts classic `name` or onboarding `first_name` + `last_name`."""

    name: str | None = Field(default=None, min_length=2, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    profession: str | None = Field(default=None, max_length=120)
    referral_source: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def resolve_name(self) -> "RegisterRequest":
        if self.name and self.name.strip():
            return self
        first = (self.first_name or "").strip()
        last = (self.last_name or "").strip()
        combined = f"{first} {last}".strip()
        if len(combined) < 2:
            raise ValueError("name or first_name+last_name required")
        self.name = combined
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    device_name: str | None = Field(default=None, max_length=255)


class CheckEmailRequest(BaseModel):
    email: EmailStr


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    key_prefix: str
    api_key: str
