import { AgentRunner } from './agent-client.mjs';
import { parseMarkdown } from './markdown.mjs';

const PROVIDER_DEFAULTS = {
  gemini: 'gemini-3.8-flash',
  openai: 'gpt-4.1-mini',
  openrouter: 'openrouter/free',
  anthropic: 'claude-sonnet-4-6',
  ollama: 'qwen3:4b',
};
const PROVIDER_LABELS = {
  gemini: 'Google Gemini',
  openai: 'OpenAI',
  openrouter: 'OpenRouter (free model)',
  anthropic: 'Anthropic Claude',
  ollama: 'Ollama',
};
let savedCredentials = new Map();

const MARKDOWN_TAGS = new Set([
  'a', 'blockquote', 'code', 'div', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'hr', 'li', 'ol', 'p', 'pre', 's', 'strong', 'table', 'tbody', 'td', 'th',
  'thead', 'tr', 'ul',
]);

export function mountAgent({ client, tools, connected, toast, getAccessToken }) {
  const $ = id => document.getElementById(id);
  const input = $('chat-input');
  const transcript = $('chat-messages');
  const welcome = $('chat-welcome');
  const consent = $('agent-allow-logs');
  const progress = $('agent-progress');
  const usageLabel = $('agent-usage');
  let controller = null;
  let ready = false;
  let epoch = 0;
  let usage = { input: 0, output: 0 };
  let providerConfig = null;
  let providerKey = '';

  function updateProviderPrivacyNote(remembered) {
    $('agent-privacy-note').textContent = remembered
      ? 'API key được mã hóa AES-256-GCM và lưu trên MCP Server theo tài khoản Keycloak của bạn. Master key nằm riêng và được systemd cấp cho tiến trình; trình duyệt không nhận lại API key. Quyền truy cập vẫn phụ thuộc bảo mật của máy chủ và tài khoản quản trị.'
      : 'API key chỉ giữ trong bộ nhớ tab và gửi qua HTTPS tới gateway. Bật tùy chọn lưu trên MCP Server để mã hóa và dùng lại trên các trình duyệt đã đăng nhập cùng tài khoản Keycloak. Chỉ gửi log khi bạn cấp quyền đọc log.';
  }

  async function loadSavedCredentials() {
    const response = await fetch('/agent/credentials', {
      method: 'GET',
      headers: await headers(),
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Không thể đọc cấu hình credential đã lưu.');
    const entries = Array.isArray(data.credentials) ? data.credentials : [];
    savedCredentials = new Map(entries
      .filter(item => item && typeof item.provider === 'string' &&
        typeof item.model === 'string' && typeof item.updated_at === 'number')
      .map(item => [item.provider, { model: item.model, updated_at: item.updated_at }]));
    return savedCredentials;
  }

  async function deleteSavedCredential(provider) {
    const response = await fetch('/agent/credentials/' + encodeURIComponent(provider), {
      method: 'DELETE',
      headers: await headers(),
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Không thể xóa API key đã lưu.');
    savedCredentials.delete(provider);
    return data.deleted === true;
  }

  async function headers() {
    const token = await getAccessToken();
    if (!token) throw new Error('Phiên Keycloak đã hết hạn. Hãy đăng nhập lại bằng Keycloak.');
    return {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + token,
    };
  }

  function appendToTranscript(node, follow = false) {
    const nearBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 40;
    welcome.hidden = true;
    transcript.hidden = false;
    transcript.append(node);
    if (follow || nearBottom) transcript.scrollTop = transcript.scrollHeight;
  }

  function appendMarkdownNode(parent, item) {
    if (item.type === 'text') {
      parent.append(document.createTextNode(item.value));
      return;
    }

    if (!MARKDOWN_TAGS.has(item.tag)) {
      parent.append(document.createTextNode(item.children.map(child => child.value ?? '').join('')));
      return;
    }

    const child = document.createElement(item.tag);
    for (const [name, value] of Object.entries(item.attributes ?? {})) {
      if (name === 'className' && typeof value === 'string') {
        child.className = value;
      } else if (name === 'data-align' && ['left', 'center', 'right'].includes(value)) {
        child.setAttribute(name, value);
      } else if (name === 'href' && item.tag === 'a' && typeof value === 'string') {
        try {
          const url = new URL(value);
          if (url.protocol === 'http:' || url.protocol === 'https:') {
            child.href = url.href;
            child.target = '_blank';
            child.rel = 'noopener noreferrer';
          }
        } catch {
          // Invalid links remain ordinary, non-clickable text.
        }
      }
    }
    for (const nested of item.children ?? []) appendMarkdownNode(child, nested);
    parent.append(child);
  }

  function appendMarkdown(parent, source) {
    const fragment = document.createDocumentFragment();
    for (const item of parseMarkdown(source)) appendMarkdownNode(fragment, item);
    parent.append(fragment);
  }

  function message(role, text) {
    const labels = { user: 'Bạn', assistant: 'Trợ lý Linux', error: 'Thông báo' };
    const node = document.createElement('article');
    node.className = 'chat-message ' + role;
    const label = document.createElement('strong');
    label.textContent = labels[role];
    const content = document.createElement('div');
    if (role === 'assistant') {
      content.className = 'chat-markdown';
      appendMarkdown(content, text);
    } else {
      content.textContent = text;
    }
    node.append(label, content);
    appendToTranscript(node, role === 'user');
  }

  function onEvent(item) {
    if (item.type === 'thinking') progress.textContent = 'AI đang xử lý · bước ' + item.round + '/5…';
    if (item.type === 'answer') message('assistant', item.text);
    if (item.type === 'tool-start') progress.textContent = 'Đang gọi công cụ MCP ' + item.name + '…';
    if (item.type === 'tool-result') {
      const details = document.createElement('details');
      details.className = 'agent-trace';
      const summary = document.createElement('summary');
      const name = document.createElement('code');
      name.textContent = item.name;
      summary.append(item.ok ? 'Kết quả MCP · ' : 'Lỗi MCP · ', name, ' · ' + Math.round(item.ms) + ' ms');
      const output = document.createElement('pre');
      output.textContent = JSON.stringify(item.result, null, 2);
      details.append(summary, output);
      appendToTranscript(details);
    }
  }

  function setProviderVisibility() {
    const local = $('agent-provider').value === 'ollama';
    $('agent-api-key-field').hidden = local;
    $('agent-ollama-field').hidden = !local;
    $('agent-remember-field').hidden = local;
  }

  function readProviderConfig() {
    const provider = $('agent-provider').value;
    const typedKey = $('agent-api-key').value.trim();
    if (typedKey) providerKey = typedKey;
    return {
      provider,
      model: $('agent-model').value.trim(),
      api_key: provider === 'ollama' ? '' : providerKey,
      ...(provider === 'ollama' ? { base_url: $('agent-ollama-url').value.trim() } : {}),
    };
  }

  function populateModels(models) {
    const list = $('agent-model-options');
    list.replaceChildren();
    for (const model of models || []) {
      if (typeof model !== 'string') continue;
      const option = document.createElement('option');
      option.value = model;
      list.append(option);
    }
  }

  function showModelState(state, label) {
    $('model-bar').dataset.state = state;
    $('agent-model-status').textContent = label;
    $('agent-recheck').disabled = state === 'checking';
  }

  function updateProviderFeedback(text, state = 'idle') {
    $('agent-provider-feedback').textContent = text;
    $('agent-provider-feedback').dataset.state = state;
  }

  async function refreshStatus() {
    if (!connected()) {
      ready = false;
      showModelState('idle', 'Kết nối MCP để cấu hình AI.');
      return;
    }
    try {
      await loadSavedCredentials();
      const currentProvider = $('agent-provider').value;
      let saved = savedCredentials.get(currentProvider);
      if (!saved && savedCredentials.size) {
        const first = savedCredentials.entries().next().value;
        if (first) {
          $('agent-provider').value = first[0];
          saved = first[1];
        }
      }
      if (saved) {
        const provider = $('agent-provider').value;
        $('agent-model').value = saved.model;
        $('agent-api-key').value = '';
        $('agent-api-key').placeholder = 'Đã lưu trên MCP Server. Để trống để dùng key đã lưu; nhập key mới để thay.';
        $('agent-remember-key').checked = true;
        $('provider-memory').textContent = 'API key đã mã hóa trên MCP Server';
        setProviderVisibility();
        updateProviderPrivacyNote(true);
        providerConfig = null;
        providerKey = '';
        updateProviderFeedback('Đã tìm thấy API key đã lưu cho ' + PROVIDER_LABELS[provider] + '. Đang xác thực lại…', 'checking');
        await testProvider({ skipRefresh: true });
        return;
      }
    } catch (error) {
      savedCredentials = new Map();
      updateProviderPrivacyNote(false);
      updateProviderFeedback('Không tải được credential từ MCP Server: ' + (error.message || 'lỗi không xác định'), 'error');
    }
    if (providerConfig) {
      ready = true;
      showModelState('ready', PROVIDER_LABELS[providerConfig.provider] + ' · ' + providerConfig.model + ' · sẵn sàng');
    } else {
      ready = false;
      $('provider-memory').textContent = 'Chưa lưu API key trên MCP Server';
      showModelState('unavailable', 'Chọn provider, nhập API key và kiểm tra kết nối.');
    }
  }

  async function testProvider({ skipRefresh = false } = {}) {
    if (!connected()) {
      toast('Kết nối MCP trước khi kiểm tra AI provider.');
      return false;
    }
    const draft = readProviderConfig();
    if (!draft.model) {
      updateProviderFeedback('Hãy nhập Model ID.', 'error');
      return false;
    }
    const button = $('agent-provider-test');
    button.disabled = true;
    $('agent-recheck').disabled = true;
    showModelState('checking', 'Đang kiểm tra ' + PROVIDER_LABELS[draft.provider] + '…');
    updateProviderFeedback('Đang xác thực API và kiểm tra model…', 'checking');
    try {
      const response = await fetch('/agent/test', {
        method: 'POST',
        headers: await headers(),
        body: JSON.stringify({ provider_config: draft, remember: $('agent-remember-key').checked }),
        cache: 'no-store',
        signal: AbortSignal.timeout(20000),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Provider gateway HTTP ' + response.status);
      populateModels(data.models);
      if (!data.available) {
        providerConfig = null;
        ready = false;
        const hint = Array.isArray(data.models) && data.models.length
          ? ' Một số model khả dụng: ' + data.models.slice(0, 8).join(', ') + '.'
          : '';
        const detail = (data.message || 'Model chưa sẵn sàng.') + hint;
        updateProviderFeedback(detail, 'error');
        showModelState('unavailable', PROVIDER_LABELS[draft.provider] + ' chưa sẵn sàng · ' + draft.model);
        return false;
      }

      const credentialSaved = data.credential_saved === true;
      providerConfig = credentialSaved
        ? { provider: draft.provider, model: draft.model }
        : { ...draft };
      providerKey = credentialSaved ? '' : draft.api_key;
      ready = true;
      let keyNote;
      if (draft.provider === 'ollama') {
        keyNote = 'Ollama local đã kết nối.';
      } else if (credentialSaved) {
        savedCredentials.set(draft.provider, { model: draft.model, updated_at: Date.now() });
        keyNote = 'API key đã được mã hóa và lưu trên MCP Server theo tài khoản Keycloak của bạn.';
        $('provider-memory').textContent = 'API key đã mã hóa trên MCP Server';
        updateProviderPrivacyNote(true);
      } else if (savedCredentials.has(draft.provider) && !draft.api_key) {
        keyNote = 'Đã dùng API key đã mã hóa trên MCP Server.';
        $('provider-memory').textContent = 'API key đã mã hóa trên MCP Server';
        updateProviderPrivacyNote(true);
      } else {
        keyNote = 'API key chỉ giữ trong bộ nhớ tab; chưa lưu trên MCP Server.';
        $('provider-memory').textContent = 'Chỉ lưu trong bộ nhớ tab';
        updateProviderPrivacyNote(false);
      }
      $('agent-api-key').value = '';
      $('agent-api-key').placeholder = savedCredentials.has(draft.provider)
        ? 'Đã lưu trên MCP Server. Để trống để dùng key đã lưu; nhập key mới để thay.'
        : 'Dán API key của provider đã chọn';
      updateProviderFeedback(data.message + ' ' + keyNote, 'success');
      $('agent-log-label').textContent = 'Cho phép gửi log tới ' + PROVIDER_LABELS[draft.provider];
      showModelState('ready', PROVIDER_LABELS[draft.provider] + ' · ' + draft.model + ' · đã kết nối');
      return true;
    } catch (error) {
      providerConfig = null;
      ready = false;
      const detail = error && error.name === 'TimeoutError'
        ? 'Kiểm tra kết nối hết thời gian.'
        : (error.message || 'Không thể kiểm tra provider.');
      updateProviderFeedback(detail, 'error');
      showModelState('unavailable', PROVIDER_LABELS[draft.provider] + ' chưa kết nối');
      return false;
    } finally {
      button.disabled = false;
      $('agent-recheck').disabled = false;
      if (!providerConfig && !skipRefresh) void refreshStatus();
    }
  }

  function createRunner() {
    const current = epoch;
    return new AgentRunner({
      tools,
      onEvent: item => { if (current === epoch) onEvent(item); },
      execute: (name, args) => client.callTool(name, args),
      generate: async (messages, allowLogs, signal) => {
        if (!providerConfig) throw new Error('Hãy cấu hình và kiểm tra AI provider trước.');
        const response = await fetch('/agent/chat', {
          method: 'POST',
          headers: await headers(),
          body: JSON.stringify({ messages, allow_logs: allowLogs, provider_config: providerConfig }),
          signal: AbortSignal.any([signal, AbortSignal.timeout(125000)]),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Model gateway HTTP ' + response.status);
        if (current === epoch && !signal.aborted && data.usage) {
          usage.input += Number(data.usage.input_tokens) || 0;
          usage.output += Number(data.usage.output_tokens) || 0;
          usageLabel.textContent = 'Lượt này · ' + usage.input.toLocaleString('vi-VN') +
            ' token vào · ' + usage.output.toLocaleString('vi-VN') + ' token ra';
        }
        return data;
      },
    });
  }
  let runner = createRunner();

  function setRunning(running) {
    $('chat-send').disabled = running;
    $('chat-stop').hidden = !running;
    $('agent-new-chat').disabled = running;
    consent.disabled = running;
    $('agent-provider').disabled = running;
    $('agent-model').disabled = running;
    $('agent-api-key').disabled = running;
    $('agent-remember-key').disabled = running;
    $('agent-ollama-url').disabled = running;
    $('agent-provider-test').disabled = running;
    $('agent-provider-clear').disabled = running;
  }

  function clearTranscript() {
    transcript.replaceChildren();
    transcript.hidden = true;
    welcome.hidden = false;
    progress.textContent = '';
    usageLabel.textContent = '';
  }

  async function clearProvider({ clearSaved = false } = {}) {
    const provider = $('agent-provider').value;
    providerConfig = null;
    providerKey = '';
    $('agent-api-key').value = '';
    ready = false;
    if (clearSaved && savedCredentials.has(provider)) {
      try {
        await deleteSavedCredential(provider);
      } catch (error) {
        updateProviderFeedback(error.message || 'Không thể xóa credential trên MCP Server.', 'error');
        return;
      }
    }
    if (clearSaved) {
      $('agent-remember-key').checked = false;
      $('provider-memory').textContent = 'Đã xóa cấu hình provider';
      updateProviderPrivacyNote(false);
    }
    updateProviderFeedback(
      clearSaved
        ? 'Đã xóa cấu hình và API key đã lưu trên MCP Server cho provider này.'
        : 'Đã xóa cấu hình đang hoạt động trong tab.',
      'idle'
    );
    showModelState('unavailable', 'Đã xóa cấu hình AI provider.');
  }

  $('agent-provider').addEventListener('change', () => {
    providerConfig = null;
    providerKey = '';
    ready = false;
    const provider = $('agent-provider').value;
    const saved = savedCredentials.get(provider);
    $('agent-model').value = saved?.model || PROVIDER_DEFAULTS[provider];
    $('agent-api-key').value = '';
    $('agent-api-key').placeholder = saved
      ? 'Đã lưu trên MCP Server. Để trống để dùng key đã lưu; nhập key mới để thay.'
      : 'Dán API key của provider đã chọn';
    $('agent-remember-key').checked = Boolean(saved);
    $('provider-memory').textContent = saved ? 'API key đã mã hóa trên MCP Server' : 'Chưa lưu API key trên MCP Server';
    $('agent-ollama-url').value = 'http://127.0.0.1:11434';
    setProviderVisibility();
    populateModels([]);
    updateProviderPrivacyNote(Boolean(saved));
    updateProviderFeedback(saved
      ? 'Đã tìm thấy API key đã mã hóa trên MCP Server. Nhấn Kiểm tra kết nối để xác thực.'
      : 'Đã chọn ' + PROVIDER_LABELS[provider] + '. Nhập Model ID và API key để kiểm tra.');
    showModelState('unavailable', saved ? 'Đã có API key lưu trên MCP Server · cần xác thực.' : 'Cần cấu hình AI provider.');
  });
  $('agent-model').addEventListener('input', () => {
    providerConfig = null;
    ready = false;
    showModelState('unavailable', 'Model đã thay đổi · cần kiểm tra lại.');
  });
  $('agent-api-key').addEventListener('input', () => {
    providerKey = $('agent-api-key').value;
    providerConfig = null;
    ready = false;
    showModelState('unavailable', 'API key đã thay đổi · cần kiểm tra lại.');
  });
  $('agent-ollama-url').addEventListener('input', () => {
    providerConfig = null;
    ready = false;
    showModelState('unavailable', 'Ollama URL đã thay đổi · cần kiểm tra lại.');
  });
  $('agent-provider-test').addEventListener('click', () => void testProvider());
  $('agent-provider-clear').addEventListener('click', () => void clearProvider({ clearSaved: true }));
  $('agent-recheck').addEventListener('click', () => void testProvider());
  $('agent-remember-key').addEventListener('change', () => {
    const provider = $('agent-provider').value;
    if (!$('agent-remember-key').checked) {
      void (async () => {
        try {
          if (savedCredentials.has(provider)) await deleteSavedCredential(provider);
          if (!providerConfig?.api_key) providerConfig = null;
          providerKey = providerConfig?.api_key || '';
          ready = Boolean(providerConfig);
          $('provider-memory').textContent = 'Không lưu API key trên MCP Server';
          updateProviderPrivacyNote(false);
          updateProviderFeedback('Đã tắt lưu bền vững và xóa API key đã lưu trên MCP Server. Key mới chỉ giữ trong bộ nhớ tab.', 'idle');
          showModelState(ready ? 'ready' : 'unavailable', ready ? 'Provider đang dùng key trong bộ nhớ tab.' : 'Cần nhập API key để tiếp tục.');
        } catch (error) {
          $('agent-remember-key').checked = true;
          updateProviderFeedback(error.message || 'Không thể xóa API key đã lưu.', 'error');
        }
      })();
      return;
    }
    if (providerConfig?.api_key) {
      void testProvider();
    } else {
      updateProviderFeedback('API key sẽ được mã hóa và lưu trên MCP Server sau khi kiểm tra kết nối thành công.', 'idle');
    }
  });

  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault();
    const draft = input.value;
    const text = draft.trim();
    if (!text || runner.running) return;
    if (!connected()) {
      toast('Kết nối MCP trước để dùng AI.');
      return;
    }
    if (!providerConfig || !ready) {
      toast('Chọn provider, nhập API key và kiểm tra kết nối trước.');
      $('agent-provider').focus();
      return;
    }
    const current = epoch;
    message('user', text);
    if (input.value === draft) input.value = '';
    usage = { input: 0, output: 0 };
    usageLabel.textContent = '';
    const turnController = new AbortController();
    controller = turnController;
    setRunning(true);
    try {
      await runner.run(text, { allowLogs: consent.checked, signal: turnController.signal });
      if (current === epoch) progress.textContent = 'Đã trả lời';
    } catch (error) {
      if (current !== epoch) return;
      const stopped = turnController.signal.aborted;
      const feedback = stopped ? 'Đã dừng lượt chat.' : error.message;
      message('error', feedback);
      progress.textContent = stopped ? 'Đã dừng' : 'Lượt chat chưa hoàn tất';
    } finally {
      if (current === epoch) {
        const restoreFocus = document.activeElement === $('chat-stop');
        setRunning(false);
        if (restoreFocus) $('chat-send').focus({ preventScroll: true });
      }
      if (controller === turnController) controller = null;
    }
  });

  function reset() {
    epoch += 1;
    controller?.abort();
    ready = false;
    providerConfig = null;
    providerKey = '';
    $('agent-api-key').value = '';
    runner = createRunner();
    clearTranscript();
    input.value = '';
    consent.checked = false;
    showModelState('idle', 'Kết nối MCP để cấu hình AI.');
    $('agent-remember-key').checked = false;
    $('provider-memory').textContent = 'Chưa tải credential từ MCP Server';
    updateProviderFeedback('Kết nối MCP để tải credential đã lưu cho tài khoản Keycloak.', 'idle');
    updateProviderPrivacyNote(false);
    $('agent-log-label').textContent = 'Cho phép AI phân tích log';
    setRunning(false);
  }

  consent.addEventListener('change', () => {
    if (runner.running || transcript.hidden) return;
    runner.clear();
    clearTranscript();
    toast('Đã bắt đầu lại hội thoại để áp dụng quyền chia sẻ log.');
  });
  $('chat-stop').addEventListener('click', () => controller?.abort());
  $('agent-new-chat').addEventListener('click', () => {
    runner.clear();
    clearTranscript();
    input.value = '';
    consent.checked = false;
    input.focus();
  });
  document.querySelectorAll('[data-question]').forEach(button => {
    button.addEventListener('click', () => {
      input.value = button.dataset.question;
      input.focus();
    });
  });
  setProviderVisibility();
  return { reset, refreshStatus };
}
