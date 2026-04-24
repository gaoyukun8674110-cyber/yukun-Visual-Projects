from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import DetectionJob, JobLog, MediaAsset
from app.schemas import DetectionJobRead, JobCreate, JobLogRead
from app.services.events import publish_job_event
from app.services.queue import enqueue_detection_job, get_redis

router = APIRouter()


def job_to_schema(job: DetectionJob) -> DetectionJobRead:
    result_url = f"/storage/{job.result_path}" if job.result_path else None
    return DetectionJobRead.model_validate(job).model_copy(update={"result_url": result_url})


@router.post("", response_model=DetectionJobRead, status_code=201)
async def create_job(
    data: JobCreate,
    session: AsyncSession = Depends(get_session),
) -> DetectionJobRead:
    asset = await session.get(MediaAsset, data.media_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")

    job = DetectionJob(media_id=asset.id, status="queued", progress=0, model_name=data.model_name)
    session.add(job)
    await session.flush()
    session.add(JobLog(job_id=job.id, level="INFO", message="任务已创建，等待 worker 消费", payload=None))
    await session.commit()
    await session.refresh(job)

    redis: Redis = await get_redis()
    try:
        await enqueue_detection_job(redis, job.id, asset.id, data.model_name)
        await publish_job_event(redis, job.id, "queued", {"status": "queued", "progress": 0})
    finally:
        await redis.aclose()

    return job_to_schema(job)


@router.get("", response_model=list[DetectionJobRead])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[DetectionJobRead]:
    result = await session.execute(select(DetectionJob).order_by(desc(DetectionJob.created_at)).limit(50))
    return [job_to_schema(job) for job in result.scalars().all()]


@router.get("/{job_id}", response_model=DetectionJobRead)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> DetectionJobRead:
    job = await session.get(DetectionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_schema(job)


@router.get("/{job_id}/logs", response_model=list[JobLogRead])
async def get_job_logs(job_id: str, session: AsyncSession = Depends(get_session)) -> list[JobLogRead]:
    result = await session.execute(
        select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.created_at.asc()).limit(500)
    )
    return [JobLogRead.model_validate(log) for log in result.scalars().all()]
