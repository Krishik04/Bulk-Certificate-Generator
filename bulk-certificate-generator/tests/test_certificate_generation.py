from datetime import date

import pytest
from pypdf import PdfReader

from app.services.certificate_service import CertificateData, generate_certificate_pdf
from app.utils.file_utils import build_download_filename, resolve_storage_path


@pytest.fixture
def certificate_data() -> CertificateData:
    return CertificateData(
        recipient_name="Sai Krishik",
        course_name="Python Programming",
        event_name="Python Bootcamp 2026",
        organization_name="ABC Technologies",
        issue_date=date(2026, 10, 9),
    )


def test_generates_valid_pdf_with_certificate_content(tmp_path, certificate_data):
    output_path = tmp_path / "job" / "certificate.pdf"

    result = generate_certificate_pdf(certificate_data, output_path)

    assert result == output_path
    assert output_path.read_bytes().startswith(b"%PDF-")
    reader = PdfReader(output_path)  # a standard PDF parser must be able to open it
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    for expected in (
        "ABC TECHNOLOGIES",
        "CERTIFICATE OF COMPLETION",
        "Sai Krishik",
        "Python Programming",
        "Python Bootcamp 2026",
        "October 09, 2026",
        "has successfully completed the course",
    ):
        assert expected in text
    # No temporary file left behind.
    assert list(output_path.parent.iterdir()) == [output_path]


def test_long_names_still_render(tmp_path, certificate_data):
    data = CertificateData(**{**certificate_data.__dict__, "recipient_name": "A" * 200})
    output_path = generate_certificate_pdf(data, tmp_path / "long.pdf")

    assert PdfReader(output_path).pages[0].extract_text()


def test_pipeline_writes_pdf_per_recipient_with_unique_paths(client, settings, make_payload):
    job_id = client.post("/api/v1/certificate-jobs", json=make_payload(recipient_count=3)).json()["job_id"]

    pdf_files = sorted((settings.certificate_output_dir / job_id).glob("*.pdf"))
    assert len(pdf_files) == 3
    assert len({path.name for path in pdf_files}) == 3


def test_resolve_storage_path_blocks_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        resolve_storage_path(tmp_path, "../outside.pdf")
    assert resolve_storage_path(tmp_path, "job/file.pdf") == (tmp_path / "job" / "file.pdf").resolve()


def test_download_filename_is_safe():
    assert build_download_filename("Sai Krishik") == "certificate-sai-krishik.pdf"
    assert build_download_filename("../../etc/passwd") == "certificate-etc-passwd.pdf"
    assert build_download_filename("José Ñúñez") == "certificate-jose-nunez.pdf"
    assert build_download_filename("!!!") == "certificate-recipient.pdf"
