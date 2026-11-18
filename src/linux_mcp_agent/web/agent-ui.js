import { AgentRunner } from './agent-client.mjs';

export function mountAgent({ client, tools, connected, toast }) {
  const $ = id => document.getElementById(id);
  const input = $('chat-input');
  const transcript = $('chat-messages');
  const welcome = $('chat-welcome');
  const consent = $('agent-allow-logs');
  const progress = $('agent-progress');
  const usageLabel = $('agent-usage');
  let controller = null;
  let statusRequest = null;
  let ready = false;
  let epoch = 0;
  let usage = { input: 0, output: 0 };

  function headers() {
    return {
      'Content-Type': 'application/json',
      ...(client.token ? { Authorization: `Bearer ${client.token}` } : {}),
    };
  }

  function appendToTranscript(node, follow = false) {
    const nearBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 40;
    welcome.hidden = true;
    transcript.hidden = false;
    transcript.append(node);
    if (follow || nearBottom) transcript.scrollTop = transcript.scrollHeight;
  }

  function message(role, text) {
    const labels = { user: 'Bạn', assistant: 'Trợ lý Linux', error: 'Thông báo' };
    const node = document.createElement('article');
    node.className = `chat-message ${role}`;
    const label = document.createElement('strong');
    label.textContent = labels[role];
    const content = document.createElement('div');
    content.textContent = text;
    node.append(label, content);
    appendToTranscript(node, role === 'user');
  }

  function onEvent(item) {
    if (item.type === 'thinking') progress.textContent = `AI đang xử lý · bước ${item.round}/5…`;
    if (item.type === 'answer') message('assistant', item.text);
    if (item.type === 'tool-start') progress.textContent = `Đang gọi công cụ MCP ${item.name}…`;
    if (item.type === 'tool-result') {
      const details = document.createElement('details');
      details.className = 'agent-trace';
      const summary = document.createElement('summary');
      const name = document.createElement('code');
      name.textContent = item.name;
      summary.append(item.ok ? 'Kết quả MCP · ' : 'Lỗi MCP · ', name, ` · ${Math.round(item.ms)} ms`);
      const output = document.createElement('pre');
      output.textContent = JSON.stringify(item.result, null, 2);
      details.append(summary, output);
      appendToTranscript(details);
    }
  }

  function createRunner() {
    const current = epoch;
    return new AgentRunner({
      tools,
      onEvent: item => { if (current === epoch) onEvent(item); },
      execute: (name, args) => client.callTool(name, args),
      generate: async (messages, allowLogs, signal) => {
        const response = await fetch('/agent/chat', {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({ messages, allow_logs: allowLogs }),
          signal: AbortSignal.any([signal, AbortSignal.timeout(125000)]),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `Model gateway HTTP ${response.status}`);
        if (current === epoch && !signal.aborted && data.usage) {
          usage.input += Number(data.usage.input_tokens) || 0;
          usage.output += Number(data.usage.output_tokens) || 0;
          usageLabel.textContent = `Lượt này · ${usage.input.toLocaleString('vi-VN')} token vào · ${usage.output.toLocaleString('vi-VN')} token ra`;
        }
        return data;
      },
    });
  }
  let runner = createRunner();

  function showModelState(state, label) {
    $('model-bar').dataset.state = state;
    $('agent-model-status').textContent = label;
    $('agent-recheck').disabled = state === 'checking';
  }

  async function checkModel(current) {
    showModelState('checking', 'Đang kiểm tra cấu hình AI…');
    $('agent-setup').hidden = true;
    try {
      const response = await fetch('/agent/status', {
        headers: headers(),
        cache: 'no-store',
        signal: AbortSignal.timeout(5000),
      });
      const status = await response.json();
      if (current !== epoch) return;
      if (!response.ok) throw new Error(status.error || 'Hãy thử kết nối lại với MCP.');

      ready = status.enabled && status.available;
      if (!status.enabled) {
        showModelState('unavailable', 'Trợ lý AI đang tắt trên máy chủ.');
        return;
      }

      const remote = status.provider !== 'ollama';
      const provider = remote ? 'OpenAI' : 'Ollama';
      const model = status.model ? `${provider} · ${status.model}` : provider;
      const available = remote ? 'đã cấu hình API key' : 'sẵn sàng';
      showModelState(ready ? 'ready' : 'unavailable', `${model} · ${ready ? available : 'chưa sẵn sàng'}`);
      $('agent-privacy-note').textContent = remote
        ? 'Câu hỏi, lịch sử chat và kết quả MCP được gửi tới OpenAI. API key được giữ ở máy chủ. Log chỉ được gửi khi bạn cấp quyền. Phí API tính theo token.'
        : 'Câu hỏi và kết quả MCP được xử lý bằng Ollama trên máy chủ. Log chỉ được đọc khi bạn cấp quyền.';
      $('agent-log-label').textContent = remote
        ? 'Cho phép gửi log tới OpenAI'
        : 'Cho phép Ollama phân tích log';
      $('agent-setup-instruction').textContent = remote
        ? 'Thêm key vào file .env của máy chủ, sau đó khởi động lại dịch vụ. '
        : 'Kiểm tra Ollama đang chạy và tải model nếu chưa có. ';
      $('agent-pull-command').textContent = remote ? 'OPENAI_API_KEY=your-key' : `ollama pull ${status.model}`;
      $('agent-setup').hidden = ready;
    } catch (error) {
      if (current !== epoch) return;
      ready = false;
      const detail = error.name === 'TimeoutError' ? 'Yêu cầu hết thời gian.' : error.message;
      showModelState('unavailable', `Không kiểm tra được model. ${detail}`);
    }
  }

  function refreshStatus() {
    if (!connected()) {
      showModelState('idle', 'Kết nối MCP để dùng AI.');
      return;
    }
    if (statusRequest) return statusRequest;

    const current = epoch;
    statusRequest = checkModel(current).finally(() => {
      if (current === epoch) statusRequest = null;
    });
    return statusRequest;
  }

  function setRunning(running) {
    $('chat-send').disabled = running;
    $('chat-stop').hidden = !running;
    $('agent-new-chat').disabled = running;
    consent.disabled = running;
  }

  function clearTranscript() {
    transcript.replaceChildren();
    transcript.hidden = true;
    welcome.hidden = false;
    progress.textContent = '';
    usageLabel.textContent = '';
  }

  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault();
    const draft = input.value;
    const text = draft.trim();
    if (!text || runner.running) return;
    if (!connected()) {
      toast('Kết nối MCP trước để dùng AI.');
      return;
    }
    const current = epoch;
    if (!ready) {
      await refreshStatus();
      if (current !== epoch || runner.running) return;
      if (!ready) {
        toast('AI chưa sẵn sàng. Xem trạng thái model phía trên.');
        return;
      }
    }
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
    statusRequest = null;
    ready = false;
    runner = createRunner();
    clearTranscript();
    input.value = '';
    consent.checked = false;
    $('agent-setup').hidden = true;
    $('agent-privacy-note').textContent = 'Tùy cấu hình, dữ liệu hội thoại được xử lý qua OpenAI API hoặc Ollama trên máy.';
    $('agent-log-label').textContent = 'Cho phép AI phân tích log';
    showModelState('idle', 'Kết nối MCP để dùng AI.');
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
  $('agent-recheck').addEventListener('click', refreshStatus);
  document.querySelectorAll('[data-question]').forEach(button => {
    button.addEventListener('click', () => {
      input.value = button.dataset.question;
      input.focus();
    });
  });
  return { reset, refreshStatus };
}
