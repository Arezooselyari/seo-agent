"""ربات دوطرفه‌ی Telegram برای تأیید/رد/بازنویسی مقاله‌ها.

فلوی کاری:
1. Pipeline مقاله را برای بازبینی می‌فرستد (مقاله + فایل HTML)
2. کاربر /approve، /reject یا /rewrite می‌فرستد
3. ربات DB را آپدیت می‌کنه و اقدام می‌کنه

ربات 24/7 مسلسل (long-polling) گوش می‌دهد.
"""
from __future__ import annotations

import time
import httpx
from datetime import datetime, timezone

from .config import Secrets
from . import db
from .generate import generate_article
from .notify import send_telegram, notify_error
from .render import save_article_html
from .research import ResearchBrief

TELEGRAM_API = "https://api.telegram.org/bot"


def _api_url(token: str, method: str) -> str:
    return f"{TELEGRAM_API}{token}/{method}"


def get_updates(token: str, offset: int = 0, timeout: int = 20) -> list[dict]:
    """دریافت پیام‌های جدید از Telegram."""
    try:
        resp = httpx.get(
            _api_url(token, "getUpdates"),
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 5,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception as e:
        print(f"[bot] getUpdates خطا: {e}")
        return []


def send_message(token: str, chat_id: str, text: str) -> bool:
    """ارسال پیام متنی."""
    try:
        resp = httpx.post(
            _api_url(token, "sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[bot] sendMessage خطا: {e}")
        return False


def handle_approve(
    article_id: int, secrets: Secrets
) -> bool:
    """تأیید مقاله و نشانه‌گذاری برای انتشار."""
    try:
        with db.connect(secrets) as client:
            client.table("articles").update({"status": "approved"}).eq(
                "id", article_id
            ).execute()
            send_message(
                secrets.telegram_bot_token,
                secrets.telegram_chat_id,
                "✅ مقاله تأیید شد. برای انتشار آماده است.",
            )
            return True
    except Exception as e:
        print(f"[bot] approve خطا: {e}")
        return False


def handle_reject(article_id: int, topic_id: int, secrets: Secrets) -> bool:
    """رد مقاله و موضوع را skip کردن."""
    try:
        with db.connect(secrets) as client:
            # مقاله را به status rejected تغییر بده
            client.table("articles").update({"status": "rejected"}).eq(
                "id", article_id
            ).execute()
            # موضوع را skip کردن
            client.table("topics").update({"status": "rejected"}).eq(
                "id", topic_id
            ).execute()
            send_message(
                secrets.telegram_bot_token,
                secrets.telegram_chat_id,
                "❌ مقاله رد شد. موضوع کنار گذاشته شد.\n\nفردا موضوع جدید ارسال می‌شود.",
            )
            return True
    except Exception as e:
        print(f"[bot] reject خطا: {e}")
        return False


def handle_rewrite(
    article_id: int, topic_id: int, cfg, secrets: Secrets
) -> tuple[bool, str]:
    """بازنویسی مقاله با همان brief. برمی‌گرداند (success: bool, error_msg: str)."""
    try:
        with db.connect(secrets) as client:
            # دریافت brief از DB
            articles = client.table("articles").select(
                "research_brief_id"
            ).eq("id", article_id).execute()
            if not articles.data:
                return False, "مقاله در DB پیدا نشد"

            brief_id = articles.data[0]["research_brief_id"]
            briefs = client.table("research_briefs").select("*").eq(
                "id", brief_id
            ).execute()
            if not briefs.data:
                return False, "brief در DB پیدا نشد"

            brief_data = briefs.data[0]
            brief = ResearchBrief(
                summary=brief_data["summary"],
                key_points=brief_data.get("key_points", []),
                claims=brief_data.get("claims", []),
                angles=brief_data.get("angles", []),
                hallucination_risks=brief_data.get("hallucination_risks", []),
                brief_id=brief_id,
            )

            # دریافت topic برای اطلاعات منبع
            topics = client.table("topics").select("*").eq(
                "id", topic_id
            ).execute()
            if not topics.data:
                return False, "موضوع در DB پیدا نشد"

            topic = topics.data[0]

            # دریافت internal links (از مقاله قدیم)
            old_articles = client.table("articles").select(
                "internal_links"
            ).eq("id", article_id).execute()
            internal_links = []
            if old_articles.data:
                links_urls = old_articles.data[0].get("internal_links", [])
                # تبدیل URLs به dict format (بدون title، فقط برای استفاده)
                internal_links = [{"url": url, "title": url} for url in links_urls]

        # بازنویسی
        send_message(
            secrets.telegram_bot_token,
            secrets.telegram_chat_id,
            "⏳ مقاله دوباره نوشته می‌شود...",
        )

        from .generate import generate_article
        from .images import fetch_pexels_image

        new_article = generate_article(
            brief=brief,
            source_name=topic["source"],
            source_url=topic["url"],
            original_title=topic["title"],
            topic_reason="بازنویسی پس از درخواست کاربر",
            internal_links=internal_links,
            cfg=cfg,
            secrets=secrets,
        )

        # ذخیره مقاله جدید
        with db.connect(secrets) as client:
            new_article_id = db.insert_article(
                client,
                tenant_id=cfg.tenant_id,
                topic_id=topic_id,
                research_brief_id=brief_id,
                title_fa=new_article.title,
                body_html=new_article.to_html(),
                meta_description=new_article.meta_description,
                slug=new_article.slug,
                tags=new_article.tags,
                internal_links=new_article.internal_links_used,
            )
            # مقاله قدیم را به superseded علامت‌گذاری کن
            client.table("articles").update({"status": "superseded"}).eq(
                "id", article_id
            ).execute()

        # عکس و HTML
        image = None
        if new_article.image_query:
            image = fetch_pexels_image(new_article.image_query, secrets)

        html_path = save_article_html(new_article, image=image)

        # ارسال مقاله جدید
        from .notify import notify_draft

        notify_draft(
            title=new_article.title,
            meta_description=new_article.meta_description,
            score=0,
            reason="بازنویسی شده",
            secrets=secrets,
        )
        from .notify import send_document

        send_document(
            html_path,
            caption=f"📄 مقاله‌ی دوباره‌نوشته:\n{new_article.title}\n\n/approve یا /reject یا /rewrite",
            secrets=secrets,
        )

        return True, ""

    except Exception as e:
        print(f"[bot] rewrite خطا: {e}")
        notify_error("bot-rewrite", str(e), secrets)
        return False, str(e)


# نماد فارسی هر وضعیت برای نمایش زیباتر
_STATUS_LABELS = {
    "pending_review": "⏳ منتظر بازبینی",
    "approved": "✅ تأییدشده",
    "rejected": "❌ ردشده",
    "superseded": "🔄 بازنویسی‌شده",
    "published": "🌐 منتشرشده",
    "pending": "⏳ در انتظار",
}
_STATUS_ICON = {
    "pending_review": "⏳",
    "approved": "✅",
    "rejected": "❌",
    "superseded": "🔄",
    "published": "🌐",
    "pending": "⏳",
}


def _build_status(secrets: Secrets, days: int = 7, max_titles: int = 15) -> str:
    """گزارش وضعیت: شمارش هر وضعیت + عنوان مقاله‌های اخیر."""
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with db.connect(secrets) as client:
        # شمارش کل بر اساس وضعیت
        counts = client.table("articles").select("status").execute()
        statuses: dict[str, int] = {}
        for row in counts.data:
            st = row["status"] or "نامشخص"
            statuses[st] = statuses.get(st, 0) + 1

        # عنوان مقاله‌های اخیر (۷ روز گذشته)
        recent = (
            client.table("articles")
            .select("id,title_fa,status,created_at")
            .gte("created_at", since)
            .order("created_at", desc=True)
            .limit(max_titles)
            .execute()
        )

    # بخش شمارش
    count_lines = []
    for st, n in sorted(statuses.items(), key=lambda x: -x[1]):
        label = _STATUS_LABELS.get(st, st)
        count_lines.append(f"{label}: {n}")
    count_text = "\n".join(count_lines) or "هیچ مقاله‌ای نیست."

    # بخش عنوان‌ها
    if recent.data:
        title_lines = []
        for r in recent.data:
            icon = _STATUS_ICON.get(r["status"], "•")
            title = (r["title_fa"] or "بدون عنوان").strip()
            if len(title) > 55:
                title = title[:55] + "…"
            title_lines.append(f"{icon} {title}")
        titles_text = "\n".join(title_lines)
        titles_block = f"\n\n📰 <b>مقاله‌های {days} روز اخیر:</b>\n{titles_text}"
    else:
        titles_block = f"\n\n📰 در {days} روز اخیر مقاله‌ای ثبت نشده."

    return f"📊 <b>وضعیت کلی:</b>\n{count_text}{titles_block}"


def process_update(update: dict, cfg, secrets: Secrets) -> None:
    """پردازش یک update (پیام) از Telegram."""
    if "message" not in update:
        return

    msg = update["message"]
    text = msg.get("text", "").strip()
    chat_id = str(msg["chat"]["id"])

    print(f"[bot] پیام دریافت شد از chat={chat_id}: «{text}»")

    # فقط از chat_id درست بپذیر
    if chat_id != secrets.telegram_chat_id:
        print(f"[bot] ⛔ chat_id غیرمجاز ({chat_id}) — نادیده گرفته شد.")
        return

    # ── دستورات مستقل (نیاز به مقاله‌ی pending ندارند) ──
    if text in ("/start", "/help"):
        send_message(
            secrets.telegram_bot_token,
            chat_id,
            "🤖 <b>ربات محتوای فارسی AI</b>\n\n"
            "وقتی مقاله‌ی جدید برات ارسال شد، یکی از این‌ها رو بفرست:\n\n"
            "✅ /approve — تأیید مقاله (آماده‌ی انتشار)\n"
            "❌ /reject — رد موضوع (فردا موضوع نو)\n"
            "🔄 /rewrite — بازنویسی مقاله با همان تحقیق\n\n"
            "📊 /status — آمار مقاله‌ها\n"
            "❓ /help — همین راهنما",
        )
        return

    if text == "/status":
        try:
            status_text = _build_status(secrets)
            send_message(secrets.telegram_bot_token, chat_id, status_text)
        except Exception as e:
            print(f"[bot] status خطا: {e}")
            send_message(secrets.telegram_bot_token, chat_id,
                        f"❌ خطا در دریافت وضعیت:\n{str(e)[:100]}")
        return

    # ── دستورات بازبینی (نیاز به مقاله‌ی pending دارند) ──
    if text not in ("/approve", "/reject", "/rewrite"):
        send_message(
            secrets.telegram_bot_token,
            chat_id,
            "❓ دستور نامعتبر. /help را بفرست.",
        )
        return

    # دریافت آخرین مقاله‌ی منتظر بازبینی
    with db.connect(secrets) as client:
        articles = (
            client.table("articles")
            .select("id,topic_id,status")
            .in_("status", ["pending_review", "pending_rewrite"])
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        if not articles.data:
            send_message(
                secrets.telegram_bot_token,
                chat_id,
                "❌ هیچ مقاله‌ی منتظر بازبینی نیست.",
            )
            return

        article = articles.data[0]
        article_id = article["id"]
        topic_id = article["topic_id"]

    # دستورات
    if text == "/approve":
        if handle_approve(article_id, secrets):
            print(f"[bot] مقاله {article_id} تأیید شد.")
        else:
            send_message(
                secrets.telegram_bot_token,
                chat_id,
                "❌ خطا در تأیید.",
            )

    elif text == "/reject":
        if handle_reject(article_id, topic_id, secrets):
            print(f"[bot] مقاله {article_id} رد شد.")
        else:
            send_message(
                secrets.telegram_bot_token,
                chat_id,
                "❌ خطا در رد.",
            )

    elif text == "/rewrite":
        success, error_msg = handle_rewrite(article_id, topic_id, cfg, secrets)
        if success:
            print(f"[bot] مقاله {article_id} بازنویسی شد.")
        else:
            if error_msg and ("quota" in error_msg.lower() or "429" in error_msg):
                send_message(
                    secrets.telegram_bot_token,
                    chat_id,
                    "⚠️ محدودیت API Gemini:\n"
                    "حد روزانه (۲۰ درخواست) تمام شده.\n"
                    "❌ بازنویسی فردا ممکن است.\n\n"
                    "/status برای وضعیت",
                )
            elif error_msg:
                send_message(
                    secrets.telegram_bot_token,
                    chat_id,
                    f"❌ خطا:\n{error_msg[:80]}",
                )
            else:
                send_message(
                    secrets.telegram_bot_token,
                    chat_id,
                    "❌ خطا در بازنویسی.",
                )


def run_bot(cfg=None, secrets: Secrets | None = None) -> None:
    """اجرای ربات (long-polling)."""
    from .config import TenantConfig

    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()

    print("[bot] شروع شد. صبر می‌کنم برای پیام‌های تلگرام...")
    offset = 0

    try:
        while True:
            updates = get_updates(secrets.telegram_bot_token, offset=offset)
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    process_update(update, cfg, secrets)
                except Exception as e:  # noqa: BLE001
                    print(f"[bot] خطا در پردازش update: {e}")

            if not updates:
                time.sleep(1)

    except KeyboardInterrupt:
        print("[bot] متوقف شد.")


if __name__ == "__main__":
    run_bot()
