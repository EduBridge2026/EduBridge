import os
import json
import uuid
import time
import base64
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import uvicorn
from dotenv import load_dotenv
from google import genai
from google.genai import _api_client as genai_api_client
from google.genai import types
from openai import OpenAI

load_dotenv()

app = FastAPI()

# Workaround for google-genai cleanup bug on some Python/runtime combinations.
_original_genai_aclose = genai_api_client.BaseApiClient.aclose

async def _safe_genai_aclose(self):
    if hasattr(self, "_async_httpx_client"):
        await _original_genai_aclose(self)

genai_api_client.BaseApiClient.aclose = _safe_genai_aclose

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data storage path
DATA_DIR = "data"
USERS_DIR = os.path.join(DATA_DIR, "users")
QUESTIONS_DIR = os.path.join(DATA_DIR, "questions")
VARIANTS_DIR = os.path.join(DATA_DIR, "variants")

for d in [DATA_DIR, USERS_DIR, QUESTIONS_DIR, VARIANTS_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

SUPPORTED_MODELS = {
    "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    "qwen": ["qwen-max", "qwen-plus", "qwen-turbo"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "kimi": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
}

class UserProfile(BaseModel):
    id: str
    name: str
    preferences: Dict[str, Any] = {}

class Question(BaseModel):
    id: str
    type: str # 'choice', 'fill', 'essay'
    content: str
    options: Optional[List[str]] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    created_at: float
    source: str # 'image', 'text'

# Helper to save JSON
def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Helper to load JSON
def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# AI Call Helper
async def call_ai(provider: str, api_key: str, prompt: str, image_data: Optional[bytes] = None, response_schema: Optional[Dict] = None, model: Optional[str] = None):
    # Use system key if not provided
    actual_key = api_key or os.getenv("GEMINI_API_KEY")
    
    if provider == 'gemini':
        if not actual_key:
            raise HTTPException(status_code=400, detail="API Key required for gemini")
        selected_model = model or "gemini-2.0-flash"
        if selected_model not in SUPPORTED_MODELS["gemini"]:
            raise HTTPException(status_code=400, detail=f"Unsupported model for gemini: {selected_model}")
        client = genai.Client(api_key=actual_key)
        try:
            contents = [prompt]
            if image_data:
                contents.append(types.Part.from_bytes(data=image_data, mime_type="image/jpeg"))
            
            config = {}
            if response_schema:
                config = {
                    "response_mime_type": "application/json",
                    "response_schema": response_schema
                }
                
            response = client.models.generate_content(
                model=selected_model,
                contents=contents,
                config=config
            )
            return json.loads(response.text) if response_schema else response.text
        finally:
            # Explicitly close SDK resources to avoid noisy cleanup issues on some runtimes.
            client.close()

    elif provider in ['qwen', 'deepseek', 'kimi']:
        # Map providers to their base URLs
        base_urls = {
            'qwen': "https://dashscope.aliyuncs.com/compatible-mode/v1",
            'deepseek': "https://api.deepseek.com",
            'kimi': "https://api.moonshot.cn/v1"
        }
        
        if not api_key:
            raise HTTPException(status_code=400, detail=f"API Key required for {provider}")
        selected_model = model or SUPPORTED_MODELS[provider][0]
        if selected_model not in SUPPORTED_MODELS[provider]:
            raise HTTPException(status_code=400, detail=f"Unsupported model for {provider}: {selected_model}")
            
        client = OpenAI(api_key=api_key, base_url=base_urls.get(provider))
        
        messages = [{"role": "user", "content": prompt}]
        
        # Note: DeepSeek doesn't support images. Qwen/Kimi might need specific multimodal endpoints.
        # For simplicity, we'll assume text-only for these unless they are multimodal.
        # If image is provided and model is not multimodal, we'd need an OCR step.
        
        response = client.chat.completions.create(
            model=selected_model,
            messages=messages,
            response_format={"type": "json_object"} if response_schema else None
        )
        return json.loads(response.choices[0].message.content) if response_schema else response.choices[0].message.content

    else:
        raise HTTPException(status_code=400, detail="Unsupported AI provider")

@app.post("/api/ai/process")
async def process_question(
    type: str = Form(...), # 'ocr_ai' or 'ai_direct'
    provider: str = Form(...), # 'qwen', 'deepseek', 'kimi', 'gemini'
    model: str = Form(None),
    api_key: str = Form(None),
    text: str = Form(None),
    file: UploadFile = File(None)
):
    image_bytes = await file.read() if file else None
    
    prompt = """
    你是一个专业的题目采集助手。请将输入的题目内容（图片或文本）转换为结构化的 JSON 格式。
    如果是图片，请先识别其中的文字和数学公式（使用 LaTeX 渲染）。
    
    输出格式必须符合以下 JSON 模式：
    {
      "type": "choice | fill | essay",
      "content": "题干内容，数学公式用 $...$ 包裹",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."], // 仅选择题需要
      "answer": "正确答案",
      "analysis": "详细解析过程"
    }
    """
    
    if text:
        prompt += f"\n题目文本内容：\n{text}"
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "type": {"type": "STRING"},
            "content": {"type": "STRING"},
            "options": {"type": "ARRAY", "items": {"type": "STRING"}},
            "answer": {"type": "STRING"},
            "analysis": {"type": "STRING"}
        },
        "required": ["type", "content", "answer", "analysis"]
    }
    
    try:
        result = await call_ai(provider, api_key, prompt, image_bytes, schema, model)
        question_id = str(uuid.uuid4())
        question_data = {
            "id": question_id,
            "created_at": time.time(),
            "source": "text" if text else "image",
            **result
        }
        save_json(os.path.join(QUESTIONS_DIR, f"{question_id}.json"), question_data)
        return question_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/correct")
async def correct_answer(
    question_id: str = Form(...),
    user_answer: str = Form(None),
    file: UploadFile = File(None),
    provider: str = Form(...),
    model: str = Form(None),
    api_key: str = Form(None)
):
    question = load_json(os.path.join(QUESTIONS_DIR, f"{question_id}.json"))
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
        
    image_bytes = await file.read() if file else None
    
    prompt = f"""
    你是一个专业的题目批改助手。请根据以下题目内容和用户提交的答案进行批改。
    
    题目内容：{question['content']}
    正确答案：{question['answer']}
    标准解析：{question['analysis']}
    
    用户提交的内容：{user_answer if user_answer else "见图片附件"}
    
    请输出以下 JSON 格式：
    {{
      "is_correct": boolean,
      "score": number (0-10),
      "feedback": "总体评价和改进建议",
      "steps": ["步骤1...", "步骤2..."],
      "error_type": "计算失误 | 公式记忆偏差 | 逻辑断层 | 无"
    }}
    """
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "is_correct": {"type": "BOOLEAN"},
            "score": {"type": "NUMBER"},
            "feedback": {"type": "STRING"},
            "steps": {"type": "ARRAY", "items": {"type": "STRING"}},
            "error_type": {"type": "STRING"}
        },
        "required": ["is_correct", "score", "feedback", "steps", "error_type"]
    }
    
    try:
        result = await call_ai(provider, api_key, prompt, image_bytes, schema, model)
        return {
            "question_id": question_id,
            "user_answer": user_answer or "image_submitted",
            **result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/variants")
async def generate_variants(
    question_id: str = Form(...),
    provider: str = Form(...),
    model: str = Form(None),
    api_key: str = Form(None)
):
    question = load_json(os.path.join(QUESTIONS_DIR, f"{question_id}.json"))
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
        
    prompt = f"""
    你是一个题目生成专家。请针对以下题目，生成 3 道知识点相同但参数或背景不同的变式题。
    
    原题内容：{question['content']}
    原题解析：{question['analysis']}
    
    请输出以下 JSON 格式：
    {{
      "variants": [
        {{
          "type": "choice | fill | essay",
          "content": "变式题干",
          "options": ["A...", "B..."],
          "answer": "答案",
          "analysis": "详细解析"
        }},
        ... // 共3道
      ]
    }}
    """
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "variants": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "type": {"type": "STRING"},
                        "content": {"type": "STRING"},
                        "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "answer": {"type": "STRING"},
                        "analysis": {"type": "STRING"}
                    },
                    "required": ["type", "content", "answer", "analysis"]
                }
            }
        },
        "required": ["variants"]
    }
    
    try:
        result = await call_ai(provider, api_key, prompt, None, schema, model)
        # Save variants
        save_json(os.path.join(VARIANTS_DIR, f"{question_id}.json"), result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/user/profile")
async def get_profile():
    profile = load_json(os.path.join(USERS_DIR, "default.json"))
    if not profile:
        profile = {"id": "default", "name": "学习者", "preferences": {"provider": "gemini"}}
        save_json(os.path.join(USERS_DIR, "default.json"), profile)
    return profile

@app.post("/api/user/profile")
async def update_profile(profile: UserProfile):
    path = os.path.join(USERS_DIR, f"{profile.id}.json")
    payload = profile.dict()
    existing = load_json(path)
    if existing != payload:
        save_json(path, payload)
    return profile

@app.get("/api/questions")
async def list_questions():
    files = os.listdir(QUESTIONS_DIR)
    questions = []
    for f in files:
        if f.endswith(".json"):
            questions.append(load_json(os.path.join(QUESTIONS_DIR, f)))
    return sorted(questions, key=lambda x: x['created_at'], reverse=True)

# Serve static files in production
if os.path.exists("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")
else:
    @app.get("/")
    async def root():
        return {"message": "Vite dev server running."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
