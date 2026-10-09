"""Shared fixtures.

Every test gets its own SQLite file and certificate folder under pytest's
tmp_path, so tests never touch development data and can run repeatedly.

Background processing is deterministic: Starlette's TestClient runs
BackgroundTasks synchronously after the response is produced, before
`client.post(...)` returns. No sleeps or polling are needed.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.main import create_app

JOBS_URL = "/api/v1/certificate-jobs"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        certificate_output_dir=tmp_path / "certificates",
        max_recipients_per_job=500,
        log_level="WARNING",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # The context manager runs the lifespan handler (creates tables + output folder).
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(app: FastAPI, client: TestClient) -> sessionmaker[Session]:
    return app.state.session_factory


@pytest.fixture
def make_payload() -> Callable[..., dict[str, Any]]:
    def _make_payload(recipient_count: int = 2, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_name": "Python Bootcamp 2026",
            "organization_name": "ABC Technologies",
            "issue_date": "2026-10-09",
            "recipients": [
                {
                    "name": f"Recipient {index}",
                    "email": f"recipient{index}@example.com",
                    "course_name": "Python Programming",
                }
                for index in range(1, recipient_count + 1)
            ],
        }
        payload.update(overrides)
        return payload

    return _make_payload
