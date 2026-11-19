/** Minimal same-origin MCP Streamable HTTP client. Credentials stay in memory. */
export class McpError extends Error {
  constructor(message, status = 0) { super(message); this.name = 'McpError'; this.status = status; }
}

export class McpClient {
  constructor(endpoint, onActivity = () => {}) {
    this.endpoint = endpoint;
    this.onActivity = onActivity;
    this.session = null;
    this.version = null;
    this.token = '';
    this.sequence = 0;
    this.generation = 0;
  }

  async connect(token = '') {
    await this.disconnect();
    this.token = token;
    const result = await this.request('initialize', {
      protocolVersion: '2025-11-25', capabilities: {},
      clientInfo: { name: 'linux-observatory-dashboard', version: '0.1.0' },
    });
    this.version = result.protocolVersion;
    await this.request('notifications/initialized', undefined, true);
    return result;
  }

  async disconnect() {
    const headers = this.headers();
    const hadSession = this.session;
    this.generation += 1;
    this.session = null;
    this.version = null;
    this.token = '';
    if (hadSession) {
      try { await fetch(this.endpoint, { method: 'DELETE', headers, signal: AbortSignal.timeout(2000) }); }
      catch { /* Session expiration is also managed by the server. */ }
    }
  }

  headers() {
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (this.session) headers['Mcp-Session-Id'] = this.session;
    if (this.version) headers['MCP-Protocol-Version'] = this.version;
    return headers;
  }

  async request(method, params, notification = false) {
    const started = performance.now();
    const generation = this.generation;
    const id = ++this.sequence;
    const payload = { jsonrpc: '2.0', method };
    if (!notification) payload.id = id;
    if (params !== undefined) payload.params = params;
    try {
      const response = await fetch(this.endpoint, {
        method: 'POST', headers: this.headers(), body: JSON.stringify(payload),
        signal: AbortSignal.timeout(15000), cache: 'no-store', redirect: 'error',
      });
      if (!response.ok) {
        const messages = { 401: 'Cần Bearer token hợp lệ để kết nối.', 403: 'Truy cập bị từ chối. Kiểm tra scope token và Origin được cho phép.', 404: 'Phiên MCP đã hết hạn hoặc endpoint không tồn tại. Hãy kết nối lại.', 421: 'Host không được phép. Kiểm tra MCP_ALLOWED_HOSTS.' };
        throw new McpError(messages[response.status] || `Server trả về HTTP ${response.status}.`, response.status);
      }
      if (generation !== this.generation) throw new McpError('Kết nối đã thay đổi.');
      const session = response.headers.get('mcp-session-id');
      if (session) this.session = session;
      if (notification || response.status === 202) return null;
      let message;
      if (response.headers.get('content-type')?.includes('text/event-stream')) {
        message = await this.readEventStream(response, id);
      } else {
        message = await response.json();
      }
      if (generation !== this.generation) throw new McpError('Kết nối đã thay đổi.');
      if (!message || message.id !== id) throw new McpError('Phản hồi MCP không khớp yêu cầu.');
      if (message.error) throw new McpError(message.error.message || 'Yêu cầu MCP thất bại.');
      if (message.result?.isError) {
        const detail = message.result.content?.filter(item => item.type === 'text').map(item => item.text).join('\n');
        throw new McpError(detail || 'Tool trả về lỗi.');
      }
      this.onActivity({ method, ok: true, ms: performance.now() - started });
      return message.result;
    } catch (error) {
      this.onActivity({ method, ok: false, ms: performance.now() - started });
      if (error instanceof McpError) throw error;
      throw new McpError(error.name === 'TimeoutError' ? 'Server phản hồi quá chậm. Hãy thử lại.' : 'Không thể liên lạc với MCP Server. Kiểm tra server và kết nối lại.', -1);
    }
  }

  async readEventStream(response, id) {
    if (!response.body) throw new McpError('Phản hồi MCP trống.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          const frame = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
          if (!data) continue;
          const message = JSON.parse(data);
          if (message.id === id) return message;
        }
        if (buffer.length > 2_000_000) throw new McpError('Phản hồi MCP vượt giới hạn dashboard.');
        if (done) break;
      }
      throw new McpError('Luồng MCP kết thúc mà chưa có kết quả.');
    } finally { await reader.cancel(); }
  }

  async list(method) {
    const key = method.split('/')[0];
    const items = [];
    let cursor;
    for (let page = 0; page < 20; page += 1) {
      const result = await this.request(method, cursor ? { cursor } : {});
      items.push(...(result[key] || []));
      if (!result.nextCursor) return items;
      if (result.nextCursor === cursor) throw new McpError('Server lặp lại cursor phân trang.');
      cursor = result.nextCursor;
    }
    throw new McpError('Registry vượt giới hạn phân trang của dashboard.');
  }

  async callTool(name, args = {}) {
    const result = await this.request('tools/call', { name, arguments: args });
    if (result.structuredContent) return result.structuredContent;
    const text = result.content?.find(item => item.type === 'text')?.text;
    if (!text) throw new McpError('Tool không trả về dữ liệu JSON.');
    try { return JSON.parse(text); } catch { throw new McpError('Dữ liệu tool không phải JSON hợp lệ.'); }
  }
}
