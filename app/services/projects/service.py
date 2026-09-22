"""Project service — owner-scoped CRUD."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.project import Project
from app.models.video import Video
from app.schemas.project import ProjectCreate, ProjectPublic, ProjectUpdate


def to_public(
    project: Project,
    *,
    latest_video: Video | None = None,
) -> ProjectPublic:
    return ProjectPublic(
        id=project.id,
        user_id=project.user_id,
        name=project.name,
        description=project.description,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
        latest_video_id=latest_video.id if latest_video else None,
        thumbnail_url=latest_video.thumbnail_url if latest_video else None,
    )


async def _latest_videos_by_project(
    session: AsyncSession,
    *,
    project_ids: list[str],
) -> dict[str, Video]:
    if not project_ids:
        return {}
    result = await session.execute(
        select(Video)
        .where(Video.project_id.in_(project_ids))
        .order_by(Video.created_at.desc())
    )
    latest: dict[str, Video] = {}
    for video in result.scalars().all():
        if video.project_id not in latest:
            latest[video.project_id] = video
    return latest


async def list_projects(
    session: AsyncSession,
    *,
    user_id: str,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list[Project], int]:
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    total = (
        await session.execute(
            select(func.count()).select_from(Project).where(Project.user_id == user_id)
        )
    ).scalar_one()
    result = await session.execute(
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(Project.updated_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.scalars().all()), total


async def list_projects_public(
    session: AsyncSession,
    *,
    user_id: str,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list[ProjectPublic], int]:
    items, total = await list_projects(
        session, user_id=user_id, page=page, per_page=per_page
    )
    latest = await _latest_videos_by_project(
        session, project_ids=[p.id for p in items]
    )
    return [to_public(p, latest_video=latest.get(p.id)) for p in items], total


async def get_owned_project(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
) -> Project:
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundException("Project not found")
    return project


async def get_owned_project_public(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
) -> ProjectPublic:
    project = await get_owned_project(session, user_id=user_id, project_id=project_id)
    latest = await _latest_videos_by_project(session, project_ids=[project.id])
    return to_public(project, latest_video=latest.get(project.id))


async def create_project(
    session: AsyncSession,
    *,
    user_id: str,
    data: ProjectCreate,
) -> Project:
    project = Project(
        user_id=user_id,
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        status="active",
    )
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project


async def update_project(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    data: ProjectUpdate,
) -> Project:
    project = await get_owned_project(session, user_id=user_id, project_id=project_id)
    payload = data.model_dump(exclude_unset=True)
    if "name" in payload and payload["name"] is not None:
        project.name = payload["name"].strip()
    if "description" in payload:
        desc = payload["description"]
        project.description = desc.strip() if isinstance(desc, str) and desc else desc
    if "status" in payload and payload["status"] is not None:
        project.status = payload["status"]
    await session.flush()
    await session.refresh(project)
    return project


async def delete_project(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
) -> None:
    project = await get_owned_project(session, user_id=user_id, project_id=project_id)
    await session.delete(project)
    await session.flush()
