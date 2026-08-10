"""باتِ تلگرامِ مشترک — هر مشتری پروفایل و سهمیه‌ی خودش را دارد.

نکته‌ی محدودیتِ تلگرام: نامِ دستورها فقط حروفِ کوچکِ انگلیسی/رقم/زیرخط می‌پذیرد
(`setMyCommands`)، پس دستورها انگلیسی‌اند ولی *توضیح* و همه‌ی دکمه‌ها فارسی‌اند.
"""
from __future__ import annotations

import asyncio
import html as _html
import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                      Update)
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from . import bot_db, demo_render, generation
from .generation import NICHES

logger = logging.getLogger(__name__)

ADMIN_CHAT_ID = str(os.environ.get("BOT_ADMIN_CHAT_ID", "")).strip()
CONTACT_URL = os.environ.get("BOT_CONTACT_URL", "https://sagharnazari.ir/")
# تولید مسدودکننده و ~۱۴۵ ثانیه‌ای است؛ چند کارگر تا صفِ روزانه سرویس را نخواباند
WORKERS = int(os.environ.get("BOT_WORKERS", "3"))

_queue: asyncio.Queue | None = None
_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="gen")

CTYPES = {"tutorial": "آموزشی", "news": "خبری"}


# ── کمکی‌ها ─────────────────────────────────────────────────────────────────
def _is_admin(chat_id: int) -> bool:
    return bool(ADMIN_CHAT_ID) and str(chat_id) == ADMIN_CHAT_ID


def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _niche_keyboard(prefix: str = "niche") -> InlineKeyboardMarkup:
    items = list(NICHES.items())
    rows = [[InlineKeyboardButton(lbl, callback_data=f"{prefix}:{key}")
             for key, lbl in items[i:i + 2]] for i in range(0, len(items), 2)]
    return InlineKeyboardMarkup(rows)


def _ctype_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("آموزشی", callback_data="ctype:tutorial"),
        InlineKeyboardButton("خبری", callback_data="ctype:news"),
    ]])


def _quota_line(cl) -> str:
    left = max(0, cl["quota_total"] - cl["quota_used"])
    plan = "آزمایشی" if cl["plan"] == "trial" else "اشتراک فعال"
    end = f" — تا {cl['period_end']}" if cl["period_end"] else ""
    return f"{plan}{end}\nمقاله‌ی باقی‌مانده: {_fa(left)} از {_fa(cl['quota_total'])}"


def _subscribe_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("فعال‌سازی اشتراک", url=CONTACT_URL)]])


# مراحلِ واقعیِ خطِ تولید — درصدها با on_step در generation.py یکی‌اند
_STAGES = [
    (10, "بررسی و گردآوری منابع"),
    (30, "تحلیل محتوای منابع"),
    (45, "استخراج کلیدواژه‌های هدف"),
    (55, "نگارش مقاله"),
    (88, "افزودن منابع و تصویر"),
]


def _progress_text(niche: str, ctype: str, keyword: str, percent: int) -> str:
    """نوارِ پیشرفتِ متنی. مرحله‌ی جاری با ◄ و تمام‌شده‌ها با ✓ مشخص می‌شوند."""
    active = 0
    for i, (p, _) in enumerate(_STAGES):
        if percent >= p:
            active = i
    lines = []
    for i, (_, label) in enumerate(_STAGES):
        mark = "✓" if i < active else ("◄" if i == active else "•")
        lines.append(f"{mark} {label}")
    head = "در حال تولید مقاله" if percent < 96 else "در حال آماده‌سازی"
    return (f"{head}\n\n" + "\n".join(lines) +
            f"\n\nحوزه: {NICHES.get(niche, niche)}"
            f"\nنوع: {CTYPES.get(ctype, ctype)}"
            f"\nموضوع: {keyword or 'انتخاب خودکار'}"
            "\n\nحدود دو تا سه دقیقه طول می‌کشد.")


# ── دستورها ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    cl = bot_db.get_or_create_client(u.id, u.full_name or "", u.username or "")
    name = (u.first_name or "").strip()
    await update.message.reply_text(
        f"سلام {name}؛ خوش آمدید.\n\n"
        "این دستیارِ تولید محتوای سئوی شماست. حوزه و موضوع را مشخص می‌کنید و یک "
        "مقاله‌ی کامل با ارجاع به منابع معتبر برایتان نوشته می‌شود.\n\n"
        f"{_quota_line(cl)}\n\n"
        "برای شروع /new را بزنید.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "دستورها:\n\n"
        "/new — تولید مقاله‌ی تازه\n"
        "/settings — حوزه و ارسال روزانه\n"
        "/articles — مقاله‌های من\n"
        "/subscription — وضعیت اشتراک\n\n"
        "تولید هر مقاله حدود دو تا سه دقیقه طول می‌کشد و نتیجه به‌صورت فایل "
        "برایتان ارسال می‌شود.")


async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_user.id
    cl = bot_db.get_or_create_client(chat_id, update.effective_user.full_name or "",
                                     update.effective_user.username or "")
    left = cl["quota_total"] - cl["quota_used"]
    expired = bool(cl["period_end"]) and cl["period_end"] < _today()
    if left <= 0 or expired:
        await update.message.reply_text(
            "سهمیه‌ی شما تمام شده است.\n\nبرای تولید مقاله‌های بیشتر اشتراک را "
            "فعال کنید.", reply_markup=_subscribe_markup())
        return

    bot_db.set_state(chat_id, "await_niche", {})
    await update.message.reply_text("حوزه‌ی کاری‌تان را انتخاب کنید:",
                                    reply_markup=_niche_keyboard())


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_user.id
    cl = bot_db.get_or_create_client(chat_id)
    niche = NICHES.get(cl["niche"] or "", "انتخاب نشده")
    daily = "روشن" if cl["daily_enabled"] else "خاموش"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تغییر حوزه", callback_data="set:niche")],
        [InlineKeyboardButton(
            "خاموش کردن ارسال روزانه" if cl["daily_enabled"] else "روشن کردن ارسال روزانه",
            callback_data="set:daily")],
    ])
    await update.message.reply_text(
        f"حوزه‌ی پیش‌فرض: {niche}\nارسال روزانه: {daily}\n\n{_quota_line(cl)}",
        reply_markup=kb)


async def cmd_articles(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_user.id
    rows = bot_db.list_articles(chat_id, limit=10)
    if not rows:
        await update.message.reply_text("هنوز مقاله‌ای تولید نکرده‌اید. /new")
        return
    lines = [f"{_fa(i)}. {r['title']}  ({_fa(round(r['seo_score']))}٪) — /a{r['id']}"
             for i, r in enumerate(rows, 1)]
    await update.message.reply_text(
        "مقاله‌های شما:\n\n" + "\n".join(lines) +
        "\n\nبرای دریافت دوباره‌ی هر مقاله، کدِ زیرش را بزنید.")


async def cmd_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_user.id
    cl = bot_db.get_or_create_client(chat_id)
    # شناسه لازم است تا مشتری بتواند برای فعال‌سازی اشتراک آن را اعلام کند
    await update.message.reply_text(
        f"{_quota_line(cl)}\n\nشناسه شما: {chat_id}",
        reply_markup=_subscribe_markup())


async def cmd_whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """شناسه‌ی عددی کاربر — برای فعال‌سازی اشتراک لازم است."""
    u = update.effective_user
    await update.message.reply_text(
        f"شناسه شما: {u.id}\nنام: {u.full_name}"
        + (f"\nیوزرنیم: @{u.username}" if u.username else ""))


async def cmd_get_article(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/a<id> — ارسالِ دوباره‌ی یک مقاله‌ی قبلی."""
    chat_id = update.effective_user.id
    try:
        art_id = int(update.message.text.strip().lstrip("/a"))
    except ValueError:
        return
    row = bot_db.get_article(art_id)
    if not row or row["chat_id"] != chat_id or row["status"] != "done":
        await update.message.reply_text("این مقاله پیدا نشد.")
        return
    await _send_article(ctx, chat_id, row["title"], row["html"], row["seo_score"])


# ── دستورهای مالک ───────────────────────────────────────────────────────────
async def cmd_grant(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/grant <chat_id> <days> <quota> — فعال‌سازیِ دستیِ اشتراک."""
    if not _is_admin(update.effective_user.id):
        return
    try:
        target, days, quota = (int(x) for x in ctx.args[:3])
    except (ValueError, IndexError):
        await update.message.reply_text("قالب: /grant <chat_id> <روز> <تعداد مقاله>")
        return
    if not bot_db.get_client(target):
        await update.message.reply_text("این کاربر هنوز /start نزده است.")
        return
    try:
        bot_db.grant_plan(target, days, quota)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    await update.message.reply_text(
        f"فعال شد: {_fa(target)} — {_fa(days)} روز، {_fa(quota)} مقاله")
    try:
        await ctx.bot.send_message(
            target, f"اشتراک شما فعال شد.\n\nمقاله‌ی در دسترس: {_fa(quota)}\n"
                    f"مدت: {_fa(days)} روز\n\nبرای شروع /new را بزنید.")
    except Exception as e:  # noqa: BLE001 — کاربر ممکن است بات را بلاک کرده باشد
        logger.warning(f"اطلاع‌رسانی به {target} نشد: {e}")


async def cmd_clients(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    rows = bot_db.list_clients(limit=50)
    if not rows:
        await update.message.reply_text("هنوز مشتری‌ای ثبت نشده.")
        return
    lines = [f"{r['chat_id']} · {r['name'] or '—'} · {r['plan']} · "
             f"{r['quota_used']}/{r['quota_total']}"
             + (f" · تا {r['period_end']}" if r["period_end"] else "")
             for r in rows]
    await update.message.reply_text("مشتریان:\n\n" + "\n".join(lines))


async def cmd_setend(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/setend <chat_id> <روز> — جابه‌جاییِ تاریخِ پایان بدونِ ریست‌کردنِ سهمیه.

    عددِ منفی هم می‌پذیرد (عقب‌بردنِ تاریخ) — برای جبرانِ خطا یا آزمایشِ چرخه‌ی
    یادآوری. برخلافِ /grant، سهمیه‌ی مصرف‌شده دست‌نخورده می‌ماند.
    """
    if not _is_admin(update.effective_user.id):
        return
    try:
        target, days = int(ctx.args[0]), int(ctx.args[1])
    except (ValueError, IndexError):
        await update.message.reply_text("قالب: /setend <chat_id> <روز از امروز>")
        return
    if not bot_db.get_client(target):
        await update.message.reply_text("این کاربر هنوز /start نزده است.")
        return
    end = bot_db.set_period_end(target, days)
    await update.message.reply_text(
        f"تاریخ پایانِ {_fa(target)} روی {end} تنظیم شد.\n"
        "برای دیدنِ فوریِ یادآوری: /checkexpiry")


async def cmd_checkexpiry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/checkexpiry — یک دورِ بررسیِ یادآوری همین حالا اجرا می‌شود."""
    if not _is_admin(update.effective_user.id):
        return
    sent = await run_expiry_pass(ctx.bot)
    await update.message.reply_text(
        f"بررسی انجام شد — {_fa(sent)} یادآوری فرستاده شد."
        if sent else "بررسی انجام شد — کسی واجدِ یادآوری نبود.")


# ── یادآوریِ اشتراک ──────────────────────────────────────────────────────────
# نقاطِ یادآوری نسبت به تاریخِ پایان. مثبت = قبل از پایان، صفر = روزِ آخر،
# منفی = بعد از پایان (بازگرداندنِ مشتری — ارزان‌تر از پیدا کردنِ مشتریِ تازه).
EXPIRY_STEPS = [3, 0, -7]


def expiry_message(days: int, end: str) -> str:
    if days > 0:
        return (f"{_fa(days)} روز تا پایان اشتراک شما باقی است.\n\n"
                f"تاریخ پایان: {end}\n\n"
                "برای تمدید، اشتراک را فعال کنید تا تولید مقاله‌هایتان بدون "
                "وقفه ادامه پیدا کند.")
    if days == 0:
        return (f"اشتراک شما امروز به پایان می‌رسد.\n\nتاریخ پایان: {end}\n\n"
                "برای تمدید، اشتراک را فعال کنید تا تولید مقاله‌هایتان بدون "
                "وقفه ادامه پیدا کند.")
    # بعد از انقضا: لحنِ دعوت، نه اخطار — اول به چیزی اشاره می‌کند که هنوز دارد
    return ("مقاله‌های شما همچنان در همین بات باقی است و با /articles می‌توانید "
            "دوباره دریافتشان کنید.\n\n"
            f"اشتراک شما در {end} به پایان رسید. برای ادامه‌ی تولید مقاله‌های "
            "تازه، اشتراک را فعال کنید.")


async def run_expiry_pass(bot) -> int:
    """یک دورِ کاملِ بررسی. تعدادِ یادآوریِ فرستاده‌شده را برمی‌گرداند."""
    sent = 0
    for days in EXPIRY_STEPS:
        for cl in bot_db.due_expiry_notice(days):
            chat_id, end = cl["chat_id"], cl["period_end"]
            try:
                await bot.send_message(chat_id, expiry_message(days, end),
                                       reply_markup=_subscribe_markup())
                sent += 1
            except Exception as e:  # noqa: BLE001 — شاید بات را بلاک کرده
                logger.warning(f"یادآوری به {chat_id} نرسید: {e}")
            if ADMIN_CHAT_ID:
                when = (f"{_fa(days)} روز مانده" if days > 0
                        else "امروز آخرین روز" if days == 0
                        else f"{_fa(-days)} روز از انقضا گذشته")
                try:
                    await bot.send_message(
                        int(ADMIN_CHAT_ID),
                        f"یادآوری اشتراک فرستاده شد\n\n"
                        f"مشتری: {cl['name'] or '—'} ({chat_id})\n"
                        f"پایان: {end} — {when}\n"
                        f"مصرف: {cl['quota_used']}/{cl['quota_total']}")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"خبر به مالک نرسید: {e}")
            # بعد از ارسال علامت می‌خورد تا در دورِ بعد تکرار نشود
            bot_db.mark_expiry_notified(chat_id, end, days)
    return sent


# ── دکمه‌ها ─────────────────────────────────────────────────────────────────
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    chat_id = update.effective_user.id
    data = q.data or ""
    await q.answer()

    if data.startswith("niche:"):
        key = data.split(":", 1)[1]
        _, sd = bot_db.get_state(chat_id)
        sd["niche"] = key
        bot_db.set_state(chat_id, "await_ctype", sd)
        await q.edit_message_text(f"حوزه: {NICHES.get(key, key)}\n\nنوع مطلب را انتخاب کنید:",
                                  reply_markup=_ctype_keyboard())

    elif data.startswith("ctype:"):
        ct = data.split(":", 1)[1]
        _, sd = bot_db.get_state(chat_id)
        sd["ctype"] = ct
        bot_db.set_state(chat_id, "await_keyword", sd)
        await q.edit_message_text(
            f"حوزه: {NICHES.get(sd.get('niche',''), '—')}\nنوع: {CTYPES.get(ct, ct)}\n\n"
            "حالا موضوع یا کلیدواژه را بنویسید.\n"
            "اگر می‌خواهید خودمان انتخاب کنیم، بنویسید: -")

    elif data.startswith("set:niche"):
        bot_db.set_state(chat_id, "await_default_niche", {})
        await q.edit_message_text("حوزه‌ی پیش‌فرض را انتخاب کنید:",
                                  reply_markup=_niche_keyboard(prefix="dniche"))

    elif data.startswith("dniche:"):
        key = data.split(":", 1)[1]
        bot_db.update_client(chat_id, niche=key)
        bot_db.set_state(chat_id, None)
        await q.edit_message_text(f"حوزه‌ی پیش‌فرض ثبت شد: {NICHES.get(key, key)}")

    elif data == "set:daily":
        cl = bot_db.get_client(chat_id)
        new = 0 if cl["daily_enabled"] else 1
        if new and not cl["niche"]:
            await q.edit_message_text(
                "برای ارسال روزانه اول باید حوزه‌ی پیش‌فرض را مشخص کنید.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("انتخاب حوزه", callback_data="set:niche")]]))
            return
        bot_db.update_client(chat_id, daily_enabled=new)
        await q.edit_message_text(
            "ارسال روزانه روشن شد. هر روز صبح یک مقاله دریافت می‌کنید."
            if new else "ارسال روزانه خاموش شد.")


# ── پیامِ متنی (کلیدواژه‌ی ویزارد) ───────────────────────────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_user.id
    state, sd = bot_db.get_state(chat_id)
    if state != "await_keyword":
        await update.message.reply_text("برای تولید مقاله /new را بزنید.")
        return

    keyword = (update.message.text or "").strip()
    if keyword in ("-", "—"):
        keyword = ""
    if len(keyword) > 80:
        keyword = keyword[:80]

    niche, ctype = sd.get("niche", ""), sd.get("ctype", "tutorial")
    bot_db.set_state(chat_id, None)

    # سهمیه **قبل** از صف برداشته می‌شود تا چند درخواستِ پشت‌سرهم دور نزند
    if not bot_db.consume_quota(chat_id):
        await update.message.reply_text(
            "سهمیه‌ی شما تمام شده است.", reply_markup=_subscribe_markup())
        return

    art_id = bot_db.create_job(chat_id, niche, ctype, keyword)
    msg = await update.message.reply_text(
        _progress_text(niche, ctype, keyword, 0))
    bot_db.set_msg_id(art_id, msg.message_id)   # کارگر همین پیام را زنده ویرایش می‌کند
    await enqueue(art_id)


# ── صف و کارگرها ────────────────────────────────────────────────────────────
async def enqueue(article_id: int) -> None:
    if _queue is None:
        raise RuntimeError("صف هنوز راه‌اندازی نشده است.")
    await _queue.put(article_id)


async def _worker(app: Application, idx: int) -> None:
    assert _queue is not None
    while True:
        art_id = await _queue.get()
        try:
            await _process(app, art_id)
        except Exception:  # noqa: BLE001 — کارگر هرگز نباید بمیرد
            logger.exception(f"[worker {idx}] کارِ #{art_id} شکست خورد")
        finally:
            _queue.task_done()


async def _process(app: Application, article_id: int) -> None:
    row = bot_db.get_article(article_id)
    if not row or row["status"] == "done":
        return
    chat_id = row["chat_id"]
    bot_db.mark_running(article_id)

    loop = asyncio.get_running_loop()
    msg_id = row["msg_id"]

    async def _edit(percent: int) -> None:
        try:
            await app.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_progress_text(row["niche"], row["ctype"], row["keyword"] or "", percent))
        except Exception:  # noqa: BLE001 — «message is not modified» و امثالش بی‌اهمیت‌اند
            pass

    def on_step(_name: str, percent: int) -> None:
        """از تردِ تولید صدا زده می‌شود، پس کار باید به حلقه‌ی async سپرده شود.

        نتیجه را منتظر نمی‌مانیم: ویرایشِ پیام نباید تولید را کُند یا متوقف کند.
        """
        if msg_id:
            asyncio.run_coroutine_threadsafe(_edit(percent), loop)

    try:
        payload = await loop.run_in_executor(
            _pool, generation.generate, row["niche"], row["ctype"],
            row["keyword"] or "", on_step)
        html = demo_render.render_page(payload, paywall=False)
        title = payload.get("title_seo", "") or payload.get("h1", "")
        score = generation.seo_score(payload)
        bot_db.finish_job(article_id, title, html, score)
        if msg_id:      # نوارِ پیشرفت نیمه‌کاره نماند
            try:
                await app.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text="مقاله آماده شد.")
            except Exception:  # noqa: BLE001
                pass
        await _send_article(app, chat_id, title, html, score)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"تولیدِ #{article_id} شکست خورد")
        bot_db.fail_job(article_id, str(e))
        bot_db.refund_quota(chat_id)      # خطای ما نباید سهمیه‌ی مشتری را بسوزاند
        try:
            await app.bot.send_message(
                chat_id, f"متأسفانه تولید این مقاله انجام نشد.\n\n{e}\n\n"
                         "سهمیه‌ی شما کسر نشد. لطفاً دوباره تلاش کنید: /new")
        except Exception:  # noqa: BLE001
            logger.warning("اطلاع‌رسانیِ خطا نشد.")


async def _send_article(app_or_ctx, chat_id: int, title: str, html: str,
                        score: float) -> None:
    """خلاصه + فایلِ HTML. الگوی اثبات‌شده‌ی telegram_approver.send_article_document."""
    bot = app_or_ctx.bot
    safe = _html.escape(title or "مقاله")
    await bot.send_message(
        chat_id, f"<b>{safe}</b>\n\nامتیاز سئو: {_fa(round(score))}٪",
        parse_mode=ParseMode.HTML)
    doc = io.BytesIO(html.encode("utf-8"))
    doc.name = "article.html"
    await bot.send_document(
        chat_id, document=doc, filename=f"{_slug(title)}.html",
        caption="متن کامل مقاله — برای خواندن باز کنید.")


def _slug(title: str) -> str:
    keep = [c if c.isalnum() or c in "-_" else "-" for c in (title or "article")[:40]]
    return "".join(keep).strip("-") or "article"


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


# ── راه‌اندازی ──────────────────────────────────────────────────────────────
COMMANDS = [
    BotCommand("new", "تولید مقاله‌ی تازه"),
    BotCommand("settings", "حوزه و ارسال روزانه"),
    BotCommand("articles", "مقاله‌های من"),
    BotCommand("subscription", "وضعیت اشتراک"),
    BotCommand("help", "راهنما"),
]


def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("articles", cmd_articles))
    app.add_handler(CommandHandler("subscription", cmd_subscription))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("clients", cmd_clients))
    app.add_handler(CommandHandler("setend", cmd_setend))
    app.add_handler(CommandHandler("checkexpiry", cmd_checkexpiry))
    app.add_handler(MessageHandler(filters.Regex(r"^/a\d+$"), cmd_get_article))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def start_workers(app: Application) -> list[asyncio.Task]:
    global _queue
    _queue = asyncio.Queue()
    tasks = [asyncio.create_task(_worker(app, i)) for i in range(WORKERS)]
    # کارهای ناتمامِ قبل از ری‌استارت دوباره به صف می‌روند
    stale = bot_db.pending_jobs()
    for row in stale:
        await _queue.put(row["id"])
    if stale:
        logger.info(f"{len(stale)} کارِ ناتمام دوباره به صف رفت.")
    return tasks
