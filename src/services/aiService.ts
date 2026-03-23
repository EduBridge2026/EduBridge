import axios from 'axios';

const API_BASE = '/api';

type StreamEvent = { event: 'stage' | 'partial' | 'result' | 'error'; data: any };

function toStreamEvent(payload: unknown): StreamEvent | null {
  if (!payload || typeof payload !== 'object') return null;
  const maybe = payload as { event?: string; data?: any };
  if (
    (maybe.event === 'stage' || maybe.event === 'partial' || maybe.event === 'result' || maybe.event === 'error') &&
    'data' in maybe
  ) {
    return maybe as StreamEvent;
  }
  return null;
}

function safeJsonParse(input: string): unknown | null {
  try {
    return JSON.parse(input);
  } catch {
    return null;
  }
}

function emitPayload(raw: string, onEvent: (event: StreamEvent) => void) {
  const trimmed = raw.trim();
  if (!trimmed) return;
  if (trimmed === '[DONE]') return;

  const parsed = safeJsonParse(trimmed);
  if (parsed !== null) {
    const evt = toStreamEvent(parsed);
    if (evt) {
      onEvent(evt);
      return;
    }
    onEvent({ event: 'partial', data: { raw: parsed } });
    return;
  }

  // Fallback: when upstream sends plain text chunks, still stream to UI.
  onEvent({ event: 'partial', data: { content_chunk: trimmed } });
}

async function streamRequest(
  endpoint: string,
  formData: FormData,
  onEvent: (event: StreamEvent) => void
) {
  const response = await fetch(endpoint, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const contentType = response.headers.get('content-type') || '';
  const preferSSE = contentType.includes('text/event-stream');

  let buffer = '';
  let sseDataLines: string[] = [];

  const flushSSEBlock = () => {
    if (!sseDataLines.length) return;
    const payload = sseDataLines.join('\n');
    sseDataLines = [];
    emitPayload(payload, onEvent);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    while (true) {
      const lineBreak = buffer.indexOf('\n');
      if (lineBreak === -1) break;

      const rawLine = buffer.slice(0, lineBreak);
      buffer = buffer.slice(lineBreak + 1);
      const line = rawLine.replace(/\r$/, '');

      // SSE mode: messages are delimited by blank lines and prefixed by "data:"
      if (preferSSE || line.startsWith('data:') || sseDataLines.length > 0) {
        if (line === '') {
          flushSSEBlock();
          continue;
        }
        if (line.startsWith('data:')) {
          sseDataLines.push(line.slice(5).trimStart());
        }
        continue;
      }

      // NDJSON mode: one json object per line
      emitPayload(line, onEvent);
    }
  }

  // Flush tail
  if (sseDataLines.length) {
    flushSSEBlock();
  }
  if (buffer.trim()) {
    emitPayload(buffer, onEvent);
  }
}

export const aiService = {
  async processQuestionStream(
    formData: FormData,
    onEvent: (event: StreamEvent) => void
  ) {
    await streamRequest(`${API_BASE}/ai/process/stream`, formData, onEvent);
  },

  async correctQuestionStream(
    formData: FormData,
    onEvent: (event: StreamEvent) => void
  ) {
    await streamRequest(`${API_BASE}/ai/correct/stream`, formData, onEvent);
  },

  async processQuestion(formData: FormData) {
    const response = await axios.post(`${API_BASE}/ai/process`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return response.data;
  },

  async correctQuestion(formData: FormData) {
    const response = await axios.post(`${API_BASE}/ai/correct`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return response.data;
  },

  async getQuestions() {
    const response = await axios.get(`${API_BASE}/questions`);
    return response.data;
  },

  async ensureQuestionSolution(
    questionId: string,
    payload: { provider?: string; model?: string; api_key?: string }
  ) {
    const response = await axios.post(`${API_BASE}/questions/${questionId}/ensure-solution`, payload);
    return response.data;
  },

  async generateVariants(formData: FormData) {
    const response = await axios.post(`${API_BASE}/ai/variants`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return response.data;
  }
};
