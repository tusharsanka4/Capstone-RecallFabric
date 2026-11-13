// RecallFabric Background Service Worker (Manifest V3)

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "rf_remember_selection",
    title: "🧠 Remember this with RecallFabric",
    contexts: ["selection"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "rf_remember_selection" && info.selectionText) {
    saveMemory(info.selectionText.trim());
  }
});

async function saveMemory(text) {
  if (!text) return;

  const config = await chrome.storage.sync.get({
    baseUrl: "http://localhost:8000",
    apiKey: "",
    userId: "default_user"
  });

  const cleanUrl = (config.baseUrl || "http://localhost:8000").replace(/\/$/, "");
  const headers = {
    "Content-Type": "application/json"
  };
  if (config.apiKey) {
    headers["Authorization"] = `Bearer ${config.apiKey}`;
    headers["X-API-Key"] = config.apiKey;
  }

  try {
    const res = await fetch(`${cleanUrl}/v1/remember`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        content: text,
        source: "browser_extension",
        extract: true
      })
    });

    if (res.ok) {
      notify("Memory Saved", `RecallFabric stored: "${text.slice(0, 60)}..."`);
    } else {
      const err = await res.text();
      notify("Failed to Save Memory", `Server returned HTTP ${res.status}: ${err.slice(0, 80)}`);
    }
  } catch (err) {
    notify("Error Saving Memory", `Could not reach ${cleanUrl}: ${err.message}`);
  }
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon48.png",
    title,
    message,
    silent: false
  }).catch(() => {
    // If notification fails (e.g. missing icon or permission), log it
    console.log(`[RecallFabric] ${title}: ${message}`);
  });
}

// Handle messages from content script for cross-origin or storage operations
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "RECALL_CONTEXT") {
    handleRecall(request.query)
      .then((data) => sendResponse({ success: true, data }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // Keep message channel open for async response
  }
  if (request.type === "REMEMBER_TEXT") {
    saveMemory(request.text)
      .then(() => sendResponse({ success: true }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  }
});

async function handleRecall(query) {
  const config = await chrome.storage.sync.get({
    baseUrl: "http://localhost:8000",
    apiKey: "",
    userId: "default_user",
    limit: 5,
    charBudget: 2000
  });

  const cleanUrl = (config.baseUrl || "http://localhost:8000").replace(/\/$/, "");
  const headers = {
    "Content-Type": "application/json"
  };
  if (config.apiKey) {
    headers["Authorization"] = `Bearer ${config.apiKey}`;
    headers["X-API-Key"] = config.apiKey;
  }

  const res = await fetch(`${cleanUrl}/v1/recall`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      query: query || "",
      limit: config.limit,
      char_budget: config.charBudget
    })
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`HTTP ${res.status}: ${errorText.slice(0, 100)}`);
  }

  return await res.json();
}
