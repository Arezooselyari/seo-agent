"""ایندکس کردن محتوای وردپرس برای RAG.

خواندن posts و pages از REST API عمومی وردپرس (بدون نیاز به احراز هویت)،
تمیز کردن HTML، chunk کردن متن، گرفتن embedding و ذخیره در kb_documents/kb_chunks.
idempotent است: اگر محتوای یک صفحه عوض نشده باشد (content_hash یکسان)، رد می‌شود.
"""
from __future__ import annotations

import hashlib
import re

import httpx
from bs4 import BeautifulSoup

from . import db
from .config import Secrets, TenantConfig
from .embeddings import embed_texts

_PER_PAGE = 50


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(separator="\n")
    # خطوط خالی پشت‌سرهم را یکی کن
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_wp_content(wp_url: str) -> list[dict]:
    """صفحه‌بندی روی /wp-json/wp/v2/posts و /pages؛ هر آیتم: id, type, url, title, content."""
    items: list[dict] = []
    base = wp_url.rstrip("/")
    with httpx.Client(timeout=30) as client:
        for wp_type in ("posts", "pages"):
            page = 1
            while True:
                resp = client.get(
                    f"{base}/wp-json/wp/v2/{wp_type}",
                    params={"per_page": _PER_PAGE, "page": page, "status": "publish"},
                )
                if resp.status_code == 400:  # صفحه‌ی خارج از محدوده — تمام شد
                    break
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    break
                for entry in data:
                    items.append({
                        "wp_id": entry["id"],
                        "wp_type": "post" if wp_type == "posts" else "page",
                        "url": entry.get("link", ""),
                        "title": _strip_html(entry.get("title", {}).get("rendered", "")),
                        "content": _strip_html(entry.get("content", {}).get("rendered", "")),
                    })
                page += 1
    return items


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """تقسیم متن به قطعات، با اولویت شکستن روی مرز پاراگراف/جمله، نه وسط کلمه."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 <= max_chars:
            current = f"{current}\n{para}".strip()
            continue
        if current:
            chunks.append(current)
        if len(para) <= max_chars:
            current = para
        else:
            # پاراگراف خیلی بزرگ — با پنجره‌ی کاراکتری با overlap بشکن
            start = 0
            while start < len(para):
                end = start + max_chars
                chunks.append(para[start:end])
                start = end - overlap
            current = ""
    if current:
        chunks.append(current)
    return chunks


def ingest_all(cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> dict:
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    client = db.get_client(secrets)

    items = fetch_wp_content(secrets.wp_url or cfg.wp_url)

    counts = {"documents": 0, "chunks": 0, "skipped": 0}

    for item in items:
        full_text = f"{item['title']}\n\n{item['content']}".strip()
        if not full_text:
            counts["skipped"] += 1
            continue

        h = content_hash(full_text)
        existing = db.get_kb_document(
            client, tenant_id=cfg.tenant_id, wp_type=item["wp_type"], wp_id=item["wp_id"]
        )
        if existing and existing.get("content_hash") == h:
            counts["skipped"] += 1
            continue

        document_id = db.upsert_kb_document(
            client,
            tenant_id=cfg.tenant_id,
            wp_type=item["wp_type"],
            wp_id=item["wp_id"],
            url=item["url"],
            title=item["title"],
            content_hash=h,
        )
        if existing:
            db.delete_chunks_for_document(client, document_id)

        chunks = chunk_text(
            full_text, max_chars=cfg.chunk_max_chars, overlap=cfg.chunk_overlap_chars
        )
        if not chunks:
            continue

        embeddings = embed_texts(chunks, task_type="retrieval_document", cfg=cfg, secrets=secrets)
        db.insert_kb_chunks(
            client,
            tenant_id=cfg.tenant_id,
            document_id=document_id,
            chunks=chunks,
            embeddings=embeddings,
        )

        counts["documents"] += 1
        counts["chunks"] += len(chunks)

    return counts
