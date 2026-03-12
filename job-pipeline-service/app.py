from fastapi import FastAPI, HTTPException
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from urllib.parse import urlparse

app = FastAPI(title="Job Scraper Service")


def merge_responses(existing, incoming):
    if isinstance(existing, list) and isinstance(incoming, list):
        return existing + incoming

    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = merge_responses(merged[key], value)
            else:
                merged[key] = value
        return merged

    return incoming

@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/jobs/hiringcafe")
async def jobs(search_url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Wait for Hiring Cafe's job search API call.
            async with page.expect_response(
                lambda response: urlparse(response.url).path == "/api/search-jobs",
                timeout=30000,
            ) as response_info:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            api_response = await response_info.value
            merged_response = await api_response.json()

            while True:
                try:
                    async with page.expect_response(
                        lambda response: urlparse(response.url).path == "/api/search-jobs",
                        timeout=4000,
                    ) as next_response_info:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                    next_response = await next_response_info.value
                    next_payload = await next_response.json()
                    merged_response = merge_responses(merged_response, next_payload)
                except PlaywrightTimeoutError:
                    break

            return merged_response
        except Exception as exc:
            raise HTTPException(
                status_code=504,
                detail=f"Failed to capture Hiring Cafe jobs response: {exc}",
            ) from exc
        finally:
            await context.close()
            await browser.close()
