"""Page object for the web UI, so tests read as user actions rather than CSS selectors."""

import re
from dataclasses import dataclass

from playwright.sync_api import Locator, Page, expect


@dataclass(frozen=True)
class Recipient:
    name: str
    email: str
    course_name: str


SAMPLE_RECIPIENTS = [
    Recipient("Sai Krishik", "krishik@example.com", "Python Programming"),
    Recipient("Rahul Sharma", "rahul@example.com", "Backend Development"),
    Recipient("Ananya Iyer", "ananya@example.com", "Data Engineering"),
]


class CertificateUI:
    def __init__(self, page: Page) -> None:
        self.page = page

    # ---------- Navigation ----------

    def open(self, job_id: str | None = None) -> None:
        self.page.goto(f"/#job={job_id}" if job_id else "/")
        expect(self.page.locator("#health-text")).to_have_text("API online")

    # ---------- New job form ----------

    def fill_job_details(
        self,
        event_name: str = "Python Bootcamp 2026",
        organization_name: str = "ABC Technologies",
        issue_date: str = "2026-10-09",
    ) -> None:
        self.page.fill("#event_name", event_name)
        self.page.fill("#organization_name", organization_name)
        self.page.fill("#issue_date", issue_date)

    def recipient_row(self, index: int) -> Locator:
        return self.page.locator("#recipients-table tbody tr").nth(index)

    def recipient_input(self, index: int, field: str) -> Locator:
        return self.recipient_row(index).locator(f'[data-field="{field}"]')

    def add_recipients(self, recipients: list[Recipient]) -> None:
        for index, recipient in enumerate(recipients):
            if index > 0:
                self.page.click("#add-row")
            self.recipient_input(index, "name").fill(recipient.name)
            self.recipient_input(index, "email").fill(recipient.email)
            self.recipient_input(index, "course_name").fill(recipient.course_name)

    def paste_csv(self, text: str) -> None:
        if not self.page.locator("#paste-box").is_visible():
            self.page.click("#toggle-paste")
        self.page.fill("#paste-text", text)
        self.page.click("#import-paste")

    def submit(self) -> None:
        self.page.click("#submit-btn")

    def submit_job(self, recipients: list[Recipient] = SAMPLE_RECIPIENTS, **details: str) -> str:
        """Fill and submit the form; return the job ID the UI starts tracking."""
        self.fill_job_details(**details)
        self.add_recipients(recipients)
        self.submit()
        expect(self.form_message).to_contain_text("Job accepted")
        expect(self.page).to_have_url(re.compile(r"#job=[0-9a-f-]{36}$"))
        return self.page.url.rsplit("#job=", 1)[1]

    @property
    def form_message(self) -> Locator:
        return self.page.locator("#form-message")

    @property
    def recipient_count(self) -> Locator:
        return self.page.locator("#recipient-count")

    # ---------- Job progress panel ----------

    def track(self, job_id: str) -> None:
        self.page.fill("#track-id", job_id)
        self.page.click("#track-form button")

    @property
    def job_view(self) -> Locator:
        return self.page.locator("#job-view")

    @property
    def job_status(self) -> Locator:
        return self.page.locator("#job-view .job-head .badge")

    @property
    def progress_label(self) -> Locator:
        return self.page.locator("#job-view .progress-label")

    @property
    def polling_note(self) -> Locator:
        return self.page.locator("#job-view .polling")

    def stat(self, label: str) -> Locator:
        return self.page.locator("#job-view .stat").filter(has_text=label).locator(".v")

    def wait_for_job_status(self, status: str) -> None:
        expect(self.job_status).to_have_text(status.replace("_", " "))

    def result_row(self, recipient_name: str) -> Locator:
        return self.page.locator("#job-view tbody tr").filter(has_text=recipient_name)

    @property
    def download_all_button(self) -> Locator:
        # Located by position, not label: the label changes to "Downloading 1/3…" while it runs.
        return self.page.locator("#job-view .job-actions button")
