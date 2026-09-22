"""Storage backends."""

from app.storage.base import LocalStorage, S3StorageStub, get_storage
from app.storage.cloudinary_storage import CloudinaryStorage, configure_cloudinary
from app.storage.types import UploadResult

__all__ = [
    "LocalStorage",
    "S3StorageStub",
    "CloudinaryStorage",
    "configure_cloudinary",
    "get_storage",
    "UploadResult",
]
