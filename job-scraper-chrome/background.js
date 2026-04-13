const DEFAULT_API_BASE_URL = 'http://localhost:8000';
const API_BASE_URL_KEY = 'apiBaseUrl';

function normalizeApiBaseUrl(value) {
  const trimmed = String(value || '').trim().replace(/\/+$/, '');
  return trimmed || DEFAULT_API_BASE_URL;
}

function getApiBaseUrl() {
  return new Promise((resolve) => {
    if (!chrome.storage?.sync?.get) {
      resolve(DEFAULT_API_BASE_URL);
      return;
    }

    chrome.storage.sync.get({ [API_BASE_URL_KEY]: DEFAULT_API_BASE_URL }, (items) => {
      resolve(normalizeApiBaseUrl(items?.[API_BASE_URL_KEY]));
    });
  });
}

function setApiBaseUrl(value) {
  return new Promise((resolve, reject) => {
    const apiBaseUrl = normalizeApiBaseUrl(value);

    if (!chrome.storage?.sync?.set) {
      resolve(apiBaseUrl);
      return;
    }

    chrome.storage.sync.set({ [API_BASE_URL_KEY]: apiBaseUrl }, () => {
      if (chrome.runtime?.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }

      resolve(apiBaseUrl);
    });
  });
}

async function postJobPayload(payload) {
  const bodyPayload = Array.isArray(payload) ? payload : [payload];
  const apiBaseUrl = await getApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/jobs/ingest`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(bodyPayload)
  });

  const text = await response.text();
  return {
    ok: response.ok,
    status: response.status,
    body: text
  };
}

async function testConnection() {
  const apiBaseUrl = await getApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/health`);
  const text = await response.text();

  return {
    ok: response.ok,
    status: response.status,
    body: text,
    apiBaseUrl
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message) return;

  if (message.type === 'postJobPayload') {
    postJobPayload(message.payload)
      .then(sendResponse)
      .catch((err) => {
        sendResponse({
          ok: false,
          status: 0,
          body: String(err)
        });
      });
    return true;
  }

  if (message.type === 'getConfig') {
    getApiBaseUrl()
      .then((apiBaseUrl) => sendResponse({ ok: true, apiBaseUrl }))
      .catch((err) => sendResponse({ ok: false, body: String(err), apiBaseUrl: DEFAULT_API_BASE_URL }));
    return true;
  }

  if (message.type === 'saveConfig') {
    setApiBaseUrl(message.apiBaseUrl)
      .then((apiBaseUrl) => sendResponse({ ok: true, apiBaseUrl }))
      .catch((err) => sendResponse({ ok: false, body: String(err) }));
    return true;
  }

  if (message.type === 'testConnection') {
    const test = message.apiBaseUrl === undefined
      ? testConnection()
      : setApiBaseUrl(message.apiBaseUrl).then(testConnection);

    test
      .then(sendResponse)
      .catch((err) => sendResponse({ ok: false, status: 0, body: String(err) }));
    return true;
  }
});
