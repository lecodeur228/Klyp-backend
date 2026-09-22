"""Projects API routes."""

from fastapi import APIRouter

from app.api.dependencies import AppSettings, CurrentUser, DbSession, LocaleDep
from app.core.responses import accepted_response, success_response
from app.i18n.messages import translate
from app.schemas.editplan import EditPlanPatchRequest, EditPlanPutRequest
from app.schemas.pagination import build_meta
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.render import RenderRequest
from app.services.editplan import service as editplan_service
from app.services.projects import service as projects_service
from app.services.render import service as render_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def list_projects(
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    page: int = 1,
    per_page: int = 15,
):
    items, total = await projects_service.list_projects_public(
        session, user_id=user.id, page=page, per_page=per_page
    )
    data = [p.model_dump(mode="json") for p in items]
    return success_response(
        data,
        translate("ok", locale),
        meta=build_meta(page=page, per_page=per_page, total=total),
    )


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    project = await projects_service.create_project(session, user_id=user.id, data=body)
    return success_response(
        projects_service.to_public(project).model_dump(mode="json"),
        translate("project_created", locale),
        status_code=201,
    )


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    project = await projects_service.get_owned_project_public(
        session, user_id=user.id, project_id=project_id
    )
    return success_response(
        project.model_dump(mode="json"),
        translate("ok", locale),
    )


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    project = await projects_service.update_project(
        session, user_id=user.id, project_id=project_id, data=body
    )
    return success_response(
        projects_service.to_public(project).model_dump(mode="json"),
        translate("project_updated", locale),
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    await projects_service.delete_project(session, user_id=user.id, project_id=project_id)
    return success_response(None, translate("project_deleted", locale))


@router.get("/{project_id}/edit-plan")
async def get_project_edit_plan(
    project_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await editplan_service.get_edit_plan(
        session, user_id=user.id, project_id=project_id
    )
    return success_response(payload.model_dump(mode="json"), translate("ok", locale))


@router.put("/{project_id}/edit-plan")
async def put_project_edit_plan(
    project_id: str,
    body: EditPlanPutRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await editplan_service.put_edit_plan(
        session, user_id=user.id, project_id=project_id, document=body.plan
    )
    return success_response(
        payload.model_dump(mode="json"),
        translate("edit_plan_updated", locale),
    )


@router.patch("/{project_id}/edit-plan")
async def patch_project_edit_plan(
    project_id: str,
    body: EditPlanPatchRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await editplan_service.patch_edit_plan(
        session, user_id=user.id, project_id=project_id, patch=body
    )
    return success_response(
        payload.model_dump(mode="json"),
        translate("edit_plan_updated", locale),
    )


@router.post("/{project_id}/render", status_code=202)
async def render_project(
    project_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
    body: RenderRequest = RenderRequest(),
):
    started = await render_service.start_render(
        session,
        user_id=user.id,
        project_id=project_id,
        kind=body.kind,
        settings=settings,
    )
    return accepted_response(
        started.model_dump(mode="json"),
        translate("render_started", locale),
    )


@router.post("/{project_id}/edit-plan/render", status_code=202)
async def render_edit_plan(
    project_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
    body: RenderRequest = RenderRequest(),
):
    """Alias of POST /projects/{id}/render (docs list both)."""
    started = await render_service.start_render(
        session,
        user_id=user.id,
        project_id=project_id,
        kind=body.kind,
        settings=settings,
    )
    return accepted_response(
        started.model_dump(mode="json"),
        translate("render_started", locale),
    )
