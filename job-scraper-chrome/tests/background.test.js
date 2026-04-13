import { describe, expect, it, vi } from 'vitest';

import { flushPromises, runScriptInContext } from './test-helpers.js';

describe('background.js', () => {
  function createChromeMock() {
    let listener;
    const storage = {};
    const chrome = {
      runtime: {
        onMessage: {
          addListener(callback) {
            listener = callback;
          }
        }
      },
      storage: {
        sync: {
          get: vi.fn((defaults, callback) => {
            callback({ ...defaults, ...storage });
          }),
          set: vi.fn((items, callback) => {
            Object.assign(storage, items);
            callback();
          })
        }
      }
    };

    return {
      chrome,
      getListener: () => listener,
      storage
    };
  }

  it('posts normalized array payloads and forwards response metadata', async () => {
    const { chrome, getListener } = createChromeMock();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      text: vi.fn().mockResolvedValue('queued')
    });

    runScriptInContext('background.js', {
      chrome,
      fetch: fetchMock,
      console
    });

    const sendResponse = vi.fn();
    const keepChannelOpen = getListener()({ type: 'postJobPayload', payload: { job_id: 'job-1' } }, null, sendResponse);
    expect(keepChannelOpen).toBe(true);
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/jobs/ingest', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify([{ job_id: 'job-1' }])
    }));
    expect(sendResponse).toHaveBeenCalledWith({
      ok: true,
      status: 202,
      body: 'queued'
    });
  });

  it('returns a transport error payload when fetch throws', async () => {
    const { chrome, getListener } = createChromeMock();

    runScriptInContext('background.js', {
      chrome,
      fetch: vi.fn().mockRejectedValue(new Error('network down')),
      console
    });

    const sendResponse = vi.fn();
    expect(getListener()({ type: 'postJobPayload', payload: [] }, null, sendResponse)).toBe(true);
    await flushPromises();

    expect(sendResponse).toHaveBeenCalledWith({
      ok: false,
      status: 0,
      body: 'Error: network down'
    });
  });

  it('saves and uses a custom API base URL', async () => {
    const { chrome, getListener } = createChromeMock();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: vi.fn().mockResolvedValue('ok')
    });

    runScriptInContext('background.js', {
      chrome,
      fetch: fetchMock,
      console
    });

    const saveResponse = vi.fn();
    expect(getListener()({ type: 'saveConfig', apiBaseUrl: 'http://127.0.0.1:8000/' }, null, saveResponse)).toBe(true);
    await flushPromises();
    expect(saveResponse).toHaveBeenCalledWith({ ok: true, apiBaseUrl: 'http://127.0.0.1:8000' });

    const postResponse = vi.fn();
    expect(getListener()({ type: 'postJobPayload', payload: { job_id: 'job-2' } }, null, postResponse)).toBe(true);
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/jobs/ingest', expect.objectContaining({
      method: 'POST'
    }));
  });

  it('tests the configured API health endpoint', async () => {
    const { chrome, getListener } = createChromeMock();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: vi.fn().mockResolvedValue('{"status":"ok"}')
    });

    runScriptInContext('background.js', {
      chrome,
      fetch: fetchMock,
      console
    });

    const sendResponse = vi.fn();
    expect(getListener()({ type: 'testConnection', apiBaseUrl: 'http://localhost:9000/' }, null, sendResponse)).toBe(true);
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:9000/health');
    expect(sendResponse).toHaveBeenCalledWith({
      ok: true,
      status: 200,
      body: '{"status":"ok"}',
      apiBaseUrl: 'http://localhost:9000'
    });
  });
});
