"""Business logic for certificate jobs: creation, batch processing, progress and queries.

This module is independent of FastAPI so it can be called directly from tests.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.enums import JobStatus, RecipientStatus
from app.models import CertificateJob, CertificateRecipient, utc_now
from app.schemas import CertificateJobCreate
from app.services import certificate_service
from app.services.certificate_service import CertificateData
from app.utils import file_utils

logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 500
FINAL_RECIPIENT_STATUSES = (RecipientStatus.SUCCESS, RecipientStatus.FAILED)


@dataclass(frozen=True)
class JobProgress:
    total: int
    successful: int
    failed: int
    pending: int
    processing: int

    @property
    def percentage(self) -> float:
        """Percentage of recipients in a final state (SUCCESS or FAILED)."""
        if self.total == 0:
            return 0.0
        return round((self.successful + self.failed) / self.total * 100, 2)


@dataclass(frozen=True)
class JobSummaryRow:
    job: CertificateJob
    total_recipients: int
    successful_count: int
    failed_count: int


# ---------- Creation and queries (used by the API) ----------


def create_job(db: Session, payload: CertificateJobCreate) -> CertificateJob:
    """Persist a job and all its recipients in a single short transaction."""
    job = CertificateJob(
        event_name=payload.event_name,
        organization_name=payload.organization_name,
        issue_date=payload.issue_date,
        status=JobStatus.PENDING,
    )
    job.recipients = [
        CertificateRecipient(
            position=index,
            name=recipient.name,
            email=str(recipient.email),
            course_name=recipient.course_name,
            status=RecipientStatus.PENDING,
        )
        for index, recipient in enumerate(payload.recipients)
    ]
    db.add(job)
    db.commit()
    logger.info("Created job %s with %d recipients", job.id, len(job.recipients))
    return job


def get_job(db: Session, job_id: str) -> CertificateJob | None:
    stmt = (
        select(CertificateJob)
        .where(CertificateJob.id == job_id)
        .options(selectinload(CertificateJob.recipients))
    )
    return db.scalars(stmt).first()


def get_recipient(db: Session, recipient_id: str) -> CertificateRecipient | None:
    return db.get(CertificateRecipient, recipient_id)


def calculate_progress(recipients: list[CertificateRecipient]) -> JobProgress:
    """Derive counters from one snapshot of persisted recipient rows."""
    counts = {status: 0 for status in RecipientStatus}
    for recipient in recipients:
        counts[recipient.status] += 1
    return JobProgress(
        total=len(recipients),
        successful=counts[RecipientStatus.SUCCESS],
        failed=counts[RecipientStatus.FAILED],
        pending=counts[RecipientStatus.PENDING],
        processing=counts[RecipientStatus.PROCESSING],
    )


def list_jobs(db: Session, limit: int, offset: int) -> tuple[list[JobSummaryRow], int]:
    """Most recent jobs first, with per-job recipient counters computed in SQL."""
    counts = (
        select(
            CertificateRecipient.job_id.label("job_id"),
            func.count().label("total"),
            func.sum(case((CertificateRecipient.status == RecipientStatus.SUCCESS, 1), else_=0)).label(
                "successful"
            ),
            func.sum(case((CertificateRecipient.status == RecipientStatus.FAILED, 1), else_=0)).label(
                "failed"
            ),
        )
        .group_by(CertificateRecipient.job_id)
        .subquery()
    )
    stmt = (
        select(
            CertificateJob,
            func.coalesce(counts.c.total, 0),
            func.coalesce(counts.c.successful, 0),
            func.coalesce(counts.c.failed, 0),
        )
        .outerjoin(counts, counts.c.job_id == CertificateJob.id)
        .order_by(CertificateJob.created_at.desc(), CertificateJob.id)
        .limit(limit)
        .offset(offset)
    )
    rows = [
        JobSummaryRow(job=job, total_recipients=total, successful_count=ok, failed_count=failed)
        for job, total, ok, failed in db.execute(stmt).all()
    ]
    total_jobs = db.scalar(select(func.count()).select_from(CertificateJob)) or 0
    return rows, total_jobs


# ---------- Background processing ----------


def process_job(job_id: str, session_factory: sessionmaker[Session], output_dir: Path) -> None:
    """Generate certificates for every pending recipient of a job.

    Runs outside the request cycle (FastAPI BackgroundTasks) with its own
    session. Every status change is committed immediately, so no transaction
    stays open for the whole batch and progress is visible to the status API.
    """
    with session_factory() as db:
        job = db.get(CertificateJob, job_id)
        if job is None:
            logger.warning("Job %s not found; nothing to process", job_id)
            return
        if job.status != JobStatus.PENDING:
            logger.warning("Job %s is %s, not PENDING; skipping", job_id, job.status)
            return

        job.status = JobStatus.PROCESSING
        db.commit()
        logger.info("Started processing job %s", job_id)

        try:
            file_utils.ensure_directory(output_dir)
            recipient_ids = db.scalars(
                select(CertificateRecipient.id)
                .where(
                    CertificateRecipient.job_id == job_id,
                    CertificateRecipient.status == RecipientStatus.PENDING,
                )
                .order_by(CertificateRecipient.position)
            ).all()

            for recipient_id in recipient_ids:
                _process_recipient(db, job, recipient_id, output_dir)

            _finalize_job(db, job)
        except Exception:
            # Unrecoverable job-level failure (e.g. storage or database unavailable).
            logger.exception("Job %s failed with an unrecoverable error", job_id)
            db.rollback()
            _mark_job_failed(db, job_id)


def _process_recipient(
    db: Session, job: CertificateJob, recipient_id: str, output_dir: Path
) -> None:
    """Generate one certificate. PDF errors are recorded on the recipient, never re-raised."""
    recipient = db.get(CertificateRecipient, recipient_id)
    if recipient is None:
        return

    recipient.status = RecipientStatus.PROCESSING
    db.commit()

    storage_key = file_utils.build_storage_key(job.id, recipient.id)
    try:
        certificate_service.generate_certificate_pdf(
            CertificateData(
                recipient_name=recipient.name,
                course_name=recipient.course_name,
                event_name=job.event_name,
                organization_name=job.organization_name,
                issue_date=job.issue_date,
            ),
            file_utils.resolve_storage_path(output_dir, storage_key),
        )
    except Exception as exc:
        logger.exception("Certificate generation failed for recipient %s (job %s)", recipient.id, job.id)
        recipient.status = RecipientStatus.FAILED
        recipient.error_message = _format_error(exc)
    else:
        recipient.status = RecipientStatus.SUCCESS
        recipient.certificate_path = storage_key
        recipient.error_message = None

    recipient.completed_at = utc_now()
    db.commit()


def _finalize_job(db: Session, job: CertificateJob) -> None:
    failed_count = db.scalar(
        select(func.count())
        .select_from(CertificateRecipient)
        .where(
            CertificateRecipient.job_id == job.id,
            CertificateRecipient.status == RecipientStatus.FAILED,
        )
    )
    job.status = JobStatus.COMPLETED_WITH_ERRORS if failed_count else JobStatus.COMPLETED
    job.completed_at = utc_now()
    db.commit()
    logger.info("Job %s finished with status %s (%d failed)", job.id, job.status, failed_count)


def _mark_job_failed(db: Session, job_id: str) -> None:
    """Mark the job FAILED and close out any recipients that never reached a final state."""
    try:
        now = utc_now()
        db.execute(
            update(CertificateRecipient)
            .where(
                CertificateRecipient.job_id == job_id,
                CertificateRecipient.status.not_in(FINAL_RECIPIENT_STATUSES),
            )
            .values(
                status=RecipientStatus.FAILED,
                error_message="Job aborted before this certificate could be generated.",
                completed_at=now,
            )
        )
        job = db.get(CertificateJob, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.completed_at = now
        db.commit()
    except Exception:
        logger.exception("Could not record failure state for job %s", job_id)
        db.rollback()


def _format_error(exc: Exception) -> str:
    message = f"Certificate generation failed: {type(exc).__name__}: {exc}"
    return message[:MAX_ERROR_MESSAGE_LENGTH]
