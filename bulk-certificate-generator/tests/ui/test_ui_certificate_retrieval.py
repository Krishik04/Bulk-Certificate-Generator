"""UI: retrieving generated certificates (single download, download all, tracking an existing job)."""

from playwright.sync_api import expect

from tests.ui.helpers import SAMPLE_RECIPIENTS


def _wait_until(page, condition, timeout_ms: int = 10_000) -> None:
    """Let the browser process events until condition() is true (fails after timeout_ms)."""
    waited = 0
    while not condition():
        assert waited < timeout_ms, "Timed out waiting for condition"
        page.wait_for_timeout(100)
        waited += 100


def test_download_single_certificate(ui, page):
    ui.open()
    ui.submit_job(SAMPLE_RECIPIENTS[:1])
    ui.wait_for_job_status("COMPLETED")

    with page.expect_download() as download_info:
        ui.result_row("Sai Krishik").get_by_role("link", name="Download PDF").click()
    download = download_info.value

    assert download.failure() is None
    assert download.suggested_filename == "certificate-sai-krishik.pdf"
    with open(download.path(), "rb") as pdf:
        assert pdf.read(5) == b"%PDF-"


def test_download_all_fetches_every_successful_certificate(ui, page):
    ui.open()
    ui.submit_job(SAMPLE_RECIPIENTS)
    ui.wait_for_job_status("COMPLETED")

    downloads = []
    page.on("download", lambda download: downloads.append(download))
    ui.download_all_button.click()

    # The button shows progress while the downloads are triggered one by one.
    expect(ui.download_all_button).to_contain_text("Downloading")
    _wait_until(page, lambda: len(downloads) == 3)
    expect(ui.download_all_button).to_have_text("Download all (3)")
    assert sorted(d.suggested_filename for d in downloads) == [
        "certificate-ananya-iyer.pdf",
        "certificate-rahul-sharma.pdf",
        "certificate-sai-krishik.pdf",
    ]


def test_existing_job_can_be_tracked_by_pasting_its_id(ui, page, browser, live_server):
    ui.open()
    job_id = ui.submit_job(SAMPLE_RECIPIENTS[:2])
    ui.wait_for_job_status("COMPLETED")

    # A different user (fresh browser context, no saved state) pastes the job ID.
    other_context = browser.new_context(base_url=live_server)
    try:
        other_page = other_context.new_page()
        other_page.goto("/")
        expect(other_page.locator("#job-view")).to_contain_text("Submit a job or paste a job ID")
        other_page.fill("#track-id", job_id)
        other_page.click("#track-form button")
        expect(other_page.locator("#job-view .job-head .badge")).to_have_text("COMPLETED")
        expect(other_page.get_by_role("link", name="Download PDF")).to_have_count(2)
    finally:
        other_context.close()


def test_reloading_the_page_resumes_tracking(ui, page):
    ui.open()
    job_id = ui.submit_job(SAMPLE_RECIPIENTS[:1])
    ui.wait_for_job_status("COMPLETED")

    page.reload()

    expect(page.locator("#track-id")).to_have_value(job_id)
    ui.wait_for_job_status("COMPLETED")
    expect(page.get_by_role("link", name="Download PDF")).to_have_count(1)
