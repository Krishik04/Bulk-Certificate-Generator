from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.enums import RecipientStatus
from app.models import CertificateRecipient
from app.schemas import CertificateJobCreate
from app.services import job_service
from tests.conftest import JOBS_URL

CERTIFICATES_URL = "/api/v1/certificates"


def _first_recipient(client, job_id: str) -> dict:
    return client.get(f"{JOBS_URL}/{job_id}").json()["recipients"][0]


def test_download_successful_certificate(client, make_payload):
    payload = make_payload(recipient_count=1)
    payload["recipients"][0]["name"] = "Sai Krishik"
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]
    recipient = _first_recipient(client, job_id)

    response = client.get(f"{CERTIFICATES_URL}/{recipient['id']}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="certificate-sai-krishik.pdf"' in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    assert "Sai Krishik" in PdfReader(BytesIO(response.content)).pages[0].extract_text()


@pytest.mark.parametrize(
    "recipient_status", [RecipientStatus.PENDING, RecipientStatus.PROCESSING, RecipientStatus.FAILED]
)
def test_download_unfinished_or_failed_certificate_returns_409(
    client, session_factory, make_payload, recipient_status
):
    with session_factory() as db:
        job = job_service.create_job(db, CertificateJobCreate(**make_payload(recipient_count=1)))
        recipient = db.scalars(
            select(CertificateRecipient).where(CertificateRecipient.job_id == job.id)
        ).one()
        recipient.status = recipient_status
        db.commit()
        recipient_id = recipient.id

    response = client.get(f"{CERTIFICATES_URL}/{recipient_id}")

    assert response.status_code == 409
    assert recipient_status in response.json()["detail"]


def test_download_unknown_recipient_returns_404(client):
    response = client.get(f"{CERTIFICATES_URL}/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "Recipient not found"}


def test_download_missing_file_returns_404(client, settings, make_payload):
    job_id = client.post(JOBS_URL, json=make_payload(recipient_count=1)).json()["job_id"]
    recipient = _first_recipient(client, job_id)
    (settings.certificate_output_dir / job_id / f"{recipient['id']}.pdf").unlink()

    response = client.get(f"{CERTIFICATES_URL}/{recipient['id']}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Certificate file not found"}
    assert str(settings.certificate_output_dir) not in response.text  # no server paths leaked


def test_download_rejects_tampered_storage_key(client, session_factory, make_payload):
    job_id = client.post(JOBS_URL, json=make_payload(recipient_count=1)).json()["job_id"]
    recipient_id = _first_recipient(client, job_id)["id"]
    with session_factory() as db:
        db.get(CertificateRecipient, recipient_id).certificate_path = "../../etc/passwd"
        db.commit()

    response = client.get(f"{CERTIFICATES_URL}/{recipient_id}")

    assert response.status_code == 404
