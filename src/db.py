"""لایه‌ی داده — Supabase (Postgres ابری).

schema در migrations/001_init.sql است و باید یک‌بار در SQL Editor داشبورد
Supabase اجرا شود. این ماژول فقط CRUD است؛ DDL اینجا نیست.

ماشین وضعیت یک topic:   new -> selected -> drafted | skipped
ماشین وضعیت یک article: pending -> approved -> published | rejected
ماشین وضعیت publishing: draft -> published
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager

from supabase import Client, create_client

from .config import Secrets

_client: Client | None = None


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def get_client(secrets: Secrets | None = None) -> Client:
    global _client
    if _client is None:
        secrets = secrets or Secrets()
        if not secrets.supabase_url or not secrets.supabase_key:
            raise RuntimeError(
                "SUPABASE_URL و SUPABASE_KEY در .env تنظیم نشده‌اند. "
                "از داشبورد Supabase → Project Settings → API بردار."
            )
        _client = create_client(secrets.supabase_url, secrets.supabase_key)
    return _client


@contextmanager
def connect(secrets: Secrets | None = None):
    """سازگاری با امضای قبلی (SQLite) — client مشترک Supabase را برمی‌گرداند."""
    yield get_client(secrets)


def init_db(secrets: Secrets | None = None) -> None:
    """بررسی می‌کند که جدول‌ها ساخته شده‌اند؛ اگر نه، خطای راهنما می‌دهد."""
    client = get_client(secrets)
    try:
        # چند جدول را تست کن
        for table_name in ["sources", "topics", "articles"]:
            try:
                client.from_(table_name).select("id").limit(1).execute()
                break
            except Exception:  # noqa: BLE001
                continue
        else:
            raise RuntimeError("هیچ جدولی در دسترس نیست.")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "جدول‌های Supabase در دسترس نیستند. migrations/001_init.sql را "
            "در SQL Editor داشبورد Supabase اجرا کن."
        ) from e


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def seed_sources(client: Client, tenant_id: int, sources: list[dict]) -> None:
    """منابع config.yaml را در جدول sources upsert می‌کند."""
    rows = [
        {"tenant_id": tenant_id, "name": s["name"], "url": s["url"], "type": "rss", "active": True}
        for s in sources
    ]
    if rows:
        client.table("sources").upsert(rows, on_conflict="tenant_id,url").execute()


def active_sources(client: Client, tenant_id: int) -> list[dict]:
    res = (
        client.table("sources")
        .select("name,url")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
        .execute()
    )
    return res.data or []


# --------------------------------------------------------------------------
# topics (قبلاً articles)
# --------------------------------------------------------------------------

def topic_exists(client: Client, tenant_id: int, url: str) -> bool:
    res = (
        client.table("topics")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("url_hash", url_hash(url))
        .limit(1)
        .execute()
    )
    return bool(res.data)


def insert_topic(client: Client, *, tenant_id: int, source: str, url: str,
                 title: str, summary: str, fetched_at: str) -> int:
    res = client.table("topics").insert({
        "tenant_id": tenant_id,
        "source": source,
        "url": url,
        "url_hash": url_hash(url),
        "title": title,
        "summary": summary,
        "fetched_at": fetched_at,
    }).execute()
    return res.data[0]["id"]


def candidate_topics(client: Client, tenant_id: int, since_iso: str, limit: int = 60) -> list[dict]:
    """موضوع‌های تازه (status=new) از بازه‌ی اخیر — کاندیدهای امتیازدهی."""
    res = (
        client.table("topics")
        .select("id,source,url,title,summary,fetched_at")
        .eq("tenant_id", tenant_id)
        .eq("status", "new")
        .gte("fetched_at", since_iso)
        .order("fetched_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def set_topic_score(client: Client, topic_id: int, *, score: float,
                    reason: str, status: str) -> None:
    client.table("topics").update(
        {"score": score, "score_reason": reason, "status": status}
    ).eq("id", topic_id).execute()


def set_topic_status(client: Client, topic_id: int, status: str) -> None:
    client.table("topics").update({"status": status}).eq("id", topic_id).execute()


# --------------------------------------------------------------------------
# research_briefs
# --------------------------------------------------------------------------

def insert_research_brief(client: Client, *, tenant_id: int, topic_id: int,
                          summary: str, key_points: list, claims: list,
                          angles: list, hallucination_risks: list) -> int:
    res = client.table("research_briefs").insert({
        "tenant_id": tenant_id,
        "topic_id": topic_id,
        "summary": summary,
        "key_points": key_points,
        "claims": claims,
        "angles": angles,
        "hallucination_risks": hallucination_risks,
    }).execute()
    return res.data[0]["id"]


# --------------------------------------------------------------------------
# articles (قبلاً drafts)
# --------------------------------------------------------------------------

def insert_article(client: Client, *, tenant_id: int, topic_id: int,
                   research_brief_id: int | None, title_fa: str, body_html: str,
                   meta_description: str, slug: str, tags: list[str],
                   internal_links: list) -> int:
    res = client.table("articles").insert({
        "tenant_id": tenant_id,
        "topic_id": topic_id,
        "research_brief_id": research_brief_id,
        "title_fa": title_fa,
        "body_html": body_html,
        "meta_description": meta_description,
        "slug": slug,
        "tags": tags,
        "internal_links": internal_links,
    }).execute()
    return res.data[0]["id"]


def set_article_status(client: Client, article_id: int, status: str) -> None:
    client.table("articles").update({"status": status}).eq("id", article_id).execute()


# --------------------------------------------------------------------------
# publishing
# --------------------------------------------------------------------------

def insert_publishing(client: Client, *, tenant_id: int, article_id: int,
                      wp_post_id: int, wp_edit_url: str) -> int:
    res = client.table("publishing").insert({
        "tenant_id": tenant_id,
        "article_id": article_id,
        "wp_post_id": wp_post_id,
        "wp_edit_url": wp_edit_url,
        "status": "draft",
    }).execute()
    return res.data[0]["id"]


def pending_publishing(client: Client, tenant_id: int) -> list[dict]:
    """ردیف‌هایی که هنوز در وردپرس منتشر نشده‌اند (برای sync)."""
    res = (
        client.table("publishing")
        .select("id,article_id,wp_post_id")
        .eq("tenant_id", tenant_id)
        .eq("status", "draft")
        .execute()
    )
    return res.data or []


def mark_published(client: Client, publishing_id: int, article_id: int,
                   published_at: str) -> None:
    client.table("publishing").update(
        {"status": "published", "published_at": published_at}
    ).eq("id", publishing_id).execute()
    set_article_status(client, article_id, "published")
