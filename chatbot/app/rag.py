"""بازیابی محتوای مرتبط از پایگاه دانش (kb_chunks) برای تزریق در context مدل.

RAG اینجا به‌صورت یک تابع جست‌وجو در ابتدای هر نوبت اجرا می‌شود — نه ابزار
قابل‌فراخوانی برای مدل — تا سطح function-calling فقط محدود به دو ابزار کسب‌وکار بماند.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import db
from .config import Secrets, TenantConfig
from .embeddings import embed_text


@dataclass
class RetrievedChunk:
    content: str
    url: str
    title: str
    similarity: float


def retrieve(query: str, *, tenant_id: int | None = None, top_k: int | None = None,
            cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> list[RetrievedChunk]:
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    tenant_id = tenant_id if tenant_id is not None else cfg.tenant_id
    top_k = top_k or cfg.rag_top_k

    client = db.get_client(secrets)
    query_embedding = embed_text(query, task_type="retrieval_query", cfg=cfg, secrets=secrets)
    rows = db.match_kb_chunks(
        client, query_embedding=query_embedding, tenant_id=tenant_id, match_count=top_k
    )
    return [
        RetrievedChunk(
            content=row["content"],
            url=row.get("url") or "",
            title=row.get("title") or "",
            similarity=row.get("similarity") or 0.0,
        )
        for row in rows
    ]


def format_context_block(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(منبع مرتبطی در پایگاه دانش پیدا نشد.)"
    parts = []
    for chunk in chunks:
        header = f"منبع: {chunk.title} ({chunk.url})" if chunk.title or chunk.url else "منبع:"
        parts.append(f"{header}\n{chunk.content}")
    return "\n\n---\n\n".join(parts)
