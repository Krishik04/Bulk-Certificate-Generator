"""UI: submitting a job produces real, readable PDF certificates."""

from playwright.sync_api import expect
from pypdf import PdfReader

from tests.ui.helpers import SAMPLE_RECIPIENTS


def test_one_pdf_is_generated_per_recipient(ui, settings):
    ui.open()
    job_id = ui.submit_job(SAMPLE_RECIPIENTS)
    ui.wait_for_job_status("COMPLETED")

    pdf_files = sorted((settings.certificate_output_dir / job_id).glob("*.pdf"))
    assert len(pdf_files) == len(SAMPLE_RECIPIENTS)
    for path in pdf_files:
        assert path.read_bytes().startswith(b"%PDF-")
        assert len(PdfReader(path).pages) == 1


def test_downloaded_certificate_contains_the_form_data(ui, page):
    ui.open()
    ui.submit_job(
        SAMPLE_RECIPIENTS[:1],
        event_name="Data Summit 2026",
        organization_name="Acme Learning",
        issue_date="2026-03-15",
    )
    ui.wait_for_job_status("COMPLETED")

    with page.expect_download() as download_info:
        ui.result_row("Sai Krishik").get_by_role("link", name="Download PDF").click()
    text = PdfReader(download_info.value.path()).pages[0].extract_text()

    for expected in (
        "ACME LEARNING",
        "CERTIFICATE OF COMPLETION",
        "Sai Krishik",
        "Python Programming",
        "Data Summit 2026",
        "March 15, 2026",
    ):
        assert expected in text


def test_every_successful_recipient_gets_a_download_link(ui):
    ui.open()
    ui.submit_job(SAMPLE_RECIPIENTS)
    ui.wait_for_job_status("COMPLETED")

    for recipient in SAMPLE_RECIPIENTS:
        row = ui.result_row(recipient.name)
        expect(row.locator(".badge")).to_have_text("SUCCESS")
        expect(row.get_by_role("link", name="Download PDF")).to_have_count(1)
