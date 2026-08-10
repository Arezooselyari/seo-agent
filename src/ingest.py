"""مرحله ۱ — Ingest: خواندن RSS منابع و تشخیص موضوع‌های جدید.

منابع از جدول sources در Supabase خوانده می‌شوند (در اولین اجرا از
config.yaml seed می‌شوند). dedup با url_hash انجام می‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser

from .config import Secrets, TenantConfig
from . import db


@dataclass
class FetchedArticle:
    source: str
    url: str
    title: str
    summary: str


def _is_relevant(title: str, summary: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = f"{title} {summary}".lower()
    return any(kw.lower() in text for kw in keywords)


def fetch_new_articles(cfg: TenantConfig, secrets: Secrets | None = None) -> list[FetchedArticle]:
    """همه‌ی منابع فعال را می‌خواند، موضوع‌های مرتبط و *جدید* را برمی‌گرداند
    و در جدول topics ثبت می‌کند (تا دفعه‌ی بعد تکراری نباشند)."""
    new_items: list[FetchedArticle] = []
    now = datetime.now(timezone.utc).isoformat()

    with db.connect(secrets) as client:
        # seed منابع config.yaml در جدول sources (idempotent)
        db.seed_sources(
            client, cfg.tenant_id,
            [{"name": s.name, "url": s.rss} for s in cfg.sources],
        )
        sources = db.active_sources(client, cfg.tenant_id)

        for source in sources:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries:
                url = entry.get("link", "")
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                if not url:
                    continue
                if not _is_relevant(title, summary, cfg.ai_keywords):
                    continue
                if db.topic_exists(client, cfg.tenant_id, url):
                    continue

                db.insert_topic(
                    client,
                    tenant_id=cfg.tenant_id,
                    source=source["name"],
                    url=url,
                    title=title,
                    summary=summary,
                    fetched_at=now,
                )
                new_items.append(
                    FetchedArticle(source=source["name"], url=url, title=title, summary=summary)
                )

    return new_items


if __name__ == "__main__":
    db.init_db()
    cfg = TenantConfig.load()
    items = fetch_new_articles(cfg)
    print(f"تعداد موضوع جدید و مرتبط: {len(items)}\n")
    for it in items[:20]:
        print(f"[{it.source}] {it.title}\n  {it.url}\n")
