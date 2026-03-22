# AI 智能学习助手 (AI Study Assistant)

一个集题目采集、智能批改、错题管理与变式训练于一体的多模态 AI 学习平台。

## 核心功能
- **题目采集**: 支持拍照上传和文本输入，自动 LaTeX 渲染。
- **智能批改**: AI 深度解析手写过程，提供多维度评价。
- **错题库**: JSON 明文存储，支持导出与复习。
- **变式训练**: 针对错题自动生成变式题目。

## 技术栈
- **前端**: React 19, Tailwind CSS 4, KaTeX
- **后端**: Python 3, FastAPI
- **AI**: 支持 Qwen、DeepSeek、Kimi、Gemini，且支持同厂商多版本模型切换

## 支持模型（按厂商）
当前版本支持以下模型选择（与设置页保持一致）：

- **Google Gemini**
  - `gemini-2.0-flash`
  - `gemini-2.5-flash`
  - `gemini-2.5-pro`
- **通义千问 Qwen（阿里云 DashScope 兼容模式）**
  - `qwen-vl-max`（支持图片识别）
  - `qwen-vl-plus`（支持图片识别）
  - `qwen-max`
  - `qwen-plus`
  - `qwen-turbo`
- **DeepSeek**
  - `deepseek-chat`
  - `deepseek-reasoner`
- **Kimi（Moonshot）**
  - `moonshot-v1-8k`
  - `moonshot-v1-32k`
  - `moonshot-v1-128k`

说明：
- 你需要先选“提供商（provider）”，再选该提供商下的“模型版本（model）”。
- 前端会把 `provider + model + api_key` 一起提交给后端，后端会校验模型是否属于对应提供商。
- 如果选择了不匹配的组合（例如把 `qwen-max` 用在 `deepseek` 提供商），后端会返回 400 错误。

## 模型与 Key 使用规则
- **Gemini**
  - 可在设置页填写 API Key。
  - 不填写时，后端会尝试使用环境变量 `GEMINI_API_KEY`。
- **Qwen / DeepSeek / Kimi**
  - 需要在设置页填写对应平台的 API Key（不使用 `GEMINI_API_KEY` 兜底）。
  - Key 必须与当前选择的提供商匹配，否则会出现 401/鉴权失败。

## 设置持久化
- 设置页中的以下内容会自动保存到浏览器本地（`localStorage`）：
  - 提供商 `provider`
  - 模型版本 `model`
  - API Key `apiKey`
  - 处理策略 `processMode`
- 刷新页面后会自动恢复。

## 快速开始
1. 安装依赖:
   ```bash
   npm install
   conda install --file requirements.txt
   ```
2. 启动开发服务器:
   ```bash
   npm run dev
   ```

## 维护文档
请参阅 `docs/MAINTENANCE.md` 获取详细的维护指南。
