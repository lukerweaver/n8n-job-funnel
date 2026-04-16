import { describe, expect, it, vi } from 'vitest';

import { createDom, evalScript, flushPromises } from './test-helpers.js';

describe('page-hook.js', () => {
  it('emits captured Hiring Cafe payloads from fetch responses', async () => {
    const seen = [];
    const dom = createDom({
      url: 'https://hiring.cafe/search-jobs',
      beforeParse(window) {
        window.fetch = vi.fn().mockResolvedValue({
          clone() {
            return {
              text: () => Promise.resolve('{"jobs":[{"id":"abc"}]}')
            };
          }
        });
      }
    });

    dom.window.addEventListener('__jobScraperHiringPayload', (event) => {
      seen.push(event.detail);
    });

    evalScript(dom, 'page-hook.js');
    await dom.window.fetch('https://hiring.cafe/api/search-jobs');
    await flushPromises();

    expect(seen).toEqual([
      {
        payload: { jobs: [{ id: 'abc' }] },
        sourceUrl: 'https://hiring.cafe/api/search-jobs'
      }
    ]);
  });

  it('ignores get-total-count requests', async () => {
    const handler = vi.fn();
    const dom = createDom({
      url: 'https://hiring.cafe/search-jobs',
      beforeParse(window) {
        window.fetch = vi.fn().mockResolvedValue({
          clone() {
            return {
              text: () => Promise.resolve('{"jobs":[{"id":"abc"}]}')
            };
          }
        });
      }
    });

    dom.window.addEventListener('__jobScraperHiringPayload', handler);
    evalScript(dom, 'page-hook.js');
    await dom.window.fetch('https://hiring.cafe/api/get-total-count');
    await flushPromises();

    expect(handler).not.toHaveBeenCalled();
  });

  it('emits job-shaped payloads from renamed endpoints', async () => {
    const seen = [];
    const dom = createDom({
      url: 'https://hiring.cafe/',
      beforeParse(window) {
        window.fetch = vi.fn().mockResolvedValue({
          clone() {
            return {
              text: () => Promise.resolve(JSON.stringify({
                hits: [
                  {
                    objectID: 'new-1',
                    job_title: 'Platform Lead',
                    v7_processed_job_data: {
                      company_profile: {
                        name: 'New API Co'
                      }
                    }
                  }
                ]
              }))
            };
          }
        });
      }
    });

    dom.window.addEventListener('__jobScraperHiringPayload', (event) => {
      seen.push(event.detail);
    });

    evalScript(dom, 'page-hook.js');
    await dom.window.fetch('https://hiring.cafe/api/search-v2');
    await flushPromises();

    expect(seen).toEqual([
      {
        payload: {
          hits: [
            expect.objectContaining({
              objectID: 'new-1',
              job_title: 'Platform Lead'
            })
          ]
        },
        sourceUrl: 'https://hiring.cafe/api/search-v2'
      }
    ]);
  });

  it('emits captured payloads from XHR responses', async () => {
    const seen = [];

    class FakeXHR {
      constructor() {
        this.listeners = {};
        this.responseText = '';
        this.response = '';
      }

      addEventListener(name, callback) {
        this.listeners[name] = callback;
      }

      open(_method, url) {
        this.__lastOpenUrl = url;
      }

      send() {
        this.responseText = '{"jobs":[{"id":"xhr-1"}]}';
        if (this.listeners.load) this.listeners.load();
      }
    }

    const dom = createDom({
      url: 'https://hiring.cafe/search-jobs',
      beforeParse(window) {
        window.fetch = vi.fn();
        window.XMLHttpRequest = FakeXHR;
      }
    });

    dom.window.addEventListener('__jobScraperHiringPayload', (event) => {
      seen.push(event.detail);
    });

    evalScript(dom, 'page-hook.js');
    const xhr = new dom.window.XMLHttpRequest();
    xhr.open('GET', 'https://hiring.cafe/api/search-jobs');
    xhr.send();

    expect(seen).toEqual([
      {
        payload: { jobs: [{ id: 'xhr-1' }] },
        sourceUrl: 'https://hiring.cafe/api/search-jobs'
      }
    ]);
  });
});
