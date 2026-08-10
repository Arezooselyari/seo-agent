"""فراخوانی مکالمه‌ای Gemini — چندنوبتی + حلقه‌ی function calling.

برخلاف src/llm.py (تک‌فراخوانی JSON-schema)، این ماژول مخصوص گفتگوی پیوسته است:
تاریخچه‌ی پیام‌ها + RAG context تزریق‌شده + حداکثر دو ابزار قابل‌فراخوانی.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import google.generativeai as genai

from .config import Secrets, TenantConfig
from .embeddings import ensure_configured

_MAX_TOOL_ITERATIONS = 4


@dataclass
class ToolSpec:
    declaration: dict  # {"name", "description", "parameters": <json schema>}
    execute: Callable[[dict], dict]


@dataclass
class ChatResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)


def build_system_prompt(cfg: TenantConfig, profile: dict | None, rag_context: str) -> str:
    parts = [cfg.system_persona.strip()]

    if profile and profile.get("summary"):
        parts.append(f"آنچه از این کاربر می‌دانیم: {profile['summary']}")

    parts.append(f"منابع مرتبط برای پاسخ به این پیام:\n{rag_context}")

    return "\n\n".join(p for p in parts if p)


def chat_once(history: list[dict], system_prompt: str, user_text: str, *,
             tools: list[ToolSpec] | None = None,
             cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> ChatResult:
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    ensure_configured(secrets)

    tools_by_name = {t.declaration["name"]: t for t in (tools or [])}
    genai_tools = None
    if tools:
        genai_tools = [{"function_declarations": [t.declaration for t in tools]}]

    model = genai.GenerativeModel(
        cfg.chat_model, system_instruction=system_prompt, tools=genai_tools
    )
    chat = model.start_chat(history=history)
    response = chat.send_message(user_text)

    tool_calls: list[dict] = []
    tool_results: list[dict] = []

    for _ in range(_MAX_TOOL_ITERATIONS):
        function_calls = [
            part.function_call
            for part in response.candidates[0].content.parts
            if part.function_call and part.function_call.name
        ]
        if not function_calls:
            break

        function_response_parts = []
        for fc in function_calls:
            args = dict(fc.args) if fc.args else {}
            tool_calls.append({"name": fc.name, "args": args})

            tool = tools_by_name.get(fc.name)
            result = tool.execute(args) if tool else {"error": f"ابزار ناشناخته: {fc.name}"}
            tool_results.append({"name": fc.name, "result": result})

            function_response_parts.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fc.name, response={"result": result}
                    )
                )
            )

        response = chat.send_message(
            genai.protos.Content(parts=function_response_parts, role="function")
        )

    return ChatResult(text=response.text, tool_calls=tool_calls, tool_results=tool_results)
