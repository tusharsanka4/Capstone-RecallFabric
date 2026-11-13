/**
 * Unit & validation tests for RecallFabric JavaScript SDK.
 */

const assert = require('assert');
const { RecallFabric, withMemory, APIError, AuthenticationError } = require('./index.js');

async function runTests() {
  console.log('Testing RecallFabric JavaScript SDK...');

  // 1. Initialization and config defaults
  const client = new RecallFabric({
    baseUrl: 'http://localhost:9000',
    apiKey: 'rf_test_key',
    userId: 'user_js',
  });
  assert.strictEqual(client.baseUrl, 'http://localhost:9000/v1');
  assert.strictEqual(client.apiKey, 'rf_test_key');
  assert.strictEqual(client.userId, 'user_js');

  // 2. Error class hierarchy
  const authErr = new AuthenticationError('Token expired');
  assert.strictEqual(authErr.statusCode, 401);
  assert.strictEqual(authErr.name, 'AuthenticationError');
  assert(authErr instanceof APIError);

  // 3. withMemory wrapper unit test
  let capturedQuery = null;
  const mockClient = {
    async recall(opts) {
      capturedQuery = opts.query;
      return {
        context: '- [preference] Prefers dark mode and TypeScript',
        memories: [],
        count: 1,
      };
    },
    async remember() {
      return { status: 'created' };
    },
  };

  async function mockLlm(messages) {
    assert.strictEqual(messages[0].role, 'system');
    assert(messages[0].content.includes('Prefers dark mode and TypeScript'));
    return { content: 'Understood, setting up TypeScript project in dark mode.' };
  }

  const agent = withMemory(mockLlm, mockClient, { userId: 'dev_user' });
  const response = await agent([
    { role: 'user', content: 'What stack should we initialize?' },
  ]);

  assert.strictEqual(capturedQuery, 'What stack should we initialize?');
  assert(response.content.includes('TypeScript'));

  console.log('OK: All JavaScript SDK unit tests passed!');
}

runTests().catch((err) => {
  console.error('JS SDK Test Failed:', err);
  process.exit(1);
});
