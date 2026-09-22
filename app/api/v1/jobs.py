"""Jobs API routes."""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession, LocaleDep
from app.core.responses import success_response
from app.i18n.messages import translate
from app.services.jobs import service as jobs_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    job = await jobs_service.get_owned_job(session, user_id=user.id, job_id=job_id)
    return success_response(
        jobs_service.to_public(job).model_dump(mode="json"),
        translate("ok", locale),
    )


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    job = await jobs_service.cancel_job(session, user_id=user.id, job_id=job_id)
    return success_response(
        jobs_service.to_public(job).model_dump(mode="json"),
        translate("job_cancelled", locale),
    )
