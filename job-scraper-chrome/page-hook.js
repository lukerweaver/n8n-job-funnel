(() => {
  if (window.__jobScraperMainWorldHookInstalled) return;
  window.__jobScraperMainWorldHookInstalled = true;

  const isHiringSearchApiUrl = (url) => {
    if (!url) return false;
    return /search-jobs/i.test(url) && !/get-total-count/i.test(url);
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
      emitPayload(data, sourceUrl);
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

    if (!isHiringSearchApiUrl(requestUrl)) return response;

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
      if (!isHiringSearchApiUrl(requestUrl)) return;

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

