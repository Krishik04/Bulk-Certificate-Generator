import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import CertificateJob
from tests.conftest import JOBS_URL


def _error_locations(response) -> list[tuple]:
    return [tuple(error["loc"]) for error in response.json()["detail"]]


def test_rejects_invalid_email(client, make_payload):
    payload = make_payload(recipient_count=2)
    payload["recipients"][1]["email"] = "not-an-email"

    response = client.post(JOBS_URL, json=payload)

    assert response.status_code == 422
    assert ("body", "recipients", 1, "email") in _error_locations(response)


def test_rejects_empty_recipient_list(client, make_payload):
    response = client.post(JOBS_URL, json=make_payload(recipients=[]))

    assert response.status_code == 422
    assert ("body", "recipients") in _error_locations(response)


@pytest.mark.parametrize("missing_field", ["event_name", "organization_name", "issue_date", "recipients"])
def test_rejects_missing_job_fields(client, make_payload, missing_field):
    payload = make_payload()
    del payload[missing_field]

    response = client.post(JOBS_URL, json=payload)

    assert response.status_code == 422
    assert ("body", missing_field) in _error_locations(response)


@pytest.mark.parametrize("missing_field", ["name", "email", "course_name"])
def test_rejects_missing_recipient_fields(client, make_payload, missing_field):
    payload = make_payload(recipient_count=1)
    del payload["recipients"][0][missing_field]

    response = client.post(JOBS_URL, json=payload)

    assert response.status_code == 422
    assert ("body", "recipients", 0, missing_field) in _error_locations(response)


@pytest.mark.parametrize("bad_date", ["2026-13-01", "2026-02-30", "09/10/2026", "not-a-date"])
def test_rejects_invalid_issue_date(client, make_payload, bad_date):
    response = client.post(JOBS_URL, json=make_payload(issue_date=bad_date))

    assert response.status_code == 422
    assert ("body", "issue_date") in _error_locations(response)


def test_rejects_blank_strings(client, make_payload):
    payload = make_payload(recipient_count=1, event_name="   ")
    payload["recipients"][0]["name"] = ""

    response = client.post(JOBS_URL, json=payload)

    assert response.status_code == 422
    locations = _error_locations(response)
    assert ("body", "event_name") in locations
    assert ("body", "recipients", 0, "name") in locations


def test_rejects_batch_larger_than_default_maximum(client, session_factory, make_payload):
    response = client.post(JOBS_URL, json=make_payload(recipient_count=501))

    assert response.status_code == 422
    assert ("body", "recipients") in _error_locations(response)
    assert "at most 500" in response.json()["detail"][0]["msg"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CertificateJob)) == 0


def test_accepts_batch_at_exactly_the_maximum(client, make_payload, settings):
    response = client.post(JOBS_URL, json=make_payload(recipient_count=settings.max_recipients_per_job))

    assert response.status_code == 202


def test_maximum_batch_size_is_configurable(tmp_path, make_payload):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'small.db'}",
        certificate_output_dir=tmp_path / "certs",
        max_recipients_per_job=3,
        log_level="WARNING",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(JOBS_URL, json=make_payload(recipient_count=4)).status_code == 422
        assert client.post(JOBS_URL, json=make_payload(recipient_count=3)).status_code == 202
