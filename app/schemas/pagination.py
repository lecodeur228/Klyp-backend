"""Pagination helpers."""

from math import ceil

from app.core.responses import PaginationMeta


def build_meta(*, page: int, per_page: int, total: int) -> PaginationMeta:
    last_page = max(1, ceil(total / per_page) if per_page else 1)
    return PaginationMeta(
        current_page=page,
        per_page=per_page,
        total=total,
        last_page=last_page,
    )
