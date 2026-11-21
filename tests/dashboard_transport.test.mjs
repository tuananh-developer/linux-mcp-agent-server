import test from 'node:test';
import assert from 'node:assert/strict';
import { McpClient, McpError } from '../src/linux_mcp_agent/web/mcp-client.mjs';

const response = (result, id, headers = {}) => new Response(JSON.stringify({ jsonrpc: '2.0', id, result }), { headers: { 'Content-Type': 'application/json', ...headers } });

test('negotiates a session and preserves auth/version headers; token clears on disconnect', async t => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    calls.push(options);
    if (options.method === 'DELETE') return new Response(null, { status: 200 });
    const body = JSON.parse(options.body);
    if (body.method === 'initialize') return response({ protocolVersion: '2025-11-25' }, body.id, { 'Mcp-Session-Id': 'session-1' });
    if (body.method === 'notifications/initialized') return new Response(null, { status: 202 });
    return response({ tools: [] }, body.id);
  });
  const client = new McpClient('/mcp');
  await client.connect('test-token');
  await client.list('tools/list');
  assert.equal(calls[0].headers.Authorization, 'Bearer test-token');
  assert.equal(calls[1].headers['Mcp-Session-Id'], 'session-1');
  assert.equal(calls[2].headers['MCP-Protocol-Version'], '2025-11-25');
  assert.equal(calls[0].redirect, 'error');
  await client.disconnect();
  assert.equal(calls.at(-1).method, 'DELETE');
  assert.equal(client.token, '');
  assert.equal(client.session, null);
});

test('parses fragmented SSE, skips notifications, and closes the reader after matching response', async t => {
  const wire = ': heartbeat\r\n\r\nevent: message\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\nevent: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\r\n\r\n';
  const encoder = new TextEncoder();
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { for (let i = 0; i < wire.length; i += 7) controller.enqueue(encoder.encode(wire.slice(i, i + 7))); },
    cancel() { cancelled = true; },
  });
  t.mock.method(globalThis, 'fetch', async () => new Response(stream, { headers: { 'content-type': 'text/event-stream' } }));
  const client = new McpClient('/mcp');
  assert.deepEqual(await client.request('tools/list'), { tools: [] });
  assert.equal(cancelled, true);
});

test('surfaces auth errors without reading or logging response bodies', async t => {
  const activities = [];
  t.mock.method(globalThis, 'fetch', async () => new Response('private diagnostic', { status: 401 }));
  const client = new McpClient('/mcp', event => activities.push(event));
  await assert.rejects(client.request('tools/list'), error => error instanceof McpError && error.status === 401 && !error.message.includes('private'));
  assert.deepEqual(Object.keys(activities[0]).sort(), ['method', 'ms', 'ok']);
  assert.equal(activities[0].ok, false);
});

test('rejects a tool error instead of treating it as healthy telemetry', async t => {
  t.mock.method(globalThis, 'fetch', async () => response({ isError: true, content: [{ type: 'text', text: 'INSUFFICIENT_SCOPE' }] }, 1));
  await assert.rejects(new McpClient('/mcp').callTool('read_allowed_log'), /INSUFFICIENT_SCOPE/);
});

test('collects paginated discovery and decodes text-only tool JSON', async t => {
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    const body = JSON.parse(options.body);
    if (body.method === 'tools/call') return response({ content: [{ type: 'text', text: '{"status":"ok"}' }] }, body.id);
    return response(body.params.cursor ? { tools: [{ name: 'second' }] } : { tools: [{ name: 'first' }], nextCursor: 'page2' }, body.id);
  });
  const client = new McpClient('/mcp');
  assert.deepEqual((await client.list('tools/list')).map(item => item.name), ['first', 'second']);
  assert.deepEqual(await client.callTool('get_system_metrics'), { status: 'ok' });
});

test('rejects responses from a session that has been disconnected', async t => {
  let resolveFetch;
  t.mock.method(globalThis, 'fetch', () => new Promise(resolve => { resolveFetch = resolve; }));
  const client = new McpClient('/mcp');
  const pending = client.request('tools/list');
  await client.disconnect();
  resolveFetch(response({ tools: [] }, 1, { 'Mcp-Session-Id': 'old-session' }));
  await assert.rejects(pending, /Kết nối đã thay đổi/);
  assert.equal(client.session, null);
});
