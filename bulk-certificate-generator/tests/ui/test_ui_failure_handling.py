"""UI: one failing certificate is reported without stopping the others."""

from playwright.sync_api import expect

from app.services import certificate_service
from app.utils import file_utils
from tests.ui.helpers import SAMPLE_RECIPIENTS


def _fail_for(name_to_fail: str, monkeypatch) -> None:
    real_generate = certificate_service.generate_certificate_pdf

    def flaky_generate(data, output_path):
        if data.recipient_name == name_to_fail:
            raise RuntimeError("simulated rendering error")
        return real_generate(data, output_path)

    monkeypatch.setattr(certificate_service, "generate_certificate_pdf", flaky_generate)


def test_single_failure_is_shown_and_other_certificates_succeed(ui, page, monkeypatch):
    _fail_for("Rahul Sharma", monkeypatch)
    ui.open()
    ui.submit_job(SAMPLE_RECIPIENTS)

    ui.wait_for_job_status("COMPLETED_WITH_ERRORS")
    expect(ui.progress_label).to_contain_text("3 of 3 processed")
    expect(ui.stat("Succeeded")).to_have_text("2")
    expect(ui.stat("Failed")).to_have_text("1")

    failed_row = ui.result_row("Rahul Sharma")
    expect(failed_row.locator(".badge")).to_have_text("FAILED")
    expect(failed_row.locator(".err-text")).to_have_text(
        "Certificate generation failed: RuntimeError: simulated rendering error"
    )
    expect(failed_row.get_by_role("link", name="Download PDF")).to_have_count(0)

    for name in ("Sai Krishik", "Ananya Iyer"):
        expect(ui.result_row(name).locator(".badge")).to_have_text("SUCCESS")
        expect(ui.result_row(name).get_by_role("link", name="Download PDF")).to_have_count(1)
    expect(ui.download_all_button).to_have_text("Download all (2)")


def test_failed_certificate_cannot_be_downloaded(ui, page, monkeypatch):
    _fail_for("Rahul Sharma", monkeypatch)
    ui.open()
    job_id = ui.submit_job(SAMPLE_RECIPIENTS[:2])
    ui.wait_for_job_status("COMPLETED_WITH_ERRORS")

    job = page.request.get(f"/api/v1/certificate-jobs/{job_id}").json()
    failed = next(r for r in job["recipients"] if r["status"] == "FAILED")
    response = page.request.get(f"/api/v1/certificates/{failed['id']}")
    assert response.status == 409


def test_job_level_failure_is_explained(ui, monkeypatch):
    def broken_storage(path):
        raise OSError("disk unavailable")

    monkeypatch.setattr(file_utils, "ensure_directory", broken_storage)
    ui.open()
    ui.submit_job(SAMPLE_RECIPIENTS[:2])

    ui.wait_for_job_status("FAILED")
    expect(ui.job_view).to_contain_text("The job stopped because of a server-side error.")
    expect(ui.stat("Failed")).to_have_text("2")
    expect(ui.download_all_button).to_be_disabled()
    for recipient in SAMPLE_RECIPIENTS[:2]:
        expect(ui.result_row(recipient.name).locator(".err-text")).to_contain_text("Job aborted")
