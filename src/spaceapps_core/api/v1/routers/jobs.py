from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from ....clients.appeears import AppEEARSClient, normalize_task_status
from ....schemas.jobs import JobResult, JobStatus
from ....services.appeears_jobs import get_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    summary="Fetch status (and parsed result when done) of an AppEEARS job",
    response_model=JobResult,
)
async def get_job_endpoint(job_id: str) -> JobResult:
    entry = get_job(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown job id: {job_id}")

    client = AppEEARSClient()
    task = await client.get_task(job_id)
    now = datetime.utcnow()
    status = JobStatus(
        id=job_id,
        source=entry.source,
        status=normalize_task_status(task.get("status")),  # type: ignore[arg-type]
        progress=None,
        created_at=_parse_iso(task.get("created")) or now,
        updated_at=_parse_iso(task.get("updated")) or now,
        message=task.get("status"),
    )

    series = []
    if status.status == "done":
        series = await client.point_task_series(job_id, entry.layers, entry.location)

    return JobResult(id=job_id, status=status, series=series)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
