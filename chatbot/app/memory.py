"""حافظه‌ی کوتاه‌مدت (پیام‌های اخیر) و بلندمدت (خلاصه‌ی نوبتی هر کاربر)."""
from __future__ import annotations

from supabase import Client

from . import db
from .config import Secrets, TenantConfig

_SUMMARY_PROMPT = """خلاصه‌ی فعلی که از این کاربر داری:
{previous_summary}

این پیام‌های تازه را بخوان و خلاصه را به‌روز کن. فقط حقایق مهم و پایدار را نگه
دار (نام، شماره تماس در صورت گفته‌شدن، نیاز/موضوع مورد علاقه، تصمیم‌های مهم).
خلاصه را در حداکثر ۳-۴ جمله‌ی فارسی بنویس. فقط متن خلاصه را برگردان، بدون توضیح اضافه.

پیام‌های تازه:
{recent_text}
"""


def get_short_term(client: Client, conversation_id: int, *, limit_turns: int) -> list[dict]:
    """آخرین N پیام، به فرمت history مدل Gemini (role: user/model)."""
    rows = db.recent_messages(client, conversation_id, limit=limit_turns * 2)
    history = []
    for row in rows:
        role = "model" if row["role"] == "model" else "user"
        if row["role"] == "tool":
            continue
        if not row.get("content"):
            continue
        history.append({"role": role, "parts": [row["content"]]})
    return history


def get_long_term(client: Client, *, tenant_id: int, external_user_id: str) -> dict | None:
    return db.get_user_profile(client, tenant_id=tenant_id, external_user_id=external_user_id)


def maybe_refresh_long_term(client: Client, *, tenant_id: int, external_user_id: str,
                            conversation_id: int, cfg: TenantConfig, secrets: Secrets) -> None:
    """هر long_term_refresh_every پیام کاربر، خلاصه را با یک فراخوانی ارزان Gemini آپدیت می‌کند."""
    user_msg_count = db.count_user_messages(client, conversation_id)
    if user_msg_count == 0 or user_msg_count % cfg.long_term_refresh_every != 0:
        return

    import google.generativeai as genai

    from .embeddings import ensure_configured
    ensure_configured(secrets)

    profile = get_long_term(client, tenant_id=tenant_id, external_user_id=external_user_id)
    previous_summary = (profile or {}).get("summary") or "(هنوز خلاصه‌ای ثبت نشده)"

    recent_rows = db.recent_messages(client, conversation_id, limit=cfg.long_term_refresh_every * 2)
    recent_text = "\n".join(
        f"{'کاربر' if r['role'] == 'user' else 'دستیار'}: {r['content']}"
        for r in recent_rows if r.get("content")
    )

    prompt = _SUMMARY_PROMPT.format(previous_summary=previous_summary, recent_text=recent_text)
    model = genai.GenerativeModel(cfg.chat_model)
    response = model.generate_content(prompt)
    new_summary = (response.text or previous_summary).strip()

    db.upsert_user_profile(
        client, tenant_id=tenant_id, external_user_id=external_user_id, summary=new_summary
    )
