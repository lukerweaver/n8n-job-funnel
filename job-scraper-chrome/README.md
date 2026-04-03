# Job Scraper Chrome Extension

Chrome extension for collecting job data from LinkedIn and Hiring Cafe, normalizing it, and posting it to the API.

The extension does more than a manual LinkedIn scrape:

- `content.js` auto-detects LinkedIn job detail pages, scrapes them, and sends normalized payloads
- `page-hook.js` runs in the page's main world on Hiring Cafe and intercepts search API responses
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

Edit `POST_ENDPOINT` in `background.js`:

```js
const POST_ENDPOINT = 'http://localhost:8000/jobs/ingest';
```

By default the extension posts to a local API on port `8000`.

If you run the stack with the repository root `docker-compose-example.yml`, the API remains available at `http://localhost:8000` and the internal UI is available at `http://localhost:8080`.

## Setup

1. Start the API.
2. If needed, update `POST_ENDPOINT` in `background.js`.
3. Open `chrome://extensions`.
4. Enable Developer mode.
5. Load the `job-scraper-chrome/` folder as an unpacked extension.

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
  "source": "linkedin",
  "source_url": "https://www.linkedin.com/jobs/view/1234567890/"
}
```

### Hiring Cafe

- Watches Hiring Cafe search pages
- Intercepts `/api/search-jobs` responses in the page context
- Normalizes result batches into API ingest payloads
- Pulls company names from `v5_processed_job_data.company_name` before falling back to older fields
- Buffers and deduplicates jobs before sending arrays to the background worker for posting

## Permissions

The manifest currently includes:

- LinkedIn host permissions
- Hiring Cafe host permissions
- a placeholder host permission for `https://your-endpoint.example.com/*`

If your API is not local, update both the endpoint in `background.js` and the relevant host permissions in `manifest.json`.

## Notes

- `background.js` always sends an array payload to the API, even for a single job.
- The popup can still be used to trigger a manual scrape on supported pages. On Hiring Cafe it reuses the most recently captured result batch.
- The API skips duplicate `job_id` values on ingest, so rescanning the same job should not reset it to `new`.
- If LinkedIn markup changes, `content.js` selectors may need updates.
- Hiring Cafe support depends on the shape of its client-side search responses and may need adjustment if their frontend changes.
