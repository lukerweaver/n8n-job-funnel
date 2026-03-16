# LinkedIn Job Scraper (Chrome Extension)

This extension scrapes LinkedIn job pages and sends this payload:

```json
{
  "job_id": "linkedin_{id}",
  "company_name": "...",
  "title": "...",
  "yearly_min_compensation": 0,
  "yearly_max_compensation": 0,
  "apply_url": "...",
  "description": "..."
}
```

## Files
- `manifest.json` – extension registration and permissions.
- `popup.html`, `popup.css`, `popup.js` – popup button + request flow.
- `content.js` – scrapes the active LinkedIn page.
- `background.js` – posts payload to endpoint.

## Setup
1. Edit `background.js`:
   - Replace `POST_ENDPOINT` with your real URL, typically `http://localhost:8000/jobs/ingest`.
2. Update selectors in `content.js` if your LinkedIn layout differs.
3. Go to `chrome://extensions`, enable Developer mode, and load unpacked this folder.
4. Open a LinkedIn job page and click **Scrape this job**.

## Notes
- If LinkedIn markup changes, only the CSS selectors in `content.js` usually need updating.
- `content.js` currently has multiple candidate selectors for resilience.
