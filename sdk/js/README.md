# @recallfabric/client

Official JavaScript/TypeScript SDK for [RecallFabric](https://github.com/tusharsanka4/Capstone-RecallFabric) — the persistent memory and context fabric for AI agents.

## Installation

```bash
npm install @recallfabric/client
```

## 5-Line Quickstart

```javascript
import { RecallFabric } from '@recallfabric/client';

const rf = new RecallFabric({ baseUrl: 'http://localhost:8000' });
await rf.remember('User prefers TypeScript and strict linting', { type: 'preference' });

const { context } = await rf.recall('coding preferences');
console.log(context);
```

## Automatic Memory Wrapper (`withMemory`)

Wrap any chat completion or LLM call to automatically retrieve context and extract memories in the background:

```javascript
import { RecallFabric, withMemory } from '@recallfabric/client';
import OpenAI from 'openai';

const openai = new OpenAI();
const rf = new RecallFabric();

// Define raw chat call
async function chat(messages) {
  const completion = await openai.chat.completions.create({
    model: 'gpt-4o-mini',
    messages,
  });
  return completion.choices[0].message.content;
}

// Wrap with memory
const chatWithMemory = withMemory(chat, rf, { userId: 'user_123' });

// Messages automatically get relevant memories injected into the system prompt!
const reply = await chatWithMemory([
  { role: 'user', content: 'What testing frameworks do I like?' }
]);
console.log(reply);
```

## Features

- **Universal Support**: Works in Node.js 18+ and modern browsers (native `fetch`).
- **Resilient**: Automatic exponential backoff retries on `429` and `5xx` errors.
- **Full TypeScript Definitions**: Strongly typed options and responses included.
- **Non-blocking Extraction**: Failures in background memory extraction never disrupt the conversation.
