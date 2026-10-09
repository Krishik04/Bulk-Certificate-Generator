"""Helpers for safe certificate file naming and path resolution."""

import re
import unicodedata
from pathlib import Path


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_storage_key(job_id: str, recipient_id: str) -> str:
    """Relative storage key, e.g. "<job_id>/<recipient_id>.pdf".

    Both parts are server-generated UUIDs, so user input never reaches the
    filesystem path and names are guaranteed to be unique.
    """
    return f"{job_id}/{recipient_id}.pdf"


def resolve_storage_path(base_dir: Path, storage_key: str) -> Path:
    """Turn a storage key into an absolute path, refusing anything outside base_dir."""
    base = base_dir.resolve()
    candidate = (base / storage_key).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("Storage key resolves outside the certificate directory")
    return candidate


def slugify(value: str, max_length: int = 60) -> str:
    """ASCII-only, filesystem-safe slug used for download filenames."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:max_length].rstrip("-") or "recipient"


def build_download_filename(recipient_name: str) -> str:
    return f"certificate-{slugify(recipient_name)}.pdf"
