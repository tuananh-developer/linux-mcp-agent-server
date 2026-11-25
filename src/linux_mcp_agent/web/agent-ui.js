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
  // Secrets live only in this module's memory and are sent only to this same-origin gateway.
  let providerConfig = null;
  let providerKey = '';

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

    const allowedTags = new Set([
      'a', 'blockquote', 'code', 'div', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'hr', 'li', 'ol', 'p', 'pre', 's', 'strong', 'table', 'tbody', 'td', 'th',
      'thead', 'tr', 'ul',
    ]);
    if (!allowedTags.has(item.tag)) {
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

  function refreshStatus() {
    if (!connected()) {
      ready = false;
      showModelState('idle', 'Kết nối MCP để cấu hình AI.');
      return;
    }
    if (providerConfig) {
      ready = true;
      showModelState('ready', PROVIDER_LABELS[providerConfig.provider] + ' · ' + providerConfig.model + ' · sẵn sàng');
    } else {
      ready = false;
      showModelState('unavailable', 'Chọn provider, nhập API key và kiểm tra kết nối.');
    }
  }

  async function testProvider() {
    if (!connected()) {
      toast('Kết nối MCP trước khi kiểm tra AI provider.');
      return false;
    }
    const draft = readProviderConfig();
    if (!draft.model) {
      updateProviderFeedback('Hãy nhập Model ID.', 'error');
      return false;
    }
    if (draft.provider !== 'ollama' && !draft.api_key) {
      updateProviderFeedback('Hãy nhập API key cho provider đã chọn.', 'error');
      $('agent-api-key').focus();
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
        body: JSON.stringify({ provider_config: draft }),
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

      providerConfig = { ...draft };
      providerKey = draft.api_key;
      $('agent-api-key').value = '';
      ready = true;
      const keyNote = draft.provider === 'ollama'
        ? 'Ollama local đã kết nối.'
        : 'API key chỉ giữ trong bộ nhớ tab, không lưu bền vững.';
      updateProviderFeedback(data.message + ' ' + keyNote, 'success');
      $('agent-privacy-note').textContent =
        'Provider: ' + PROVIDER_LABELS[draft.provider] + '. Câu hỏi, lịch sử hội thoại và kết quả MCP được chuyển qua máy chủ Linux Observatory tới provider đã chọn. API key chỉ giữ trong bộ nhớ tab và dùng trong request tạm thời; không ghi vào file, database hay localStorage. Chỉ gửi log khi bạn cấp quyền đọc log. Phí API có thể phát sinh theo chính sách provider.';
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
      if (!providerConfig) refreshStatus();
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

  function clearProvider() {
    providerConfig = null;
    providerKey = '';
    $('agent-api-key').value = '';
    ready = false;
    updateProviderFeedback('Đã xóa cấu hình trong bộ nhớ của tab. Nhập API key và kiểm tra lại khi cần.', 'idle');
    showModelState('unavailable', 'Đã xóa cấu hình AI provider.');
  }

  $('agent-provider').addEventListener('change', () => {
    clearProvider();
    const provider = $('agent-provider').value;
    $('agent-model').value = PROVIDER_DEFAULTS[provider];
    $('agent-ollama-url').value = 'http://127.0.0.1:11434';
    setProviderVisibility();
    populateModels([]);
    updateProviderFeedback('Đã chọn ' + PROVIDER_LABELS[provider] + '. Nhập Model ID và API key để kiểm tra.');
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
  $('agent-provider-clear').addEventListener('click', clearProvider);
  $('agent-recheck').addEventListener('click', () => void testProvider());

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
    updateProviderFeedback('API key không được ghi vào localStorage, database hoặc file cấu hình.');
    $('agent-privacy-note').textContent =
      'Câu hỏi, lịch sử chat và kết quả MCP sẽ được gửi qua máy chủ Linux Observatory tới provider bạn chọn. API key chỉ được giữ trong bộ nhớ tab, không được lưu bền vững.';
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
