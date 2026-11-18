import { McpClient } from './mcp-client.mjs';
import { mountAgent } from './agent-ui.js';

const $ = id => document.getElementById(id);
const state = { connected: false, connecting: false, epoch: 0, tools: [] };
let toastTimer;

function toast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500);
}

function banner(message = '') {
  $('banner').textContent = message;
  $('banner').hidden = !message;
}

function renderConnection(label) {
  $('connection-open-top').dataset.state = state.connected ? 'online' : state.connecting ? 'checking' : 'offline';
  $('connection-status').textContent = label;
  $('sidebar-host').textContent = location.host;
  $('reconnect').disabled = state.connecting;
  $('connect-submit').disabled = state.connecting;
  $('disconnect').disabled = !state.connected;
  $('tool-count').textContent = state.connected
    ? `${state.tools.length} công cụ sẵn sàng`
    : 'Chưa khám phá';
}

const client = new McpClient('/mcp', entry => {
  const time = new Date().toLocaleTimeString('vi-VN');
  $('last-updated').textContent = `MCP · ${entry.ok ? 'phản hồi' : 'yêu cầu thất bại'} lúc ${time}`;
});
const agentUI = mountAgent({
  client,
  tools: () => state.tools,
  connected: () => state.connected,
  toast,
});

function openConnection() {
  $('endpoint-display').value = `${location.origin}/mcp`;
  if (!$('connection-dialog').open) $('connection-dialog').showModal();
}

async function connect(token = '') {
  if (state.connecting) return;
  const epoch = ++state.epoch;
  state.connecting = true;
  state.connected = false;
  state.tools = [];
  agentUI.reset();
  banner();
  $('connection-error').textContent = '';
  renderConnection('Đang kết nối');
  try {
    await client.connect(token);
    const tools = await client.list('tools/list');
    if (epoch !== state.epoch) return;
    state.tools = tools;
    state.connected = true;
    if ($('connection-dialog').open) $('connection-dialog').close();
    void agentUI.refreshStatus();
  } catch (error) {
    if (epoch !== state.epoch) return;
    const message = error instanceof Error ? error.message : 'Không thể kết nối MCP.';
    banner(message);
    $('connection-error').textContent = message;
    if (error.status === 401 || error.status === 403) openConnection();
  } finally {
    if (epoch === state.epoch) {
      state.connecting = false;
      renderConnection(state.connected ? 'MCP đã kết nối' : 'Chưa kết nối');
    }
  }
}

$('connection-open-top').addEventListener('click', openConnection);
$('close-dialog').addEventListener('click', () => $('connection-dialog').close());
$('connection-form').addEventListener('submit', event => {
  event.preventDefault();
  const token = $('bearer-token').value.trim();
  $('bearer-token').value = '';
  connect(token);
});
$('disconnect').addEventListener('click', async () => {
  const epoch = ++state.epoch;
  state.connected = false;
  state.connecting = false;
  state.tools = [];
  agentUI.reset();
  $('bearer-token').value = '';
  renderConnection('Đã ngắt kết nối');
  banner();
  $('connection-dialog').close();
  await client.disconnect();
  if (epoch === state.epoch) $('last-updated').textContent = 'Đã ngắt phiên MCP';
});
$('reconnect').addEventListener('click', () => connect(client.token));
// Old dashboard bookmarks now open the single supported AI workspace.
history.replaceState(null, '', '#agent');
connect();
