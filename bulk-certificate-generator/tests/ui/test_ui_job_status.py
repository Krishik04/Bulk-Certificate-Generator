"""UI: job status and progress display, including live updates while a job is running."""

from sqlalchemy import select

from playwright.sync_api import expect

from app.enums import JobStatus, RecipientStatus
from app.models import CertificateJob, CertificateRecipient, utc_now
from app.schemas import CertificateJobCreate
from app.services import job_service
from tests.ui.helpers import SAMPLE_RECIPIENTS


def test_completed_job_shows_full_progress(ui):
    ui.open()
    ui.submit_job(SAMPLE_RECIPIENTS)
    ui.wait_for_job_status("COMPLETED")

    expect(ui.progress_label).to_contain_text("3 of 3 processed")
    expect(ui.progress_label).to_contain_text("100%")
    expect(ui.stat("Total")).to_have_text("3")
    expect(ui.stat("Succeeded")).to_have_text("3")
    expect(ui.stat("Failed")).to_have_text("0")
    expect(ui.stat("Processing")).to_have_text("0")
    expect(ui.stat("Pending")).to_have_text("0")
    expect(ui.polling_note).to_have_text("Job finished.")
    expect(ui.job_view).to_contain_text("Finished")


def test_in_progress_job_updates_live_until_finished(ui, app_session_factory, make_payload):
    # Arrange a job frozen mid-way through processing (no background task runs for it).
    with app_session_factory() as db:
        job = job_service.create_job(db, CertificateJobCreate(**make_payload(recipient_count=4)))
        recipients = db.scalars(
            select(CertificateRecipient)
            .where(CertificateRecipient.job_id == job.id)
            .order_by(CertificateRecipient.position)
        ).all()
        job.status = JobStatus.PROCESSING
        recipients[0].status = RecipientStatus.SUCCESS
        recipients[1].status = RecipientStatus.FAILED
        recipients[1].error_message = "Certificate generation failed: RuntimeError: boom"
        recipients[2].status = RecipientStatus.PROCESSING
        db.commit()
        job_id = job.id

    ui.open(job_id)

    ui.wait_for_job_status("PROCESSING")
    expect(ui.progress_label).to_contain_text("2 of 4 processed")
    expect(ui.progress_label).to_contain_text("50%")
    expect(ui.stat("Succeeded")).to_have_text("1")
    expect(ui.stat("Failed")).to_have_text("1")
    expect(ui.stat("Processing")).to_have_text("1")
    expect(ui.stat("Pending")).to_have_text("1")
    expect(ui.polling_note).to_have_text("Updating every second…")
    expect(ui.result_row("Recipient 3")).to_contain_text("Generating…")
    expect(ui.result_row("Recipient 4")).to_contain_text("Waiting…")

    # Finish the job in the database; the page must pick it up by polling.
    with app_session_factory() as db:
        for recipient in db.scalars(
            select(CertificateRecipient).where(
                CertificateRecipient.job_id == job_id,
                CertificateRecipient.status.in_([RecipientStatus.PENDING, RecipientStatus.PROCESSING]),
            )
        ):
            recipient.status = RecipientStatus.SUCCESS
        finished_job = db.get(CertificateJob, job_id)
        finished_job.status = JobStatus.COMPLETED_WITH_ERRORS
        finished_job.completed_at = utc_now()
        db.commit()

    ui.wait_for_job_status("COMPLETED_WITH_ERRORS")
    expect(ui.progress_label).to_contain_text("4 of 4 processed")
    expect(ui.stat("Succeeded")).to_have_text("3")
    expect(ui.polling_note).to_have_text("Job finished.")


def test_unknown_job_id_shows_not_found(ui):
    ui.open()
    ui.track("00000000-0000-0000-0000-000000000000")

    expect(ui.job_view).to_contain_text("No job found with ID 00000000-0000-0000-0000-000000000000.")
