(() => {
  if (window.__jobScraperMainWorldHookInstalled) return;
  window.__jobScraperMainWorldHookInstalled = true;

  const isHiringSearchApiUrl = (url) => {
    if (!url) return false;
    return /search-jobs/i.test(url) && !/get-total-count/i.test(url);
  };

  const looksLikeHiringJob = (item) => {
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

  const hasHiringJobs = (value, depth = 0, seen = new Set()) => {
    if (!value || depth > 5) return false;
    if (typeof value !== 'object') return false;
    if (seen.has(value)) return false;
    seen.add(value);

    if (Array.isArray(value)) {
      return value.some((item) => looksLikeHiringJob(item) || hasHiringJobs(item, depth + 1, seen));
    }

    for (const key of ['jobs', 'hits', 'results', 'items', 'data']) {
      if (Array.isArray(value[key]) && value[key].some(looksLikeHiringJob)) return true;
    }

    return Object.values(value).some((child) => hasHiringJobs(child, depth + 1, seen));
  };

  const emitPayload = (payload, sourceUrl) => {
    if (!payload) return;

    try {
      const event = new CustomEvent('__jobScraperHiringPayload', {
        detail: {
          payload,
          sourceUrl: sourceUrl || ''
        }
      });
      window.dispatchEvent(event);
    } catch (_err) {
      // ignore emit errors
    }
  };

  const handleResponseText = (text, sourceUrl) => {
    if (!text) return;
    try {
      const data = JSON.parse(text);
      if (isHiringSearchApiUrl(sourceUrl) || hasHiringJobs(data)) {
        emitPayload(data, sourceUrl);
      }
    } catch (_err) {
      // ignore parse errors
    }
  };

  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const req = args[0];
    const requestUrl = typeof req === 'string'
      ? req
      : req?.url || '';

    const response = await originalFetch(...args);

    try {
      const cloned = response.clone();
      const text = await cloned.text();
      handleResponseText(text, requestUrl);
    } catch (_err) {
      // ignore parse errors
    }

    return response;
  };

  const originalXHROpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this.__jobScraperRequestUrl = typeof url === 'string' ? url : '';
    return originalXHROpen.call(this, method, url, ...rest);
  };

  const originalXHRSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function(body) {
    this.addEventListener('load', () => {
      const requestUrl = this.__jobScraperRequestUrl || '';

      const text = this.responseText || (typeof this.response === 'string' ? this.response : '');
      if (text) {
        handleResponseText(text, requestUrl);
        return;
      }

      if (typeof this.response === 'object' && this.response !== null) {
        try {
          handleResponseText(JSON.stringify(this.response), requestUrl);
        } catch (_err) {
          // ignore parse/serialize errors
        }
      }
    });

    return originalXHRSend.call(this, body);
  };
})();
