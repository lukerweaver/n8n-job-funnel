const scrapeButton = document.getElementById('scrapeBtn');
const statusBox = document.getElementById('status');
const apiBaseUrlInput = document.getElementById('apiBaseUrl');
const saveConfigButton = document.getElementById('saveConfigBtn');
const testConnectionButton = document.getElementById('testConnectionBtn');
const configStatusBox = document.getElementById('configStatus');

const setStatus = (text) => {
  statusBox.textContent = text;
};

const setConfigStatus = (text) => {
  if (configStatusBox) {
    configStatusBox.textContent = text;
  }
};

const setConfigControlsDisabled = (disabled) => {
  if (saveConfigButton) saveConfigButton.disabled = disabled;
  if (testConnectionButton) testConnectionButton.disabled = disabled;
};

const sendRuntimeMessage = (message) => chrome.runtime.sendMessage(message);

const loadConfig = async () => {
  if (!apiBaseUrlInput) return;

  try {
    const result = await sendRuntimeMessage({ type: 'getConfig' });
    if (result?.apiBaseUrl) {
      apiBaseUrlInput.value = result.apiBaseUrl;
      setConfigStatus(`Using ${result.apiBaseUrl}`);
    } else {
      setConfigStatus('Using the default local API URL.');
    }
  } catch (err) {
    setConfigStatus(`Could not load settings: ${String(err.message || err)}`);
  }
};

const saveConfig = async () => {
  if (!apiBaseUrlInput) return;

  setConfigControlsDisabled(true);
  setConfigStatus('Saving API URL...');

  try {
    const result = await sendRuntimeMessage({
      type: 'saveConfig',
      apiBaseUrl: apiBaseUrlInput.value
    });

    if (result?.ok) {
      apiBaseUrlInput.value = result.apiBaseUrl;
      setConfigStatus(`Saved ${result.apiBaseUrl}`);
    } else {
      setConfigStatus(`Could not save settings: ${result?.body || 'Unknown error'}`);
    }
  } catch (err) {
    setConfigStatus(`Could not save settings: ${String(err.message || err)}`);
  } finally {
    setConfigControlsDisabled(false);
  }
};

const testConnection = async () => {
  setConfigControlsDisabled(true);
  setConfigStatus('Testing connection...');

  try {
    const result = await sendRuntimeMessage({
      type: 'testConnection',
      apiBaseUrl: apiBaseUrlInput?.value
    });
    if (result?.ok) {
      setConfigStatus(`Connected to ${result.apiBaseUrl}.`);
    } else {
      setConfigStatus(`Could not reach the app. Status: ${result?.status ?? 0}`);
    }
  } catch (err) {
    setConfigStatus(`Could not reach the app: ${String(err.message || err)}`);
  } finally {
    setConfigControlsDisabled(false);
  }
};

if (saveConfigButton) {
  saveConfigButton.addEventListener('click', saveConfig);
}

if (testConnectionButton) {
  testConnectionButton.addEventListener('click', testConnection);
}

loadConfig();

scrapeButton.addEventListener('click', async () => {
  scrapeButton.disabled = true;
  setStatus('Collecting job data...');

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    if (!tab || !tab.id) {
      setStatus('No active tab found.');
      return;
    }

    const payload = await chrome.tabs.sendMessage(tab.id, { type: 'scrapeJob' });
    if (!payload) {
      setStatus('Could not scrape data. Are you on a supported job page?');
      return;
    }

    setStatus('Sending payload...');
    const result = await chrome.runtime.sendMessage({
      type: 'postJobPayload',
      payload
    });

    if (!result) {
      setStatus('No response from background.');
      return;
    }

    if (result.ok) {
      setStatus(`Sent successfully.\nStatus: ${result.status}`);
    } else {
      setStatus(`Failed to send.\nStatus: ${result.status}\n${result.body || ''}`);
    }
  } catch (err) {
    setStatus(`Error: ${String(err.message || err)}`);
  } finally {
    scrapeButton.disabled = false;
  }
});

