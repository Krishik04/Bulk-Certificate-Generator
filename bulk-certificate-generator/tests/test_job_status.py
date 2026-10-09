from sqlalchemy import select

from app.enums import JobStatus, RecipientStatus
from app.models import CertificateRecipient
from app.schemas import CertificateJobCreate
from app.services import job_service
from tests.conftest import JOBS_URL


def test_status_of_completed_job_reports_counters(client, make_payload):
    job_id = client.post(JOBS_URL, json=make_payload(recipient_count=3)).json()["job_id"]

    response = client.get(f"{JOBS_URL}/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["status"] == JobStatus.COMPLETED
    assert body["total_recipients"] == 3
    assert body["successful_count"] == 3
    assert body["failed_count"] == 0
    assert body["pending_count"] == 0
    assert body["processing_count"] == 0
    assert body["progress_percentage"] == 100.0
    assert body["created_at"] is not None
    assert body["completed_at"] is not None
    for recipient in body["recipients"]:
        assert recipient["status"] == RecipientStatus.SUCCESS
        assert recipient["error_message"] is None
        assert recipient["download_url"].endswith(f"/api/v1/certificates/{recipient['id']}")


def test_status_of_partially_processed_job(client, session_factory, make_payload):
    """Build an in-progress snapshot directly in the DB (no background run) and check the maths."""
    with session_factory() as db:
        job = job_service.create_job(db, CertificateJobCreate(**make_payload(recipient_count=4)))
        job.status = JobStatus.PROCESSING
        recipients = db.scalars(
            select(CertificateRecipient)
            .where(CertificateRecipient.job_id == job.id)
            .order_by(CertificateRecipient.position)
        ).all()
        recipients[0].status = RecipientStatus.SUCCESS
        recipients[0].certificate_path = f"{job.id}/{recipients[0].id}.pdf"
        recipients[1].status = RecipientStatus.FAILED
        recipients[1].error_message = "boom"
        recipients[2].status = RecipientStatus.PROCESSING
        db.commit()
        job_id = job.id

    body = client.get(f"{JOBS_URL}/{job_id}").json()

    assert body["status"] == JobStatus.PROCESSING
    assert body["successful_count"] == 1
    assert body["failed_count"] == 1
    assert body["processing_count"] == 1
    assert body["pending_count"] == 1
    assert body["progress_percentage"] == 50.0
    assert body["completed_at"] is None
    statuses = [r["status"] for r in body["recipients"]]
    assert statuses == ["SUCCESS", "FAILED", "PROCESSING", "PENDING"]  # submission order kept
    assert [r["download_url"] is not None for r in body["recipients"]] == [True, False, False, False]


def test_unknown_job_returns_404(client):
    response = client.get(f"{JOBS_URL}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "Certificate job not found"}
