"""UI: creating a certificate generation job."""

from playwright.sync_api import expect

from tests.ui.helpers import SAMPLE_RECIPIENTS


def test_submitting_the_form_creates_a_job(ui, page):
    ui.open()
    job_id = ui.submit_job(SAMPLE_RECIPIENTS[:2], event_name="Python Bootcamp 2026")

    expect(ui.form_message).to_have_text(
        "Job accepted: 2 certificates queued. Tracking progress on the right."
    )
    expect(page.locator("#track-id")).to_have_value(job_id)
    expect(ui.job_view.locator("h3")).to_have_text("Python Bootcamp 2026")

    # The job really exists in the API with the data typed into the form.
    job = page.request.get(f"/api/v1/certificate-jobs/{job_id}").json()
    assert job["organization_name"] == "ABC Technologies"
    assert job["issue_date"] == "2026-10-09"
    assert [(r["name"], r["email"], r["course_name"]) for r in job["recipients"]] == [
        (r.name, r.email, r.course_name) for r in SAMPLE_RECIPIENTS[:2]
    ]


def test_recipient_counter_follows_typing_adding_and_removing_rows(ui, page):
    ui.open()
    expect(ui.recipient_count).to_have_text("0 recipients")

    ui.add_recipients(SAMPLE_RECIPIENTS)
    expect(ui.recipient_count).to_have_text("3 recipients")

    ui.recipient_row(1).get_by_role("button", name="Remove recipient").click()
    expect(ui.recipient_count).to_have_text("2 recipients")
    expect(ui.recipient_input(1, "name")).to_have_value("Ananya Iyer")


def test_sample_data_button_fills_a_submittable_job(ui, page):
    ui.open()
    page.click("#load-sample")
    expect(ui.recipient_count).to_have_text("3 recipients")

    page.click("#submit-btn")

    expect(ui.form_message).to_contain_text("Job accepted: 3 certificates queued")
    ui.wait_for_job_status("COMPLETED")


def test_pasted_csv_with_header_in_any_order_and_quoted_fields(ui, page):
    ui.open()
    ui.fill_job_details()
    ui.paste_csv(
        'email,course,name\n'
        'krishik@example.com,"Python, Advanced",Sai Krishik\n'
        'rahul@example.com,Backend Development,Rahul Sharma\n'
    )

    expect(page.locator("#paste-result")).to_have_text("Added 2 recipients from pasted text.")
    expect(ui.recipient_count).to_have_text("2 recipients")
    expect(ui.recipient_input(0, "name")).to_have_value("Sai Krishik")
    expect(ui.recipient_input(0, "course_name")).to_have_value("Python, Advanced")
    expect(ui.recipient_input(1, "email")).to_have_value("rahul@example.com")

    ui.submit()
    expect(ui.form_message).to_contain_text("Job accepted: 2 certificates queued")


def test_uploaded_csv_file_without_header(ui, page):
    ui.open()
    ui.fill_job_details()
    page.set_input_files(
        "#csv-file",
        files=[{
            "name": "recipients.csv",
            "mimeType": "text/csv",
            "buffer": b"Sai Krishik,krishik@example.com,Python Programming\r\n"
                      b"Rahul Sharma,rahul@example.com,Backend Development\r\n",
        }],
    )

    expect(page.locator("#paste-result")).to_have_text("Added 2 recipients from recipients.csv.")
    expect(ui.recipient_input(1, "course_name")).to_have_value("Backend Development")

    ui.submit()
    expect(ui.form_message).to_contain_text("Job accepted: 2 certificates queued")
