"""SQLAlchemy ORM models."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import JobStatus, RecipientStatus


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores datetimes as UTC and always returns timezone-aware values.

    SQLite has no native timezone support and returns naive datetimes; this
    type re-attaches UTC so API responses are unambiguous (e.g. "...+00:00").
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class CertificateJob(Base):
    __tablename__ = "certificate_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    event_name: Mapped[str] = mapped_column(String(200))
    organization_name: Mapped[str] = mapped_column(String(200))
    issue_date: Mapped[date] = mapped_column(Date)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32),
        default=JobStatus.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    recipients: Mapped[list["CertificateRecipient"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="CertificateRecipient.position",
    )


class CertificateRecipient(Base):
    __tablename__ = "certificate_recipients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("certificate_jobs.id", ondelete="CASCADE"), index=True
    )
    # Preserves the order recipients were submitted in.
    position: Mapped[int] = mapped_column(default=0)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    course_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[RecipientStatus] = mapped_column(
        Enum(RecipientStatus, native_enum=False, length=32),
        default=RecipientStatus.PENDING,
        index=True,
    )
    # Storage key relative to the configured certificate directory, never an absolute path.
    certificate_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    job: Mapped[CertificateJob] = relationship(back_populates="recipients")
