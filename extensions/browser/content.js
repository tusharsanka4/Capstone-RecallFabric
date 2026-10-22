// RecallFabric Content Script for ChatGPT, Claude, and Gemini

(function () {
  "use strict";

  const BUTTON_ID = "rf-injected-recall-button";
  let lastInjectedTarget = null;

  function findChatInput() {
    const hostname = window.location.hostname;

    if (hostname.includes("chatgpt.com") || hostname.includes("openai.com")) {
      return (
        document.querySelector("#prompt-textarea") ||
        document.querySelector("div[contenteditable='true'][data-placeholder]") ||
        document.querySelector("textarea")
      );
    }

    if (hostname.includes("claude.ai")) {
      return (
        document.querySelector(".ProseMirror[contenteditable='true']") ||
        document.querySelector("div[contenteditable='true']") ||
        document.querySelector("textarea")
      );
    }

    if (hostname.includes("gemini.google.com")) {
      return (
        document.querySelector("rich-textarea div[contenteditable='true']") ||
        document.querySelector("div[contenteditable='true']") ||
        document.querySelector("textarea")
      );
    }

    return document.querySelector("textarea") || document.querySelector("div[contenteditable='true']");
  }

  function getInputValue(element) {
    if (!element) return "";
    if (element.tagName === "TEXTAREA" || element.tagName === "INPUT") {
      return element.value || "";
    }
    return element.innerText || element.textContent || "";
  }

  function insertTextIntoInput(element, newText) {
    if (!element) return;
    element.focus();

    if (element.tagName === "TEXTAREA" || element.tagName === "INPUT") {
      const current = element.value || "";
      const separator = current.trim().length > 0 ? "\n\n" : "";
      element.value = `${newText}${separator}${current}`;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      // ContentEditable elements (ChatGPT ProseMirror / Gemini)
      try {
        const success = document.execCommand("insertText", false, `${newText}\n\n`);
        if (!success) {
          throw new Error("execCommand failed");
        }
      } catch {
        const textNode = document.createTextNode(`${newText}\n\n`);
        element.prepend(textNode);
        element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
      }
    }
  }

  function showToast(message, isError = false) {
    let toast = document.getElementById("rf-toast-notification");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "rf-toast-notification";
      toast.className = "rf-toast";
      document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.className = `rf-toast visible ${isError ? "error" : ""}`;
    setTimeout(() => {
      toast.className = "rf-toast";
    }, 3500);
  }

  function handleRecallClick(inputElement, button) {
    const existingPrompt = getInputValue(inputElement).trim();
    const query = existingPrompt.length > 0 ? existingPrompt : "";

    button.classList.add("loading");
    button.textContent = "🧠 Recalling...";

    chrome.runtime.sendMessage(
      { type: "RECALL_CONTEXT", query },
      (response) => {
        button.classList.remove("loading");
        button.textContent = "🧠 Recall";

        if (!response || !response.success) {
          const err = response?.error || "Could not connect to RecallFabric";
          showToast(`Recall failed: ${err}`, true);
          return;
        }

        const data = response.data;
        const context = data?.context || "";
        const count = data?.memories?.length || 0;

        if (!context || count === 0) {
          showToast("No relevant memories found.");
          return;
        }

        insertTextIntoInput(inputElement, context);
        showToast(`Injected ${count} relevant memories into prompt!`);
      }
    );
  }

  function injectRecallButton() {
    const inputElement = findChatInput();
    if (!inputElement) return;

    if (document.getElementById(BUTTON_ID) && lastInjectedTarget === inputElement) {
      return;
    }

    // Remove stale button if target shifted
    const oldBtn = document.getElementById(BUTTON_ID);
    if (oldBtn) oldBtn.remove();

    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.className = "rf-recall-btn";
    button.innerHTML = "<span>🧠</span><span>Recall</span>";
    button.title = "Recall relevant memories from RecallFabric and insert into prompt";

    button.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleRecallClick(inputElement, button);
    });

    // Determine injection site: parent container of input element
    const container = inputElement.closest("form") || inputElement.parentElement;
    if (container) {
      container.insertBefore(button, container.firstChild);
      lastInjectedTarget = inputElement;
    }
  }

  // Periodic and observer check for SPA page transitions
  const observer = new MutationObserver(() => {
    injectRecallButton();
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true
  });

  // Initial check
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectRecallButton);
  } else {
    injectRecallButton();
  }
})();
