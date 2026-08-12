"""باتِ خصوصیِ مدیریت — داشبوردِ مالک روی تلگرام.

چرا باتِ جدا از باتِ مشتری: پیام‌های مدیریتی نباید لای گفت‌وگوی مشتری‌ها گم
شوند، و توکنِ باتِ مشتری نباید جایی باشد که فقط مالک می‌بیندش.

چرا داخلِ همین سرویس (نه سرویسِ جدا روی Railway): دیتابیسِ مشتری‌ها
(`bot.db`) روی والیومِ همین سرویس است و والیوم فقط به یک سرویس وصل می‌شود.
سرویسِ دوم مجبور بود همه‌چیز را با HTTP از این یکی بپرسد — یک لایه‌ی اضافه
برای داده‌ای که همین‌جا در دسترس است.

با `ADMIN_BOT_TOKEN` فعال می‌شود؛ نبودش یعنی این بات اصلاً بالا نمی‌آید و
باتِ مشتری دست‌نخورده کار می‌کند.
"""
from __future__ import annotations

import logging
import os
from datetime import date

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                      Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from . import bot_db

logger = logging.getLogger(__name__)

ADMIN_CHAT_ID = str(os.environ.get("BOT_ADMIN_CHAT_ID", "")).strip()
ADMIN_KEY = (os.environ.get("BOT_ADMIN_KEY") or "").strip()
BASE_URL = (os.environ.get("BOT_BASE_URL") or "").rstrip("/")

# گزینه‌های آماده‌ی تمدید: (روز، تعداد مقاله). بیشترِ تمدیدها همین‌هاست و
# تایپ‌کردنِ عدد روی موبایل خطاخیز است.
GRANT_PRESETS = [(30, 30), (30, 10), (90, 100)]

PAGE_SIZE = 8


def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _num(n) -> str:
    """عدد با جداکننده‌ی هزارگان و رقم فارسی — برای شمارِ توکن."""
    return _fa(f"{int(n or 0):,}")


def _is_admin(chat_id: int) -> bool:
    return bool(ADMIN_CHAT_ID) and str(chat_id) == ADMIN_CHAT_ID


def _days_left(period_end: str | None) -> int | None:
    if not period_end:
        return None
    try:
        y, m, d = (int(x) for x in str(period_end).split("-"))
        return (date(y, m, d) - date.today()).days
    except (ValueError, AttributeError):
        return None


def _status_label(cl) -> str:
    d = _days_left(cl["period_end"])
    if d is None:
        return "بدون اشتراک"
    if d < 0:
        return f"منقضی ({_fa(-d)} روز پیش)"
    if d == 0:
        return "امروز آخرین روز"
    return f"{_fa(d)} روز مانده"


def _home_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📊 خلاصه", callback_data="a:stats"),
         InlineKeyboardButton("👥 مشتری‌ها", callback_data="a:clients:0")],
        [InlineKeyboardButton("🩺 سلامت سیستم", callback_data="a:health")],
    ]
    if BASE_URL and ADMIN_KEY:
        rows.append([InlineKeyboardButton(
            "🔗 داشبورد وب", url=f"{BASE_URL}/admin?key={ADMIN_KEY}")])
    return InlineKeyboardMarkup(rows)


def _back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("🏠 منوی اصلی", callback_data="a:home")]


# ── صفحه‌ها ─────────────────────────────────────────────────────────────────
def _home_text() -> str:
    s = bot_db.stats()
    return (f"داشبورد مدیریت\n\n"
            f"مشتری‌ها: {_fa(s['clients'])}  (اشتراک فعال: {_fa(s['active'])})\n"
            f"مقاله‌ی امروز: {_fa(s['done_today'])}\n\n"
            "یکی را انتخاب کنید:")


def _stats_view() -> tuple[str, InlineKeyboardMarkup]:
    s = bot_db.stats()
    total_tok = (s["ti"] or 0) + (s["to_"] or 0)
    text = (
        "📊 خلاصه‌ی کلی\n\n"
        f"👥 مشتری‌ها: {_fa(s['clients'])}\n"
        f"   • اشتراک فعال: {_fa(s['active'])}\n"
        f"   • منقضی‌شده: {_fa(s['expired'])}\n\n"
        f"📝 مقاله‌ها\n"
        f"   • امروز: {_fa(s['done_today'])}\n"
        f"   • مجموع: {_fa(s['done'])}\n"
        f"   • در حال تولید: {_fa(s['busy'])}\n"
        f"   • ناموفق: {_fa(s['errors'])}\n\n"
        f"🔢 مصرف توکن\n"
        f"   • ورودی: {_num(s['ti'])}\n"
        f"   • خروجی: {_num(s['to_'])}\n"
        f"   • مجموع: {_num(total_tok)}"
    )
    return text, InlineKeyboardMarkup([_back_row()])


def _clients_view(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    rows = bot_db.list_clients_by_urgency()
    usage = bot_db.client_token_usage()
    if not rows:
        return "هنوز مشتری‌ای ثبت نشده.", InlineKeyboardMarkup([_back_row()])

    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [f"👥 مشتری‌ها ({_fa(len(rows))} نفر) — صفحه {_fa(page + 1)} از {_fa(pages)}\n"]
    buttons = []
    for cl in chunk:
        left = max(0, cl["quota_total"] - cl["quota_used"])
        n, ti, to = usage.get(cl["chat_id"], (0, 0, 0))
        name = cl["name"] or "—"
        handle = f" (@{cl['username']})" if cl["username"] else ""
        lines.append(
            f"\n• {name}{handle}\n"
            f"  اعتبار: {_fa(left)} مقاله از {_fa(cl['quota_total'])} — {_status_label(cl)}\n"
            f"  تولیدشده: {_fa(n)} مقاله · توکن: {_num(ti + to)}")
        buttons.append([InlineKeyboardButton(
            f"{name}{handle} — {_fa(left)} مقاله",
            callback_data=f"a:c:{cl['chat_id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("‹ قبلی", callback_data=f"a:clients:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("بعدی ›", callback_data=f"a:clients:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append(_back_row())
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def _client_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    cl = bot_db.get_client(chat_id)
    if not cl:
        return "این مشتری پیدا نشد.", InlineKeyboardMarkup([_back_row()])

    left = max(0, cl["quota_total"] - cl["quota_used"])
    n, ti, to = bot_db.client_token_usage().get(chat_id, (0, 0, 0))
    handle = f"@{cl['username']}" if cl["username"] else "—"
    text = (
        f"👤 {cl['name'] or '—'}\n"
        f"یوزرنیم: {handle}\n"
        f"شناسه: {chat_id}\n\n"
        f"پلن: {cl['plan']}\n"
        f"اعتبار: {_fa(left)} مقاله از {_fa(cl['quota_total'])} (مصرف‌شده: {_fa(cl['quota_used'])})\n"
        f"پایان اشتراک: {cl['period_end'] or '—'} — {_status_label(cl)}\n"
        f"حوزه: {cl['niche'] or '—'}\n"
        f"ارسال روزانه: {'روشن' if cl['daily_enabled'] else 'خاموش'}\n\n"
        f"📝 مقاله‌ی تحویل‌شده: {_fa(n)}\n"
        f"🔢 توکن مصرفی: {_num(ti + to)}  (ورودی {_num(ti)} / خروجی {_num(to)})\n"
        f"عضویت از: {cl['created_at']}"
    )
    buttons = [[InlineKeyboardButton(
        f"تمدید {_fa(d)} روز / {_fa(q)} مقاله", callback_data=f"a:g:{chat_id}:{d}:{q}")]
        for d, q in GRANT_PRESETS]
    buttons.append([InlineKeyboardButton("‹ فهرست مشتری‌ها", callback_data="a:clients:0")])
    buttons.append(_back_row())
    return text, InlineKeyboardMarkup(buttons)


def _health_view() -> tuple[str, InlineKeyboardMarkup]:
    lines = ["🩺 سلامت سیستم\n"]
    try:
        s = bot_db.stats()
        lines.append("دیتابیس: ✅ در دسترس")
        lines.append(f"در صف/در حال تولید: {_fa(s['busy'])}")
        lines.append(f"کارهای ناموفق: {_fa(s['errors'])}")
    except Exception as e:  # noqa: BLE001 — این صفحه باید حتی وقتی DB خراب است باز شود
        lines.append(f"دیتابیس: ❌ {str(e)[:80]}")
        return "\n".join(lines), InlineKeyboardMarkup([_back_row()])

    last = bot_db.last_article_at()
    lines.append(f"آخرین مقاله‌ی موفق: {last or '—'}")
    lines.append(f"تعداد کارگرها: {_fa(os.environ.get('BOT_WORKERS', '3'))}")
    lines.append(f"سهمیه‌ی آزمایشی: {_fa(os.environ.get('BOT_TRIAL_QUOTA', '1'))} مقاله")
    lines.append(f"ارائه‌دهنده‌ی مدل: {os.environ.get('DEMO_PROVIDER', 'openrouter')}")

    errs = bot_db.recent_errors(limit=3)
    if errs:
        lines.append("\nآخرین خطاها:")
        for e in errs:
            kw = (e["keyword"] or "—")[:28]
            lines.append(f"• #{e['id']} ({kw}): {(e['error'] or '')[:70]}")
    return "\n".join(lines), InlineKeyboardMarkup([_back_row()])


# ── دستورها و دکمه‌ها ────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        # به کاربرِ ناشناس نباید فهماند که این بات چه‌کاره است
        logger.warning(f"دسترسیِ غیرمجاز به باتِ مدیریت از {update.effective_user.id}")
        return
    await update.message.reply_text(_home_text(), reply_markup=_home_keyboard())


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    chat_id = update.effective_user.id
    if not _is_admin(chat_id):
        await q.answer("دسترسی مجاز نیست.", show_alert=True)
        return
    data = q.data or ""

    # تاییدِ مقاله‌های سایتِ خودمان: تصمیم را اینجا اجرا نمی‌کنیم چون دیتابیسِ
    # آن مقاله‌ها روی کامپیوترِ خانگی است. کلیک را در صف می‌گذاریم تا
    # process_approvals محلی برش دارد (همان کاری که قبلاً getUpdates می‌کرد).
    if data.startswith("approval_"):
        try:
            bot_db.store_relay(data, q.message.chat_id, q.message.message_id,
                               q.message.text)
            await q.answer("ثبت شد ✓ — تا چند دقیقه‌ی دیگر اعمال می‌شود")
        except Exception:  # noqa: BLE001 — کلیکِ گم‌شده بدترین حالت است، نه کرش
            logger.exception("ثبتِ کلیکِ تایید نشد.")
            await q.answer("ثبت نشد — دوباره بزنید.", show_alert=True)
        return

    await q.answer()

    if data == "a:home":
        text, kb = _home_text(), _home_keyboard()
    elif data == "a:stats":
        text, kb = _stats_view()
    elif data.startswith("a:clients:"):
        text, kb = _clients_view(int(data.rsplit(":", 1)[1]))
    elif data.startswith("a:c:"):
        text, kb = _client_view(int(data.rsplit(":", 1)[1]))
    elif data == "a:health":
        text, kb = _health_view()
    elif data.startswith("a:g:"):
        _, _, target, days, quota = data.split(":")
        text, kb = await _do_grant(ctx, int(target), int(days), int(quota))
    else:
        return

    try:
        await q.edit_message_text(text, reply_markup=kb)
    except Exception as e:  # noqa: BLE001 — «message is not modified» و امثالش
        logger.debug(f"ویرایشِ پیام نشد: {e}")


async def _do_grant(ctx, target: int, days: int, quota: int
                    ) -> tuple[str, InlineKeyboardMarkup]:
    """تمدیدِ اشتراک + خبردادن به مشتری. متنِ نتیجه را برمی‌گرداند."""
    if not bot_db.get_client(target):
        return "این کاربر پیدا نشد.", InlineKeyboardMarkup([_back_row()])
    try:
        bot_db.grant_plan(target, days, quota)
    except ValueError as e:
        return f"تمدید نشد: {e}", InlineKeyboardMarkup([_back_row()])

    note = ""
    try:
        # خبر باید از باتِ *مشتری* برود؛ مشتری اصلاً باتِ مدیریت را ندارد.
        from . import bot as botmod
        customer_bot = getattr(botmod, "_customer_bot", None)
        if customer_bot is not None:
            await customer_bot.send_message(
                target, f"اشتراک شما تمدید شد.\n\nمقاله‌ی در دسترس: {_fa(quota)}\n"
                        f"مدت: {_fa(days)} روز")
        else:
            note = "\n\n⚠️ خبر به مشتری فرستاده نشد (باتِ مشتری در دسترس نبود)."
    except Exception as e:  # noqa: BLE001 — شاید بات را بلاک کرده باشد
        logger.warning(f"اطلاع‌رسانیِ تمدید به {target} نشد: {e}")
        note = "\n\n⚠️ تمدید ثبت شد ولی پیام به مشتری نرسید (شاید بات را بلاک کرده)."

    text, kb = _client_view(target)
    return f"✅ تمدید شد: {_fa(days)} روز / {_fa(quota)} مقاله{note}\n\n{text}", kb


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    await update.message.reply_text(_home_text(), reply_markup=_home_keyboard())


COMMANDS = [
    BotCommand("start", "داشبورد مدیریت"),
]


def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app
