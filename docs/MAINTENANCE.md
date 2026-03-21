# AI 智能学习助手 (AI Study Assistant) - 维护文档

## 1. 项目概述
本项目是一个基于多模态大模型的智能学习辅助系统，旨在通过 AI 技术简化题目采集、批改及强化训练流程。

## 2. 核心架构
- **前端**: React 19 + Tailwind CSS 4 + KaTeX (公式渲染)
- **后端**: Python 3 (FastAPI)
- **存储**: 本地明文 JSON 文件存储 (`/data` 目录)
- **AI 交互**: 支持多模型接入（Qwen, DeepSeek, Kimi, Gemini 等），支持 OCR + AI 链路。

## 3. 目录结构
- `/src`: 前端源代码
  - `/components`: UI 组件
  - `/services`: API 调用逻辑
- `/server.py`: 后端 FastAPI 服务入口
- `/data`: 数据存储目录
  - `/questions`: 题目 JSON 文件
  - `/users`: 用户画像数据
- `/docs`: 文档目录

## 4. 数据规范
### 题目 JSON 格式
```json
{
  "id": "uuid",
  "type": "choice | fill | essay",
  "content": "LaTeX 渲染的题干",
  "options": ["A...", "B..."],
  "answer": "正确答案",
  "analysis": "解析过程",
  "created_at": 1234567890.0,
  "source": "image | text"
}
```

## 5. 维护要点
- **模型切换**: 后端 `process_question` 接口支持 `provider` 参数，新增模型需在后端适配对应的 API 调用。
- **视觉模型限制**: DeepSeek 目前不支持视觉任务，前端需在选择图片处理时过滤或提示。
- **公式渲染**: 前端统一使用 `react-katex`，确保题干中的 LaTeX 代码被 `$` 或 `$$` 包裹。
- **存储透明性**: 严禁使用二进制数据库，所有用户数据必须以可读 JSON 格式保存在 `/data` 下。

## 6. 开发环境启动
1. 安装 Python 依赖: `pip install -r requirements.txt`
2. 安装 Node 依赖: `npm install`
3. 启动服务: `npm run dev` (通过 `server.py` 启动)
