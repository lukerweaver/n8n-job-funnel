import { describe, expect, it, vi } from 'vitest';

import { createDom, evalScript, flushPromises } from './test-helpers.js';

function installChrome(window, overrides = {}) {
  let messageListener;
  const chrome = {
    runtime: {
      onMessage: {
        addListener(callback) {
          messageListener = callback;
        }
      },
      sendMessage: vi.fn()
    },
    ...overrides
  };

  window.chrome = chrome;
  return {
    chrome,
    getMessageListener: () => messageListener
  };
}

describe('content.js', () => {
  it('scrapes LinkedIn pages through the runtime message handler', () => {
    let env;
    const dom = createDom({
      url: 'https://www.linkedin.com/jobs/view/1234567890/',
      html: `
        <!doctype html>
        <html>
          <body>
            <a class="topcard__org-name-link">Acme</a>
            <h1 class="topcard__title">Senior Product Manager</h1>
            <a class="topcard__link" href="https://example.com/apply">Apply</a>
            <div class="jobs-description-content__text">Lead roadmap execution.</div>
            <span class="tvm__text--low-emphasis">$150K - $180K /yr</span>
          </body>
        </html>
      `,
      beforeParse(window) {
        env = installChrome(window);
        window.setTimeout = vi.fn(() => 1);
        window.clearTimeout = vi.fn();
      }
    });

    evalScript(dom, 'content.js');

    let payload;
    env.getMessageListener()({ type: 'scrapeJob' }, null, (value) => {
      payload = value;
    });

    expect(payload).toHaveLength(1);
    expect(payload[0]).toMatchObject({
      job_id: 'linkedin_1234567890',
      company_name: 'Acme',
      title: 'Senior Product Manager',
      apply_url: 'https://example.com/apply',
      yearly_min_compensation: 150000,
      yearly_max_compensation: 180000,
      source: 'linkedin'
    });
  });

  it('normalizes Hiring Cafe payloads and forwards them to the background script', async () => {
    let env;
    const dom = createDom({
      url: 'https://hiring.cafe/search-jobs',
      beforeParse(window) {
        env = installChrome(window);
        window.setTimeout = (fn) => {
          fn();
          return 1;
        };
        window.clearTimeout = vi.fn();
      }
    });

    evalScript(dom, 'content.js');

    const payload = {
      jobs: [
        {
          id: 'abc123',
          job_title: 'Platform PM',
          apply_url: 'https://example.com/jobs/abc123',
          v5_processed_job_data: {
            company_name: 'Hiring Cafe Co'
          },
          job_information: {
            description: '<p>Own platform strategy.</p>',
            compensation_range: '$170K - $190K',
            location: 'Remote'
          }
        }
      ]
    };

    dom.window.dispatchEvent(new dom.window.CustomEvent('__jobScraperHiringPayload', {
      detail: {
        payload,
        sourceUrl: 'https://hiring.cafe/api/search-jobs'
      }
    }));
    await flushPromises();

    expect(env.chrome.runtime.sendMessage).toHaveBeenCalledTimes(1);
    expect(env.chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'postJobPayload',
      payload: [
        expect.objectContaining({
          job_id: 'hiring_abc123',
          company_name: 'Hiring Cafe Co',
          title: 'Platform PM',
          yearly_min_compensation: 170000,
          yearly_max_compensation: 190000,
          location: 'Remote',
          source: 'hiring.cafe',
          source_url: 'https://hiring.cafe/api/search-jobs'
        })
      ]
    }, expect.any(Function));
  });

  it('deduplicates repeated Hiring Cafe payloads by job id retention', async () => {
    let env;
    const dom = createDom({
      url: 'https://hiring.cafe/search-jobs',
      beforeParse(window) {
        env = installChrome(window);
        window.setTimeout = (fn) => {
          fn();
          return 1;
        };
        window.clearTimeout = vi.fn();
      }
    });

    evalScript(dom, 'content.js');

    const event = new dom.window.CustomEvent('__jobScraperHiringPayload', {
      detail: {
        payload: {
          jobs: [
            {
              id: 'dup-1',
              title: 'Duplicate Job',
              company_name: 'Repeat Co',
              job_information: {
                description: 'Repeated role'
              }
            }
          ]
        },
        sourceUrl: 'https://hiring.cafe/api/search-jobs'
      }
    });

    dom.window.dispatchEvent(event);
    dom.window.dispatchEvent(event);
    await flushPromises();

    expect(env.chrome.runtime.sendMessage).toHaveBeenCalledTimes(1);
  });
});
