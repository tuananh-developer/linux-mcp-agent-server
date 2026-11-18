import test from 'node:test';
import assert from 'node:assert/strict';
import { AgentRunner } from '../src/linux_mcp_agent/web/agent-client.mjs';

test('model chooses MCP tools and receives actual results before the final answer', async () => {
  const seen = [], events = [];
  let round = 0;
  const runner = new AgentRunner({ tools: () => [{ name: 'get_system_metrics' }], onEvent: e => events.push(e),
    generate: async messages => {
      seen.push(JSON.parse(JSON.stringify(messages)));
      return { message: round++ === 0 ? { role: 'assistant', content: '', tool_calls: [{ id: 'call_metrics', function: { name: 'get_system_metrics', arguments: {} } }] } : { role: 'assistant', content: 'CPU observed: 12%' } };
    }, execute: async name => { assert.equal(name, 'get_system_metrics'); return { cpuUsagePercent: 12 }; },
  });
  assert.equal(await runner.run('How is the host?'), 'CPU observed: 12%');
  assert.equal(JSON.parse(seen[1].at(-1).content).cpuUsagePercent, 12);
  assert.equal(seen[1].at(-1).role, 'tool');
  assert.equal(seen[1].at(-1).tool_call_id, 'call_metrics');
  assert.equal(events.filter(e => e.type === 'tool-result').length, 1);
});

test('does not execute unknown tools or logs without user consent', async () => {
  for (const name of ['run_shell', 'read_allowed_log']) {
    let round = 0, executed = false;
    const runner = new AgentRunner({ tools: () => [{ name: 'read_allowed_log' }],
      generate: async messages => ({ message: round++ === 0 ? { role: 'assistant', content: '', tool_calls: [{ function: { name, arguments: {} } }] } : { role: 'assistant', content: messages.at(-1).content } }),
      execute: async () => { executed = true; },
    });
    assert.match(await runner.run('Check'), /error/);
    assert.equal(executed, false);
  }
});

test('bounded loop rolls back unfinished conversations', async () => {
  const runner = new AgentRunner({ tools: () => [], execute: async () => {}, generate: async () => ({ message: { role: 'assistant', content: '', tool_calls: [{ function: { name: 'unknown', arguments: {} } }] } }) });
  await assert.rejects(runner.run('loop'), /5 vòng/);
  assert.equal(runner.running, false); assert.deepEqual(runner.messages, []);
});

test('cancellation prevents tool execution after a pending model response', async () => {
  const controller = new AbortController(); let executed = false;
  const runner = new AgentRunner({ tools: () => [{ name: 'get_system_metrics' }], execute: async () => { executed = true; }, generate: async () => { controller.abort(); return { message: { role: 'assistant', content: '', tool_calls: [{ function: { name: 'get_system_metrics', arguments: {} } }] } }; } });
  await assert.rejects(runner.run('check', { signal: controller.signal }), /dừng/);
  assert.equal(executed, false); assert.deepEqual(runner.messages, []);
});
