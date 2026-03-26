import { describe, expect, it, vi } from 'vitest';

import { flushPromises, runScriptInContext } from './test-helpers.js';

describe('background.js', () => {
  it('posts normalized array payloads and forwards response metadata', async () => {
    let listener;
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      text: vi.fn().mockResolvedValue('queued')
    });
    const chrome = {
      runtime: {
        onMessage: {
          addListener(callback) {
            listener = callback;
          }
        }
      }
    };

    runScriptInContext('background.js', {
      chrome,
      fetch: fetchMock,
      console
    });

    const sendResponse = vi.fn();
    const keepChannelOpen = listener({ type: 'postJobPayload', payload: { job_id: 'job-1' } }, null, sendResponse);
    await expect(keepChannelOpen).resolves.toBe(true);

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
    let listener;
    const chrome = {
      runtime: {
        onMessage: {
          addListener(callback) {
            listener = callback;
          }
        }
      }
    };

    runScriptInContext('background.js', {
      chrome,
      fetch: vi.fn().mockRejectedValue(new Error('network down')),
      console
    });

    const sendResponse = vi.fn();
    await expect(listener({ type: 'postJobPayload', payload: [] }, null, sendResponse)).resolves.toBe(true);
    await flushPromises();

    expect(sendResponse).toHaveBeenCalledWith({
      ok: false,
      status: 0,
      body: 'Error: network down'
    });
  });
});
