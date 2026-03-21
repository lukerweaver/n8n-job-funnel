const scrapeButton = document.getElementById('scrapeBtn');
const statusBox = document.getElementById('status');

const setStatus = (text) => {
  statusBox.textContent = text;
};

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

