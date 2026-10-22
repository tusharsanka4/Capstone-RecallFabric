# RecallFabric Client SDKs

Official client libraries for [RecallFabric](https://github.com/tusharsanka4/Capstone-RecallFabric) — the persistent memory and context fabric for AI agents.

Add production-ready persistent agent memory in just a few lines of code.

---

## Python Quickstart (`recallfabric-client`)

### 1. Installation

```bash
pip install recallfabric-client
```

### 2. 5-Line Quickstart

```python
from recallfabric_client import RecallFabric

rf = RecallFabric(base_url="http://localhost:8000")
rf.remember("User prefers Python and dark mode in all editors", type="preference")

memories = rf.recall("editor preferences")
print(memories.context)
```

### 3. Universal LLM Wrapper (`with_memory`)

Drop memory onto any chat completion function without modifying internal prompt logic:

```python
from recallfabric_client import RecallFabric, with_memory

rf = RecallFabric()


# Wrap any function that takes a list of chat messages:
@with_memory(client=rf, user_id="user_123")
def chat(messages):
    return call_my_model(messages)


# Context automatically recalled and injected into system message!
response = chat([{"role": "user", "content": "What was my favorite editor theme?"}])
```

### 4. Framework Adapters

#### LangChain
```python
from recallfabric_client.adapters.langchain import RecallFabricRetriever, RecallFabricMemory

retriever = RecallFabricRetriever(user_id="user_123", limit=5)
docs = retriever.invoke("What are my project preferences?")

memory = RecallFabricMemory(user_id="user_123")
```

#### LlamaIndex
```python
from recallfabric_client.adapters.llamaindex import RecallFabricLlamaIndexRetriever

retriever = RecallFabricLlamaIndexRetriever(user_id="user_123")
nodes = retriever.retrieve("deployment architecture")
```

---

## JavaScript / TypeScript Quickstart (`@recallfabric/client`)

### 1. Installation

```bash
npm install @recallfabric/client
```

### 2. 5-Line Quickstart

```javascript
import { RecallFabric } from '@recallfabric/client';

const rf = new RecallFabric({ baseUrl: 'http://localhost:8000' });
await rf.remember('User prefers TypeScript and strict linting', { type: 'preference' });

const { context } = await rf.recall('coding preferences');
console.log(context);
```

### 3. Universal LLM Wrapper (`withMemory`)

```javascript
import { RecallFabric, withMemory } from '@recallfabric/client';

const rf = new RecallFabric();

async function chat(messages) {
  return await callOpenAIOrClaude(messages);
}

const chatWithMemory = withMemory(chat, rf, { userId: 'user_123' });

const reply = await chatWithMemory([
  { role: 'user', content: 'What coding standards do I follow?' }
]);
console.log(reply);
```

---

## Environment Variables

Both SDKs automatically configure themselves from standard environment variables:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `RECALLFABRIC_BASE_URL` | Base URL of the deployed RecallFabric service | `http://localhost:8000` |
| `RECALLFABRIC_API_KEY` | Bearer API token for authenticated environments | `None` (unauthenticated local mode) |

---

## Working Examples

Check out runnable end-to-end examples comparing agents with and without memory:
- [`examples/openai_agent.py`](../examples/openai_agent.py): OpenAI agent demo.
- [`examples/anthropic_agent.py`](../examples/anthropic_agent.py): Anthropic Claude agent demo.
- [`examples/gemini_agent.py`](../examples/gemini_agent.py): Google Gemini agent demo.
