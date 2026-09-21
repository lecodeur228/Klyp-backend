"""File upload routes."""

from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import AppSettings, LocaleDep, require_permission
from app.core.exceptions import ValidationException
from app.core.responses import success_response
from app.i18n.messages import translate
from app.models.user import User
from app.schemas.files import FileUploadResponse
from app.storage import get_storage

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_TYPES = {
    "text/plain",
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/json",
}


@router.post("/upload", status_code=201)
async def upload_file(
    settings: AppSettings,
    locale: LocaleDep,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("files.upload")),
):
    content = await file.read()
    max_bytes = settings.storage_max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationException(
            "File too large",
            errors={"file": [f"Max size is {settings.storage_max_upload_mb}MB"]},
        )
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_TYPES:
        raise ValidationException(
            "Unsupported file type",
            errors={"file": [f"Type {content_type} not allowed"]},
        )

    storage = get_storage(settings)
    path = await storage.save(
        filename=file.filename or "upload.bin",
        content=content,
        content_type=content_type,
    )
    payload = FileUploadResponse(
        id=str(uuid4()),
        filename=file.filename or "upload.bin",
        content_type=content_type,
        size=len(content),
        path=path,
    )
    return success_response(
        payload.model_dump(), translate("file_uploaded", locale), status_code=201
    )
