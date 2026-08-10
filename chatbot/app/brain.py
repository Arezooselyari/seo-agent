"""هسته‌ی مرکزی چت‌بات — تنها نقطه‌ی ورودی مشترک هر سه کانال (تلگرام، وب، ویجت).

هر کانال فقط باید channel و external_user_id بسازد و متن پیام را به
handle_message بدهد؛ بقیه (حافظه، RAG، ابزارها) اینجا یک‌جا مدیریت می‌شود.
"""
from __future__ import annotations

from . import db, identity, memory, rag
from .config import Secrets, TenantConfig
from .llm_chat import ChatResult, build_system_prompt, chat_once
from .tools import get_tool_specs


def handle_message(channel: str, external_user_id: str, text: str, *,
                   cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> str:
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    client = db.get_client(secrets)

    conversation = identity.get_or_create_conversation(
        client, tenant_id=cfg.tenant_id, channel=channel, external_user_id=external_user_id
    )
    conversation_id = conversation["id"]

    db.insert_message(
        client, tenant_id=cfg.tenant_id, conversation_id=conversation_id,
        role="user", content=text,
    )
    db.touch_conversation(client, conversation_id)

    retrieved = rag.retrieve(text, tenant_id=cfg.tenant_id, cfg=cfg, secrets=secrets)
    rag_context = rag.format_context_block(retrieved)

    profile = memory.get_long_term(client, tenant_id=cfg.tenant_id, external_user_id=external_user_id)
    history = memory.get_short_term(client, conversation_id, limit_turns=cfg.short_term_turns)
    system_prompt = build_system_prompt(cfg, profile, rag_context)

    tools = get_tool_specs(
        client=client, tenant_id=cfg.tenant_id, conversation_id=conversation_id, secrets=secrets,
    )

    result: ChatResult = chat_once(
        history, system_prompt, text, tools=tools, cfg=cfg, secrets=secrets
    )

    db.insert_message(
        client, tenant_id=cfg.tenant_id, conversation_id=conversation_id,
        role="model", content=result.text,
        tool_calls=result.tool_calls or None, tool_results=result.tool_results or None,
    )

    memory.maybe_refresh_long_term(
        client, tenant_id=cfg.tenant_id, external_user_id=external_user_id,
        conversation_id=conversation_id, cfg=cfg, secrets=secrets,
    )

    return result.text
