import { describe, expect, it, vi } from 'vitest';

import { createDom, evalScript, flushPromises } from './test-helpers.js';

describe('popup.js', () => {
  const configHtml = `
    <!doctype html>
    <input id="apiBaseUrl" />
    <button id="saveConfigBtn">Save</button>
    <button id="testConnectionBtn">Test</button>
    <p id="configStatus"></p>
    <button id="scrapeBtn">Scrape</button>
    <pre id="status"></pre>
  `;

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

  it('loads, saves, and tests the API URL', async () => {
    const chrome = {
      tabs: {
        query: vi.fn(),
        sendMessage: vi.fn()
      },
      runtime: {
        sendMessage: vi.fn((message) => {
          if (message.type === 'getConfig') {
            return Promise.resolve({ ok: true, apiBaseUrl: 'http://localhost:8000' });
          }
          if (message.type === 'saveConfig') {
            return Promise.resolve({ ok: true, apiBaseUrl: message.apiBaseUrl.replace(/\/+$/, '') });
          }
          if (message.type === 'testConnection') {
            return Promise.resolve({ ok: true, status: 200, apiBaseUrl: message.apiBaseUrl.replace(/\/+$/, '') });
          }
          return Promise.resolve({ ok: false });
        })
      }
    };
    const dom = createDom({
      html: configHtml,
      beforeParse(window) {
        window.chrome = chrome;
      }
    });

    evalScript(dom, 'popup.js');
    await flushPromises();

    const apiBaseUrlInput = dom.window.document.getElementById('apiBaseUrl');
    const configStatus = dom.window.document.getElementById('configStatus');
    expect(apiBaseUrlInput.value).toBe('http://localhost:8000');
    expect(configStatus.textContent).toContain('Using http://localhost:8000');

    apiBaseUrlInput.value = 'http://127.0.0.1:8000/';
    dom.window.document.getElementById('saveConfigBtn').click();
    await flushPromises();

    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'saveConfig',
      apiBaseUrl: 'http://127.0.0.1:8000/'
    });
    expect(apiBaseUrlInput.value).toBe('http://127.0.0.1:8000');
    expect(configStatus.textContent).toContain('Saved http://127.0.0.1:8000');

    dom.window.document.getElementById('testConnectionBtn').click();
    await flushPromises();

    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'testConnection',
      apiBaseUrl: 'http://127.0.0.1:8000'
    });
    expect(configStatus.textContent).toContain('Connected to http://127.0.0.1:8000');
  });
});
