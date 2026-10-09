"""Pydantic request/response schemas (kept separate from the SQLAlchemy models)."""

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.enums import JobStatus, RecipientStatus

# Trims surrounding whitespace, then rejects empty strings and overly long values.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


# ---------- Requests ----------


class RecipientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr
    email: EmailStr
    course_name: NonEmptyStr


class CertificateJobCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "event_name": "Python Bootcamp 2026",
                    "organization_name": "ABC Technologies",
                    "issue_date": "2026-10-09",
                    "recipients": [
                        {
                            "name": "Sai Krishik",
                            "email": "krishik@example.com",
                            "course_name": "Python Programming",
                        },
                        {
                            "name": "Rahul Sharma",
                            "email": "rahul@example.com",
                            "course_name": "Backend Development",
                        },
                    ],
                }
            ]
        },
    )

    event_name: NonEmptyStr
    organization_name: NonEmptyStr
    issue_date: date
    # The upper bound is enforced in the route using the configurable
    # MAX_RECIPIENTS_PER_JOB setting, so it can be changed without code edits.
    recipients: list[RecipientIn] = Field(min_length=1)


# ---------- Responses ----------


class ErrorResponse(BaseModel):
    detail: str


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus
    total_recipients: int
    created_at: datetime
    status_url: str


class RecipientStatusOut(BaseModel):
    id: str
    name: str
    email: str
    course_name: str
    status: RecipientStatus
    error_message: str | None
    download_url: str | None = Field(
        description="Present only when the certificate was generated successfully."
    )
    completed_at: datetime | None


class JobStatusResponse(BaseModel):
    job_id: str
    event_name: str
    organization_name: str
    issue_date: date
    status: JobStatus
    total_recipients: int
    successful_count: int
    failed_count: int
    pending_count: int
    processing_count: int
    progress_percentage: float = Field(
        description="Share of recipients that reached a final state (SUCCESS or FAILED), 0-100."
    )
    created_at: datetime
    completed_at: datetime | None
    recipients: list[RecipientStatusOut]


class JobSummary(BaseModel):
    job_id: str
    event_name: str
    organization_name: str
    status: JobStatus
    total_recipients: int
    successful_count: int
    failed_count: int
    created_at: datetime
    completed_at: datetime | None
    status_url: str


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int
    limit: int
    offset: int
