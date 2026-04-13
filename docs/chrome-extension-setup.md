# Chrome Extension Setup

Use the Chrome extension to send jobs from LinkedIn and Hiring Cafe into the Job Funnel app.

## Before you start

Start the app first. With the repository root compose file, the app uses:

- UI: `http://localhost:8080`
- API: `http://localhost:8000`

The extension sends jobs to the API, not the UI.

## Install the extension

1. Open Chrome.
2. Go to `chrome://extensions`.
3. Turn on Developer mode.
4. Select Load unpacked.
5. Select the repository's `job-scraper-chrome/` folder.

## Connect it to the app

1. Open the Job Scraper extension popup.
2. Confirm App API URL is `http://localhost:8000`.
3. Select Test.
4. If the popup says it is connected, the extension can send jobs to the app.

If the app is running somewhere else, enter that API URL and select Save. The URL should be the API base URL, for example `http://127.0.0.1:8000`, not the `/jobs/ingest` route.

## Use it

LinkedIn:

1. Open a LinkedIn job page.
2. The extension attempts to send supported job pages automatically.
3. To send the visible job manually, open the extension popup and select Scrape this job.

Hiring Cafe:

1. Open Hiring Cafe search results.
2. The extension watches search responses and sends job batches automatically.
3. The popup can reuse the most recently captured result batch.

After jobs are sent, open the Job Funnel UI and check the jobs or applications views. Duplicate jobs are skipped by external job ID, so visiting the same job again should not create a second copy.

## Troubleshooting

- If Test says the app cannot be reached, confirm the API is running at `http://localhost:8000/health`.
- If the API runs on a different port, update App API URL in the popup and select Save.
- If Chrome blocks a non-local API, update `host_permissions` in `job-scraper-chrome/manifest.json` for that API host and reload the extension.
- If LinkedIn or Hiring Cafe pages change, the scraper selectors may need updates.
