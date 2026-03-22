import os
import json
import uuid
import time
import base64
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    "qwen": ["qwen-vl-max", "qwen-vl-plus", "qwen-max", "qwen-plus", "qwen-turbo"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "kimi": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
}
QWEN_VISION_MODELS = {"qwen-vl-max", "qwen-vl-plus"}

class UserProfile(BaseModel):
    id: str
    name: str
    preferences: Dict[str, Any] = {}

class EnsureSolutionRequest(BaseModel):
    provider: Optional[str] = "gemini"
    model: Optional[str] = None
    api_key: Optional[str] = None

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

def ensure_mapping_result(result: Any, context: str) -> Dict[str, Any]:
    if isinstance(result, dict):
        return result

    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    raise HTTPException(
        status_code=502,
        detail=f"{context} 返回格式异常：模型未返回 JSON 对象，请切换模型或重试。"
    )

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

        if image_data:
            if provider != "qwen":
                raise HTTPException(status_code=400, detail=f"{provider} 当前不支持图片识别，请使用文本输入或切换到 Gemini/Qwen。")

            if selected_model not in QWEN_VISION_MODELS:
                selected_model = "qwen-vl-max"

            image_b64 = base64.b64encode(image_data).decode("utf-8")
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ],
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        
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
    
    extraction_prompt = """
    你是一个专业的题目采集助手。请将输入的题目内容（图片或文本）转换为结构化的 JSON 格式。
    如果是图片，请先识别其中的文字和数学公式（使用 LaTeX 渲染）。
    
    你只需要做“题面提取”，不要展开推理，不要详细讲解。
    
    输出格式必须符合以下 JSON 模式：
    {
      "type": "choice | fill | essay",
      "content": "题干内容，数学公式用 $...$ 包裹",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."] // 仅选择题需要
    }
    """
    
    if text:
        extraction_prompt += f"\n题目文本内容：\n{text}"
    
    extraction_schema = {
        "type": "OBJECT",
        "properties": {
            "type": {"type": "STRING"},
            "content": {"type": "STRING"},
            "options": {"type": "ARRAY", "items": {"type": "STRING"}}
        },
        "required": ["type", "content"]
    }

    try:
        extracted = await call_ai(provider, api_key, extraction_prompt, image_bytes, extraction_schema, model)
        extracted = ensure_mapping_result(extracted, "题目采集")

        question_id = str(uuid.uuid4())
        question_data = {
            "id": question_id,
            "created_at": time.time(),
            "source": "text" if text else "image",
            "type": extracted.get("type", "essay"),
            "content": extracted.get("content", ""),
            "options": extracted.get("options"),
            "answer": None,
            "analysis": None
        }
        save_json(os.path.join(QUESTIONS_DIR, f"{question_id}.json"), question_data)
        return question_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/process/stream")
async def process_question_stream(
    type: str = Form(...), # 'ocr_ai' or 'ai_direct'
    provider: str = Form(...), # 'qwen', 'deepseek', 'kimi', 'gemini'
    model: str = Form(None),
    api_key: str = Form(None),
    text: str = Form(None),
    file: UploadFile = File(None)
):
    image_bytes = await file.read() if file else None

    extraction_prompt = """
    你是一个专业的题目采集助手。请将输入的题目内容（图片或文本）转换为结构化的 JSON 格式。
    如果是图片，请先识别其中的文字和数学公式（使用 LaTeX 渲染）。
    
    你只需要做“题面提取”，不要展开推理，不要详细讲解。
    
    输出格式必须符合以下 JSON 模式：
    {
      "type": "choice | fill | essay",
      "content": "题干内容，数学公式用 $...$ 包裹",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."] // 仅选择题需要
    }
    """

    if text:
        extraction_prompt += f"\n题目文本内容：\n{text}"

    extraction_schema = {
        "type": "OBJECT",
        "properties": {
            "type": {"type": "STRING"},
            "content": {"type": "STRING"},
            "options": {"type": "ARRAY", "items": {"type": "STRING"}}
        },
        "required": ["type", "content"]
    }

    async def event_stream():
        try:
            yield json.dumps({"event": "stage", "data": {"message": "已接收请求，准备识别题目..."}}) + "\n"
            await asyncio.sleep(0)

            extracted = await call_ai(provider, api_key, extraction_prompt, image_bytes, extraction_schema, model)
            extracted = ensure_mapping_result(extracted, "题目采集")

            extracted_type = extracted.get("type", "essay")
            extracted_content = extracted.get("content", "") or ""
            extracted_options = extracted.get("options") if isinstance(extracted.get("options"), list) else []

            yield json.dumps({"event": "partial", "data": {"type": extracted_type}}, ensure_ascii=False) + "\n"
            await asyncio.sleep(0)

            if extracted_content:
                yield json.dumps({"event": "stage", "data": {"message": "正在同步题干内容..."}}) + "\n"
                chunk_size = 28
                for i in range(0, len(extracted_content), chunk_size):
                    chunk = extracted_content[i:i + chunk_size]
                    yield json.dumps({"event": "partial", "data": {"content_chunk": chunk}}, ensure_ascii=False) + "\n"
                    await asyncio.sleep(0.01)

            if extracted_options:
                yield json.dumps({"event": "stage", "data": {"message": "正在同步选项..."}}) + "\n"
                for option in extracted_options:
                    yield json.dumps({"event": "partial", "data": {"option": option}}, ensure_ascii=False) + "\n"
                    await asyncio.sleep(0.01)

            yield json.dumps({"event": "stage", "data": {"message": "已完成题面提取，正在保存..."}}) + "\n"
            await asyncio.sleep(0)

            question_id = str(uuid.uuid4())
            question_data = {
                "id": question_id,
                "created_at": time.time(),
                "source": "text" if text else "image",
                "type": extracted_type,
                "content": extracted_content,
                "options": extracted_options or None,
                "answer": None,
                "analysis": None
            }
            save_json(os.path.join(QUESTIONS_DIR, f"{question_id}.json"), question_data)

            yield json.dumps({"event": "result", "data": question_data}, ensure_ascii=False) + "\n"
        except HTTPException as e:
            yield json.dumps({"event": "error", "data": {"detail": e.detail}}) + "\n"
        except Exception as e:
            yield json.dumps({"event": "error", "data": {"detail": str(e)}}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

@app.post("/api/ai/correct")
async def correct_answer(
    question_id: str = Form(...),
    user_answer: str = Form(None),
    file: UploadFile = File(None),
    provider: str = Form(...),
    model: str = Form(None),
    api_key: str = Form(None)
):
    question_path = os.path.join(QUESTIONS_DIR, f"{question_id}.json")
    question = load_json(question_path)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
        
    image_bytes = await file.read() if file else None
    
    if not question.get("answer") or not question.get("analysis"):
        fill_schema = {
            "type": "OBJECT",
            "properties": {
                "answer": {"type": "STRING"},
                "analysis": {"type": "STRING"}
            },
            "required": ["answer", "analysis"]
        }
        fill_prompt = f"""
        你是一个专业的题目解析助手。请根据以下题目信息生成“正确答案”和“标准解析”。
        请优先保证数学与逻辑严谨，解析步骤清晰。

        题目类型：{question.get('type', '')}
        题干：{question.get('content', '')}
        选项：{json.dumps(question.get('options', []), ensure_ascii=False)}

        输出 JSON:
        {{
          "answer": "正确答案",
          "analysis": "详细解析过程"
        }}
        """
        filled = await call_ai(provider, api_key, fill_prompt, None, fill_schema, model)
        filled = ensure_mapping_result(filled, "标准答案生成")
        question["answer"] = filled.get("answer", "")
        question["analysis"] = filled.get("analysis", "")
        save_json(question_path, question)

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
        result = ensure_mapping_result(result, "智能批改")
        attempt = {
            "id": str(uuid.uuid4()),
            "submitted_at": time.time(),
            "provider": provider,
            "model": model,
            "user_answer": user_answer if user_answer else "",
            "has_image_submission": bool(image_bytes),
            "analysis": result
        }
        question.setdefault("attempts", []).append(attempt)
        save_json(question_path, question)
        return {
            "question_id": question_id,
            "user_answer": user_answer or "image_submitted",
            "attempt_id": attempt["id"],
            "attempts_count": len(question["attempts"]),
            **result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/correct/stream")
async def correct_answer_stream(
    question_id: str = Form(...),
    user_answer: str = Form(None),
    file: UploadFile = File(None),
    provider: str = Form(...),
    model: str = Form(None),
    api_key: str = Form(None)
):
    question_path = os.path.join(QUESTIONS_DIR, f"{question_id}.json")
    question = load_json(question_path)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    image_bytes = await file.read() if file else None

    async def emit_text_chunks(field: str, text: str, chunk_size: int = 28):
        if not text:
            return
        for i in range(0, len(text), chunk_size):
            yield json.dumps({"event": "partial", "data": {f"{field}_chunk": text[i:i + chunk_size]}}, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.01)

    async def event_stream():
        try:
            if not question.get("answer") or not question.get("analysis"):
                yield json.dumps({"event": "stage", "data": {"message": "正在生成标准答案与解析..."}}) + "\n"
                await asyncio.sleep(0)

                fill_schema = {
                    "type": "OBJECT",
                    "properties": {
                        "answer": {"type": "STRING"},
                        "analysis": {"type": "STRING"}
                    },
                    "required": ["answer", "analysis"]
                }
                fill_prompt = f"""
                你是一个专业的题目解析助手。请根据以下题目信息生成“正确答案”和“标准解析”。
                请优先保证数学与逻辑严谨，解析步骤清晰。

                题目类型：{question.get('type', '')}
                题干：{question.get('content', '')}
                选项：{json.dumps(question.get('options', []), ensure_ascii=False)}

                输出 JSON:
                {{
                  "answer": "正确答案",
                  "analysis": "详细解析过程"
                }}
                """
                filled = await call_ai(provider, api_key, fill_prompt, None, fill_schema, model)
                filled = ensure_mapping_result(filled, "标准答案生成")
                question["answer"] = filled.get("answer", "")
                question["analysis"] = filled.get("analysis", "")
                save_json(question_path, question)

            async for chunk in emit_text_chunks("answer", question.get("answer", "")):
                yield chunk
            async for chunk in emit_text_chunks("analysis", question.get("analysis", "")):
                yield chunk

            yield json.dumps({"event": "stage", "data": {"message": "正在批改作答..."}}) + "\n"
            await asyncio.sleep(0)

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

            result = await call_ai(provider, api_key, prompt, image_bytes, schema, model)
            result = ensure_mapping_result(result, "智能批改")

            attempt = {
                "id": str(uuid.uuid4()),
                "submitted_at": time.time(),
                "provider": provider,
                "model": model,
                "user_answer": user_answer if user_answer else "",
                "has_image_submission": bool(image_bytes),
                "analysis": result
            }
            question.setdefault("attempts", []).append(attempt)
            save_json(question_path, question)

            payload = {
                "question_id": question_id,
                "user_answer": user_answer or "image_submitted",
                "attempt_id": attempt["id"],
                "attempts_count": len(question["attempts"]),
                "question_answer": question.get("answer"),
                "question_analysis": question.get("analysis"),
                **result
            }
            yield json.dumps({"event": "result", "data": payload}, ensure_ascii=False) + "\n"
        except HTTPException as e:
            yield json.dumps({"event": "error", "data": {"detail": e.detail}}) + "\n"
        except Exception as e:
            yield json.dumps({"event": "error", "data": {"detail": str(e)}}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

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
        result = ensure_mapping_result(result, "变式生成")
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

@app.post("/api/questions/{question_id}/ensure-solution")
async def ensure_solution(question_id: str, req: EnsureSolutionRequest):
    question_path = os.path.join(QUESTIONS_DIR, f"{question_id}.json")
    question = load_json(question_path)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if question.get("answer") and question.get("analysis"):
        return {
            "question_id": question_id,
            "generated": False,
            "answer": question.get("answer"),
            "analysis": question.get("analysis"),
        }

    fill_schema = {
        "type": "OBJECT",
        "properties": {
            "answer": {"type": "STRING"},
            "analysis": {"type": "STRING"}
        },
        "required": ["answer", "analysis"]
    }
    fill_prompt = f"""
    你是一个专业的题目解析助手。请根据以下题目信息生成“正确答案”和“标准解析”。
    请优先保证数学与逻辑严谨，解析步骤清晰。

    题目类型：{question.get('type', '')}
    题干：{question.get('content', '')}
    选项：{json.dumps(question.get('options', []), ensure_ascii=False)}

    输出 JSON:
    {{
      "answer": "正确答案",
      "analysis": "详细解析过程"
    }}
    """

    try:
        provider = req.provider or "gemini"
        result = await call_ai(provider, req.api_key, fill_prompt, None, fill_schema, req.model)
        result = ensure_mapping_result(result, "标准答案生成")
        question["answer"] = result.get("answer", "")
        question["analysis"] = result.get("analysis", "")
        save_json(question_path, question)
        return {
            "question_id": question_id,
            "generated": True,
            "answer": question["answer"],
            "analysis": question["analysis"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Serve static files in production
if os.path.exists("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")
else:
    @app.get("/")
    async def root():
        return {"message": "Vite dev server running."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
