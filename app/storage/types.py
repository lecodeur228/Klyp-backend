"""Upload result shared by storage backends."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class UploadResult:
    public_id: str
    secure_url: str
    resource_type: str
    format: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    bytes: int = 0
    metadata: dict = field(default_factory=dict)
