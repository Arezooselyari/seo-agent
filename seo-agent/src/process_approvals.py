"""پردازش کلیک دکمه‌های تایید از تلگرام (یک‌بار اجرا، مطمئن).

برخلاف run_polling که باید همیشه روشن بماند، این اسکریپت یک‌بار اجرا می‌شود،
تمام کلیک‌های در صف را می‌خواند، دیتابیس را آپدیت می‌کند و پیام‌ها را ویرایش می‌کند.

می‌توان آن را در Task Scheduler هر چند دقیقه اجرا کرد (مثل بقیه‌ی پروژه).
"""
import asyncio
import logging
import sys

from telegram import Bot

from . import db
from .config import env

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_STATUS_TEXT = {
    "approve": ("approved", "✅ تایید شد — آماده‌ی انتشار"),
    "reject": ("rejected", "❌ ردّ شد"),
    "cancel": (None, "⊗ لغو شد (وضعیت تغییر نکرد)"),
}


def _try_publish(article_id: int) -> str:
    """پس از تایید، مقاله را در وردپرس منتشر می‌کند. یک خطِ وضعیت برای نمایش برمی‌گرداند.

    شکست (رمزِ نامعتبر/اتصال) مانعِ ثبتِ «approved» نمی‌شود — مقاله در صف می‌ماند و بعداً
    با `python -m src.wordpress <id>` قابلِ انتشار است.
    """
    try:
        from . import wordpress
        result = wordpress.publish_by_id(article_id)
        url = result.get("url")
        if url:
            return f"🌐 منتشر شد: {url}"
        return "⚠️ انتشار نتیجه‌ای نداشت — دستی تلاش کن."
    except Exception as e:
        logger.warning(f"انتشارِ خودکارِ #{article_id} نشد: {e}")
        return f"⏳ در صفِ انتشار (خطای وردپرس: {str(e)[:80]})"


async def process_pending_clicks() -> int:
    """تمام کلیک‌های در صف را پردازش می‌کند. تعداد پردازش‌شده را برمی‌گرداند."""
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN تنظیم نشده.")
        return 0

    bot = Bot(token)
    processed = 0
    conn = db.connect()

    try:
        async with bot:
            updates = await bot.get_updates(timeout=5)
            last_update_id = None

            for u in updates:
                last_update_id = u.update_id
                cq = u.callback_query
                if not cq or not cq.data.startswith("approval_"):
                    continue

                parts = cq.data.split("_")  # approval_<action>_<id>
                if len(parts) < 3:
                    continue
                action = parts[1]
                try:
                    article_id = int(parts[2])
                except ValueError:
                    continue

                new_status, status_text = _STATUS_TEXT.get(action, (None, None))
                if status_text is None:
                    continue

                article = db.get_article(conn, article_id)
                if not article:
                    await cq.answer("مقاله یافت نشد")
                    continue

                if new_status:
                    db.set_status(conn, article_id, new_status)

                # پس از تایید → تلاش برای انتشارِ خودکار در وردپرس
                if action == "approve":
                    publish_note = _try_publish(article_id)
                    status_text = status_text + "\n" + publish_note

                # پاسخِ کوتاهِ callback (اگر کلیک قدیمی باشد 400 می‌دهد — بی‌اهمیت)
                try:
                    await cq.answer("ثبت شد ✓")
                except Exception:
                    pass
                # ویرایشِ پیام از طریقِ chat_id+message_id (نه از طریقِ callback query که
                # منقضی می‌شود) — پس بازخوردِ بصری حتی برای کلیک‌های قدیمی هم کار می‌کند.
                try:
                    new_text = (cq.message.text or "") + f"\n\n✔️ تصمیم: {status_text}"
                    await bot.edit_message_text(
                        chat_id=cq.message.chat_id,
                        message_id=cq.message.message_id,
                        text=new_text,
                    )
                except Exception as e:
                    # حتی اگر ویرایش پیام شکست خورد، دیتابیس آپدیت شده
                    logger.warning(f"ویرایش پیام مقاله #{article_id} نشد: {e}")

                logger.info(f"مقاله #{article_id}: {action.upper()} → {new_status or 'بدون تغییر'}")
                processed += 1

            # offset را جلو ببر تا این آپدیت‌ها دوباره خوانده نشوند
            if last_update_id is not None:
                await bot.get_updates(offset=last_update_id + 1, timeout=1)

    finally:
        conn.close()

    return processed


if __name__ == "__main__":
    n = asyncio.run(process_pending_clicks())
    print(f"\n{n} کلیک پردازش شد.")
