const POST_ENDPOINT = 'http://localhost:8000/jobs/ingest';

chrome.runtime.onMessage.addListener(async (message, _sender, sendResponse) => {
  if (!message || message.type !== 'postJobPayload') return;

  const bodyPayload = Array.isArray(message.payload) ? message.payload : [message.payload];

  try {
    const response = await fetch(POST_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(bodyPayload)
    });

    const text = await response.text();
    sendResponse({
      ok: response.ok,
      status: response.status,
      body: text
    });
  } catch (err) {
    sendResponse({
      ok: false,
      status: 0,
      body: String(err)
    });
  }

  return true;
});
