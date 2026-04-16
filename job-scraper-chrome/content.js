(() => {
  const AUTO_SEND_DELAY_MS = 1200;
  const HIRING_DUPLICATE_WINDOW_MS = 15000;
  const HIRING_SEEN_RETENTION_MS = 30 * 60 * 1000;

  const companySelectors = ['[class*="job-details-jobs-unified-top-card__company-name"]', 'a.topcard__org-name-link', '.jobs-unified-top-card__company-name a', 'a[data-field="companyName"]', '.job-details-jobs-unified-top-card__primary-description a', 'h3[data-test-entity-lockup-title] + a'];
  const titleSelectors = ['[class*="job-details-jobs-unified-top-card__job-title"]', 'h1.topcard__title', '.jobs-unified-top-card__job-title', '[data-test-job-title]'];
  const applySelectors = ['a.topcard__link', 'a[data-tracking-control-name="public_jobs_apply-top-card-apply-button"]', 'a[href*="/jobs/apply/"]', 'a.jobs-apply-button', 'button[role="link"]#jobs-apply-button-id', 'button[role="link"][aria-label*="Apply to"]', 'button[data-live-test-job-apply-button]', '[aria-label*="Apply to"]'];
  const descriptionSelectors = ['[class*="jobs-description-content__text"]', '.jobs-description__content', '[class*="show-more"][class*="jobs-description"]', '.jobs-description-content__text'];
  const compensationSelectors = ['[class*="job-details-jobs-unified-top-card__job-insight"][class*="salary"]', '.jobs-unified-top-card__bullet li', 'ul.job-criteria__list li', 'span.tvm__text--low-emphasis', '[aria-label*="minimum pay" i]', '[aria-label*="salary" i]'];

  const isHiringCafeSearchPage = () => {
    const host = window.location.hostname.replace(/^www\./, '').toLowerCase();
    return host === 'hiring.cafe' && !window.location.pathname.startsWith('/viewjob/');
  };

  const textOf = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node && node.textContent) return node.textContent.trim();
    }
    return '';
  };

  const stripHtml = (html) => {
    if (!html || typeof html !== 'string') return '';
    return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  };

  const seemsLikeCompensationText = (text) => {
    if (!text) return false;
    const t = text.toLowerCase();
    const hasDollars = t.includes('$');
    const hasYear = t.includes('/yr') || t.includes('year');
    const hasRange = t.includes('-') || t.includes(' to ');
    const hasKeyword = t.includes('salary') || t.includes('pay') || t.includes('compensation');
    const countLikeMoney = (text.match(/\$?\d+(?:\.\d+)?\s*[km]?/gi) || []).length;
    return countLikeMoney >= 1 && (hasYear || hasKeyword || hasRange) && hasDollars;
  };

  const extractCompensationText = () => {
    for (const selector of compensationSelectors) {
      const nodes = document.querySelectorAll(selector);
      for (const node of nodes) {
        if (!(node instanceof Element)) continue;
        const text = node.textContent ? node.textContent.trim() : '';
        if (seemsLikeCompensationText(text)) return text;
      }
    }

    const fallbackNodes = document.querySelectorAll('button, li, span, div, p');
    for (const node of fallbackNodes) {
      if (!(node instanceof Element)) continue;
      const text = node.textContent ? node.textContent.trim() : '';
      if (seemsLikeCompensationText(text)) return text;
    }

    return '';
  };

  const parseCompensation = (text) => {
    if (!text) return { min: 0, max: 0 };
    const nums = text
      .replace(/,/g, '')
      .match(/\$?\d+(?:\.\d+)?[kKmM]?/g)
      ?.map((part) => {
        const lower = part.toLowerCase();
        const value = parseFloat(lower.replace(/[$,]/g, ''));
        if (Number.isNaN(value)) return null;
        if (lower.endsWith('k')) return value * 1000;
        if (lower.endsWith('m')) return value * 1000000;
        return value;
      })
      .filter(Boolean) || [];

    if (!nums.length) return { min: 0, max: 0 };
    if (nums.length === 1) return { min: nums[0], max: nums[0] };
    return { min: Math.min(...nums), max: Math.max(...nums) };
  };

  const normalizeUrl = (value) => {
    if (!value || typeof value !== 'string') return '';
    const trimmed = value.trim();
    if (!trimmed) return '';

    if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) return trimmed;
    if (trimmed.startsWith('//')) return window.location.protocol + trimmed;
    if (trimmed.startsWith('/')) {
      try {
        return new URL(trimmed, window.location.origin).href;
      } catch (_err) {
        return '';
      }
    }
    return '';
  };

  const findUrlLikeAttribute = (node) => {
    const attrNames = ['href', 'action', 'data-url', 'data-href', 'data-redirect-url', 'data-apply-url', 'data-job-apply-url', 'data-apply-button-url'];

    for (const attr of attrNames) {
      const raw = node.getAttribute?.(attr);
      const url = normalizeUrl(raw);
      if (url) return url;
    }

    if (node.dataset) {
      for (const value of Object.values(node.dataset)) {
        const url = normalizeUrl(value);
        if (url) return url;
      }
    }

    return '';
  };

  const findUrlInJs = (node) => {
    const eventAttrs = ['onclick', 'data-handle'];

    for (const attr of eventAttrs) {
      const raw = node.getAttribute?.(attr);
      if (!raw) continue;
      const match = raw.match(/['"](https?:\/\/[^'\"]+)['"]/i) ||
        raw.match(/(https?:[^\s"';]+)/i) ||
        raw.match(/(\/\/[^\s"';]+)/i);
      if (!match) continue;
      const url = normalizeUrl(match[1]);
      if (url) return url;
    }

    return '';
  };

  const urlOf = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (!node) continue;

      if (node instanceof HTMLAnchorElement && node.href) return node.href;

      const nodeHref = findUrlLikeAttribute(node);
      if (nodeHref) return nodeHref;

      const parentAnchor = node.closest?.('a[href]');
      if (parentAnchor && parentAnchor.href) return parentAnchor.href;

      const formAction = node.closest?.('form[action]');
      if (formAction && formAction.action) return formAction.action;

      if (node instanceof HTMLButtonElement) {
        const data = findUrlLikeAttribute(node);
        if (data) return data;

        const inJs = findUrlInJs(node);
        if (inJs) return inJs;

        const parentFormAction = node.closest?.('form[action]');
        if (parentFormAction && parentFormAction.action) return parentFormAction.action;
      }
    }

    return '';
  };

  const findApplyUrlInScripts = () => {
    const scripts = document.querySelectorAll('script[type="application/ld+json"], script');
    const maybeJsonKeys = ['applyUrl', 'apply_url', 'applicationUrl', 'application_url', 'applyLink', 'externalApplyUrl'];

    const findUrlInValue = (value, seen = new Set()) => {
      if (!value || seen.has(value)) return '';
      const text = String(value).trim();
      seen.add(text);
      if (!text) return '';
      return normalizeUrl(text);
    };

    const crawl = (obj, seen = new Set()) => {
      if (!obj || typeof obj !== 'object') return '';
      if (Array.isArray(obj)) {
        for (const item of obj) {
          const result = crawl(item, seen);
          if (result) return result;
        }
        return '';
      }

      for (const [key, value] of Object.entries(obj)) {
        if (typeof key === 'string' && maybeJsonKeys.includes(key)) {
          const byValue = findUrlInValue(value, seen);
          if (byValue) return byValue;
        }

        if (typeof value === 'string') {
          const byValue = findUrlInValue(value, seen);
          if (byValue && /\b(apply|application)\b/i.test(byValue)) return byValue;
        }

        if (typeof value === 'object') {
          const byChild = crawl(value, seen);
          if (byChild) return byChild;
        }
      }

      return '';
    };

    for (const script of scripts) {
      const raw = script.textContent || '';
      if (!raw) continue;

      const rawMatch = raw.match(/applyUrl\"\s*:\s*\"([^\"]+)\"/i) ||
        raw.match(/apply_url\"\s*:\s*\"([^\"]+)\"/i) ||
        raw.match(/applicationUrl\"\s*:\s*\"([^\"]+)\"/i) ||
        raw.match(/\"url\"\s*:\s*\"([^\"]*apply[^\"]*)\"/i);
      if (rawMatch && rawMatch[1]) {
        const parsed = normalizeUrl(rawMatch[1]);
        if (parsed) return parsed;
      }

      if (script.type === 'application/ld+json') {
        try {
          const json = JSON.parse(raw);
          const found = crawl(json);
          if (found) return found;
        } catch (_err) {
          // ignore malformed
        }
      }
    }

    return '';
  };
  const extractApplyUrl = () => {
    const direct = urlOf(applySelectors);
    if (direct) return direct;

    const applyButton = document.getElementById('jobs-apply-button-id') || document.querySelector('button[role="link"][aria-label*="Apply to"]');
    if (applyButton) {
      const attrUrl = findUrlLikeAttribute(applyButton);
      if (attrUrl) return attrUrl;

      const jsUrl = findUrlInJs(applyButton);
      if (jsUrl) return jsUrl;
    }

    const scriptUrl = findApplyUrlInScripts();
    if (scriptUrl) return scriptUrl;

    const linkedInShare = document.querySelector('meta[property="og:url"]')?.content;
    if (linkedInShare && linkedInShare.includes('linkedin.com/jobs/view/')) return linkedInShare;

    return window.location.href;
  };

  const getLinkedInPayload = () => {
    const company = textOf(companySelectors);
    const title = textOf(titleSelectors);
    const applyUrl = extractApplyUrl();
    const compensationText = extractCompensationText();
    const compensation = parseCompensation(compensationText);
    const description = textOf(descriptionSelectors) || stripHtml(document.body?.innerText || '');

    const jobId = (() => {
      const idFromUrl = window.location.pathname.match(/\/jobs\/view\/([0-9]+)/i)?.[1];
      if (idFromUrl) return `linkedin_${idFromUrl}`;
      const hash = window.location.pathname.replace(/\W+/g, '_');
      return `linkedin_${hash}`;
    })();

    return {
      job_id: jobId,
      company_name: company || 'Unknown Company',
      title: title || 'Unknown Title',
      yearly_min_compensation: compensation.min || 0,
      yearly_max_compensation: compensation.max || 0,
      apply_url: applyUrl,
      description,
      source: 'linkedin',
      source_url: window.location.href
    };
  };

  const normalizeHiringResponse = (data, sourceUrl = window.location.href) => {
    if (!data || typeof data !== 'object') return [];

    const collectItems = (value, depth = 0, seen = new Set()) => {
      if (!value || depth > 6 || typeof value !== 'object') return [];
      if (seen.has(value)) return [];
      seen.add(value);

      if (Array.isArray(value)) {
        if (value.some(looksLikeHiringJobItem)) return value.filter(looksLikeHiringJobItem);
        return value.flatMap((item) => collectItems(item, depth + 1, seen));
      }

      const directItems = [
        value.jobs,
        value.hits,
        value.results,
        value.items,
        value.data
      ].find((candidate) => Array.isArray(candidate) && candidate.some(looksLikeHiringJobItem));
      if (directItems) return directItems.filter(looksLikeHiringJobItem);

      return Object.values(value).flatMap((child) => collectItems(child, depth + 1, seen));
    };

    const items = (() => {
      if (Array.isArray(data)) return data;
      if (Array.isArray(data.jobs)) return data.jobs;
      if (Array.isArray(data.hits)) return data.hits;
      if (Array.isArray(data.results)) return data.results;
      if (Array.isArray(data.items)) return data.items;
      if (Array.isArray(data.data)) return data.data;
      return collectItems(data);
    })();

    if (!Array.isArray(items)) return [];

    return items
      .map((item) => {
        const info = item?.job_information || {};
        const v5 = item?.v5_processed_job_data || {};
        const v7 = item?.v7_processed_job_data || {};
        const companyProfile = v7?.company_profile || {};
        const hiringCompanyName = (() => {
          const companyCandidates = [
            companyProfile?.name,
            item?.enriched_company_data?.name,
            v5?.company_name,
            v5?.companyName,
            v5?.company?.name,
            item?.company_name,
            item?.companyName,
            item?.company?.name,
            item?.company?.title,
            item?.employer_name,
            item?.employer?.name,
            item?.employerName,
            item?.organization,
            item?.job_board?.name,
            info?.company_name,
            info?.companyName,
            info?.company,
            info?.employer_name,
            info?.employerName,
            info?.organization
          ];

          for (const candidate of companyCandidates) {
            if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
            if (candidate && typeof candidate === 'object' && typeof candidate.name === 'string' && candidate.name.trim()) {
              return candidate.name.trim();
            }
          }

          return '';
        })();

        const rawDescription = info.description || '';
        const compensation = extractHiringCompensation(item, info);
        const location = extractHiringLocation(item, info) || '';
        const stableId = getHiringStableId(item);
        const applyUrl = item?.apply_url || item?.url || buildHiringApplyUrl(item) || '';
        const description = rawDescription || item?.job_description || item?.description || info?.summary || '';

        return {
          job_id: stableId,
          company_name: hiringCompanyName || 'Unknown Company',
          title: item?.job_title || item?.title || info?.title || info?.job_title || info?.job_title_raw || 'Unknown Title',
          yearly_min_compensation: compensation.min || 0,
          yearly_max_compensation: compensation.max || 0,
          apply_url: applyUrl,
          description: stripHtml(description),
          source: 'hiring.cafe',
          source_url: sourceUrl,
          location,
          board_token: item?.board_token || '',
          source_name: item?.source || ''
        };
      })
      .filter((job) => job.title !== 'Unknown Title' || job.company_name !== 'Unknown Company' || job.description || job.apply_url);
  };

  const looksLikeHiringJobItem = (item) => {
    if (!item || typeof item !== 'object') return false;
    return Boolean(
      item.job_information ||
      item.v5_processed_job_data ||
      item.v7_processed_job_data ||
      item.board_token ||
      item.objectID ||
      item.job_title
    );
  };

  const getHiringStableId = (item) => {
    const raw = item?.objectID || item?.id || item?.job_id;
    if (raw) return `hiring_${String(raw)}`;

    const fingerprint = [
      item?.source,
      item?.board_token,
      item?.job_title || item?.title || item?.job_information?.title,
      item?.apply_url || item?.url
    ].filter(Boolean).join('|');

    return `hiring_${hashCode(fingerprint || JSON.stringify(item).slice(0, 1000))}`;
  };

  const buildHiringApplyUrl = (item) => {
    const source = String(item?.source || '').toLowerCase();
    const boardToken = item?.board_token;
    const jobId = item?.job_id || item?.id || item?.objectID;
    if (!source || !boardToken || !jobId) return '';

    if (source === 'grnhse') return `https://boards.greenhouse.io/embed/job_app?for=${boardToken}&token=${jobId}`;
    if (source === 'ashby') return `https://jobs.ashbyhq.com/${boardToken}/${jobId}/application`;
    if (source === 'lever') return `https://jobs.lever.co/${boardToken}/${jobId}/apply`;
    if (source === 'eu_lever') return `https://jobs.eu.lever.co/${boardToken}/${jobId}/apply`;
    if (source === 'breezy') return `https://${boardToken}.breezy.hr/p/${jobId}`;

    return '';
  };

  const extractHiringLocation = (item, info) => {
    if (!info || typeof info !== 'object') return '';
    if (item?.v5_processed_job_data?.formatted_workplace_location) return String(item.v5_processed_job_data.formatted_workplace_location);
    if (item?.gpt_data?.formatted_location) return String(item.gpt_data.formatted_location);
    if (item?.job_location) return String(item.job_location);
    if (info.location) return String(info.location);
    if (info.Location) return String(info.Location);

    const html = String(info.description || '');
    if (!html) return '';

    const m1 = html.match(/<h3>\s*Location\s*<\/h3>\s*<div>([^<]+)<\/div>/i);
    if (m1) return m1[1].trim();

    return '';
  };

  const extractHiringCompensation = (item, info) => {
    const processed = item?.v5_processed_job_data || {};
    const directMin = Number(processed.yearly_min_compensation || item?.yearly_min_compensation || 0);
    const directMax = Number(processed.yearly_max_compensation || item?.yearly_max_compensation || 0);
    if (directMin || directMax) {
      return {
        min: directMin || directMax,
        max: directMax || directMin
      };
    }

    const compensationText = extractCompensationFromHiringInfo(info) ||
      processed.listed_compensation_range ||
      processed.compensation_range ||
      item?.compensation_range ||
      item?.salary ||
      stripHtml(String(info?.description || item?.job_description || item?.description || ''));

    return parseCompensation(compensationText);
  };

  const extractCompensationFromHiringInfo = (info) => {
    if (!info || typeof info !== 'object') return '';

    if (typeof info.compensation_range === 'string') return info.compensation_range;
    if (typeof info.salary === 'string') return info.salary;

    const html = String(info.description || '');
    if (!html) return '';

    const matches = html.match(/\$[^<]{0,120}?(?:\d+[\d,]*\.?\d*\s*[kKmM]?(?:\s*[-–]\s*\$?\d+[\d,]*\.?\d*\s*[kKmM]?)?)/g);
    return matches?.[0] || '';
  };

  const dedupeState = {
    inFlightResponses: new Set(),
    seenJobIds: new Map()
  };

  const hiringPayloadBuffer = [];
  let lastHiringPayload = [];
  let lastHiringSendTimer = null;

  const pruneSeenJobIds = () => {
    const now = Date.now();
    for (const [id, ts] of dedupeState.seenJobIds.entries()) {
      if (now - ts > HIRING_SEEN_RETENTION_MS) dedupeState.seenJobIds.delete(id);
    }
  };

  const hashCode = (value) => {
    let hash = 0;
    for (let i = 0; i < value.length; i += 1) {
      hash = (hash * 31 + value.charCodeAt(i)) % 2147483647;
    }
    return String(hash);
  };
  const sendToBackground = (payload, reason) => {
    const jobArray = Array.isArray(payload) ? payload : [payload];

    if (!jobArray.length) return;
    if (!window.chrome?.runtime?.sendMessage) return;

    chrome.runtime.sendMessage({
      type: 'postJobPayload',
      payload: jobArray
    }, (_response) => {
      // best effort only
    });

    if (reason) {
      window.__jobScraperLastSendReason = reason;
    }
  };

  const handleHiringPayload = (payload, url = window.location.href) => {
    if (!payload) return;

    const keyRaw = `${window.location.href}::${JSON.stringify(payload).slice(0, 2000)}::${Date.now()}`;
    const key = `${window.location.pathname}|${hashCode(keyRaw)}`;

    if (dedupeState.inFlightResponses.has(key)) return;
    dedupeState.inFlightResponses.add(key);

    window.setTimeout(() => {
      dedupeState.inFlightResponses.delete(key);
    }, HIRING_DUPLICATE_WINDOW_MS);

    const jobs = normalizeHiringResponse(payload, url);
    if (!jobs.length) return;

    pruneSeenJobIds();
    const now = Date.now();
    const toSend = [];
    for (const job of jobs) {
      const seenAt = dedupeState.seenJobIds.get(job.job_id);
      if (seenAt && now - seenAt < HIRING_SEEN_RETENTION_MS) continue;
      dedupeState.seenJobIds.set(job.job_id, now);
      toSend.push(job);
    }

    if (!toSend.length) return;

    lastHiringPayload = toSend;

    for (const job of toSend) {
      hiringPayloadBuffer.push(job);
    }

    if (lastHiringSendTimer) return;

    lastHiringSendTimer = window.setTimeout(() => {
      const payloadToSend = [...hiringPayloadBuffer];
      hiringPayloadBuffer.length = 0;
      lastHiringSendTimer = null;
      sendToBackground(payloadToSend, 'hiring.search-jobs');
    }, AUTO_SEND_DELAY_MS);
  };

  const isHiringSearchApiUrl = (url) => {
    if (!url) return false;
    return /search-jobs/i.test(url) && !/get-total-count/i.test(url);
  };

  const isLinkedInJobDetailPage = () => {
    const host = window.location.hostname.replace(/^www\./, '').toLowerCase();
    if (!host.endsWith('linkedin.com')) return false;
    return /\/jobs\/view\/\d+/i.test(window.location.pathname);
  };

  const linkedInAutoState = {
    pendingTimer: null,
    lastUrl: '',
    sentJobIds: new Map()
  };

  const pruneLinkedInSentJobIds = () => {
    const now = Date.now();
    for (const [jobId, ts] of linkedInAutoState.sentJobIds.entries()) {
      if (now - ts > HIRING_SEEN_RETENTION_MS) linkedInAutoState.sentJobIds.delete(jobId);
    }
  };

  const attemptLinkedInAutoSend = (reason) => {
    if (!isLinkedInJobDetailPage()) return;

    const payload = scrapeJob();
    if (!Array.isArray(payload) || !payload.length) return;
    const job = payload[0];
    if (job.title === 'Unknown Title' && job.company_name === 'Unknown Company') return;
    if (!job.description && !job.apply_url) return;

    if (!job?.job_id) return;
    pruneLinkedInSentJobIds();

    const now = Date.now();
    const lastSent = linkedInAutoState.sentJobIds.get(job.job_id);
    if (lastSent && now - lastSent < HIRING_SEEN_RETENTION_MS) return;

    linkedInAutoState.sentJobIds.set(job.job_id, now);
    sendToBackground(payload, reason || 'linkedin.auto');
  };

  const scheduleLinkedInAutoScrape = (reason) => {
    if (!isLinkedInJobDetailPage()) return;

    if (linkedInAutoState.pendingTimer) {
      window.clearTimeout(linkedInAutoState.pendingTimer);
    }

    linkedInAutoState.pendingTimer = window.setTimeout(() => {
      linkedInAutoState.pendingTimer = null;
      attemptLinkedInAutoSend(reason);
    }, AUTO_SEND_DELAY_MS);
  };

  const installLinkedInAutoScrapeHooks = () => {
    if (window.__jobScraperLinkedInAutoHooksInstalled) return;
    window.__jobScraperLinkedInAutoHooksInstalled = true;

    const updateUrl = () => {
      const currentUrl = window.location.href;
      if (linkedInAutoState.lastUrl === currentUrl) return;
      linkedInAutoState.lastUrl = currentUrl;
      scheduleLinkedInAutoScrape('linkedin.url-change');
    };

    const originalPushState = window.history.pushState;
    const originalReplaceState = window.history.replaceState;

    window.history.pushState = function(...args) {
      const result = originalPushState.apply(this, args);
      updateUrl();
      return result;
    };

    window.history.replaceState = function(...args) {
      const result = originalReplaceState.apply(this, args);
      updateUrl();
      return result;
    };

    window.addEventListener('popstate', () => {
      updateUrl();
    });

    window.addEventListener('hashchange', () => {
      updateUrl();
    });

    const observerTarget = document.body || document.documentElement;
    if (observerTarget) {
      const observer = new MutationObserver(() => {
        scheduleLinkedInAutoScrape('linkedin.dom-mutation');
      });
      observer.observe(observerTarget, { childList: true, subtree: true, characterData: true });
    }

    scheduleLinkedInAutoScrape('linkedin.init');
  };

  const installHiringInterceptors = () => {
    if (window.__jobScraperHiringInterceptorsInstalled) return;
    window.__jobScraperHiringInterceptorsInstalled = true;

    const onHiringPayloadEvent = (event) => {
      const detail = event?.detail || {};
      if (!detail || !detail.payload) return;

      const sourceUrl = detail.url || detail.sourceUrl || window.location.href;
      handleHiringPayload(detail.payload, sourceUrl);
    };

    window.addEventListener('__jobScraperHiringPayload', onHiringPayloadEvent);
  };

  const scrapeHiringPageData = () => {
    const scripts = [
      document.getElementById('__NEXT_DATA__'),
      ...document.querySelectorAll('script[type="application/json"]')
    ].filter(Boolean);

    for (const script of scripts) {
      const raw = script.textContent || '';
      if (!raw || !/(job_information|v5_processed_job_data|v7_processed_job_data|objectID|job_title)/.test(raw)) continue;

      try {
        const data = JSON.parse(raw);
        const jobs = normalizeHiringResponse(data, window.location.href);
        if (jobs.length) return jobs;
      } catch (_err) {
        // ignore malformed page data
      }
    }

    return [];
  };

  const scheduleHiringPageDataScrape = () => {
    window.setTimeout(() => {
      const jobs = scrapeHiringPageData();
      if (jobs.length) {
        handleHiringPayload({ jobs }, window.location.href);
      }
    }, AUTO_SEND_DELAY_MS);
  };

  const scrapeJob = () => {
    if (isHiringCafeSearchPage()) {
      return lastHiringPayload.length ? lastHiringPayload : scrapeHiringPageData();
    }

    return [getLinkedInPayload()];
  };

  if (window.chrome?.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (!message || message.type !== 'scrapeJob') return;

      const payload = scrapeJob();
      sendResponse(payload);
    });
  }

  if (isHiringCafeSearchPage()) {
    installHiringInterceptors();
    scheduleHiringPageDataScrape();
  } else {
    installLinkedInAutoScrapeHooks();
  }
})();
