// RecallFabric Extension - Popup Controller

document.addEventListener("DOMContentLoaded", async () => {
  const connStatus = document.getElementById("connStatus");
  const profileSummary = document.getElementById("profileSummary");
  const openOptions = document.getElementById("openOptions");

  openOptions.addEventListener("click", () => {
    if (chrome.runtime.openOptionsPage) {
      chrome.runtime.openOptionsPage();
    } else {
      window.open(chrome.runtime.getURL("options.html"));
    }
  });

  chrome.storage.sync.get(
    {
      baseUrl: "http://localhost:8000",
      apiKey: "",
      userId: "default_user"
    },
    async (config) => {
      let cleanUrl = (config.baseUrl || "http://localhost:8000").replace(/\/$/, "");
      const headers = {};
      if (config.apiKey) {
        headers["Authorization"] = `Bearer ${config.apiKey}`;
        headers["X-API-Key"] = config.apiKey;
      }

      try {
        const res = await fetch(`${cleanUrl}/v1/profile`, { headers });
        if (res.ok) {
          connStatus.textContent = "Online";
          connStatus.className = "status-badge online";
          const data = await res.json();
          if (data && data.summary) {
            profileSummary.textContent = data.summary;
          } else if (data && data.profile) {
            profileSummary.textContent = JSON.stringify(data.profile, null, 2);
          } else {
            profileSummary.textContent = "No stored profile memories yet.";
          }
        } else {
          connStatus.textContent = `HTTP ${res.status}`;
          connStatus.className = "status-badge offline";
          profileSummary.textContent = "Unable to fetch profile. Check options and API key.";
        }
      } catch (err) {
        connStatus.textContent = "Offline";
        connStatus.className = "status-badge offline";
        profileSummary.textContent = `Error connecting to ${cleanUrl}: ${err.message}`;
      }
    }
  );
});
