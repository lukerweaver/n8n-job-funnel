import { describe, expect, it, vi } from 'vitest';

import { createDom, evalScript, flushPromises } from './test-helpers.js';

describe('popup.js', () => {
  it('shows a success state after scraping and sending payload', async () => {
    const chrome = {
      tabs: {
        query: vi.fn().mockResolvedValue([{ id: 7 }]),
        sendMessage: vi.fn().mockResolvedValue([{ job_id: 'linkedin_123' }])
      },
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({ ok: true, status: 200 })
      }
    };
    const dom = createDom({
      html: '<!doctype html><button id="scrapeBtn">Scrape</button><pre id="status"></pre>',
      beforeParse(window) {
        window.chrome = chrome;
      }
    });

    evalScript(dom, 'popup.js');
    dom.window.document.getElementById('scrapeBtn').click();
    await flushPromises();

    expect(chrome.tabs.query).toHaveBeenCalledWith({ active: true, currentWindow: true });
    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(7, { type: 'scrapeJob' });
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'postJobPayload',
      payload: [{ job_id: 'linkedin_123' }]
    });
    expect(dom.window.document.getElementById('status').textContent).toContain('Sent successfully.');
  });

  it('shows a helpful message when there is no active tab', async () => {
    const chrome = {
      tabs: {
        query: vi.fn().mockResolvedValue([]),
        sendMessage: vi.fn()
      },
      runtime: {
        sendMessage: vi.fn()
      }
    };
    const dom = createDom({
      html: '<!doctype html><button id="scrapeBtn">Scrape</button><pre id="status"></pre>',
      beforeParse(window) {
        window.chrome = chrome;
      }
    });

    evalScript(dom, 'popup.js');
    dom.window.document.getElementById('scrapeBtn').click();
    await flushPromises();

    expect(dom.window.document.getElementById('status').textContent).toBe('No active tab found.');
    expect(chrome.tabs.sendMessage).not.toHaveBeenCalled();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });

  it('shows the background failure details when posting fails', async () => {
    const chrome = {
      tabs: {
        query: vi.fn().mockResolvedValue([{ id: 9 }]),
        sendMessage: vi.fn().mockResolvedValue([{ job_id: 'linkedin_999' }])
      },
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({ ok: false, status: 503, body: 'upstream unavailable' })
      }
    };
    const dom = createDom({
      html: '<!doctype html><button id="scrapeBtn">Scrape</button><pre id="status"></pre>',
      beforeParse(window) {
        window.chrome = chrome;
      }
    });

    evalScript(dom, 'popup.js');
    dom.window.document.getElementById('scrapeBtn').click();
    await flushPromises();

    expect(dom.window.document.getElementById('status').textContent).toContain('Failed to send.');
    expect(dom.window.document.getElementById('status').textContent).toContain('503');
  });
});
