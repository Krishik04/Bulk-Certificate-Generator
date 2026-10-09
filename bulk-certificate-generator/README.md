# Bulk Certificate Generator API

A FastAPI backend that accepts a batch of recipients, generates a PDF certificate for each one in the background, lets clients track the job's progress, and serves each finished certificate as a download.

## Contents

- [Overview](#overview)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Running the API](#running-the-api)
- [Web UI](#web-ui)
- [Using the API](#using-the-api)
- [Running the tests](#running-the-tests)
- [Database schema](#database-schema)
- [Background processing](#background-processing)
- [Progress and completion semantics](#progress-and-completion-semantics)
- [Failure handling](#failure-handling)
- [Design decisions and trade-offs](#design-decisions-and-trade-offs)
- [Limitations and future improvements](#limitations-and-future-improvements)

## Overview

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| `POST` | `/api/v1/certificate-jobs` | Submit a batch (1–500 recipients) | `202 Accepted` |
| `GET` | `/api/v1/certificate-jobs` | List recent jobs (paginated) | `200 OK` |
| `GET` | `/api/v1/certificate-jobs/{job_id}` | Job status, counters, per-recipient details | `200 OK` |
| `GET` | `/api/v1/certificates/{recipient_id}` | Download one certificate PDF | `200 OK` |
| `GET` | `/health` | Liveness check | `200 OK` |
| `GET` | `/` | Single-page web UI (not part of the API schema) | `200 OK` |

Error codes: `422` for invalid input, `404` for an unknown job, recipient or missing file, and `409` when a certificate is not downloadable yet (pending, processing or failed).

## Technology stack

- **Python 3.11+** (developed and tested on 3.13)
- **FastAPI**: web framework, dependency injection, OpenAPI docs, BackgroundTasks
- **Uvicorn**: ASGI server
- **SQLAlchemy 2.x** with **SQLite**: ORM and relational storage
- **Pydantic v2** / **pydantic-settings**: request/response validation and environment-based config
- **email-validator**: backs Pydantic's `EmailStr`
- **ReportLab**: PDF rendering
- **Pytest** with FastAPI `TestClient` (**httpx2**) and **pypdf**: tests; pypdf checks that generated PDFs open and contain the right text
- **Playwright**: end-to-end tests of the web UI in headless Chrome

## Project structure

```text
bulk-certificate-generator/
├── app/
│   ├── main.py                    # App factory (create_app), lifespan, global error handler
│   ├── config.py                  # Settings loaded from env vars / .env
│   ├── database.py                # Engine, session factory, get_db dependency, init_db
│   ├── models.py                  # SQLAlchemy models: CertificateJob, CertificateRecipient
│   ├── schemas.py                 # Pydantic request/response schemas
│   ├── enums.py                   # JobStatus, RecipientStatus
│   ├── static/
│   │   └── index.html             # Single-file web UI served at /
│   ├── api/
│   │   └── routes.py              # APIRouter with the four endpoints (thin)
│   ├── services/
│   │   ├── certificate_service.py # ReportLab PDF template
│   │   └── job_service.py         # Job creation, batch processing, progress, queries
│   └── utils/
│       └── file_utils.py          # Storage keys, safe path resolution, download filenames
├── tests/
│   ├── conftest.py                # Isolated temp DB + temp certificate dir per test
│   ├── test_job_creation.py
│   ├── test_validation.py
│   ├── test_certificate_generation.py
│   ├── test_job_status.py
│   ├── test_failure_handling.py
│   ├── test_certificate_download.py
│   ├── test_web_ui.py
│   └── ui/                        # End-to-end browser tests of the web UI (Playwright)
│       ├── conftest.py            # Live Uvicorn server + headless browser per test
│       ├── helpers.py             # Page object: user actions on the UI
│       ├── test_ui_job_creation.py
│       ├── test_ui_validation.py
│       ├── test_ui_certificate_generation.py
│       ├── test_ui_job_status.py
│       ├── test_ui_failure_handling.py
│       └── test_ui_certificate_retrieval.py
├── generated_certificates/        # Default PDF output folder (git-ignored)
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

## Setup

### Prerequisites

- Python 3.11 or newer (`python3 --version` / `py --version`)
- pip

### Create a virtual environment

macOS / Linux:

```bash
cd bulk-certificate-generator
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
cd bulk-certificate-generator
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

Windows (cmd.exe):

```bat
cd bulk-certificate-generator
py -3 -m venv .venv
.venv\Scripts\activate.bat
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment variables (optional)

Every setting has a working default. To change one, copy the example file and edit it:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///<project>/certificates.db` | SQLAlchemy database URL |
| `CERTIFICATE_OUTPUT_DIR` | `generated_certificates` | PDF output folder; relative paths resolve against the project root |
| `MAX_RECIPIENTS_PER_JOB` | `500` | Larger batches are rejected with `422` |
| `LOG_LEVEL` | `INFO` | Python logging level |

Real environment variables take precedence over values in `.env`.

## Running the API

```bash
uvicorn app.main:app --reload
```

The server listens on `http://127.0.0.1:8000`, and the web UI is at `http://127.0.0.1:8000/`. On startup it creates the SQLite tables and the output folder if they don't exist yet.

- Swagger UI: **http://127.0.0.1:8000/docs**
- ReDoc: http://127.0.0.1:8000/redoc
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

The Swagger UI shows every endpoint with its request schema, response schemas and status codes, and you can send requests from it with "Try it out".

## Web UI

With the server running, open **http://127.0.0.1:8000/** to use the browser interface. It is one self-contained HTML file (`app/static/index.html`) with no external libraries, served by FastAPI from the same origin as the API, so no CORS setup is needed.

- **Create a job.** Enter the event, organization and issue date, then add recipients:
  - type them into the table;
  - paste CSV; or
  - upload a `.csv` file. A header row such as `name,email,course_name` is optional. When a header is present, columns are matched by name in any order, and quoted fields are supported.
- **Validation feedback.** If the API returns `422`, every error is listed and the offending field is highlighted, for example *Row 2 email: value is not a valid email address*.
- **Live progress.** After you submit, the job is polled every second until it finishes. The page shows a progress bar (green for succeeded, red for failed), the counters, and every recipient's status, with error messages for failures.
- **Certificates.** Each successful recipient gets a *Download PDF* link, and *Download all* fetches every successful certificate. Your browser may ask once for permission to download multiple files.
- **Track any job.** Paste a job ID into the *Job progress* box. The tracked job is stored in the URL (`#job=<id>`), so a page refresh resumes tracking. To list all jobs, use `GET /api/v1/certificate-jobs`.
- The page follows the system light or dark theme and works on phone-width screens.

## Using the API

The examples below use `curl` on macOS/Linux. On Windows, use `curl.exe` and put the JSON in a file (`-d @request.json`).

### 1. Submit a bulk certificate job

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/certificate-jobs \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "Python Bootcamp 2026",
    "organization_name": "ABC Technologies",
    "issue_date": "2026-10-09",
    "recipients": [
      {"name": "Sai Krishik",  "email": "krishik@example.com", "course_name": "Python Programming"},
      {"name": "Rahul Sharma", "email": "rahul@example.com",   "course_name": "Backend Development"}
    ]
  }'
```

Response: `202 Accepted`

```json
{
  "job_id": "74aba260-1d45-46bb-81d9-c7c67347ba7b",
  "status": "PENDING",
  "total_recipients": 2,
  "created_at": "2026-10-09T04:40:39.119923Z",
  "status_url": "http://127.0.0.1:8000/api/v1/certificate-jobs/74aba260-1d45-46bb-81d9-c7c67347ba7b"
}
```

Invalid input is rejected with `422` and a list of field errors:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/certificate-jobs \
  -H "Content-Type: application/json" \
  -d '{"event_name":"X","organization_name":"Y","issue_date":"2026-02-30",
       "recipients":[{"name":"A","email":"bad","course_name":"C"}]}'
```

```json
{
  "detail": [
    {"type": "date_from_datetime_parsing", "loc": ["body", "issue_date"],
     "msg": "Input should be a valid date or datetime, day value is outside expected range", "...": "..."},
    {"type": "value_error", "loc": ["body", "recipients", 0, "email"],
     "msg": "value is not a valid email address: An email address must have an @-sign.", "...": "..."}
  ]
}
```

### 2. Check job progress

```bash
curl -s http://127.0.0.1:8000/api/v1/certificate-jobs/74aba260-1d45-46bb-81d9-c7c67347ba7b
```

Response: `200 OK`

```json
{
  "job_id": "74aba260-1d45-46bb-81d9-c7c67347ba7b",
  "event_name": "Python Bootcamp 2026",
  "organization_name": "ABC Technologies",
  "issue_date": "2026-10-09",
  "status": "COMPLETED",
  "total_recipients": 2,
  "successful_count": 2,
  "failed_count": 0,
  "pending_count": 0,
  "processing_count": 0,
  "progress_percentage": 100.0,
  "created_at": "2026-10-09T04:40:39.119923Z",
  "completed_at": "2026-10-09T04:40:39.133987Z",
  "recipients": [
    {
      "id": "e1fba046-a42b-4c49-9018-69a0d2c3bb1b",
      "name": "Sai Krishik",
      "email": "krishik@example.com",
      "course_name": "Python Programming",
      "status": "SUCCESS",
      "error_message": null,
      "download_url": "http://127.0.0.1:8000/api/v1/certificates/e1fba046-a42b-4c49-9018-69a0d2c3bb1b",
      "completed_at": "2026-10-09T04:40:39.128473Z"
    },
    {
      "id": "1629a2a2-affe-4fb0-be02-b1ac0cdd7a03",
      "name": "Rahul Sharma",
      "email": "rahul@example.com",
      "course_name": "Backend Development",
      "status": "SUCCESS",
      "error_message": null,
      "download_url": "http://127.0.0.1:8000/api/v1/certificates/1629a2a2-affe-4fb0-be02-b1ac0cdd7a03",
      "completed_at": "2026-10-09T04:40:39.131868Z"
    }
  ]
}
```

A recipient that failed has `"status": "FAILED"`, `"download_url": null` and a readable `error_message`, for example `"Certificate generation failed: RuntimeError: ..."`. An unknown job ID returns `404 {"detail": "Certificate job not found"}`.

### 3. Download a certificate

```bash
curl -OJ http://127.0.0.1:8000/api/v1/certificates/e1fba046-a42b-4c49-9018-69a0d2c3bb1b
# saves certificate-sai-krishik.pdf
```

The response carries `Content-Type: application/pdf` and `Content-Disposition: attachment; filename="certificate-sai-krishik.pdf"`.

| Situation | Response |
|---|---|
| Certificate generated | `200` with the PDF |
| Unknown recipient ID | `404 {"detail": "Recipient not found"}` |
| Status is `PENDING`, `PROCESSING` or `FAILED` | `409 {"detail": "Certificate is not available for download (status: PENDING)"}` |
| Database says `SUCCESS` but the file was deleted from disk | `404 {"detail": "Certificate file not found"}` (and the error is logged on the server) |

### 4. List jobs

```bash
curl -s "http://127.0.0.1:8000/api/v1/certificate-jobs?limit=20&offset=0"
```

```json
{
  "items": [
    {
      "job_id": "74aba260-1d45-46bb-81d9-c7c67347ba7b",
      "event_name": "Python Bootcamp 2026",
      "organization_name": "ABC Technologies",
      "status": "COMPLETED",
      "total_recipients": 2,
      "successful_count": 2,
      "failed_count": 0,
      "created_at": "2026-10-09T04:40:39.119923Z",
      "completed_at": "2026-10-09T04:40:39.133987Z",
      "status_url": "http://127.0.0.1:8000/api/v1/certificate-jobs/74aba260-1d45-46bb-81d9-c7c67347ba7b"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

Jobs are returned newest first. `limit` must be between 1 and 100 (default 20) and `offset` must be 0 or more.

## Running the tests

```bash
pytest                                        # all tests
pytest -v                                     # verbose
pytest tests/test_failure_handling.py         # one file
pytest tests/test_validation.py::test_rejects_invalid_email   # one test
```

```bash
pytest -m "not ui"                            # API tests only (no browser needed)
pytest tests/ui                               # browser tests of the web UI only
```

How the tests stay isolated and deterministic:

- **Isolated data.** Each test builds its own app with `create_app(settings)`, pointing at a SQLite file and a certificate folder inside pytest's `tmp_path`. Your development database and `generated_certificates/` are never touched, and the suite can be run any number of times.
- **No sleeps.** Starlette's `TestClient` runs `BackgroundTasks` synchronously before `client.post()` returns. When a test asks for the job status, processing has already finished.
- **Simulated failures.** `monkeypatch` replaces `certificate_service.generate_certificate_pdf` so that it fails for one named recipient, or replaces `file_utils.ensure_directory` to simulate a storage failure for the whole job.
- **In-progress states.** For pending or processing states, tests call `job_service.create_job` directly (no background run) and set the statuses in the database.

### Web UI tests (`tests/ui/`)

These tests drive the real page (`app/static/index.html`) in a headless browser, the way a user would. Each test:

- starts a real Uvicorn server with the app in a background thread, on a free port, with its own temporary database and certificate folder;
- opens the page in a fresh browser context with clean storage and downloads enabled;
- fails if any JavaScript error happens on the page.

They use the Google Chrome or Microsoft Edge already installed on your machine. If neither is installed, run `playwright install chromium` once. If no browser can be launched, the UI tests are skipped instead of failing. The server runs in the same process as the tests, so `monkeypatch` can still simulate certificate failures. Waiting uses Playwright's auto-retrying `expect` assertions, never fixed sleeps.

| Area | File | What the browser test does |
|---|---|---|
| Creating a job | `test_ui_job_creation.py` | Fills the form and submits it, then checks the success message, that the new job is tracked, and the stored data. Also covers the recipient counter, the sample data button, pasting CSV (header in any order, quoted commas) and uploading a CSV file |
| Input validation | `test_ui_validation.py` | Submits an invalid email, an empty recipient list, a blank event or organization, a missing date, a missing course, and 501 recipients. Checks the error is shown, the right field is highlighted, the highlight clears when the field is fixed, and no job is created |
| Certificate generation | `test_ui_certificate_generation.py` | Checks one valid PDF per recipient on disk, that the downloaded PDF contains the name, course, event, organization and date from the form, and a download link for every recipient |
| Job status and progress | `test_ui_job_status.py` | Checks the counters and 100% for a finished job, follows a job that is part-way through (50%, "Generating…", "Waiting…") until it finishes, and checks the unknown-job message |
| A certificate failing | `test_ui_failure_handling.py` | With one recipient's PDF set to fail: the job shows COMPLETED WITH ERRORS, the failed row shows its error and has no link, the others can be downloaded, and the failed certificate returns 409. Also covers a whole-job failure message |
| Getting certificates | `test_ui_certificate_retrieval.py` | Downloads a single PDF (checking its file name and content), uses "Download all" for 3 files, tracks a job by pasting its ID in a new session, and resumes tracking after a page reload |

What the API tests cover: valid job creation (202, persistence, background completion); validation (invalid email, empty list, missing fields, invalid dates, blank strings, more than 500 recipients, a configurable maximum); PDF validity (opened with pypdf and its text checked); progress counters for finished and partly finished jobs; one recipient failing while the rest succeed; job-level failure; download success; 409 for pending, processing and failed certificates; 404 for unknown jobs, unknown recipients and missing files; path-traversal protection; pagination.

## Database schema

```text
certificate_jobs                          certificate_recipients
─────────────────                         ──────────────────────
id              VARCHAR(36) PK (UUID)  ◄──┐ id               VARCHAR(36) PK (UUID)
event_name      VARCHAR(200)              └─ job_id           VARCHAR(36) FK → certificate_jobs.id  [index]
organization_name VARCHAR(200)              position         INTEGER  (submission order)
issue_date      DATE                        name             VARCHAR(200)
status          VARCHAR(32)  [index]        email            VARCHAR(320)
created_at      DATETIME     [index]        course_name      VARCHAR(200)
completed_at    DATETIME NULL               status           VARCHAR(32)  [index]
                                            certificate_path VARCHAR(500) NULL  (storage key, not an absolute path)
                                            error_message    TEXT NULL
                                            created_at       DATETIME
                                            completed_at     DATETIME NULL
```

- **One-to-many.** A job has many recipients (`CertificateJob.recipients` ↔ `CertificateRecipient.job`). The relationship cascades deletes and is ordered by `position`.
- **UUID primary keys** are generated by the server. They are hard to guess, and they also serve as safe file names.
- **Indexes** cover `job_id`, which every per-job query filters on; recipient and job `status`; and job `created_at`, which the list endpoint sorts on.
- **Enums** are stored as strings (`native_enum=False`), so the schema works on SQLite and moves to other databases unchanged.
- **Timestamps** are stored in UTC. A small `UTCDateTime` type puts the timezone back when reading, because SQLite drops it, so the API always returns times like `...Z`.
- **PDFs live on disk.** The database stores only a storage key relative to `CERTIFICATE_OUTPUT_DIR`, such as `<job_id>/<recipient_id>.pdf`.
- **Table creation.** `Base.metadata.create_all` runs in the app's lifespan hook, which is fine for local development. A production deployment would use Alembic migrations instead.

## Background processing

Request flow:

```text
Client ── POST /certificate-jobs ──► routes.create_certificate_job
                                        │ 1. Pydantic validates the body (422 on error)
                                        │ 2. job_service.create_job → INSERT job + recipients, COMMIT
                                        │ 3. background_tasks.add_task(job_service.process_job, ...)
Client ◄── 202 {job_id, status_url} ────┘
                                        ▼ (after the response has been sent, same process)
                         job_service.process_job(job_id, session_factory, output_dir)
                           opens its OWN session
                           job → PROCESSING, COMMIT
                           for each PENDING recipient (in submission order):
                               recipient → PROCESSING, COMMIT
                               certificate_service.generate_certificate_pdf(...)
                               recipient → SUCCESS (+ path) or FAILED (+ error), COMMIT
                           job → COMPLETED / COMPLETED_WITH_ERRORS, COMMIT
Client ── GET /certificate-jobs/{id} ──► reads the committed rows and computes progress
```

- **Separate sessions.** API requests get a session from the `get_db` dependency, which closes it after the request. The background task opens its own session from the same `sessionmaker`. A request-scoped session must never be handed to a background task, because it is closed by the time the task runs.
- **Short transactions.** Every status change is committed at once, so no transaction stays open for the whole batch, the SQLite write lock is held only briefly, and the status endpoint sees live progress.
- **Concurrency.** `process_job` is a plain `def`, so FastAPI runs it in its threadpool and it doesn't block the event loop. The SQLite engine is created with `check_same_thread=False` for this reason.
- **Idempotent.** `process_job` does nothing unless the job is `PENDING`, so a duplicate call cannot regenerate certificates.

### Limitation of FastAPI BackgroundTasks (important)

`BackgroundTasks` runs work **inside the web server process** after the response has been sent. It is **not a durable job queue**:

- If the server stops, restarts or crashes during a batch (including `--reload` on a code change), that batch is interrupted. Its job stays in `PROCESSING` and its remaining recipients stay `PENDING` or `PROCESSING`. Nothing resumes them automatically.
- There are no automatic retries, no scheduling and no spreading of work across machines.
- PDF generation uses CPU in the same process that answers API requests.

This is an acceptable trade-off for an assignment that runs on a laptop. The [future improvements](#limitations-and-future-improvements) section explains how to make processing durable.

## Progress and completion semantics

- `progress_percentage = (successful_count + failed_count) / total_recipients × 100`, rounded to 2 decimals. It measures how much of the batch has been **processed**, not how much succeeded. A job whose certificates all failed is still at 100% progress.
- All counters are calculated from a single read of the job's persisted recipient rows, so they always add up: `successful + failed + pending + processing = total`.
- A job is **complete** when every recipient has reached a final state (`SUCCESS` or `FAILED`). At that point the job gets `completed_at` and a final status:

| Final job status | Meaning |
|---|---|
| `COMPLETED` | Every certificate was generated |
| `COMPLETED_WITH_ERRORS` | Processing finished but at least one recipient failed (including the case where all failed) |
| `FAILED` | An unrecoverable job-level error (such as storage or the database being unavailable) stopped processing; all unfinished recipients are marked `FAILED` |

`PENDING` means the job is queued but not started. `PROCESSING` means it is in progress.

## Failure handling

- **Per-recipient isolation.** Each PDF is generated inside its own `try/except`. An exception marks only that recipient `FAILED`, with a short message such as `"Certificate generation failed: RuntimeError: ..."`, and the loop moves on to the next recipient.
- **Atomic file writes.** A PDF is written to a `.tmp` file and then renamed with `os.replace`. A failure partway through never leaves a half-written or corrupt PDF behind.
- **Job-level failures.** Any other exception, such as the output folder or the database being unavailable, is caught at the top of `process_job`. The job is marked `FAILED` and every unfinished recipient is closed out.
- **No stack traces sent to clients.** Full tracebacks go to the server log via `logger.exception`. API clients receive structured `detail` messages only, and a global exception handler turns anything unexpected into `500 {"detail": "Internal server error"}`.
- **Safe file serving.** The download endpoint looks up the stored key, resolves it, and checks that the path is inside `CERTIFICATE_OUTPUT_DIR` (path-traversal protection). Server paths never appear in responses, and the download file name is an ASCII slug of the recipient's name.

## Design decisions and trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| App factory `create_app(settings)` | Tests build a fully isolated app (temp DB and folder) without patching globals | Slightly more code than a single module-level `app` |
| Thin routes, logic in `services/` | `job_service.process_job` can be called and tested without HTTP | One more layer to navigate |
| Pydantic schemas separate from ORM models | The API contract can change without changing the database, and internal fields like `position` and `certificate_path` stay hidden | Mapping code in the routes |
| Batch limit checked in the route instead of a fixed schema constant | It can be configured through `MAX_RECIPIENTS_PER_JOB` and gives the same `422` error format | `/docs` does not show the maximum as a schema constraint |
| Storage key in the DB, not an absolute path | The output folder can be moved; this is also the shape needed to switch to object storage later | The key has to be resolved on every download |
| Server-generated UUID file names | Unique, collision-free, and not open to path injection | Needs a separate, friendly download file name |
| `202 Accepted` + polling | The standard pattern for long-running work | Clients have to poll |
| Status counters calculated on read | Always consistent with the stored rows; no counter columns that can drift | O(recipients) per status call, which is fine up to 500 |
| SQLite + `create_all` | Nothing to install; runs on any laptop | Writes from many processes are serialized; no migrations |

## Limitations and future improvements

Current limitations:

1. **Processing is not durable** (see above). Interrupted jobs stay in `PROCESSING` until someone intervenes.
2. **Throughput.** Recipients are processed one after another inside the web process. 500 certificates take a few seconds, but large volumes would compete with API traffic.
3. **Fonts.** The built-in ReportLab fonts (Helvetica, Times) cover Latin-1 only, so names in non-Latin scripts render incorrectly.
4. **No authentication.** Anyone who has a recipient ID can download that certificate. UUIDs are hard to guess, but they are not an access control.
5. **SQLite** is not suited to many writers working at once or to multiple server instances.
6. **No retention policy**, so PDFs and jobs are kept forever.

Possible improvements:

- Move processing to a durable queue (Celery or RQ with Redis, Dramatiq, or a cloud queue) with retries and backoff. At minimum, add a startup task that marks jobs left in `PROCESSING` as `FAILED` or puts them back in the queue.
- Add `POST /certificate-jobs/{id}/retry` to regenerate only the failed recipients.
- Use PostgreSQL with Alembic migrations.
- Store PDFs in S3 or other object storage and serve them through pre-signed URLs.
- Add API-key or OAuth2 authentication and per-tenant authorization.
- Register TTF fonts (for example Noto Sans) to support Unicode names, and add a configurable logo or signature image.
- Offer a ZIP download of a whole job, and webhook or email notifications when a job finishes.
- Process recipients in parallel with a bounded worker pool.
- Add structured JSON logging, metrics (jobs per minute, failure rate) and request IDs.
