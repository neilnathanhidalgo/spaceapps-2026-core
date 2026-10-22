from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from ....clients.appeears import AppEEARSClient
from ....schemas.jobs import JobResult, JobStatus
from ....services.appeears_jobs import get_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

_STATUS_MAP = {
    "pending": "pending",
    "queued": "queued",
    "processing": "running",
    "running": "running",
    "done": "done",
    "complete": "done",
    "expired": "failed",
    "error": "failed",
    "failed": "failed",
}


def _normalize_status(upstream_status: str | None) -> str:
    if not upstream_status:
        return "pending"
    return _STATUS_MAP.get(upstream_status.lower(), "running")


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
        status=_normalize_status(task.get("status")),  # type: ignore[arg-type]
        progress=None,
        created_at=_parse_iso(task.get("created")) or now,
        updated_at=_parse_iso(task.get("updated")) or now,
        message=task.get("status"),
    )

    series = []
    if status.status == "done":
        files = await client.list_bundle(job_id)
        csv_file = next(
            (f for f in files if (f.get("file_name") or "").lower().endswith(".csv")),
            None,
        )
        if csv_file is not None:
            content = await client.download_file(job_id, csv_file["file_id"])
            series = client.parse_point_csv(content, entry.layers, entry.location)

    return JobResult(id=job_id, status=status, series=series)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
