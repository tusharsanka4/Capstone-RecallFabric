// RecallFabric Extension - Options Controller

const defaultSettings = {
  baseUrl: "http://localhost:8000",
  apiKey: "",
  userId: "default_user",
  limit: 5,
  charBudget: 2000
};

document.addEventListener("DOMContentLoaded", () => {
  const baseUrlInput = document.getElementById("baseUrl");
  const apiKeyInput = document.getElementById("apiKey");
  const userIdInput = document.getElementById("userId");
  const limitInput = document.getElementById("limit");
  const charBudgetInput = document.getElementById("charBudget");
  const saveBtn = document.getElementById("saveBtn");
  const testBtn = document.getElementById("testBtn");
  const statusDiv = document.getElementById("status");

  // Load existing options
  chrome.storage.sync.get(defaultSettings, (items) => {
    baseUrlInput.value = items.baseUrl || defaultSettings.baseUrl;
    apiKeyInput.value = items.apiKey || "";
    userIdInput.value = items.userId || defaultSettings.userId;
    limitInput.value = items.limit || defaultSettings.limit;
    charBudgetInput.value = items.charBudget || defaultSettings.charBudget;
  });

  // Save settings
  saveBtn.addEventListener("click", () => {
    let cleanUrl = baseUrlInput.value.trim();
    if (cleanUrl.endsWith("/")) {
      cleanUrl = cleanUrl.slice(0, -1);
    }
    const newSettings = {
      baseUrl: cleanUrl || defaultSettings.baseUrl,
      apiKey: apiKeyInput.value.trim(),
      userId: userIdInput.value.trim() || defaultSettings.userId,
      limit: parseInt(limitInput.value, 10) || defaultSettings.limit,
      charBudget: parseInt(charBudgetInput.value, 10) || defaultSettings.charBudget
    };

    chrome.storage.sync.set(newSettings, () => {
      showStatus("Settings saved successfully!", "text-success");
    });
  });

  // Test connection
  testBtn.addEventListener("click", async () => {
    let cleanUrl = baseUrlInput.value.trim();
    if (cleanUrl.endsWith("/")) {
      cleanUrl = cleanUrl.slice(0, -1);
    }
    const apiKey = apiKeyInput.value.trim();
    showStatus("Connecting to RecallFabric...", "");

    try {
      const headers = {};
      if (apiKey) {
        headers["Authorization"] = `Bearer ${apiKey}`;
        headers["X-API-Key"] = apiKey;
      }
      const res = await fetch(`${cleanUrl}/v1/capabilities`, { headers });
      if (res.ok) {
        const data = await res.json();
        showStatus(`Connected! Version: ${data.version || "active"}`, "text-success");
      } else {
        showStatus(`Connection failed: HTTP ${res.status}`, "text-error");
      }
    } catch (err) {
      showStatus(`Error: ${err.message}`, "text-error");
    }
  });

  function showStatus(msg, className) {
    statusDiv.textContent = msg;
    statusDiv.className = className;
    if (className === "text-success") {
      setTimeout(() => {
        if (statusDiv.textContent === msg) {
          statusDiv.textContent = "";
        }
      }, 3000);
    }
  }
});
