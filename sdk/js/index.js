/**
 * RecallFabric JavaScript Client SDK (CommonJS)
 */

class RecallFabricError extends Error {
  constructor(message) {
    super(message);
    this.name = 'RecallFabricError';
  }
}

class APIError extends RecallFabricError {
  constructor(statusCode, message, code = 'API_ERROR', details = null) {
    super(`[${code}] ${message} (HTTP ${statusCode})`);
    this.name = 'APIError';
    this.statusCode = statusCode;
    this.code = code;
    this.details = details;
  }
}

class AuthenticationError extends APIError {
  constructor(message = 'Invalid or missing API key.', details = null) {
    super(401, message, 'AUTHENTICATION_ERROR', details);
    this.name = 'AuthenticationError';
  }
}

class PermissionDeniedError extends APIError {
  constructor(message = 'Access forbidden.', details = null) {
    super(403, message, 'PERMISSION_DENIED', details);
    this.name = 'PermissionDeniedError';
  }
}

class NotFoundError extends APIError {
  constructor(message = 'Resource not found.', details = null) {
    super(404, message, 'NOT_FOUND', details);
    this.name = 'NotFoundError';
  }
}

class RateLimitError extends APIError {
  constructor(message = 'Rate limit exceeded. Please back off.', details = null) {
    super(429, message, 'RATE_LIMIT_EXCEEDED', details);
    this.name = 'RateLimitError';
  }
}

class TimeoutError extends RecallFabricError {
  constructor(message = 'Request timed out.') {
    super(message);
    this.name = 'TimeoutError';
  }
}

class ConnectionError extends RecallFabricError {
  constructor(message = 'Connection failed.') {
    super(message);
    this.name = 'ConnectionError';
  }
}

const RETRY_STATUS_CODES = new Set([429, 500, 502, 503, 504]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolveBaseUrl(url) {
  let base = (url || (typeof process !== 'undefined' && process.env?.RECALLFABRIC_BASE_URL) || 'http://localhost:8000').replace(/\/+$/, '');
  if (!base.endsWith('/v1')) {
    base = `${base}/v1`;
  }
  return base;
}

class RecallFabric {
  constructor(config = {}) {
    this.baseUrl = resolveBaseUrl(config.baseUrl);
    this.apiKey = config.apiKey || (typeof process !== 'undefined' ? process.env?.RECALLFABRIC_API_KEY : undefined);
    this.userId = config.userId;
    this.timeoutMs = config.timeoutMs || 15000;
    this.maxRetries = config.maxRetries !== undefined ? config.maxRetries : 3;
    this.backoffFactor = config.backoffFactor || 0.5;
  }

  async _request(method, path, options = {}) {
    const url = path.startsWith('http') ? path : `${this.baseUrl}${path}`;
    const headers = {
      'Content-Type': 'application/json',
      'User-Agent': 'recallfabric-js-client/0.1.0',
      ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}),
      ...(options.headers || {}),
    };

    let lastError = null;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        let timeoutId = null;
        if (controller && this.timeoutMs) {
          timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);
        }

        const fetchOptions = {
          method,
          headers,
          signal: controller ? controller.signal : undefined,
          ...(options.body ? { body: JSON.stringify(options.body) } : {}),
        };

        const res = await fetch(url, fetchOptions);
        if (timeoutId) clearTimeout(timeoutId);

        if (RETRY_STATUS_CODES.has(res.status) && attempt < this.maxRetries) {
          const delay = this.backoffFactor * Math.pow(2, attempt) * 1000;
          await sleep(delay);
          continue;
        }

        if (!res.ok) {
          let errCode = 'API_ERROR';
          let errMsg = res.statusText;
          let details = null;
          try {
            const data = await res.json();
            details = data;
            if (data?.error) {
              errCode = data.error.code || 'API_ERROR';
              errMsg = data.error.message || errMsg;
            } else if (data?.detail) {
              errMsg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
            }
          } catch (_) {
            errMsg = await res.text().catch(() => res.statusText);
          }

          if (res.status === 401) throw new AuthenticationError(errMsg, details);
          if (res.status === 403) throw new PermissionDeniedError(errMsg, details);
          if (res.status === 404) throw new NotFoundError(errMsg, details);
          if (res.status === 429) throw new RateLimitError(errMsg, details);
          throw new APIError(res.status, errMsg, errCode, details);
        }

        if (res.status === 204) {
          return null;
        }
        return await res.json();
      } catch (err) {
        if (err instanceof APIError) {
          throw err;
        }
        if (err?.name === 'AbortError') {
          if (attempt < this.maxRetries) {
            await sleep(this.backoffFactor * Math.pow(2, attempt) * 1000);
            continue;
          }
          throw new TimeoutError(`Request to ${url} timed out.`);
        }
        if (attempt < this.maxRetries) {
          await sleep(this.backoffFactor * Math.pow(2, attempt) * 1000);
          continue;
        }
        throw new ConnectionError(`Failed to fetch ${url}: ${err.message}`);
      }
    }

    throw lastError || new RecallFabricError('Request failed after max retries.');
  }

  async remember(options) {
    const opts = typeof options === 'string' ? { content: options } : options;
    const payload = {
      type: opts.type || 'fact',
      confidence: opts.confidence !== undefined ? opts.confidence : 1.0,
      source: opts.source || 'js_sdk',
      extract: Boolean(opts.extract),
    };
    if (opts.content !== undefined) payload.content = opts.content;
    if (opts.text !== undefined) payload.text = opts.text;
    if (opts.importance !== undefined) payload.importance = opts.importance;
    const uid = opts.userId || this.userId;
    if (uid) payload.user_id = uid;
    if (opts.metadata) payload.metadata = opts.metadata;

    const headers = {};
    if (opts.idempotencyKey) {
      headers['Idempotency-Key'] = opts.idempotencyKey;
    }

    return await this._request('POST', '/remember', { body: payload, headers });
  }

  async recall(options) {
    const opts = typeof options === 'string' ? { query: options } : options;
    const payload = {
      query: opts.query,
      limit: opts.limit || 5,
    };
    if (opts.type) payload.type = opts.type;
    if (opts.minSimilarity !== undefined) payload.min_similarity = opts.minSimilarity;
    const uid = opts.userId || this.userId;
    if (uid) payload.user_id = uid;

    return await this._request('POST', '/recall', { body: payload });
  }

  async forget(options) {
    const payload = { confirm: Boolean(options.confirm) };
    if (options.memoryId) payload.memory_id = options.memoryId;
    if (options.query) payload.query = options.query;
    const uid = options.userId || this.userId;
    if (uid) payload.user_id = uid;

    return await this._request('POST', '/forget', { body: payload });
  }

  async profile(options = {}) {
    const params = new URLSearchParams();
    if (options.limit) params.set('limit', String(options.limit));
    const uid = options.userId || this.userId;
    if (uid) params.set('user_id', uid);

    const query = params.toString() ? `?${params.toString()}` : '';
    return await this._request('GET', `/profile${query}`);
  }

  async capabilities() {
    return await this._request('GET', '/capabilities');
  }

  async list(options = {}) {
    const params = new URLSearchParams();
    if (options.status) params.set('status', options.status);
    if (options.type) params.set('type', options.type);
    if (options.limit) params.set('limit', String(options.limit));
    if (options.offset) params.set('offset', String(options.offset));
    const uid = options.userId || this.userId;
    if (uid) params.set('user_id', uid);

    const query = params.toString() ? `?${params.toString()}` : '';
    return await this._request('GET', `/memories${query}`);
  }

  async update(memoryId, options = {}) {
    const payload = {};
    if (options.content !== undefined) payload.content = options.content;
    if (options.type !== undefined) payload.type = options.type;
    if (options.importance !== undefined) payload.importance = options.importance;

    const params = new URLSearchParams();
    const uid = options.userId || this.userId;
    if (uid) params.set('user_id', uid);
    const query = params.toString() ? `?${params.toString()}` : '';

    return await this._request('PATCH', `/memories/${memoryId}${query}`, { body: payload });
  }
}

function withMemory(llmCall, client, options = {}) {
  const {
    userId,
    extractAfter = true,
    limit = 5,
    minSimilarity,
    contextTemplate = 'Relevant User Memories:\n{context}\n\n',
  } = options;

  return async function wrapped(messages, ...args) {
    let lastQuery = '';
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        lastQuery = messages[i].content || '';
        break;
      }
    }
    if (!lastQuery && messages.length > 0) {
      lastQuery = messages[messages.length - 1].content || '';
    }

    const clonedMessages = JSON.parse(JSON.stringify(messages));

    if (lastQuery) {
      try {
        const recallRes = await client.recall({
          query: lastQuery,
          limit,
          minSimilarity,
          userId,
        });

        if (recallRes?.context) {
          const formatted = contextTemplate.replace('{context}', recallRes.context.trim());
          if (clonedMessages.length > 0 && clonedMessages[0].role === 'system') {
            clonedMessages[0].content = `${formatted}${clonedMessages[0].content}`;
          } else {
            clonedMessages.unshift({ role: 'system', content: formatted });
          }
        }
      } catch (err) {
        console.warn('RecallFabric: memory recall failed; proceeding without memories:', err?.message || err);
      }
    }

    const response = await llmCall(clonedMessages, ...args);

    if (extractAfter && lastQuery) {
      const respText = typeof response === 'string' ? response : (response?.content || response?.text || JSON.stringify(response));
      const exchange = `User: ${lastQuery}\nAssistant: ${respText}`;

      // Non-blocking fire-and-forget extraction
      client.remember({
        text: exchange,
        extract: true,
        userId,
        source: 'with_memory_js',
      }).catch((bgErr) => {
        // Silently ignore background failures so chat never breaks
      });
    }

    return response;
  };
}

module.exports = {
  RecallFabric,
  withMemory,
  RecallFabricError,
  APIError,
  AuthenticationError,
  PermissionDeniedError,
  NotFoundError,
  RateLimitError,
  TimeoutError,
  ConnectionError,
};
