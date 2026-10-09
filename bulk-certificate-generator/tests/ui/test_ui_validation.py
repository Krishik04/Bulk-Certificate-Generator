"""UI: input validation errors from the API are shown on the form and nothing is created."""

import re

from playwright.sync_api import expect

from tests.ui.helpers import SAMPLE_RECIPIENTS, Recipient

INVALID = re.compile(r"\binvalid\b")


def _job_count(page) -> int:
    return page.request.get("/api/v1/certificate-jobs").json()["total"]


def test_invalid_email_is_reported_on_its_row(ui, page):
    ui.open()
    ui.fill_job_details()
    ui.add_recipients([SAMPLE_RECIPIENTS[0], Recipient("Rahul Sharma", "not-an-email", "Backend")])
    ui.submit()

    expect(ui.form_message).to_contain_text("Please fix the following:")
    expect(ui.form_message).to_contain_text("Row 2 email: value is not a valid email address")
    expect(ui.recipient_input(1, "email")).to_have_class(INVALID)
    expect(ui.recipient_input(0, "email")).not_to_have_class(INVALID)
    assert _job_count(page) == 0

    # Fixing the field clears the highlight, and resubmitting succeeds.
    ui.recipient_input(1, "email").fill("rahul@example.com")
    expect(ui.recipient_input(1, "email")).not_to_have_class(INVALID)
    ui.submit()
    expect(ui.form_message).to_contain_text("Job accepted: 2 certificates queued")


def test_empty_recipient_list_is_rejected(ui, page):
    ui.open()
    ui.fill_job_details()
    ui.submit()

    expect(ui.form_message).to_contain_text("recipients: List should have at least 1 item")
    assert _job_count(page) == 0


def test_missing_event_and_organization_are_highlighted(ui, page):
    ui.open()
    ui.fill_job_details(event_name="", organization_name="   ")
    ui.add_recipients(SAMPLE_RECIPIENTS[:1])
    ui.submit()

    expect(ui.form_message).to_contain_text("event name:")
    expect(ui.form_message).to_contain_text("organization name:")
    expect(page.locator("#event_name")).to_have_class(INVALID)
    expect(page.locator("#organization_name")).to_have_class(INVALID)
    assert _job_count(page) == 0


def test_missing_issue_date_is_rejected(ui, page):
    ui.open()
    ui.fill_job_details(issue_date="")
    ui.add_recipients(SAMPLE_RECIPIENTS[:1])
    ui.submit()

    expect(ui.form_message).to_contain_text("issue date:")
    expect(page.locator("#issue_date")).to_have_class(INVALID)
    assert _job_count(page) == 0


def test_missing_recipient_fields_are_reported_per_field(ui, page):
    ui.open()
    ui.fill_job_details()
    ui.add_recipients([Recipient("Sai Krishik", "krishik@example.com", "")])
    ui.submit()

    expect(ui.form_message).to_contain_text("Row 1 course name:")
    expect(ui.recipient_input(0, "course_name")).to_have_class(INVALID)
    assert _job_count(page) == 0


def test_batch_larger_than_500_is_rejected(ui, page):
    ui.open()
    ui.fill_job_details()
    ui.paste_csv("\n".join(f"Person {i},person{i}@example.com,Course" for i in range(501)))
    expect(ui.recipient_count).to_have_text("501 recipients")

    ui.submit()

    expect(ui.form_message).to_contain_text("A job may contain at most 500 recipients (received 501)")
    assert _job_count(page) == 0
