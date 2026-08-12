"""پردازش کلیک دکمه‌های تایید از تلگرام (یک‌بار اجرا، مطمئن).

برخلاف run_polling که باید همیشه روشن بماند، این اسکریپت یک‌بار اجرا می‌شود،
تمام کلیک‌های در صف را می‌خواند، دیتابیس را آپدیت می‌کند و پیام‌ها را ویرایش می‌کند.

می‌توان آن را در Task Scheduler هر چند دقیقه اجرا کرد (مثل بقیه‌ی پروژه).
"""
import asyncio
import logging
import sys

import httpx
from telegram import Bot

from . import db
from .config import ROOT, env

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_STATUS_TEXT = {
    "approve": ("approved", "✅ تایید شد — آماده‌ی انتشار"),
    "reject": ("rejected", "❌ ردّ شد"),
    "cancel": (None, "⊗ لغو شد (وضعیت تغییر نکرد)"),
}


def _relay_config() -> tuple[str, str]:
    """(آدرسِ سرویس، کلیدِ ادمین) — از env، وگرنه از همان فایل‌هایی که از قبل داریم."""
    def _file(name: str) -> str:
        p = ROOT / name
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""

    base = (env("BOT_BASE_URL") or _file("botdomain.txt")).rstrip("/")
    key = env("BOT_ADMIN_KEY") or _file("botadminkey.txt")
    return base, key


def _fetch_relay_clicks() -> list[dict]:
    """کلیک‌های در صف روی Railway. لیستِ خالی یعنی «چیزی نیست یا در دسترس نیست»."""
    base, key = _relay_config()
    if not (base and key):
        return []
    try:
        r = httpx.get(f"{base}/relay/approvals", params={"key": key}, timeout=20)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:  # noqa: BLE001 — قطعیِ شبکه نباید اسکریپت را بکُشد
        logger.warning(f"خواندنِ صفِ تاییدها نشد: {e}")
        return []


def _ack_relay_clicks(ids: list[int]) -> None:
    base, key = _relay_config()
    if not (base and key and ids):
        return
    try:
        httpx.post(f"{base}/relay/approvals/ack", params={"key": key},
                   data={"ids": ",".join(str(i) for i in ids)}, timeout=20)
    except Exception as e:  # noqa: BLE001
        # علامت‌نخوردن یعنی دفعه‌ی بعد دوباره پردازش می‌شود؛ چون تصمیم
        # idempotent است (همان وضعیت دوباره ست می‌شود) خطرِ جدی ندارد.
        logger.warning(f"علامت‌زدنِ صف نشد: {e}")


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


async def _apply_click(bot, conn, data: str, chat_id: int, message_id: int,
                       message_text: str | None) -> bool:
    """یک کلیک را اعمال می‌کند. True یعنی پردازش شد (یا عمداً نادیده گرفته شد).

    idempotent است: اعمالِ دوباره‌ی همان کلیک، همان وضعیت را می‌نویسد.
    """
    parts = data.split("_")             # approval_<action>_<id>
    if len(parts) < 3:
        return True
    action = parts[1]
    try:
        article_id = int(parts[2])
    except ValueError:
        return True

    new_status, status_text = _STATUS_TEXT.get(action, (None, None))
    if status_text is None:
        return True

    if not db.get_article(conn, article_id):
        logger.warning(f"مقاله #{article_id} در دیتابیسِ محلی نیست.")
        return True

    if new_status:
        db.set_status(conn, article_id, new_status)

    # پس از تایید → تلاش برای انتشارِ خودکار در وردپرس
    if action == "approve":
        status_text = status_text + "\n" + _try_publish(article_id)

    # ویرایش از طریقِ chat_id+message_id (نه callback query که منقضی می‌شود) —
    # پس بازخوردِ بصری حتی برای کلیک‌های قدیمی هم کار می‌کند.
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=(message_text or "") + f"\n\n✔️ تصمیم: {status_text}")
    except Exception as e:  # noqa: BLE001 — دیتابیس آپدیت شده، نمایش مهم‌تر نیست
        logger.warning(f"ویرایش پیام مقاله #{article_id} نشد: {e}")

    logger.info(f"مقاله #{article_id}: {action.upper()} → {new_status or 'بدون تغییر'}")
    return True


async def process_pending_clicks() -> int:
    """تمام کلیک‌های در صف را پردازش می‌کند. تعداد پردازش‌شده را برمی‌گرداند.

    دو منبع خوانده می‌شود چون بسته به اینکه باتِ مالک webhook داشته باشد یا نه
    کلیک از یکی از این دو می‌آید — و در جابه‌جایی بینشان هیچ کلیکی نباید گم شود:
    ۱) صفِ Railway (وقتی webhook فعال است و getUpdates دیگر کار نمی‌کند)
    ۲) getUpdates (رفتارِ قدیمی، وقتی webhook فعال نیست)
    """
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN تنظیم نشده.")
        return 0

    bot = Bot(token)
    processed = 0
    conn = db.connect()

    try:
        async with bot:
            # ── ۱) صفِ Railway ──
            done_ids = []
            for item in _fetch_relay_clicks():
                if not str(item.get("data", "")).startswith("approval_"):
                    done_ids.append(item["id"])
                    continue
                try:
                    await _apply_click(bot, conn, item["data"], item["chat_id"],
                                       item["message_id"], item.get("message_text"))
                    done_ids.append(item["id"])
                    processed += 1
                except Exception:  # noqa: BLE001 — ack نمی‌کنیم تا دوباره تلاش شود
                    logger.exception(f"اعمالِ کلیکِ صف #{item.get('id')} نشد.")
            _ack_relay_clicks(done_ids)

            # ── ۲) getUpdates (اگر webhook فعال باشد خطا می‌دهد — طبیعی است) ──
            try:
                updates = await bot.get_updates(timeout=5)
            except Exception as e:  # noqa: BLE001
                logger.info(f"getUpdates در دسترس نیست (webhook فعال است؟): {e}")
                updates = []

            last_update_id = None
            for u in updates:
                last_update_id = u.update_id
                cq = u.callback_query
                if not cq or not (cq.data or "").startswith("approval_"):
                    continue
                try:
                    await cq.answer("ثبت شد ✓")
                except Exception:  # noqa: BLE001 — کلیکِ قدیمی 400 می‌دهد
                    pass
                await _apply_click(bot, conn, cq.data, cq.message.chat_id,
                                   cq.message.message_id, cq.message.text)
                processed += 1

            # offset را جلو ببر تا این آپدیت‌ها دوباره خوانده نشوند
            if last_update_id is not None:
                try:
                    await bot.get_updates(offset=last_update_id + 1, timeout=1)
                except Exception:  # noqa: BLE001
                    pass

    finally:
        conn.close()

    return processed


if __name__ == "__main__":
    n = asyncio.run(process_pending_clicks())
    print(f"\n{n} کلیک پردازش شد.")
