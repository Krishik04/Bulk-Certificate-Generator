from uuid import UUID

from sqlalchemy import select

from app.enums import JobStatus, RecipientStatus
from app.models import CertificateJob, CertificateRecipient
from tests.conftest import JOBS_URL


def test_create_job_returns_202_with_job_id_and_status_url(client, make_payload):
    response = client.post(JOBS_URL, json=make_payload(recipient_count=2))

    assert response.status_code == 202
    body = response.json()
    UUID(body["job_id"])  # raises if not a valid UUID
    # The response reflects the state at submission time, before background work ran.
    assert body["status"] == JobStatus.PENDING
    assert body["total_recipients"] == 2
    assert body["status_url"].endswith(f"{JOBS_URL}/{body['job_id']}")


def test_create_job_persists_job_and_recipients(client, session_factory, make_payload):
    payload = make_payload(recipient_count=3)
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]

    with session_factory() as db:
        job = db.get(CertificateJob, job_id)
        assert job is not None
        assert job.event_name == payload["event_name"]
        assert job.organization_name == payload["organization_name"]
        assert job.issue_date.isoformat() == payload["issue_date"]

        recipients = db.scalars(
            select(CertificateRecipient)
            .where(CertificateRecipient.job_id == job_id)
            .order_by(CertificateRecipient.position)
        ).all()
        assert [r.email for r in recipients] == [r["email"] for r in payload["recipients"]]


def test_background_processing_completes_job(client, make_payload):
    job_id = client.post(JOBS_URL, json=make_payload(recipient_count=2)).json()["job_id"]

    body = client.get(f"{JOBS_URL}/{job_id}").json()
    assert body["status"] == JobStatus.COMPLETED
    assert all(r["status"] == RecipientStatus.SUCCESS for r in body["recipients"])


def test_list_jobs_returns_recent_jobs_with_pagination(client, make_payload):
    first = client.post(JOBS_URL, json=make_payload(recipient_count=1)).json()["job_id"]
    second = client.post(JOBS_URL, json=make_payload(recipient_count=3)).json()["job_id"]

    response = client.get(JOBS_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["job_id"] for item in body["items"]] == [second, first]  # newest first
    assert body["items"][0]["total_recipients"] == 3
    assert body["items"][0]["successful_count"] == 3
    assert body["items"][0]["failed_count"] == 0

    page = client.get(JOBS_URL, params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2
    assert [item["job_id"] for item in page["items"]] == [first]


def test_list_jobs_rejects_invalid_pagination(client):
    assert client.get(JOBS_URL, params={"limit": 0}).status_code == 422
    assert client.get(JOBS_URL, params={"offset": -1}).status_code == 422
