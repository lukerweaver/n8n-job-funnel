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
            <time datetime="2026-04-10T00:00:00Z">3 days ago</time>
            <span class="_2a866d47">Posted on April 1, 2026</span>
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
      posted_at: '2026-04-10T00:00:00.000Z',
      posted_at_raw: '3 days ago',
      source: 'linkedin'
    });
  });

  it('falls back to LinkedIn posted-date text when time metadata is missing', () => {
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
            <span class="_2a866d47">Posted on April 11, 2026</span>
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

    expect(payload[0]).toMatchObject({
      posted_at: '2026-04-11T00:00:00.000Z',
      posted_at_raw: 'Posted on April 11, 2026'
    });
  });

  it('ignores unrelated document-level time elements before the active LinkedIn job', () => {
    let env;
    const dom = createDom({
      url: 'https://www.linkedin.com/jobs/view/1234567890/',
      html: `
        <!doctype html>
        <html>
          <body>
            <aside>
              <time datetime="2026-03-01T00:00:00Z">old recommendation</time>
            </aside>
            <main class="jobs-details__main-content">
              <a class="topcard__org-name-link">Acme</a>
              <h1 class="topcard__title">Senior Product Manager</h1>
              <a class="topcard__link" href="https://example.com/apply">Apply</a>
              <div class="jobs-description-content__text">Lead roadmap execution.</div>
              <time datetime="2026-04-10T00:00:00Z">3 days ago</time>
            </main>
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

    expect(payload[0]).toMatchObject({
      posted_at: '2026-04-10T00:00:00.000Z',
      posted_at_raw: '3 days ago'
    });
  });

  it('parses plain relative LinkedIn posted text when time metadata is missing', () => {
    let env;
    const expectedPostedAt = Date.now() - (3 * 24 * 60 * 60 * 1000);
    const dom = createDom({
      url: 'https://www.linkedin.com/jobs/view/1234567890/',
      html: `
        <!doctype html>
        <html>
          <body>
            <main class="jobs-details__main-content">
              <a class="topcard__org-name-link">Acme</a>
              <h1 class="topcard__title">Senior Product Manager</h1>
              <a class="topcard__link" href="https://example.com/apply">Apply</a>
              <div class="jobs-description-content__text">Lead roadmap execution.</div>
              <span>3 days ago</span>
            </main>
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

    expect(payload[0].posted_at_raw).toBe('3 days ago');
    expect(Math.abs(Date.parse(payload[0].posted_at) - expectedPostedAt)).toBeLessThan(2000);
  });

  it('finds LinkedIn posted dates in multiple job card contexts', () => {
    let env;
    const dom = createDom({
      url: 'https://www.linkedin.com/jobs/search/',
      html: `
        <!doctype html>
        <html>
          <body>
            <li class="jobs-search-results__list-item" data-job-id="1">
              <time datetime="2026-04-10T00:00:00Z">3 days ago</time>
            </li>
            <li class="jobs-search-results__list-item" data-job-id="2">
              <div>Reposted on April 12, 2026</div>
            </li>
          </body>
        </html>
      `,
      beforeParse(window) {
        env = installChrome(window);
        window.__jobScraperDebug = true;
        window.setTimeout = vi.fn(() => 1);
        window.clearTimeout = vi.fn();
      }
    });

    evalScript(dom, 'content.js');

    expect(env.chrome.runtime.onMessage.addListener).toBeDefined();
    expect(dom.window.__jobScraperDebugApi.extractLinkedInPostedDates()).toEqual([
      {
        absoluteDate: '2026-04-10T00:00:00Z',
        relativeText: '3 days ago'
      },
      {
        absoluteDate: '2026-04-12T00:00:00.000Z',
        relativeText: 'Reposted on April 12, 2026'
      }
    ]);
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
            company_name: 'Hiring Cafe Co',
            estimated_publish_date: '2026-04-09T00:00:00Z',
            estimated_publish_date_millis: 1775779200000
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
          posted_at: '2026-04-09T00:00:00.000Z',
          posted_at_raw: '2026-04-09T00:00:00Z',
          location: 'Remote',
          source: 'hiring.cafe',
          source_url: 'https://hiring.cafe/api/search-jobs'
        })
      ]
    }, expect.any(Function));
  });

  it('normalizes Hiring Cafe estimated publish date millis when the date string is missing', async () => {
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

    dom.window.dispatchEvent(new dom.window.CustomEvent('__jobScraperHiringPayload', {
      detail: {
        payload: {
          jobs: [
            {
              id: 'millis-only',
              job_title: 'Platform PM',
              v5_processed_job_data: {
                company_name: 'Hiring Cafe Co',
                estimated_publish_date: null,
                estimated_publish_date_millis: 1775865600000
              },
              job_information: {
                description: '<p>Own platform strategy.</p>'
              }
            },
            {
              id: 'missing-v5',
              job_title: 'Null Safe PM',
              v5_processed_job_data: null,
              job_information: {
                description: '<p>Handle missing date data.</p>'
              }
            }
          ]
        },
        sourceUrl: 'https://hiring.cafe/api/search-jobs'
      }
    }));
    await flushPromises();

    expect(env.chrome.runtime.sendMessage).toHaveBeenCalledTimes(1);
    expect(env.chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'postJobPayload',
      payload: [
        expect.objectContaining({
          job_id: 'hiring_millis-only',
          posted_at: '2026-04-11T00:00:00.000Z',
          posted_at_raw: '1775865600000'
        }),
        expect.objectContaining({
          job_id: 'hiring_missing-v5',
          posted_at: null,
          posted_at_raw: null
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

  it('normalizes newer Hiring Cafe hits payloads', async () => {
    let env;
    const dom = createDom({
      url: 'https://hiring.cafe/',
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

    dom.window.dispatchEvent(new dom.window.CustomEvent('__jobScraperHiringPayload', {
      detail: {
        payload: {
          hits: [
            {
              objectID: 'v7-abc',
              job_title: 'Staff Product Manager',
              source: 'ashby',
              board_token: 'example-board',
              job_id: 'job-123',
              job_description: '<p>Lead product systems.</p>',
              job_location: 'Remote - US',
              v5_processed_job_data: {
                yearly_min_compensation: 180000,
                yearly_max_compensation: 220000
              },
              v7_processed_job_data: {
                company_profile: {
                  name: 'V7 Company'
                }
              }
            }
          ]
        },
        sourceUrl: 'https://hiring.cafe/api/search-v2'
      }
    }));
    await flushPromises();

    expect(env.chrome.runtime.sendMessage).toHaveBeenCalledTimes(1);
    expect(env.chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'postJobPayload',
      payload: [
        expect.objectContaining({
          job_id: 'hiring_v7-abc',
          company_name: 'V7 Company',
          title: 'Staff Product Manager',
          yearly_min_compensation: 180000,
          yearly_max_compensation: 220000,
          apply_url: 'https://jobs.ashbyhq.com/example-board/job-123/application',
          description: 'Lead product systems.',
          location: 'Remote - US',
          source: 'hiring.cafe',
          source_url: 'https://hiring.cafe/api/search-v2'
        })
      ]
    }, expect.any(Function));
  });

  it('scrapes Hiring Cafe jobs from Next page data when no search request fires', () => {
    let env;
    const dom = createDom({
      url: 'https://hiring.cafe/',
      html: `
        <!doctype html>
        <html>
          <body>
            <script id="__NEXT_DATA__" type="application/json">
              {
                "props": {
                  "pageProps": {
                    "hits": [
                      {
                        "objectID": "ssr-1",
                        "job_title": "SSR Product Lead",
                        "job_description": "Own SSR capture.",
                        "v7_processed_job_data": {
                          "company_profile": {
                            "name": "SSR Co"
                          }
                        }
                      }
                    ]
                  }
                }
              }
            </script>
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

    expect(payload).toEqual([
      expect.objectContaining({
        job_id: 'hiring_ssr-1',
        company_name: 'SSR Co',
        title: 'SSR Product Lead',
        description: 'Own SSR capture.',
        source: 'hiring.cafe'
      })
    ]);
  });
});
