"""Domain exceptions mapped to API responses."""

from typing import Any

from app.core.constants import ErrorCode


class AppException(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.BAD_REQUEST,
        status_code: int = 400,
        errors: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.errors = errors


class AuthenticationException(AppException):
    def __init__(
        self,
        message: str = "Unauthenticated",
        *,
        code: ErrorCode = ErrorCode.UNAUTHENTICATED,
    ) -> None:
        super().__init__(message, code=code, status_code=401)


class AuthorizationException(AppException):
    def __init__(
        self,
        message: str = "Forbidden",
        *,
        code: ErrorCode = ErrorCode.FORBIDDEN,
    ) -> None:
        super().__init__(message, code=code, status_code=403)


class NotFoundException(AppException):
    def __init__(self, message: str = "Not found") -> None:
        super().__init__(message, code=ErrorCode.NOT_FOUND, status_code=404)


class ValidationException(AppException):
    def __init__(
        self,
        message: str = "Validation failed",
        *,
        errors: dict[str, list[str]] | None = None,
        code: ErrorCode = ErrorCode.VALIDATION_ERROR,
    ) -> None:
        super().__init__(
            message,
            code=code,
            status_code=422,
            errors=errors,
        )


class EditPlanInvalidException(ValidationException):
    def __init__(
        self,
        message: str = "Invalid EditPlan",
        *,
        errors: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message, errors=errors, code=ErrorCode.EDIT_PLAN_INVALID)


class InsufficientCreditsException(AppException):
    def __init__(self, message: str = "Insufficient credits") -> None:
        super().__init__(message, code=ErrorCode.INSUFFICIENT_CREDITS, status_code=402)


class ConflictException(AppException):
    def __init__(
        self,
        message: str = "Conflict",
        *,
        code: ErrorCode = ErrorCode.CONFLICT,
    ) -> None:
        super().__init__(message, code=code, status_code=409)


class RateLimitException(AppException):
    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(
            message,
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            status_code=429,
        )


class AIException(AppException):
    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.AI_PROVIDER_UNAVAILABLE,
        status_code: int = 502,
        errors: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, errors=errors)


class AIProviderException(AIException):
    pass


class AIRateLimitException(AIException):
    def __init__(self, message: str = "AI provider rate limited") -> None:
        super().__init__(message, code=ErrorCode.AI_RATE_LIMITED, status_code=429)


class AITimeoutException(AIException):
    def __init__(self, message: str = "AI provider timeout") -> None:
        super().__init__(message, code=ErrorCode.AI_TIMEOUT, status_code=504)


def exception_to_body(exc: AppException) -> dict[str, Any]:
    body: dict[str, Any] = {
        "success": False,
        "message": exc.message,
        "code": exc.code.value,
    }
    if exc.errors:
        body["errors"] = exc.errors
    return body
