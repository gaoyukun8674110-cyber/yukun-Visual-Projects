from fastapi import APIRouter, Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.core.security import require_api_key
from app.db import get_session
from app.models import DetectionJob, JobLog, MediaAsset
from app.schemas import DetectionJobRead, JobCreate, JobLogRead
from app.services.events import publish_job_event
from app.services.queue import enqueue_detection_job, get_queue_depth, get_redis
from app.services.quota import consume_daily_job_quota, ensure_active_job_quota, rollback_daily_job_quota

router = APIRouter()
settings = get_settings()


def job_to_schema(job: DetectionJob) -> DetectionJobRead:
    result_url = f"/api/files/{job.result_path}" if job.result_path else None
    return DetectionJobRead.model_validate(job).model_copy(update={"result_url": result_url})


def validate_model_name(model_name: str) -> None:
    if "/" in model_name or "\\" in model_name or ".." in model_name or model_name not in settings.allowed_models:
        raise HTTPException(status_code=422, detail="Unsupported model")


@router.post("", response_model=DetectionJobRead, status_code=201)
@limiter.limit("10/minute")
async def create_job(
    request: Request,
    data: JobCreate,
    client_id: str = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> DetectionJobRead:
    validate_model_name(data.model_name)

    redis: Redis = await get_redis()
    daily_quota_consumed = False
    try:
        depth = await get_queue_depth(redis)
        if depth > settings.queue_max_depth:
            raise HTTPException(
                status_code=503,
                detail="System busy, retry later",
                headers={"Retry-After": "30"},
            )

        asset = await session.get(MediaAsset, data.media_id)
        if asset is None or asset.client_id != client_id:
            raise HTTPException(status_code=404, detail="Media asset not found")

        await ensure_active_job_quota(session, client_id)
        await consume_daily_job_quota(redis, client_id)
        daily_quota_consumed = True

        job = DetectionJob(
            media_id=asset.id,
            status="queued",
            progress=0,
            model_name=data.model_name,
            client_id=client_id,
        )
        session.add(job)
        await session.flush()
        session.add(JobLog(job_id=job.id, level="INFO", message="任务已创建，等待 worker 消费", payload=None))
        await session.commit()
        await session.refresh(job)

        await enqueue_detection_job(redis, job.id, asset.id, data.model_name)
        await publish_job_event(redis, job.id, "queued", {"status": "queued", "progress": 0})
    except HTTPException:
        if daily_quota_consumed:
            await rollback_daily_job_quota(redis, client_id)
        raise
    except Exception:
        if daily_quota_consumed:
            await rollback_daily_job_quota(redis, client_id)
        await session.rollback()
        raise
    finally:
        await redis.aclose()

    return job_to_schema(job)


@router.get("", response_model=list[DetectionJobRead])
@limiter.limit("120/minute")
async def list_jobs(
    request: Request,
    client_id: str = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> list[DetectionJobRead]:
    result = await session.execute(
        select(DetectionJob)
        .where(DetectionJob.client_id == client_id)
        .order_by(desc(DetectionJob.created_at))
        .limit(50)
    )
    return [job_to_schema(job) for job in result.scalars().all()]


@router.get("/{job_id}", response_model=DetectionJobRead)
@limiter.limit("120/minute")
async def get_job(
    request: Request,
    job_id: str,
    client_id: str = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> DetectionJobRead:
    job = await session.get(DetectionJob, job_id)
    if job is None or job.client_id != client_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_schema(job)


@router.get("/{job_id}/logs", response_model=list[JobLogRead])
@limiter.limit("120/minute")
async def get_job_logs(
    request: Request,
    job_id: str,
    client_id: str = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> list[JobLogRead]:
    job = await session.get(DetectionJob, job_id)
    if job is None or job.client_id != client_id:
        raise HTTPException(status_code=404, detail="Job not found")
    result = await session.execute(
        select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.created_at.asc()).limit(500)
    )
    return [JobLogRead.model_validate(log) for log in result.scalars().all()]
