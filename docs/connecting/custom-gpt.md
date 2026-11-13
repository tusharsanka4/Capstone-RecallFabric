# Custom GPT & Gemini Gem Integration Kit

This guide provides everything needed to connect **OpenAI Custom GPTs**, **Google Gemini Gems**, and no-code AI agent platforms (Dify, Coze, Voiceflow, Langflow) directly to RecallFabric via REST OpenAPI Actions.

---

## 1. Quick Setup Overview

| Component | Value |
|---|---|
| **OpenAPI Spec URL** | `https://<YOUR-HOST>/openapi.json` |
| **Authentication Type** | `API Key` |
| **Auth Header** | `Bearer` (or `Authorization: Bearer <YOUR_API_KEY>`) |
| **Target Endpoints** | `POST /v1/recall`, `POST /v1/remember`, `GET /v1/profile`, `POST /v1/forget` |

---

## 2. OpenAI Custom GPT Configuration

### Step A: Configure Actions Schema
1. Open [ChatGPT GPT Editor](https://chatgpt.com/gpts/editor).
2. Click **Configure** -> scroll down to **Actions** -> click **Create new action**.
3. Under **Authentication**, select:
   - **Authentication Type**: `API Key`
   - **Auth Type**: `Bearer`
   - Paste your RecallFabric API Key (`rf_...`).
4. In the **Schema** box, paste the following YAML (replace `https://api.recallfabric.example.com` with your deployment URL):

```yaml
openapi: 3.1.0
info:
  title: RecallFabric Memory Actions
  description: Persistent memory layer for Custom GPTs and Gemini Gems.
  version: 1.0.0
servers:
  - url: https://api.recallfabric.example.com
    description: RecallFabric Server
paths:
  /v1/recall:
    post:
      operationId: recallMemories
      summary: Recall relevant memories for a user query
      description: Searches the user's persistent memory fabric for relevant context, preferences, and facts.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                query:
                  type: string
                  description: The search query, question, or user prompt draft to recall memories for.
                limit:
                  type: integer
                  description: Maximum number of memories to return (default 5).
                  default: 5
                char_budget:
                  type: integer
                  description: Maximum character budget for the formatted context string.
                  default: 2000
              required:
                - query
      responses:
        '200':
          description: Ranked memories and ready-to-insert context string.
          content:
            application/json:
              schema:
                type: object
                properties:
                  memories:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                        content:
                          type: string
                        type:
                          type: string
                        score:
                          type: number
                  context:
                    type: string
                    description: Ready-to-use formatted context string.

  /v1/remember:
    post:
      operationId: rememberFact
      summary: Store or extract a durable memory
      description: Stores an explicit memory or automatically extracts atomic facts from conversation text.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                content:
                  type: string
                  description: The text or conversation excerpt to remember.
                type:
                  type: string
                  enum: [fact, preference, goal, belief, context]
                  description: Optional category of the memory.
                importance:
                  type: number
                  description: Importance rating between 0.0 and 1.0.
                source:
                  type: string
                  description: Provenance attribution tag.
                  default: custom_gpt
                extract:
                  type: boolean
                  description: Set to true to automatically extract atomic facts from unstructured text.
                  default: true
              required:
                - content
      responses:
        '200':
          description: Stored memory confirmation.
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  memories:
                    type: array
                    items:
                      type: object

  /v1/profile:
    get:
      operationId: getMemoryProfile
      summary: Get core user memory profile
      description: Retrieves the user's top durable memories, personal background, and global preferences.
      responses:
        '200':
          description: User memory profile.
          content:
            application/json:
              schema:
                type: object
                properties:
                  user_id:
                    type: string
                  summary:
                    type: string
                  total_memories:
                    type: integer

  /v1/forget:
    post:
      operationId: forgetMemory
      summary: Delete or invalidate a memory
      description: Removes an obsolete memory by exact ID or semantic search query.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                memory_id:
                  type: string
                  description: UUID of the specific memory to delete.
                query:
                  type: string
                  description: Search query identifying the memory to forget if ID is unknown.
                confirm:
                  type: boolean
                  description: Set to true to confirm deletion when searching by query.
                  default: true
      responses:
        '200':
          description: Deletion confirmation.
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  message:
                    type: string
```

---

## 3. Exact Instructions Text to Paste

In your Custom GPT **Instructions** or Gemini Gem **System Prompt** box, paste the following text:

```text
You are an intelligent assistant equipped with persistent, long-term memory powered by RecallFabric.

### HOW TO USE YOUR MEMORY:

1. PROACTIVE RECALL AT START:
   - When a conversation begins, call `getMemoryProfile` or `recallMemories` with a general query to ground yourself in the user's established preferences, background, and goals.
   - When the user asks a question that might depend on previous conversations or personal context (e.g., "what tech stack do I use?", "draft an email in my style", "resume our project"), call `recallMemories` with relevant keywords BEFORE formulating your response.

2. PROACTIVE SAVING (REMEMBERING):
   - Whenever the user shares a durable personal fact, preference, technical constraint, habit, or instruction (e.g., "I use Python 3.12 and prefer dark mode", "Never use semicolons", "I live in Berlin"), immediately call `rememberFact` with `extract=true`.
   - Do NOT ask for permission to remember unless the information is sensitive or ambiguous. Seamlessly store durable facts in the background while acknowledging the user's message naturally.

3. FORGETTING & CORRECTIONS:
   - If the user explicitly states that something is no longer true, or asks you to forget a past decision (e.g., "I no longer drink coffee", "forget my previous address"), call `forgetMemory` with the search query or memory ID.

4. SEAMLESS INTEGRATION:
   - Never say "According to my RecallFabric tool..."; simply speak naturally with the benefit of the recalled context, just as a human colleague would remember past interactions.
```

---

## 4. Google Gemini Gems & Agent Platforms

For platforms requiring a raw OpenAPI specification URL:
- Provide your hosted instance URL: `https://<YOUR-HOST>/openapi.json`.
- Or upload the Action Schema YAML above into the platform's API/Tools section.
- Set Header Name: `Authorization` with value `Bearer <YOUR_API_KEY>`.
