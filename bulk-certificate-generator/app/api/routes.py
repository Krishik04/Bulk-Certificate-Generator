"""HTTP endpoints. Routes stay thin: validate, delegate to services, map to response schemas."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.enums import RecipientStatus
from app.models import CertificateJob, CertificateRecipient
from app.schemas import (
    CertificateJobCreate,
    ErrorResponse,
    JobCreatedResponse,
    JobListResponse,
    JobStatusResponse,
    JobSummary,
    RecipientStatusOut,
)
from app.services import job_service
from app.utils import file_utils

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


# ---------- Response mapping helpers ----------


def _status_url(request: Request, job_id: str) -> str:
    return str(request.url_for("get_certificate_job", job_id=job_id))


def _download_url(request: Request, recipient: CertificateRecipient) -> str | None:
    if recipient.status != RecipientStatus.SUCCESS:
        return None
    return str(request.url_for("download_certificate", recipient_id=recipient.id))


def _to_status_response(request: Request, job: CertificateJob) -> JobStatusResponse:
    progress = job_service.calculate_progress(job.recipients)
    return JobStatusResponse(
        job_id=job.id,
        event_name=job.event_name,
        organization_name=job.organization_name,
        issue_date=job.issue_date,
        status=job.status,
        total_recipients=progress.total,
        successful_count=progress.successful,
        failed_count=progress.failed,
        pending_count=progress.pending,
        processing_count=progress.processing,
        progress_percentage=progress.percentage,
        created_at=job.created_at,
        completed_at=job.completed_at,
        recipients=[
            RecipientStatusOut(
                id=recipient.id,
                name=recipient.name,
                email=recipient.email,
                course_name=recipient.course_name,
                status=recipient.status,
                error_message=recipient.error_message,
                download_url=_download_url(request, recipient),
                completed_at=recipient.completed_at,
            )
            for recipient in job.recipients
        ],
    )


# ---------- Endpoints ----------


@router.post(
    "/certificate-jobs",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Certificate jobs"],
    summary="Submit a bulk certificate generation job",
    description=(
        "Validates the batch, stores the job and its recipients, and schedules PDF "
        "generation in the background. Returns immediately with the job ID and a status URL."
    ),
    responses={422: {"description": "Validation error (missing fields, invalid email/date, "
                                     "empty or oversized recipient list)"}},
)
def create_certificate_job(
    payload: CertificateJobCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobCreatedResponse:
    if len(payload.recipients) > settings.max_recipients_per_job:
        raise RequestValidationError(
            [
                {
                    "type": "too_long",
                    "loc": ("body", "recipients"),
                    "msg": (
                        f"A job may contain at most {settings.max_recipients_per_job} recipients "
                        f"(received {len(payload.recipients)})"
                    ),
                    "input": None,
                }
            ]
        )

    job = job_service.create_job(db, payload)
    background_tasks.add_task(
        job_service.process_job,
        job.id,
        request.app.state.session_factory,
        settings.certificate_output_dir,
    )
    return JobCreatedResponse(
        job_id=job.id,
        status=job.status,
        total_recipients=len(job.recipients),
        created_at=job.created_at,
        status_url=_status_url(request, job.id),
    )


@router.get(
    "/certificate-jobs",
    response_model=JobListResponse,
    tags=["Certificate jobs"],
    summary="List recent certificate jobs",
    description="Returns jobs newest first, with recipient counters. Supports limit/offset pagination.",
)
def list_certificate_jobs(
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Maximum number of jobs to return"),
    offset: int = Query(0, ge=0, description="Number of jobs to skip"),
    db: Session = Depends(get_db),
) -> JobListResponse:
    rows, total = job_service.list_jobs(db, limit=limit, offset=offset)
    return JobListResponse(
        items=[
            JobSummary(
                job_id=row.job.id,
                event_name=row.job.event_name,
                organization_name=row.job.organization_name,
                status=row.job.status,
                total_recipients=row.total_recipients,
                successful_count=row.successful_count,
                failed_count=row.failed_count,
                created_at=row.job.created_at,
                completed_at=row.job.completed_at,
                status_url=_status_url(request, row.job.id),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/certificate-jobs/{job_id}",
    name="get_certificate_job",
    response_model=JobStatusResponse,
    tags=["Certificate jobs"],
    summary="Get job status and progress",
    description=(
        "Returns the job status, progress counters and each recipient's status. "
        "`progress_percentage` is the share of recipients that reached a final state "
        "(SUCCESS or FAILED)."
    ),
    responses={404: {"model": ErrorResponse, "description": "Job not found"}},
)
def get_certificate_job(job_id: str, request: Request, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate job not found")
    return _to_status_response(request, job)


@router.get(
    "/certificates/{recipient_id}",
    name="download_certificate",
    response_class=FileResponse,
    tags=["Certificates"],
    summary="Download a generated certificate PDF",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The certificate PDF"},
        404: {"model": ErrorResponse, "description": "Recipient or certificate file not found"},
        409: {"model": ErrorResponse, "description": "Certificate is pending, processing or failed"},
    },
)
def download_certificate(
    recipient_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    recipient = job_service.get_recipient(db, recipient_id)
    if recipient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found")

    if recipient.status != RecipientStatus.SUCCESS or not recipient.certificate_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Certificate is not available for download (status: {recipient.status})",
        )

    try:
        file_path = file_utils.resolve_storage_path(
            settings.certificate_output_dir, recipient.certificate_path
        )
    except ValueError:
        logger.error("Rejected unsafe storage key for recipient %s", recipient_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate file not found")

    if not file_path.is_file():
        logger.error("Certificate file missing on disk for recipient %s", recipient_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate file not found")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=file_utils.build_download_filename(recipient.name),
    )
