"""PDF certificate rendering with ReportLab (one fixed template)."""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)

NAVY = colors.HexColor("#1F3A5F")
GOLD = colors.HexColor("#B8860B")
TEXT_GREY = colors.HexColor("#333333")


@dataclass(frozen=True)
class CertificateData:
    recipient_name: str
    course_name: str
    event_name: str
    organization_name: str
    issue_date: date


def _fit_font_size(text: str, font_name: str, preferred_size: float, max_width: float) -> float:
    """Shrink the font until the text fits on one line (handles long names)."""
    size = preferred_size
    while size > 10 and stringWidth(text, font_name, size) > max_width:
        size -= 1
    return size


def _draw_centered(
    pdf: canvas.Canvas,
    text: str,
    y: float,
    font_name: str,
    size: float,
    color: colors.Color = TEXT_GREY,
    max_width: float = PAGE_WIDTH - 160,
) -> None:
    pdf.setFont(font_name, _fit_font_size(text, font_name, size, max_width))
    pdf.setFillColor(color)
    pdf.drawCentredString(PAGE_WIDTH / 2, y, text)


def _draw_border(pdf: canvas.Canvas) -> None:
    pdf.setStrokeColor(NAVY)
    pdf.setLineWidth(6)
    pdf.rect(20, 20, PAGE_WIDTH - 40, PAGE_HEIGHT - 40)
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(1.5)
    pdf.rect(34, 34, PAGE_WIDTH - 68, PAGE_HEIGHT - 68)


def _draw_signature_lines(pdf: canvas.Canvas, issue_date_text: str) -> None:
    line_y = 95
    pdf.setStrokeColor(TEXT_GREY)
    pdf.setLineWidth(0.8)
    for center_x, label, value in (
        (PAGE_WIDTH * 0.27, "Date of Issue", issue_date_text),
        (PAGE_WIDTH * 0.73, "Authorized Signatory", ""),
    ):
        pdf.line(center_x - 110, line_y, center_x + 110, line_y)
        pdf.setFillColor(TEXT_GREY)
        if value:
            pdf.setFont("Helvetica", 13)
            pdf.drawCentredString(center_x, line_y + 8, value)
        pdf.setFont("Helvetica-Oblique", 11)
        pdf.drawCentredString(center_x, line_y - 16, label)


def generate_certificate_pdf(data: CertificateData, output_path: Path) -> Path:
    """Render a certificate PDF to output_path.

    The PDF is written to a temporary file first and then atomically renamed,
    so a failure part-way through never leaves a corrupt file at output_path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".pdf.tmp")
    issue_date_text = data.issue_date.strftime("%B %d, %Y")

    try:
        pdf = canvas.Canvas(str(temp_path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
        pdf.setTitle(f"Certificate of Completion - {data.recipient_name}")
        pdf.setAuthor(data.organization_name)
        pdf.setSubject(data.event_name)

        _draw_border(pdf)

        _draw_centered(pdf, data.organization_name.upper(), PAGE_HEIGHT - 95, "Helvetica-Bold", 20, NAVY)
        _draw_centered(pdf, "CERTIFICATE OF COMPLETION", PAGE_HEIGHT - 150, "Times-Bold", 36, NAVY)

        pdf.setStrokeColor(GOLD)
        pdf.setLineWidth(2)
        pdf.line(PAGE_WIDTH / 2 - 120, PAGE_HEIGHT - 165, PAGE_WIDTH / 2 + 120, PAGE_HEIGHT - 165)

        _draw_centered(pdf, "This is to certify that", PAGE_HEIGHT - 210, "Helvetica-Oblique", 16)
        _draw_centered(pdf, data.recipient_name, PAGE_HEIGHT - 260, "Times-BoldItalic", 40, NAVY)
        _draw_centered(
            pdf, "has successfully completed the course", PAGE_HEIGHT - 305, "Helvetica", 16
        )
        _draw_centered(pdf, data.course_name, PAGE_HEIGHT - 340, "Helvetica-Bold", 22, GOLD)
        _draw_centered(
            pdf,
            f"as part of {data.event_name}, conducted by {data.organization_name}.",
            PAGE_HEIGHT - 378,
            "Helvetica",
            14,
        )

        _draw_signature_lines(pdf, issue_date_text)

        pdf.showPage()
        pdf.save()
        os.replace(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)

    return output_path
