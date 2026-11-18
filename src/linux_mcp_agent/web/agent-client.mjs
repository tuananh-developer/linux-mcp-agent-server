/** Bounded agent loop: the model chooses tools; execution always goes through MCP. */
export class AgentRunner {
  constructor({ generate, execute, tools, onEvent = () => {} }) {
    this.generate = generate; this.execute = execute; this.tools = tools; this.onEvent = onEvent;
    this.messages = []; this.running = false;
  }
  clear() { if (this.running) throw new Error('Hãy dừng lượt hiện tại trước.'); this.messages = []; }
  async run(text, { allowLogs = false, signal } = {}) {
    if (this.running) throw new Error('AI đang xử lý yêu cầu trước.');
    if (!text.trim() || text.length > 4000) throw new Error('Câu hỏi phải có từ 1 đến 4000 ký tự.');
    if (this.messages.length > 20) throw new Error('Phiên hội thoại đã dài. Hãy tạo hội thoại mới.');
    const check = () => { if (signal?.aborted) throw new Error('Đã dừng lượt chat.'); };
    const start = this.messages.length;
    this.running = true;
    this.messages.push({ role: 'user', content: text });
    let calls = 0;
    try {
      for (let round = 0; round < 5; round += 1) {
        check(); this.onEvent({ type: 'thinking', round: round + 1 });
        const { message } = await this.generate(this.messages, allowLogs, signal);
        check();
        if (message.role !== 'assistant' || typeof message.content !== 'string') throw new Error('Phản hồi model không hợp lệ.');
        const requested = message.tool_calls || [];
        if (!Array.isArray(requested) || requested.length > 4) throw new Error('Model gọi quá nhiều tool trong một bước.');
        this.messages.push(message);
        if (!requested.length) {
          if (!message.content.trim()) throw new Error('Model trả về câu trả lời trống. Hãy thử lại.');
          this.onEvent({ type: 'answer', text: message.content });
          return message.content;
        }
        for (const call of requested) {
          check();
          if (++calls > 10) throw new Error('Đã đạt giới hạn 10 lần gọi tool. Hãy thu hẹp câu hỏi.');
          const name = call.function?.name;
          const args = call.function?.arguments || {};
          const started = performance.now();
          this.onEvent({ type: 'tool-start', name, args });
          let result;
          try {
            if (!this.tools().some(tool => tool.name === name)) throw new Error('Tool không được server công bố.');
            if (name === 'read_allowed_log' && !allowLogs) throw new Error('Người dùng chưa cho phép AI đọc log.');
            if (!args || Array.isArray(args) || typeof args !== 'object') throw new Error('Tham số tool không hợp lệ.');
            result = await this.execute(name, args);
            check();
            this.onEvent({ type: 'tool-result', name, result, ms: performance.now() - started, ok: true });
          } catch (error) {
            check();
            result = { error: error.message };
            this.onEvent({ type: 'tool-result', name, result, ms: performance.now() - started, ok: false });
          }
          let content = JSON.stringify(result);
          if (content.length > 12000) content = JSON.stringify({ truncated: true, note: 'Tool result shortened for context', excerpt: content.slice(0, 11000) });
          this.messages.push({ role: 'tool', tool_name: name, content, ...(call.id ? { tool_call_id: call.id } : {}) });
        }
      }
      throw new Error('Đã đạt giới hạn 5 vòng suy luận. Hãy thu hẹp câu hỏi và thử lại.');
    } catch (error) {
      // Roll back incomplete calls so a later turn never gets orphaned tool results.
      this.messages.splice(start);
      throw error;
    } finally { this.running = false; }
  }
}
