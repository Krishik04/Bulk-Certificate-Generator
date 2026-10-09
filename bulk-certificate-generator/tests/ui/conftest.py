"""Fixtures for end-to-end tests of the web UI (app/static/index.html).

Each test gets:
- a real Uvicorn server running the app in a background thread, on a free port,
  with its own temporary SQLite database and certificate folder (from tests/conftest.py);
- a fresh browser context (clean localStorage, downloads enabled) in headless Chrome.

The server runs in-process, so tests can still use `monkeypatch` to simulate
certificate failures. Waiting is done with Playwright's auto-retrying `expect`
assertions, which poll the page until the condition holds (no fixed sleeps).

Browser: the locally installed Google Chrome or Microsoft Edge is used; if neither
is available, Playwright's bundled Chromium (`playwright install chromium`).
If no browser can be launched, the UI tests are skipped.
"""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI

from tests.ui.helpers import CertificateUI

sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")

DEFAULT_TIMEOUT_MS = 10_000


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/ui/" in item.nodeid:
            item.add_marker(pytest.mark.ui)


@pytest.fixture(scope="session")
def browser() -> Iterator["sync_api.Browser"]:
    with sync_api.sync_playwright() as playwright:
        errors = []
        for options in ({"channel": "chrome"}, {"channel": "msedge"}, {}):
            try:
                launched = playwright.chromium.launch(headless=True, **options)
                break
            except Exception as exc:  # browser not installed
                errors.append(f"{options or 'bundled chromium'}: {str(exc).splitlines()[0]}")
        else:
            pytest.skip("No Chromium-based browser available for UI tests: " + "; ".join(errors))
        yield launched
        launched.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(app: FastAPI) -> Iterator[str]:
    """Serve the test app over real HTTP so the browser can load the page and call the API."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Test server failed to start")
        time.sleep(0.02)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def page(browser: "sync_api.Browser", live_server: str) -> Iterator["sync_api.Page"]:
    context = browser.new_context(base_url=live_server, accept_downloads=True)
    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    sync_api.expect.set_options(timeout=DEFAULT_TIMEOUT_MS)
    new_page = context.new_page()
    js_errors: list[str] = []
    new_page.on("pageerror", lambda exc: js_errors.append(str(exc)))

    yield new_page

    context.close()
    assert not js_errors, f"JavaScript errors on the page: {js_errors}"


@pytest.fixture
def ui(page: "sync_api.Page") -> CertificateUI:
    return CertificateUI(page)


@pytest.fixture
def app_session_factory(app: FastAPI):
    """Database sessions for the app served by `live_server` (for arranging test data)."""
    return app.state.session_factory
