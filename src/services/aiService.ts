import axios from 'axios';

const API_BASE = '/api';

type StreamEvent = { event: 'stage' | 'partial' | 'result' | 'error'; data: any };

export const aiService = {
  async processQuestionStream(
    formData: FormData,
    onEvent: (event: StreamEvent) => void
  ) {
    const response = await fetch(`${API_BASE}/ai/process/stream`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok || !response.body) {
      throw new Error(`流式请求失败: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        const parsed = JSON.parse(trimmed) as StreamEvent;
        onEvent(parsed);
      }
    }
  },

  async correctQuestionStream(
    formData: FormData,
    onEvent: (event: StreamEvent) => void
  ) {
    const response = await fetch(`${API_BASE}/ai/correct/stream`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok || !response.body) {
      throw new Error(`流式请求失败: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        const parsed = JSON.parse(trimmed) as StreamEvent;
        onEvent(parsed);
      }
    }
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
