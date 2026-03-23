#!/usr/bin/env python3
"""Stream benchmark for OpenAI-compatible Chat Completions APIs.

Features:
- Print timestamp before request starts.
- Print timestamp for every streamed content chunk.
- Print TTFT (time to first token/chunk) and total elapsed time.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any

import requests

PROVIDER_BASE_URL = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com",
    "kimi": "https://api.moonshot.cn/v1",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark streaming LLM API speed")
    parser.add_argument("--provider", choices=["qwen", "deepseek", "kimi"], default=None)
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base url")
    parser.add_argument("--api-key", default=None, help="API key (optional if env var is set)")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--prompt", required=True, help="User prompt")
    parser.add_argument("--system", default="你是一个简洁且准确的助手。", help="System prompt")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser


def resolve_base_url(provider: str | None, base_url: str | None) -> str:
    if base_url:
        return base_url.rstrip("/")
    if provider:
        return PROVIDER_BASE_URL[provider]
    raise ValueError("You must provide either --provider or --base-url")


def resolve_api_key(args: argparse.Namespace) -> str | None:
    if args.api_key:
        return args.api_key

    env_name = None
    if args.provider == "qwen":
        env_name = "QWEN_API_KEY"
    elif args.provider == "deepseek":
        env_name = "DEEPSEEK_API_KEY"
    elif args.provider == "kimi":
        env_name = "KIMI_API_KEY"

    if env_name:
        return os.getenv(env_name)

    # Fallback for --base-url usage
    if args.base_url:
        url = args.base_url.lower()
        if "deepseek" in url:
            return os.getenv("DEEPSEEK_API_KEY")
        if "moonshot" in url or "kimi" in url:
            return os.getenv("KIMI_API_KEY")
        if "dashscope" in url or "qwen" in url:
            return os.getenv("QWEN_API_KEY")

    return None


def parse_sse_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return {"_done": True}
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {"_raw": data}


def main() -> int:
    args = build_parser().parse_args()

    base_url = resolve_base_url(args.provider, args.base_url)
    api_key = resolve_api_key(args)
    if not api_key:
        print(f"[{now_str()}] 未检测到 API Key。")
        print("请先设置环境变量，例如：")
        print('  export DEEPSEEK_API_KEY=\"你的key\"')
        print('  export QWEN_API_KEY=\"你的key\"')
        print('  export KIMI_API_KEY=\"你的key\"')
        print("或使用参数：--api-key \"你的key\"")
        return 1

    url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": args.system},
            {"role": "user", "content": args.prompt},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": True,
    }

    print(f"[{now_str()}] 准备调用 API")
    print(f"[{now_str()}] POST {url}")
    start = time.perf_counter()
    first_chunk_at: float | None = None
    full_text_parts: list[str] = []

    try:
        with requests.post(url, headers=headers, json=payload, stream=True, timeout=args.timeout) as resp:
            response_arrived = time.perf_counter()
            print(
                f"[{now_str()}] 收到 HTTP 响应: status={resp.status_code}, "
                f"耗时={response_arrived - start:.3f}s"
            )
            resp.raise_for_status()

            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue

                parsed = parse_sse_line(raw_line)
                if not parsed:
                    continue

                if parsed.get("_done"):
                    print(f"[{now_str()}] [DONE]")
                    break

                if "_raw" in parsed:
                    elapsed = time.perf_counter() - start
                    print(f"[{now_str()}] +{elapsed:.3f}s 原始片段: {parsed['_raw']}")
                    continue

                choices = parsed.get("choices") or []
                if not choices:
                    continue

                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                reasoning = delta.get("reasoning_content")

                if content:
                    now = time.perf_counter()
                    if first_chunk_at is None:
                        first_chunk_at = now
                        print(f"[{now_str()}] 首个内容片段到达 TTFT={first_chunk_at - start:.3f}s")
                    elapsed = now - start
                    full_text_parts.append(content)
                    print(f"[{now_str()}] +{elapsed:.3f}s 内容片段: {content}")

                if reasoning:
                    elapsed = time.perf_counter() - start
                    print(f"[{now_str()}] +{elapsed:.3f}s 思考片段: {reasoning}")

    except requests.RequestException as exc:
        elapsed = time.perf_counter() - start
        print(f"[{now_str()}] 请求失败 +{elapsed:.3f}s: {exc}")
        return 1

    total_elapsed = time.perf_counter() - start
    merged = "".join(full_text_parts)

    print("\n========== 汇总 ==========")
    print(f"总耗时: {total_elapsed:.3f}s")
    if first_chunk_at is not None:
        print(f"TTFT: {first_chunk_at - start:.3f}s")
    else:
        print("TTFT: 未收到内容片段")
    print("完整回复:")
    print(merged)

    return 0


if __name__ == "__main__":
    sys.exit(main())
