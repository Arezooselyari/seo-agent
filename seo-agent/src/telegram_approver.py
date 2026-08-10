"""ارسال پیام‌های تایید به تلگرام و پردازش کلیک دکمه‌ها.

این ماژول دو بخش دارد:
1. send_approval_request() — یک پیام تکی با دکمه می‌فرستد (یک‌بار، با telegram.Bot)
2. run_listener() — فرآیند دائمی که کلیک دکمه‌ها را می‌گیرد و DB را به‌روزرسانی می‌کند

برای کارکردن دکمه‌ها، listener باید همیشه در حال اجرا باشد (polling).
"""

import io
import logging
import re

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackContext, CallbackQueryHandler

from . import db
from .config import env

logger = logging.getLogger(__name__)


def _markers_to_links(body: str) -> str:
    """نشانگرهای [[anchor:]] (به صفحه‌ی واقعیِ سایت) و [[external:]] را به <a> خوانا تبدیل می‌کند.

    از همان resolverِ واقعی‌سازیِ لینکِ داخلی استفاده می‌شود که در انتشار به‌کار می‌رود،
    تا پیش‌نمایشِ تلگرام دقیقاً همان چیزی باشد که در سایت منتشر می‌شود.
    """
    try:
        from . import internal_links
        body = internal_links.linkify_internal(body)
    except Exception:
        pass  # پیش‌نمایش نباید به‌خاطرِ شکستِ شبکه/وردپرس گیر کند

    def _repl(m):
        inner = m.group(1).split("|")
        text = inner[0].split(":", 1)[-1].strip()
        url = inner[1].strip() if len(inner) > 1 else "#"
        return f'<a href="{url}">{text}</a>'
    return re.sub(r"\[\[(external:[^\]]*)\]\]", _repl, body)


def _article_to_readable_html(title: str, meta: str, body_html: str,
                              featured_url: str = "", featured_alt: str = "") -> str:
    """مقاله را به یک صفحه‌ی HTMLِ راست‌به‌چپِ زیبا و خوانا می‌پیچد (فونت Vazirmatn)."""
    body = _markers_to_links(body_html or "")
    featured = (f'<img class="featured" src="{featured_url}" alt="{featured_alt}">'
                if featured_url else "")
    return (
        "<!doctype html><html lang='fa' dir='rtl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title}</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
        "family=Vazirmatn:wght@400;500;700&display=swap'>"
        "<style>"
        ":root{--brand:#12a150;--ink:#1f2328;--muted:#6b7280;--line:#e6e8eb;--bg:#f5f7f6}"
        "*{box-sizing:border-box}"
        "body{font-family:Vazirmatn,Tahoma,'Segoe UI',sans-serif;background:var(--bg);"
        "color:var(--ink);line-height:2.05;margin:0;padding:26px 12px}"
        ".card{max-width:780px;margin:0 auto;background:#fff;border:1px solid var(--line);"
        "border-radius:16px;padding:30px 26px;box-shadow:0 1px 4px rgba(0,0,0,.06)}"
        "h1{font-size:1.6rem;line-height:1.6;margin:0 0 12px;font-weight:700}"
        ".meta{color:var(--muted);font-size:.92rem;border-bottom:1px solid var(--line);"
        "padding-bottom:16px;margin-bottom:6px}"
        "h2{font-size:1.3rem;font-weight:700;margin:1.9em 0 .6em;color:var(--brand);"
        "padding-right:12px;border-right:4px solid var(--brand)}"
        "h3{font-size:1.1rem;font-weight:500;margin:1.4em 0 .4em}"
        "p{margin:.75em 0;text-align:justify}"
        "ul,ol{padding-right:1.5em;margin:.6em 0}li{margin:.4em 0}"
        "a{color:var(--brand);text-decoration:none;border-bottom:1px dashed var(--brand)}"
        "img{max-width:100%;height:auto;border-radius:12px;margin:1.1em 0}"
        ".featured{width:100%;margin:0 0 18px;display:block}"
        "blockquote{border-right:4px solid var(--line);margin:1em 0;padding:.4em 14px;"
        "color:var(--muted)}"
        "</style></head><body><div class='card'>"
        f"<h1>{title}</h1><div class='meta'>{meta}</div>{featured}{body}"
        "</div></body></html>"
    )


async def send_article_document(
    article_id: int, title: str, body_html: str, meta: str = "",
    featured_url: str = "", featured_alt: str = "",
    token: str | None = None, chat_id: str | None = None,
) -> bool:
    """متنِ کاملِ مقاله را به‌صورت فایلِ HTMLِ خوانا به تلگرام می‌فرستد (برای مطالعه پیش از تایید)."""
    token = token or env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    if not body_html:
        return False
    html = _article_to_readable_html(title, meta, body_html, featured_url, featured_alt)
    doc = io.BytesIO(html.encode("utf-8"))
    doc.name = f"article_{article_id}.html"
    bot = Bot(token=token)
    try:
        async with bot:
            await bot.send_document(
                chat_id=chat_id, document=doc, filename=f"article_{article_id}.html",
                caption=f"📄 متنِ کاملِ مقاله #{article_id} — برای خواندن باز کن",
            )
        return True
    except Exception as e:
        logger.error(f"ارسالِ فایلِ مقاله #{article_id} نشد: {e}")
        return False


def _build_keyboard(article_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های inline تایید/ردّ/لغو را می‌سازد."""
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"approval_approve_{article_id}"),
            InlineKeyboardButton("❌ ردّ", callback_data=f"approval_reject_{article_id}"),
        ],
        [
            InlineKeyboardButton("⊗ لغو", callback_data=f"approval_cancel_{article_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _build_message(
    title: str, seo_grade: int, preview: str, warning: str | None = None,
    final_score: float | None = None, final_verdict: str | None = None,
) -> str:
    """متن پیام تایید را می‌سازد (متن ساده — بدون Markdown تا entity نشکند).

    warning: اگر مقاله از گیت خودکار عبور نکرده ولی نزدیک بوده، دلایل اینجا می‌آید.
    final_score/final_verdict: خروجی لایه‌ی نمره‌ی نهایی — اگر None باشد (داده‌ی
    قدیمی) پیام مثل قبل فقط نمره‌ی فنی را نشان می‌دهد (سازگاری عقب‌رو).
    """
    header = "📝 مقاله جدید برای تایید" if not warning else "⚠️ مقاله نزدیک به مرز — نیاز به بررسی شما"
    msg = (
        f"{header}\n\n"
        f"📌 عنوان: {title}\n"
        f"⭐ نمره‌ی SEO: {seo_grade}/100\n"
    )
    if final_score is not None:
        verdict_fa = {"approved": "تایید خودکار", "needs_review": "نیاز به بررسی"}.get(
            final_verdict, final_verdict or "-"
        )
        msg += f"🎯 نمره‌ی نهایی: {final_score}/100 — {verdict_fa}\n"
    if warning:
        msg += f"\n🔎 دلایل عدم تایید خودکار:\n{warning}\n"
    msg += (
        f"\n📖 پیش‌نمایش:\n{preview}\n\n"
        f"🔗 لطفاً تصمیم بگیرید:"
    )
    return msg


async def send_approval_request(
    article_id: int, title: str, seo_grade: int, preview: str,
    token: str | None = None, chat_id: str | None = None,
    warning: str | None = None,
    final_score: float | None = None, final_verdict: str | None = None,
) -> bool:
    """یک پیام تایید را به تلگرام می‌فرستد (با telegram.Bot، بدون نیاز به Application).

    Returns:
        True اگر موفق بود.
    """
    token = token or env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or env("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("توکن یا Chat ID تلگرام تنظیم نشده.")
        return False

    bot = Bot(token=token)
    try:
        async with bot:
            await bot.send_message(
                chat_id=chat_id,
                text=_build_message(title, seo_grade, preview, warning,
                                    final_score=final_score, final_verdict=final_verdict),
                reply_markup=_build_keyboard(article_id),
            )
        logger.info(f"پیام تایید برای مقاله #{article_id} ارسال شد.")
        return True
    except Exception as e:
        logger.error(f"خطا در ارسال پیام تلگرام: {e}")
        return False


async def _handle_button(update: Update, context: CallbackContext) -> None:
    """کلیک دکمه‌ی تایید/ردّ/لغو را پردازش می‌کند."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")  # "approval_<action>_<id>"
    if len(parts) < 3:
        return
    action = parts[1]
    try:
        article_id = int(parts[2])
    except ValueError:
        return

    conn = db.connect()
    try:
        article = db.get_article(conn, article_id)
        if not article:
            await query.edit_message_text(f"❌ مقاله #{article_id} یافت نشد.")
            return

        if action == "approve":
            db.set_status(conn, article_id, "approved")
            status_text = "✅ تایید شد — آماده‌ی انتشار"
        elif action == "reject":
            db.set_status(conn, article_id, "rejected")
            status_text = "❌ ردّ شد"
        elif action == "cancel":
            status_text = "⊗ لغو شد (وضعیت تغییر نکرد)"
        else:
            return

        new_text = (query.message.text or "") + f"\n\n✔️ *تصمیم:* {status_text}"
        await query.edit_message_text(new_text, parse_mode="Markdown")
        logger.info(f"مقاله #{article_id}: {action.upper()}")
    except Exception as e:
        logger.error(f"خطا در پردازش دکمه: {e}")
    finally:
        conn.close()


def run_listener(token: str | None = None) -> None:
    """فرآیند دائمی که کلیک دکمه‌ها را می‌گیرد (polling).

    این را در یک پنجره‌ی جدا اجرا کن و باز نگه دار:
        python -m src.telegram_approver
    """
    token = token or env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")

    app = Application.builder().token(token).build()
    app.add_handler(CallbackQueryHandler(_handle_button, pattern="^approval_"))
    logger.info("شنونده‌ی تلگرام شروع شد — منتظر کلیک دکمه‌ها... (Ctrl+C برای توقف)")
    app.run_polling()


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    run_listener()
