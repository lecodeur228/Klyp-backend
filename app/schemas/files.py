"""File schemas."""

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    path: str
