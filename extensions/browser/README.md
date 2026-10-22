# RecallFabric Browser Extension (Manifest V3)

A lightweight web extension that brings persistent cross-model memory to ChatGPT, Claude, and Google Gemini web interfaces.

---

## Features

1. **Prompt Injection ("Recall")**: Injects a clean `🧠 Recall` button into chat prompt areas on `chatgpt.com`, `claude.ai`, and `gemini.google.com`. Clicking it searches RecallFabric for memories relevant to your prompt draft and prepends them as structured context directly into the text box.
2. **Context Menu ("Remember this")**: Select any text on any webpage, right-click, and select **"🧠 Remember this with RecallFabric"** to asynchronously store the memory using `POST /v1/remember` with automatic atomic fact extraction.
3. **Popup Overview**: Click the extension icon to view service connectivity and a live summary of your active user profile memories.
4. **Options Page**: Easily configure your RecallFabric base URL, API key (`rf_...`), user ID, recall limit, and character budget.

---

## Installation & Setup

1. Open your Chromium-based browser (Chrome, Edge, Brave, Arc, Opera).
2. Navigate to `chrome://extensions/` (or `edge://extensions/`).
3. Enable **Developer mode** toggle in the top-right corner.
4. Click **Load unpacked** and select the folder:
   ```
   <repo-root>/extensions/browser
   ```
5. Right-click the extension icon in your toolbar, select **Options**, and configure:
   - **Base URL**: e.g., `http://localhost:8000` or your cloud deployment `https://api.yourdomain.com`
   - **API Key**: your `rf_...` secret token (leave blank if local auth is disabled)
   - Click **Save Settings** and **Test Connection**.

---

## Documented Limitations

While the extension provides instantaneous memory access without code changes, be aware of the following web platform limitations:

1. **Dynamic Single Page Application (SPA) DOM Structure**:
   - ChatGPT, Claude, and Gemini frequently update their web clients and obfuscate CSS classes or DOM nesting. While this extension uses flexible selector heuristics (`#prompt-textarea`, `rich-textarea`, `.ProseMirror`, and contenteditable selectors) combined with a `MutationObserver`, major upstream redesigns may temporarily require selector adjustments.
2. **ContentEditable vs. Native Textarea**:
   - Modern chat interfaces use rich content-editable divs (ProseMirror / Draft.js / Quill) rather than standard `<textarea>` elements. Synthetic dispatch of `InputEvent` and `document.execCommand('insertText')` is used to trigger client-side React/Angular state updates. In some browsers, manual user focus on the input box before clicking Recall may be required.
3. **Content Security Policy (CSP) & CORS**:
   - Some enterprise web environments or browser configurations enforce strict CSP rules blocking content scripts from fetching external APIs directly. This extension routes all network requests through the background service worker (`background.js`), which utilizes Chrome's privileged background permissions to bypass page-level CSP.
4. **Token & Character Budgets**:
   - Web chat input boxes do not automatically manage upstream LLM token budgets. The extension adheres to your configured `charBudget` (default: 2,000 characters) to avoid overflowing chat prompt limits.
5. **No Automatic Conversation Ingestion on Web Clients**:
   - Web chats do not expose conversation completion hooks to extensions. To persist memories from web chats, use the right-click **"Remember this"** action on any model answer or prompt text, or point programmatic apps at the OpenAI-compatible proxy (`POST /v1/proxy/chat/completions`).
