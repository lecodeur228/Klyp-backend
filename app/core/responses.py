"""Standard API response helpers."""

from typing import Any, Generic, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiSuccess(BaseModel, Generic[T]):
    success: bool = True
    message: str
    data: T


class PaginationMeta(BaseModel):
    current_page: int
    per_page: int
    total: int
    last_page: int


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    meta: PaginationMeta


def success_response(
    data: Any,
    message: str = "OK",
    *,
    status_code: int = 200,
    meta: PaginationMeta | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "success": True,
        "message": message,
        "data": data,
    }
    if meta is not None:
        payload["meta"] = meta.model_dump()
    return JSONResponse(content=payload, status_code=status_code)


def accepted_response(data: Any, message: str = "Accepted") -> JSONResponse:
    return success_response(data, message, status_code=202)


def error_response(
    message: str,
    code: str,
    *,
    status_code: int = 400,
    errors: dict[str, list[str]] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "success": False,
        "message": message,
        "code": code,
    }
    if errors:
        payload["errors"] = errors
    return JSONResponse(content=payload, status_code=status_code)


class MessageOnly(BaseModel):
    detail: str = Field(description="Human-readable message")
