"""لایه‌ی داده — همان پروژه‌ی Supabase ریشه، جدول‌های جدید چت‌بات.

schema در migrations/002_chatbot.sql است و باید یک‌بار در SQL Editor
داشبورد Supabase اجرا شود. این ماژول فقط CRUD است.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

from .config import Secrets

_client: Client | None = None

_REQUIRED_TABLES = [
    "conversations", "messages", "user_profiles",
    "kb_documents", "kb_chunks", "leads", "consultation_requests",
]


def get_client(secrets: Secrets | None = None) -> Client:
    global _client
    if _client is None:
        secrets = secrets or Secrets()
        if not secrets.supabase_url or not secrets.supabase_key:
            raise RuntimeError(
                "SUPABASE_URL و SUPABASE_KEY در chatbot/.env تنظیم نشده‌اند."
            )
        _client = create_client(secrets.supabase_url, secrets.supabase_key)
    return _client


def init_db(secrets: Secrets | None = None) -> None:
    """بررسی می‌کند که جدول‌های چت‌بات ساخته شده‌اند؛ اگر نه، خطای راهنما می‌دهد."""
    client = get_client(secrets)
    missing = []
    for table_name in _REQUIRED_TABLES:
        try:
            client.table(table_name).select("id").limit(1).execute()
        except Exception:  # noqa: BLE001
            missing.append(table_name)
    if missing:
        raise RuntimeError(
            f"جدول‌های زیر در Supabase در دسترس نیستند: {missing}. "
            "chatbot/migrations/002_chatbot.sql را در SQL Editor اجرا کن."
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# conversations / messages
# --------------------------------------------------------------------------

def get_active_conversation(client: Client, *, tenant_id: int, channel: str,
                            external_user_id: str) -> dict | None:
    res = (
        client.table("conversations")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("channel", channel)
        .eq("external_user_id", external_user_id)
        .eq("status", "active")
        .order("last_active_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def create_conversation(client: Client, *, tenant_id: int, channel: str,
                        external_user_id: str) -> dict:
    res = client.table("conversations").insert({
        "tenant_id": tenant_id,
        "channel": channel,
        "external_user_id": external_user_id,
    }).execute()
    return res.data[0]


def touch_conversation(client: Client, conversation_id: int) -> None:
    client.table("conversations").update(
        {"last_active_at": _now_iso()}
    ).eq("id", conversation_id).execute()


def insert_message(client: Client, *, tenant_id: int, conversation_id: int,
                   role: str, content: str | None, tool_calls: list | None = None,
                   tool_results: list | None = None) -> dict:
    res = client.table("messages").insert({
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
    }).execute()
    return res.data[0]


def recent_messages(client: Client, conversation_id: int, *, limit: int = 10) -> list[dict]:
    res = (
        client.table("messages")
        .select("role,content,created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data or []))


def count_user_messages(client: Client, conversation_id: int) -> int:
    res = (
        client.table("messages")
        .select("id", count="exact")
        .eq("conversation_id", conversation_id)
        .eq("role", "user")
        .execute()
    )
    return res.count or 0


# --------------------------------------------------------------------------
# user_profiles (حافظه‌ی بلندمدت)
# --------------------------------------------------------------------------

def get_user_profile(client: Client, *, tenant_id: int, external_user_id: str) -> dict | None:
    res = (
        client.table("user_profiles")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("external_user_id", external_user_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_user_profile(client: Client, *, tenant_id: int, external_user_id: str,
                        summary: str | None = None, facts: list | None = None,
                        display_name: str | None = None, phone: str | None = None) -> None:
    row: dict[str, Any] = {
        "tenant_id": tenant_id,
        "external_user_id": external_user_id,
        "updated_at": _now_iso(),
    }
    if summary is not None:
        row["summary"] = summary
    if facts is not None:
        row["facts"] = facts
    if display_name is not None:
        row["display_name"] = display_name
    if phone is not None:
        row["phone"] = phone
    client.table("user_profiles").upsert(
        row, on_conflict="tenant_id,external_user_id"
    ).execute()


# --------------------------------------------------------------------------
# kb_documents / kb_chunks (RAG)
# --------------------------------------------------------------------------

def get_kb_document(client: Client, *, tenant_id: int, wp_type: str, wp_id: int) -> dict | None:
    res = (
        client.table("kb_documents")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("wp_type", wp_type)
        .eq("wp_id", wp_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_kb_document(client: Client, *, tenant_id: int, wp_type: str, wp_id: int,
                       url: str, title: str, content_hash: str) -> int:
    res = client.table("kb_documents").upsert({
        "tenant_id": tenant_id,
        "source_type": "wordpress",
        "wp_type": wp_type,
        "wp_id": wp_id,
        "url": url,
        "title": title,
        "content_hash": content_hash,
        "fetched_at": _now_iso(),
    }, on_conflict="tenant_id,wp_type,wp_id").execute()
    return res.data[0]["id"]


def delete_chunks_for_document(client: Client, document_id: int) -> None:
    client.table("kb_chunks").delete().eq("document_id", document_id).execute()


def insert_kb_chunks(client: Client, *, tenant_id: int, document_id: int,
                     chunks: list[str], embeddings: list[list[float]]) -> None:
    rows = [
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "chunk_index": i,
            "content": chunk,
            "embedding": embedding,
            "token_count": len(chunk) // 4,
        }
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    if rows:
        client.table("kb_chunks").insert(rows).execute()


def match_kb_chunks(client: Client, *, query_embedding: list[float], tenant_id: int,
                    match_count: int = 5) -> list[dict]:
    res = client.rpc("match_kb_chunks", {
        "query_embedding": query_embedding,
        "match_tenant_id": tenant_id,
        "match_count": match_count,
    }).execute()
    return res.data or []


# --------------------------------------------------------------------------
# leads / consultation_requests
# --------------------------------------------------------------------------

def insert_lead_and_consultation(client: Client, *, tenant_id: int, conversation_id: int,
                                 name: str, phone: str, topic: str | None,
                                 message: str | None, reference_code: str) -> dict:
    lead = client.table("leads").insert({
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "name": name,
        "phone": phone,
        "topic": topic,
        "message": message,
        "reference_code": reference_code,
    }).execute().data[0]

    consultation = client.table("consultation_requests").insert({
        "tenant_id": tenant_id,
        "lead_id": lead["id"],
        "reference_code": reference_code,
        "phone": phone,
        "status": "pending",
    }).execute().data[0]

    return {"lead": lead, "consultation": consultation}


def find_consultation_request(client: Client, *, tenant_id: int,
                              reference_code: str | None = None,
                              phone: str | None = None) -> dict | None:
    query = client.table("consultation_requests").select("*").eq("tenant_id", tenant_id)
    if reference_code:
        query = query.eq("reference_code", reference_code)
    elif phone:
        query = query.eq("phone", phone).order("created_at", desc=True)
    else:
        return None
    res = query.limit(1).execute()
    return res.data[0] if res.data else None


# --------------------------------------------------------------------------
# رزرو تقویمی (/booking) — همان leads/consultation_requests را پر می‌کند،
# با booking_date/booking_time به‌جای پیگیری تلفنی صرف.
# --------------------------------------------------------------------------

def list_booked_times(client: Client, *, tenant_id: int, booking_date: str) -> set[str]:
    res = (
        client.table("consultation_requests")
        .select("booking_time")
        .eq("tenant_id", tenant_id)
        .eq("booking_date", booking_date)
        .neq("status", "cancelled")
        .execute()
    )
    return {row["booking_time"] for row in (res.data or []) if row.get("booking_time")}


def insert_booking(client: Client, *, tenant_id: int, name: str, phone: str,
                   topic: str | None, notes: str | None,
                   booking_date: str, booking_time: str,
                   reference_code: str) -> dict:
    lead = client.table("leads").insert({
        "tenant_id": tenant_id,
        "conversation_id": None,
        "name": name,
        "phone": phone,
        "topic": topic,
        "message": notes,
        "reference_code": reference_code,
    }).execute().data[0]

    consultation = client.table("consultation_requests").insert({
        "tenant_id": tenant_id,
        "lead_id": lead["id"],
        "reference_code": reference_code,
        "phone": phone,
        "status": "pending",
        "booking_date": booking_date,
        "booking_time": booking_time,
    }).execute().data[0]

    return {"lead": lead, "consultation": consultation}
