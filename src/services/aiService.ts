import axios from 'axios';

const API_BASE = '/api';

export const aiService = {
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

  async generateVariants(formData: FormData) {
    const response = await axios.post(`${API_BASE}/ai/variants`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return response.data;
  }
};
