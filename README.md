# Page Pulse

A small tool that audits any URL: HTTP status, response time, page title,
meta description, H1 count, images missing alt text, and word count —
returned as JSON from an API, and rendered on a simple frontend.

Built for the Digital Heroes SDE internship task kit (Role 03/16, Task A + B).

**Live URL:** https://page-pulse-n14w.onrender.com
**Repo:** https://github.com/jailakshmi7683/Page-Pulse.git

---

## Setup

Requires Python 3.10+.

```bash
git clone <your-repo-url>
cd page-pulse
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

# run the app
python3 -m flask --app app.main run --port 5000
# open http://127.0.0.1:5000

# run the tests
pytest tests/ -v
```

### Deploying (free tier)

This is a standard Flask app with a `requirements.txt` and a `gunicorn`
entry point (`app.main:app`), so it deploys as-is to Render, Railway, or
Fly.io's free tiers. Example for Render: New Web Service → connect the
repo → build command `pip install -r requirements.txt` → start command
`gunicorn app.main:app`.

---

## API contract

### `POST /api/audit`

**Request body** (JSON):
```json
{ "url": "https://example.com" }
```

**Success — `200 OK`:**
```json
{
  "url": "https://example.com",
  "status_code": 200,
  "response_time_ms": 83,
  "title": "Example Domain",
  "meta_description": "An example page for testing.",
  "h1_count": 1,
  "images_missing_alt": 2,
  "total_images": 3,
  "word_count": 250,
  "content_type": "text/html; charset=UTF-8"
}
```

**Failure — `4xx` / `5xx`:**
```json
{ "error": "Human-readable explanation of what went wrong." }
```

| Status | Meaning                                                    |
|--------|-------------------------------------------------------------|
| `400`  | Missing or malformed URL (no `http(s)://`, no host)          |
| `422`  | URL resolved but the response wasn't HTML                    |
| `502`  | Couldn't connect (DNS failure, connection refused, etc.)     |
| `504`  | Request timed out (8s default)                               |
| `500`  | Unexpected server error (still returns JSON, never a crash)  |

### `GET /api/health`
Returns `{"status": "ok"}`. Used for uptime checks on the free-tier host.

---

## Design decisions

**1. Split parsing logic from the Flask layer (`audit.py` vs `main.py`).**
`audit.py` has no knowledge of HTTP status codes, Flask's `request`/`jsonify`,
or routing — it's a plain function that takes a URL and returns a dataclass
or raises a typed exception. This is what let Task B's tests run in
milliseconds with no server or network involved: they mock `requests.get`
directly and assert on Python objects. The Flask layer's only job is to
catch the exception types and map them to HTTP status codes.

**2. Typed exceptions instead of a generic `try/except` with string
matching.** `InvalidURLError`, `UnreachableError`, `TimeoutErrorAudit`, and
`NonHTMLError` each carry their own `status_code`. This means adding a new
failure mode later (say, a redirect-loop error) is a five-line addition —
a new exception class — rather than editing a growing if/elif chain in the
API route. It also makes the "never crash" requirement enforceable in code:
the route only has to catch `AuditError` for expected failures, plus one
broad `except Exception` as a last-resort net for anything truly
unanticipated, so the response is always JSON, never a Python traceback
page.

**3. Reject bare hostnames instead of guessing a scheme.** If a user
enters `example.com`, we return `400` and ask for `http://` or `https://`
rather than silently trying `https://example.com` on their behalf. It's a
small UX tradeoff, but auto-prepending a scheme hides real typos (e.g. a
user who meant `htps://`) behind a false-looking success case, and makes
debugging their own tool harder for them. The frontend's placeholder text
(`https://example.com`) sets the expectation upfront instead.

**Other choices worth a note:**
- **Streaming + a 5MB read cap** on the response body, so a link to a huge
  file can't hang the request or blow up memory before the content-type
  check even runs.
- **Word count strips `<script>`/`<style>` first** — otherwise minified JS
  gets counted as "page content," which would make the number meaningless.
- **Alt-text check treats `alt=""` as missing**, same as an absent `alt`
  attribute — an empty alt is only valid for genuinely decorative images,
  and this tool has no way to tell the difference, so it flags it and lets
  a human decide.

---

## AI use

Used Claude to scaffold the initial Flask/audit.py split and to write the
first pass of the test suite (happy path + the four failure cases), then
adjusted the alt-text logic (empty `alt=""` counts as missing, matching
what accessibility auditors actually flag) and tightened the word-count
regex after checking it against a page with inline SVGs. Also used it to
draft this README's API contract table, which I edited down after actually
running the endpoints to confirm the status codes it initially proposed
matched what the code returns.

---

## What I'd change with another day

The word-count and "missing alt" numbers are useful signals but not fully
reliable SEO/a11y verdicts — e.g. `role="presentation"` images are
legitimately alt-less and currently get flagged anyway. With more time I'd
add a config flag to exclude those, add a small in-memory cache (same URL
audited twice in 60s shouldn't re-fetch), and add a Playwright-based
option for JS-rendered pages, since right now anything that renders its
`<title>`/content client-side after load will under-report.
