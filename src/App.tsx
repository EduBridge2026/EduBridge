import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { 
  Camera, 
  Type, 
  Send, 
  History, 
  Settings, 
  CheckCircle2, 
  XCircle, 
  ChevronRight, 
  Loader2,
  Plus,
  Image as ImageIcon,
  FileJson,
  BrainCircuit
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import 'katex/dist/katex.min.css';
import { InlineMath, BlockMath } from 'react-katex';
import { aiService } from './services/aiService';

type QuestionType = 'choice' | 'fill' | 'essay';
type Provider = 'qwen' | 'deepseek' | 'kimi' | 'gemini';

interface Question {
  id: string;
  type: QuestionType;
  content: string;
  options?: string[];
  answer?: string;
  analysis?: string;
  created_at: number;
  source: string;
}

interface CorrectionResult {
  question_id: string;
  user_answer: string;
  is_correct: boolean;
  score: number;
  feedback: string;
  steps?: string[];
  error_type?: string;
}

const SETTINGS_STORAGE_KEY = 'edubridge_settings_v1';
const MODEL_OPTIONS: Record<Provider, { value: string; label: string }[]> = {
  gemini: [
    { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
    { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
    { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  ],
  qwen: [
    { value: 'qwen-max', label: 'Qwen Max' },
    { value: 'qwen-plus', label: 'Qwen Plus' },
    { value: 'qwen-turbo', label: 'Qwen Turbo' },
  ],
  deepseek: [
    { value: 'deepseek-chat', label: 'DeepSeek Chat' },
    { value: 'deepseek-reasoner', label: 'DeepSeek Reasoner' },
  ],
  kimi: [
    { value: 'moonshot-v1-8k', label: 'Moonshot v1 8K' },
    { value: 'moonshot-v1-32k', label: 'Moonshot v1 32K' },
    { value: 'moonshot-v1-128k', label: 'Moonshot v1 128K' },
  ],
};

const getDefaultModel = (nextProvider: Provider) => MODEL_OPTIONS[nextProvider][0].value;
const isValidProvider = (value: string): value is Provider =>
  value === 'qwen' || value === 'deepseek' || value === 'kimi' || value === 'gemini';
const isValidModelForProvider = (nextProvider: Provider, model: string) =>
  MODEL_OPTIONS[nextProvider].some((item) => item.value === model);

export default function App() {
  const [activeTab, setActiveTab] = useState<'collect' | 'history' | 'settings'>('collect');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(false);
  const [currentQuestion, setCurrentQuestion] = useState<Question | null>(null);
  const [correction, setCorrection] = useState<CorrectionResult | null>(null);
  const [variants, setVariants] = useState<Question[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  
  // Settings
  const [provider, setProvider] = useState<Provider>('gemini');
  const [model, setModel] = useState(getDefaultModel('gemini'));
  const [apiKey, setApiKey] = useState('');
  const [processMode, setProcessMode] = useState<'ocr_ai' | 'ai_direct'>('ocr_ai');

  const fileInputRef = useRef<HTMLInputElement>(null);
  const answerFileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadHistory();
    loadLocalSettings();
  }, []);

  useEffect(() => {
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({ provider, model, apiKey, processMode })
    );
  }, [provider, model, apiKey, processMode]);

  const parseApiErrorMessage = (err: unknown) => {
    const buildFriendlyMessage = (rawText?: string, requestId?: string) => {
      const text = (rawText || '').toLowerCase();
      const rid = requestId ? `（请求ID: ${requestId}）` : '';

      if (text.includes('invalid_api_key') || text.includes('incorrect api key') || text.includes('api key')) {
        return `API Key 无效或已过期，请在“设置”中重新填写对应模型提供商的 Key。${rid}`;
      }
      if (text.includes('401') || text.includes('unauthorized') || text.includes('forbidden')) {
        return `鉴权失败，请检查当前提供商与 API Key 是否匹配。${rid}`;
      }
      if (text.includes('429') || text.includes('rate limit')) {
        return '请求过于频繁，请稍后再试。';
      }
      if (text.includes('timeout') || text.includes('timed out')) {
        return '请求超时，请稍后重试。';
      }
      if (text.includes('network') || text.includes('connect')) {
        return '网络连接失败，请检查网络后重试。';
      }
      return '';
    };

    if (!axios.isAxiosError(err)) {
      return '请求失败，请稍后重试。';
    }

    const data = err.response?.data as any;
    const backendDetail = typeof data?.detail === 'string' ? data.detail : null;
    const providerError = data?.error || null;
    const providerCode = providerError?.code as string | undefined;
    const providerMessage = providerError?.message as string | undefined;
    const requestId = data?.request_id as string | undefined;

    if (providerCode === 'invalid_api_key') {
      return `API Key 无效或已过期，请在“设置”中重新填写对应模型提供商的 Key。${requestId ? `（请求ID: ${requestId}）` : ''}`;
    }

    const friendlyFromDetail = buildFriendlyMessage(backendDetail || undefined, requestId);
    if (friendlyFromDetail) {
      return friendlyFromDetail;
    }

    const friendlyFromProvider = buildFriendlyMessage(providerMessage || undefined, requestId);
    if (friendlyFromProvider) {
      return friendlyFromProvider;
    }

    const fallbackFriendly = buildFriendlyMessage(err.message, requestId);
    if (fallbackFriendly) {
      return fallbackFriendly;
    }

    return '请求失败，请稍后重试。';
  };

  const handleApiError = (label: string, err: unknown) => {
    setErrorMessage(parseApiErrorMessage(err));
    if (axios.isAxiosError(err)) {
      console.error(label, err.response?.data || err.message);
      return;
    }
    console.error(label, err);
  };

  const loadLocalSettings = () => {
    try {
      const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        const savedProvider = isValidProvider(saved.provider) ? saved.provider : 'gemini';
        setProvider(savedProvider);
        if (typeof saved.model === 'string' && isValidModelForProvider(savedProvider, saved.model)) {
          setModel(saved.model);
        } else {
          setModel(getDefaultModel(savedProvider));
        }
        if (typeof saved.apiKey === 'string') {
          setApiKey(saved.apiKey);
        }
        if (saved.processMode === 'ocr_ai' || saved.processMode === 'ai_direct') {
          setProcessMode(saved.processMode);
        }
      }
    } catch (err) {
      console.error("Failed to load local settings", err);
      localStorage.removeItem(SETTINGS_STORAGE_KEY);
    }
  };

  const loadHistory = async () => {
    try {
      const data = await aiService.getQuestions();
      setQuestions(data);
    } catch (err) {
      handleApiError("Failed to load history", err);
    }
  };

  const handleGenerateVariants = async () => {
    if (!currentQuestion) return;
    const formData = new FormData();
    formData.append('question_id', currentQuestion.id);
    formData.append('provider', provider);
    formData.append('model', model);
    if (apiKey) formData.append('api_key', apiKey);

    setLoading(true);
    try {
      const result = await aiService.generateVariants(formData);
      setVariants(result.variants);
    } catch (err) {
      handleApiError("Variants generation failed", err);
    } finally {
      setLoading(false);
    }
  };

  const exportWrongQuestion = () => {
    if (!currentQuestion) return;
    const data = {
      question: currentQuestion,
      correction: correction,
      variants: variants
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `wrong_question_${currentQuestion.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('type', processMode);
    formData.append('provider', provider);
    formData.append('model', model);
    if (apiKey) formData.append('api_key', apiKey);

    setLoading(true);
    try {
      const result = await aiService.processQuestion(formData);
      setCurrentQuestion(result);
      setQuestions([result, ...questions]);
      setCorrection(null);
    } catch (err) {
      handleApiError("Upload failed", err);
    } finally {
      setLoading(false);
    }
  };

  const handleTextSubmit = async (text: string) => {
    if (!text.trim()) return;
    const formData = new FormData();
    formData.append('text', text);
    formData.append('type', 'ai_direct');
    formData.append('provider', provider);
    formData.append('model', model);
    if (apiKey) formData.append('api_key', apiKey);

    setLoading(true);
    try {
      const result = await aiService.processQuestion(formData);
      setCurrentQuestion(result);
      setQuestions([result, ...questions]);
      setCorrection(null);
    } catch (err) {
      handleApiError("Submit failed", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCorrection = async (answer: string, file?: File) => {
    if (!currentQuestion) return;
    const formData = new FormData();
    formData.append('question_id', currentQuestion.id);
    if (answer) formData.append('user_answer', answer);
    if (file) formData.append('file', file);
    formData.append('provider', provider);
    formData.append('model', model);
    if (apiKey) formData.append('api_key', apiKey);

    setLoading(true);
    try {
      const result = await aiService.correctQuestion(formData);
      setCorrection(result);
    } catch (err) {
      handleApiError("Correction failed", err);
    } finally {
      setLoading(false);
    }
  };

  const renderContent = (content: string) => {
    const parts = content.split(/(\$\$[\s\S]*?\$\$|\$[\s\S]*?\$)/g);
    return (
      <>
        {parts.map((part, i) => {
          if (part.startsWith('$$')) {
            return <BlockMath key={i} math={part.slice(2, -2)} />;
          } else if (part.startsWith('$')) {
            return <InlineMath key={i} math={part.slice(1, -1)} />;
          }
          return <span key={i}>{part}</span>;
        })}
      </>
    );
  };

  return (
    <div className="min-h-screen bg-[#F5F5F0] text-[#141414] font-sans">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-black/5 px-6 py-4 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-black rounded-lg flex items-center justify-center">
            <BrainCircuit className="text-white w-5 h-5" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">AI Study Assistant</h1>
        </div>
        <nav className="flex gap-1 bg-black/5 p-1 rounded-xl">
          <button 
            onClick={() => setActiveTab('collect')}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'collect' ? 'bg-white shadow-sm' : 'hover:bg-white/50'}`}
          >
            采集答题
          </button>
          <button 
            onClick={() => setActiveTab('history')}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'history' ? 'bg-white shadow-sm' : 'hover:bg-white/50'}`}
          >
            错题库
          </button>
          <button 
            onClick={() => setActiveTab('settings')}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'settings' ? 'bg-white shadow-sm' : 'hover:bg-white/50'}`}
          >
            设置
          </button>
        </nav>
      </header>

      <main className="max-w-4xl mx-auto p-6">
        <AnimatePresence mode="wait">
          {activeTab === 'collect' && (
            <motion.div 
              key="collect"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-6"
            >
              {/* Collection Area */}
              {!currentQuestion ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <button 
                    onClick={() => fileInputRef.current?.click()}
                    className="group relative h-64 bg-white border-2 border-dashed border-black/10 rounded-3xl flex flex-col items-center justify-center gap-4 hover:border-black/30 transition-all overflow-hidden"
                  >
                    <div className="w-16 h-16 bg-black/5 rounded-full flex items-center justify-center group-hover:scale-110 transition-transform">
                      <Camera className="w-8 h-8" />
                    </div>
                    <div className="text-center">
                      <p className="font-medium">拍照/上传题目</p>
                      <p className="text-sm text-black/40">支持 OCR 或 AI 直接识别</p>
                    </div>
                    <input 
                      type="file" 
                      ref={fileInputRef} 
                      className="hidden" 
                      accept="image/*" 
                      onChange={handleUpload}
                    />
                  </button>

                  <div className="h-64 bg-white border border-black/5 rounded-3xl p-6 flex flex-col">
                    <div className="flex items-center gap-2 mb-4">
                      <Type className="w-5 h-5 text-black/40" />
                      <span className="font-medium">文本输入题意</span>
                    </div>
                    <textarea 
                      placeholder="输入题目内容，AI 将自动格式化..."
                      className="flex-1 bg-transparent resize-none focus:outline-none text-sm leading-relaxed"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && e.metaKey) {
                          handleTextSubmit(e.currentTarget.value);
                        }
                      }}
                    />
                    <div className="flex justify-between items-center mt-4">
                      <span className="text-[10px] uppercase tracking-wider text-black/30 font-bold">Cmd + Enter 发送</span>
                      <button 
                        onClick={(e) => {
                          const textarea = e.currentTarget.parentElement?.previousElementSibling as HTMLTextAreaElement;
                          handleTextSubmit(textarea.value);
                        }}
                        className="p-2 bg-black text-white rounded-xl hover:opacity-80 transition-opacity"
                      >
                        <Send className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Question Display */}
                  <div className="bg-white rounded-3xl p-8 border border-black/5 shadow-sm relative">
                    <button 
                      onClick={() => setCurrentQuestion(null)}
                      className="absolute top-6 right-6 p-2 hover:bg-black/5 rounded-full transition-colors"
                    >
                      <Plus className="w-5 h-5 rotate-45" />
                    </button>
                    <div className="flex items-center gap-3 mb-6">
                      <span className="px-3 py-1 bg-black/5 rounded-full text-[10px] font-bold uppercase tracking-widest">
                        {currentQuestion.type === 'choice' ? '选择题' : currentQuestion.type === 'fill' ? '填空题' : '大题'}
                      </span>
                      <span className="text-black/30 text-xs">
                        {new Date(currentQuestion.created_at * 1000).toLocaleString()}
                      </span>
                    </div>
                    <div className="prose prose-sm max-w-none">
                      <div className="text-lg leading-relaxed mb-8">
                        {renderContent(currentQuestion.content)}
                      </div>
                      {currentQuestion.options && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {currentQuestion.options.map((opt, i) => (
                            <div key={i} className="p-4 bg-[#F9F9F7] rounded-2xl border border-black/5 hover:border-black/20 transition-colors cursor-pointer">
                              {renderContent(opt)}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Answering Area */}
                  {!correction ? (
                    <div className="bg-white rounded-3xl p-8 border border-black/5 shadow-sm">
                      <h3 className="font-semibold mb-6 flex items-center gap-2">
                        <ChevronRight className="w-4 h-4" />
                        提交答案
                      </h3>
                      <div className="space-y-4">
                        <textarea 
                          placeholder="在此输入你的答案..."
                          className="w-full h-32 p-4 bg-[#F9F9F7] rounded-2xl border border-black/5 focus:outline-none focus:border-black/20 transition-all resize-none"
                          id="user-answer-input"
                        />
                        <div className="flex gap-4">
                          <button 
                            onClick={() => answerFileRef.current?.click()}
                            className="flex-1 py-4 bg-[#F9F9F7] border border-black/5 rounded-2xl font-medium flex items-center justify-center gap-2 hover:bg-black/5 transition-colors"
                          >
                            <ImageIcon className="w-5 h-5" />
                            上传手写过程
                          </button>
                          <button 
                            onClick={() => {
                              const input = document.getElementById('user-answer-input') as HTMLTextAreaElement;
                              handleCorrection(input.value);
                            }}
                            className="flex-1 py-4 bg-black text-white rounded-2xl font-medium flex items-center justify-center gap-2 hover:opacity-90 transition-opacity"
                          >
                            <CheckCircle2 className="w-5 h-5" />
                            智能批改
                          </button>
                        </div>
                        <input 
                          type="file" 
                          ref={answerFileRef} 
                          className="hidden" 
                          accept="image/*" 
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) handleCorrection('', file);
                          }}
                        />
                      </div>
                    </div>
                  ) : (
                    <motion.div 
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="bg-white rounded-3xl p-8 border border-black/5 shadow-md space-y-6"
                    >
                      <div className="flex justify-between items-start">
                        <div>
                          <h3 className="text-2xl font-bold flex items-center gap-3">
                            {correction.is_correct ? (
                              <CheckCircle2 className="text-emerald-500 w-8 h-8" />
                            ) : (
                              <XCircle className="text-rose-500 w-8 h-8" />
                            )}
                            {correction.is_correct ? '回答正确' : '需要改进'}
                          </h3>
                          <p className="text-black/40 mt-1">得分: {correction.score} / 10.0</p>
                        </div>
                        <button 
                          onClick={() => setCorrection(null)}
                          className="text-sm font-medium text-black/40 hover:text-black"
                        >
                          重新作答
                        </button>
                      </div>

                      <div className="p-6 bg-[#F9F9F7] rounded-2xl border border-black/5">
                        <h4 className="text-xs font-bold uppercase tracking-widest text-black/30 mb-3">AI 评价</h4>
                        <p className="leading-relaxed">{correction.feedback}</p>
                      </div>

                      {correction.steps && (
                        <div className="space-y-4">
                          <h4 className="text-xs font-bold uppercase tracking-widest text-black/30">解题步骤</h4>
                          <div className="space-y-3">
                            {correction.steps.map((step, i) => (
                              <div key={i} className="flex gap-4 items-start">
                                <span className="w-6 h-6 bg-black text-white text-[10px] font-bold rounded-full flex items-center justify-center shrink-0 mt-0.5">
                                  {i + 1}
                                </span>
                                <div className="text-sm leading-relaxed">
                                  {renderContent(step)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="pt-6 border-t border-black/5 flex gap-4">
                        <button 
                          onClick={handleGenerateVariants}
                          className="flex-1 py-3 bg-black text-white rounded-xl font-medium flex items-center justify-center gap-2 hover:opacity-90 transition-opacity"
                        >
                          <Plus className="w-4 h-4" />
                          生成变式训练 (3道)
                        </button>
                        <button 
                          onClick={exportWrongQuestion}
                          className="px-6 py-3 bg-white border border-black/10 rounded-xl font-medium hover:bg-black/5 transition-colors"
                        >
                          导出错题卡
                        </button>
                      </div>

                      {variants.length > 0 && (
                        <motion.div 
                          initial={{ opacity: 0, y: 20 }}
                          animate={{ opacity: 1, y: 0 }}
                          className="space-y-6 pt-6 border-t border-black/5"
                        >
                          <h4 className="text-xs font-bold uppercase tracking-widest text-black/30">变式训练</h4>
                          <div className="space-y-4">
                            {variants.map((v, i) => (
                              <div key={i} className="p-6 bg-[#F9F9F7] rounded-2xl border border-black/5 space-y-4">
                                <div className="flex justify-between items-center">
                                  <span className="text-[10px] font-bold uppercase tracking-widest text-black/40">变式 {i + 1}</span>
                                  <span className="px-2 py-0.5 bg-black/5 rounded text-[8px] font-bold uppercase tracking-widest">{v.type}</span>
                                </div>
                                <div className="text-sm leading-relaxed">
                                  {renderContent(v.content)}
                                </div>
                                <details className="group">
                                  <summary className="text-[10px] font-bold uppercase tracking-widest text-black/30 cursor-pointer hover:text-black transition-colors list-none flex items-center gap-1">
                                    <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                                    查看解析
                                  </summary>
                                  <div className="mt-4 pt-4 border-t border-black/5 text-sm leading-relaxed text-black/60">
                                    <p className="font-bold text-black mb-2">答案：{v.answer}</p>
                                    {renderContent(v.analysis || '')}
                                  </div>
                                </details>
                              </div>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </motion.div>
                  )}
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'history' && (
            <motion.div 
              key="history"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-4"
            >
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold tracking-tight">错题库</h2>
                <div className="flex gap-2">
                  <button className="p-2 bg-white border border-black/5 rounded-xl hover:bg-black/5 transition-colors">
                    <FileJson className="w-5 h-5" />
                  </button>
                </div>
              </div>
              
              <div className="grid grid-cols-1 gap-4">
                {questions.map((q) => (
                  <div 
                    key={q.id} 
                    onClick={() => {
                      setCurrentQuestion(q);
                      setActiveTab('collect');
                    }}
                    className="bg-white p-6 rounded-3xl border border-black/5 hover:border-black/20 transition-all cursor-pointer group"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <span className="px-2 py-0.5 bg-black/5 rounded text-[9px] font-bold uppercase tracking-widest">
                        {q.type}
                      </span>
                      <span className="text-[10px] text-black/30">
                        {new Date(q.created_at * 1000).toLocaleDateString()}
                      </span>
                    </div>
                    <div className="line-clamp-2 text-sm text-black/60 group-hover:text-black transition-colors">
                      {q.content}
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}

          {activeTab === 'settings' && (
            <motion.div 
              key="settings"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="max-w-xl mx-auto space-y-8"
            >
              <section className="space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-widest text-black/30">模型配置</h3>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">选择大模型提供商</label>
                    <select 
                      value={provider}
                      onChange={(e) => {
                        const nextProvider = e.target.value as Provider;
                        setProvider(nextProvider);
                        setModel(getDefaultModel(nextProvider));
                      }}
                      className="w-full p-3 bg-white border border-black/5 rounded-xl focus:outline-none focus:border-black/20"
                    >
                      <option value="qwen">通义千问 (Qwen)</option>
                      <option value="deepseek">DeepSeek (仅推理)</option>
                      <option value="kimi">Kimi (Moonshot)</option>
                      <option value="gemini">Google Gemini</option>
                    </select>
                    {provider === 'deepseek' && (
                      <p className="text-[10px] text-rose-500 font-medium">注意：DeepSeek 目前不支持视觉任务，请使用文本输入。</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">选择模型版本</label>
                    <select
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      className="w-full p-3 bg-white border border-black/5 rounded-xl focus:outline-none focus:border-black/20"
                    >
                      {MODEL_OPTIONS[provider].map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">API Key (可选)</label>
                    <input 
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="留空则使用系统默认配置"
                      className="w-full p-3 bg-white border border-black/5 rounded-xl focus:outline-none focus:border-black/20"
                    />
                  </div>
                </div>
              </section>

              <section className="space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-widest text-black/30">处理策略</h3>
                <div className="grid grid-cols-2 gap-4">
                  <button 
                    onClick={() => setProcessMode('ocr_ai')}
                    className={`p-4 rounded-2xl border transition-all text-left ${processMode === 'ocr_ai' ? 'bg-black text-white border-black' : 'bg-white border-black/5 hover:border-black/20'}`}
                  >
                    <p className="font-bold">OCR + 简单 AI</p>
                    <p className={`text-[10px] mt-1 ${processMode === 'ocr_ai' ? 'text-white/60' : 'text-black/40'}`}>分层处理，节省 Token</p>
                  </button>
                  <button 
                    onClick={() => setProcessMode('ai_direct')}
                    className={`p-4 rounded-2xl border transition-all text-left ${processMode === 'ai_direct' ? 'bg-black text-white border-black' : 'bg-white border-black/5 hover:border-black/20'}`}
                  >
                    <p className="font-bold">AI 一步到位</p>
                    <p className={`text-[10px] mt-1 ${processMode === 'ai_direct' ? 'text-white/60' : 'text-black/40'}`}>多模态直接识别，更精准</p>
                  </button>
                </div>
              </section>

              <div className="pt-6 border-t border-black/5">
                <p className="text-[10px] text-center text-black/30 uppercase tracking-widest font-bold">
                  AI Study Assistant v1.0.0
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Loading Overlay */}
      <AnimatePresence>
        {loading && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] bg-white/60 backdrop-blur-sm flex items-center justify-center"
          >
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="w-10 h-10 animate-spin text-black" />
              <p className="text-sm font-medium animate-pulse">AI 正在思考中...</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {errorMessage && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[110] bg-black/35 backdrop-blur-sm flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              className="w-full max-w-md bg-white rounded-2xl border border-black/10 shadow-xl p-6 space-y-4"
            >
              <h3 className="text-lg font-semibold">请求失败</h3>
              <p className="text-sm leading-relaxed text-black/70">{errorMessage}</p>
              <div className="flex justify-end">
                <button
                  onClick={() => setErrorMessage(null)}
                  className="px-4 py-2 bg-black text-white rounded-xl text-sm font-medium hover:opacity-90 transition-opacity"
                >
                  我知道了
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
