# Job Scraper Chrome Extension

Chrome extension for collecting job data from LinkedIn and Hiring Cafe, normalizing it, and posting it to the API.

The extension does more than a manual LinkedIn scrape:

- `content.js` auto-detects LinkedIn job detail pages, scrapes them, and sends normalized payloads
- `page-hook.js` runs in the page's main world on Hiring Cafe and intercepts job-shaped search responses
- `content.js` listens for captured Hiring Cafe payloads, normalizes them, and forwards them
- `popup.js` supports manual scrape/send from the extension popup
- `background.js` posts the normalized jobs to `POST /jobs/ingest`

## Files

- `manifest.json` - extension registration, permissions, and content script wiring
- `popup.html`, `popup.css`, `popup.js` - popup UI and manual scrape trigger
- `content.js` - LinkedIn scraping and Hiring Cafe payload normalization
- `page-hook.js` - fetch/XHR interception for Hiring Cafe search responses
- `background.js` - API POST bridge

## Endpoint configuration

By default the extension posts to a local API on port `8000`.

If you run the stack with the repository root `docker-compose-example.yml`, the API remains available at `http://localhost:8000` and the internal UI is available at `http://localhost:8080`.

The extension only talks to the API. It does not depend on the UX service directly.

To change the API target, open the extension popup and update App API URL. Enter the API base URL, for example `http://127.0.0.1:8000`, not the `/jobs/ingest` route. Select Test to verify the extension can reach `/health`.

## Setup

1. Start the API.
2. Open `chrome://extensions`.
3. Enable Developer mode.
4. Load the `job-scraper-chrome/` folder as an unpacked extension.
5. Open the extension popup.
6. Confirm App API URL is `http://localhost:8000`, or enter the API URL you are using.
7. Select Test.

For a user-facing walkthrough, see `../docs/chrome-extension-setup.md`.

## Testing

The extension now includes a lightweight Node-based test harness built around Vitest.

From `job-scraper-chrome/`:

```bash
npm install
npm test
```

This suite exercises the current extension scripts directly with mocked `chrome` APIs:

- `tests/content.test.js` covers LinkedIn scraping and Hiring Cafe normalization/deduping
- `tests/background.test.js` covers the background POST bridge
- `tests/popup.test.js` covers popup interaction flows
- `tests/page-hook.test.js` covers Hiring Cafe fetch/XHR interception

The tests use `jsdom` and small script-evaluation helpers rather than a bundler or extension-specific runner, so they stay close to the shipped scripts and remain cheap to maintain.

## Behavior

### LinkedIn

- Designed for LinkedIn job pages
- Extracts company, title, description, compensation hints, and apply URL
- Extracts posted date metadata when the page/API exposes it in a recognizable field
- Uses the current page URL to derive a stable external `job_id`
- Auto-sends when the LinkedIn job page changes or re-renders, with duplicate suppression to avoid rapid re-posts

Example normalized payload:

```json
{
  "job_id": "linkedin_1234567890",
  "company_name": "Example Co",
  "title": "Product Manager",
  "yearly_min_compensation": 150000,
  "yearly_max_compensation": 180000,
  "apply_url": "https://example.com/jobs/123",
  "description": "Full job description",
  "posted_at": "2026-04-10T00:00:00.000Z",
  "posted_at_raw": "3 days ago",
  "source": "linkedin",
  "source_url": "https://www.linkedin.com/jobs/view/1234567890/"
}
```

### Hiring Cafe

- Watches Hiring Cafe search pages
- Intercepts job-shaped search responses in the page context, including renamed endpoints
- Falls back to jobs embedded in Next page data when no search API request fires
- Normalizes result batches from `jobs`, `hits`, and similar payloads into API ingest payloads
- Pulls company names from `v5_processed_job_data.company_name` before falling back to older fields
- Buffers and deduplicates jobs before sending arrays to the background worker for posting

## Permissions

The manifest currently includes:

- LinkedIn host permissions
- Hiring Cafe host permissions
- local/LAN API host permissions for `http://192.168.86.2:8000/*`, `http://localhost:8000/*`, and `http://127.0.0.1:8000/*`
- a placeholder host permission for `https://your-endpoint.example.com/*`

If your API is not local, update the API URL in the popup and add the relevant host permission in `manifest.json`.

## Notes

- `background.js` always sends an array payload to the API, even for a single job.
- The popup can still be used to trigger a manual scrape on supported pages. On Hiring Cafe it reuses the most recently captured result batch.
- The API skips duplicate `job_id` values on ingest, so rescanning the same job should not reset it to `new`.
- If LinkedIn markup changes, `content.js` selectors may need updates.
- Hiring Cafe support depends on the shape of its client-side search responses and may need adjustment if their frontend changes.
