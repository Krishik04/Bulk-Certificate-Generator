from app.enums import JobStatus, RecipientStatus
from app.schemas import CertificateJobCreate
from app.services import certificate_service, job_service
from app.utils import file_utils
from tests.conftest import JOBS_URL


def _fail_for(name_to_fail: str, monkeypatch):
    """Patch PDF generation so it raises for one specific recipient only."""
    real_generate = certificate_service.generate_certificate_pdf

    def flaky_generate(data, output_path):
        if data.recipient_name == name_to_fail:
            raise RuntimeError("simulated rendering error")
        return real_generate(data, output_path)

    monkeypatch.setattr(certificate_service, "generate_certificate_pdf", flaky_generate)


def test_one_failure_does_not_stop_the_batch(client, settings, monkeypatch, make_payload):
    _fail_for("Recipient 2", monkeypatch)

    job_id = client.post(JOBS_URL, json=make_payload(recipient_count=3)).json()["job_id"]
    body = client.get(f"{JOBS_URL}/{job_id}").json()

    assert body["status"] == JobStatus.COMPLETED_WITH_ERRORS
    assert body["successful_count"] == 2
    assert body["failed_count"] == 1
    assert body["progress_percentage"] == 100.0
    assert body["completed_at"] is not None

    by_name = {r["name"]: r for r in body["recipients"]}
    failed = by_name["Recipient 2"]
    assert failed["status"] == RecipientStatus.FAILED
    assert "simulated rendering error" in failed["error_message"]
    assert "Traceback" not in failed["error_message"]
    assert failed["download_url"] is None
    for name in ("Recipient 1", "Recipient 3"):
        assert by_name[name]["status"] == RecipientStatus.SUCCESS
        assert client.get(by_name[name]["download_url"]).status_code == 200

    assert len(list((settings.certificate_output_dir / job_id).glob("*.pdf"))) == 2


def test_job_level_failure_marks_job_and_remaining_recipients_failed(
    session_factory, settings, monkeypatch, make_payload
):
    def broken_storage(path):
        raise OSError("disk unavailable")

    monkeypatch.setattr(file_utils, "ensure_directory", broken_storage)
    with session_factory() as db:
        job_id = job_service.create_job(db, CertificateJobCreate(**make_payload(recipient_count=2))).id

    job_service.process_job(job_id, session_factory, settings.certificate_output_dir)

    with session_factory() as db:
        job = job_service.get_job(db, job_id)
        assert job.status == JobStatus.FAILED
        assert job.completed_at is not None
        assert all(r.status == RecipientStatus.FAILED for r in job.recipients)
        assert all(r.error_message for r in job.recipients)


def test_process_job_is_callable_directly_and_idempotent(session_factory, settings, make_payload):
    with session_factory() as db:
        job_id = job_service.create_job(db, CertificateJobCreate(**make_payload(recipient_count=2))).id

    job_service.process_job(job_id, session_factory, settings.certificate_output_dir)
    # A second call must not reprocess an already finished job.
    job_service.process_job(job_id, session_factory, settings.certificate_output_dir)

    with session_factory() as db:
        job = job_service.get_job(db, job_id)
        assert job.status == JobStatus.COMPLETED
        progress = job_service.calculate_progress(job.recipients)
        assert (progress.successful, progress.failed, progress.percentage) == (2, 0, 100.0)


def test_process_job_with_unknown_id_is_a_no_op(session_factory, settings):
    job_service.process_job("does-not-exist", session_factory, settings.certificate_output_dir)
