"""میزبانِ باتِ تلگرام روی Railway — webhook + صف + زمان‌بندِ روزانه.

چرا webhook و نه polling: Railway از قبل HTTPS عمومی می‌دهد، پروسه‌ی دائمیِ
اضافه لازم نیست، و همین اپ بعداً میزبانِ callbackِ درگاهِ پرداخت هم می‌شود.

اجرا: uvicorn src.bot_app:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

# ماژول‌های پایپ‌لاین با «✓/✗» لاگ می‌گیرند؛ روی کنسولِ غیرUTF این‌ها استثنا
# می‌دهند و چون داخلِ مسیرِ تولیدند کلِ مقاله را می‌کُشند.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import (HTMLResponse, JSONResponse,  # noqa: E402
                               PlainTextResponse, RedirectResponse)
from telegram import Update  # noqa: E402

from . import llm  # noqa: E402

# پروایدرِ این پروسه — settings.yaml دست نمی‌خورد، پس پایپ‌لاینِ روزانه‌ی سایتِ
# خودمان (پروسه‌ی جدا) با تنظیماتِ خودش کار می‌کند.
llm._settings["provider"] = os.environ.get("DEMO_PROVIDER", "openrouter")

from . import bot as botmod  # noqa: E402
from . import bot_db  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
SECRET = (os.environ.get("BOT_WEBHOOK_SECRET") or "").strip()
BASE_URL = (os.environ.get("BOT_BASE_URL") or "").rstrip("/")

_app = None          # telegram.ext.Application
_tasks: list = []


async def _daily_loop(tg_app) -> None:
    """هر دقیقه بررسی می‌کند کدام مشتری وقتِ مقاله‌ی روزانه‌اش رسیده.

    خودِ صف جلوی هجوم را می‌گیرد؛ اینجا فقط کار ساخته و به صف داده می‌شود.
    """
    while True:
        try:
            hour = datetime.now().hour
            for cl in bot_db.due_daily(hour):
                if not bot_db.consume_quota(cl["chat_id"]):
                    continue
                art_id = bot_db.create_job(cl["chat_id"], cl["niche"] or "business",
                                           cl["ctype"] or "tutorial", "", source="daily")
                await botmod.enqueue(art_id)
                logger.info(f"مقاله‌ی روزانه برای {cl['chat_id']} به صف رفت (#{art_id}).")
        except Exception:  # noqa: BLE001 — زمان‌بند هرگز نباید بمیرد
            logger.exception("حلقه‌ی روزانه خطا داد.")
        await asyncio.sleep(60)


async def _expiry_loop(tg_app) -> None:
    """یادآوریِ پایانِ اشتراک. خودِ منطق در `bot.run_expiry_pass` است تا دستورِ
    ادمینِ /checkexpiry هم دقیقاً همان مسیر را اجرا کند، نه یک نسخه‌ی موازی.

    بدونِ این، تاریخِ مشتری بی‌سروصدا می‌گذرد و او فقط وقتی می‌فهمد که /new
    مسدود شود؛ برای نگه‌داشتنِ مشتری دیر است.
    """
    while True:
        try:
            n = await botmod.run_expiry_pass(tg_app.bot)
            if n:
                logger.info(f"{n} یادآوریِ اشتراک فرستاده شد.")
        except Exception:  # noqa: BLE001 — این حلقه هرگز نباید بمیرد
            logger.exception("حلقه‌ی یادآوریِ انقضا خطا داد.")
        await asyncio.sleep(3600)      # ساعتی یک بار کافی است


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _app, _tasks
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN تنظیم نشده — بات غیرفعال است.")
        yield
        return

    _app = botmod.build_application(TOKEN)
    await _app.initialize()
    await _app.start()
    await _app.bot.set_my_commands(botmod.COMMANDS)

    if BASE_URL and SECRET:
        url = f"{BASE_URL}/webhook/{SECRET}"
        await _app.bot.set_webhook(url=url, drop_pending_updates=True,
                                   allowed_updates=["message", "callback_query"])
        logger.info(f"webhook ثبت شد: {url}")
    else:
        logger.warning("BOT_BASE_URL یا BOT_WEBHOOK_SECRET نیست — webhook ثبت نشد.")

    _tasks = await botmod.start_workers(_app)
    _tasks.append(asyncio.create_task(_daily_loop(_app)))
    _tasks.append(asyncio.create_task(_expiry_loop(_app)))

    try:
        yield
    finally:
        for t in _tasks:
            t.cancel()
        await _app.stop()
        await _app.shutdown()


app = FastAPI(title="باتِ تولید محتوا", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "bot": bool(_app),
        "clients": len(bot_db.list_clients(limit=1000)),
    })


# ── داشبوردِ مدیریتی ─────────────────────────────────────────────────────────
# همان الگویِ پنلِ لینک‌های دمو در client_demo.py: کلید در URL، بدونِ حساب/رمزِ
# جدا. عمداً import از client_demo نشده تا این پروسه بارِ اضافه‌ی اپِ دیگر
# (CORS، mount فایل‌های استاتیک) را با خودش بالا نیاورد — این دو سرویسِ جدا روی
# Railway هستند و باید مستقل بمانند.
_ADMIN_KEY = (os.environ.get("BOT_ADMIN_KEY") or "").strip()


def _admin_ok(key: str) -> bool:
    import hmac
    return bool(_ADMIN_KEY) and hmac.compare_digest(key or "", _ADMIN_KEY)  # fail-closed


def _esc(s) -> str:
    import html as _h
    return _h.escape(str(s or ""))


def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _days_left(period_end: str) -> int | None:
    if not period_end:
        return None
    from datetime import date
    try:
        y, m, d = (int(x) for x in period_end.split("-"))
        return (date(y, m, d) - date.today()).days
    except ValueError:
        return None


def _row_html(cl, key: str) -> str:
    left = cl["quota_total"] - cl["quota_used"]
    dleft = _days_left(cl["period_end"])
    if dleft is None:
        status, cls = "بدونِ اشتراک", ""
    elif dleft < 0:
        status, cls = f"{_fa(-dleft)} روز پیش منقضی شد", "expired"
    elif dleft <= 3:
        status, cls = f"{_fa(dleft)} روز مانده", "soon"
    else:
        status, cls = f"{_fa(dleft)} روز مانده", ""
    name = _esc(cl["name"]) + (f" (@{_esc(cl['username'])})" if cl["username"] else "")
    return f"""<tr class="{cls}">
      <td>{name or '—'}<div class="cid">{cl['chat_id']}</div></td>
      <td>{_esc(cl['plan'])}</td>
      <td>{_fa(cl['quota_used'])}/{_fa(cl['quota_total'])} ({_fa(max(0,left))} مانده)</td>
      <td>{_esc(cl['period_end']) or '—'}<div class="cid">{status}</div></td>
      <td>
        <form method="post" action="/admin/grant?key={key}" class="inline">
          <input type="hidden" name="chat_id" value="{cl['chat_id']}">
          <input type="number" name="days" value="30" min="1" style="width:52px">
          <input type="number" name="quota" value="30" min="1" style="width:52px">
          <button>تمدید</button>
        </form>
        <form method="post" action="/admin/setend?key={key}" class="inline">
          <input type="hidden" name="chat_id" value="{cl['chat_id']}">
          <input type="number" name="days" placeholder="روز از امروز" style="width:96px">
          <button>تنظیمِ پایان</button>
        </form>
      </td>
    </tr>"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(key: str = "") -> HTMLResponse:
    if not _admin_ok(key):
        return HTMLResponse("<p style='font-family:sans-serif'>دسترسی مجاز نیست.</p>",
                            status_code=403)
    rows = bot_db.list_clients_by_urgency()
    total = len(rows)
    active = sum(1 for r in rows if r["plan"] != "trial")
    expired = sum(1 for r in rows if (_days_left(r["period_end"]) or 0) < 0
                  and r["plan"] != "trial")
    html = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>داشبورد مشتریان</title>
<style>
body{{font-family:Tahoma,sans-serif;background:#f6f8f7;color:#17282c;padding:20px;
 max-width:1000px;margin:0 auto;line-height:1.8}}
h1{{font-size:19px}}
.stats{{display:flex;gap:10px;margin:14px 0 20px;flex-wrap:wrap}}
.stat{{background:#fff;border:1px solid #e2eae6;border-radius:10px;padding:10px 16px}}
.stat b{{display:block;font-size:20px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2eae6;
 border-radius:10px;overflow:hidden;font-size:13.5px}}
th,td{{padding:10px 12px;text-align:right;border-bottom:1px solid #eef1ef;vertical-align:top}}
th{{background:#fafcfb;font-size:12.5px;color:#5c6e72}}
tr.soon{{background:#fff8ec}} tr.expired{{background:#fdf1f0}}
.cid{{font-size:11.5px;color:#8a9a9d;direction:ltr;text-align:right}}
form.inline{{display:inline-flex;gap:4px;align-items:center;margin:2px 4px 2px 0}}
input{{border:1px solid #e2eae6;border-radius:6px;padding:4px 6px;font-size:12.5px}}
button{{border:0;background:#12876a;color:#fff;border-radius:6px;padding:5px 10px;
 cursor:pointer;font-size:12.5px}}
button:hover{{filter:brightness(1.1)}}
</style></head><body>
<h1>داشبورد مشتریان بات</h1>
<div class="stats">
  <div class="stat"><b>{_fa(total)}</b>کل مشتریان</div>
  <div class="stat"><b>{_fa(active)}</b>اشتراکِ فعال</div>
  <div class="stat"><b>{_fa(expired)}</b>منقضی</div>
</div>
<table>
<tr><th>مشتری</th><th>پلن</th><th>سهمیه</th><th>پایانِ اشتراک</th><th>اقدام</th></tr>
{''.join(_row_html(r, _esc(key)) for r in rows) or '<tr><td colspan=5>هنوز مشتری‌ای نیست.</td></tr>'}
</table>
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.post("/admin/grant")
async def admin_grant(key: str = "", chat_id: int = Form(...),
                      days: int = Form(...), quota: int = Form(...)):
    if not _admin_ok(key):
        return PlainTextResponse("forbidden", status_code=403)
    try:
        bot_db.grant_plan(chat_id, days, quota)
    except ValueError:
        pass  # ورودیِ نامعتبر — صفحه بدونِ تغییر برمی‌گردد
    else:
        if _app:
            try:
                await _app.bot.send_message(
                    chat_id, f"اشتراک شما فعال شد.\n\nمقاله‌ی در دسترس: {botmod._fa(quota)}\n"
                             f"مدت: {botmod._fa(days)} روز\n\nبرای شروع /new را بزنید.")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"اطلاع‌رسانی به {chat_id} نشد: {e}")
    return RedirectResponse(f"/admin?key={key}", status_code=303)


@app.post("/admin/setend")
async def admin_setend(key: str = "", chat_id: int = Form(...), days: int = Form(...)):
    if not _admin_ok(key):
        return PlainTextResponse("forbidden", status_code=403)
    bot_db.set_period_end(chat_id, days)
    return RedirectResponse(f"/admin?key={key}", status_code=303)


@app.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    if not SECRET or secret != SECRET:
        return PlainTextResponse("forbidden", status_code=403)
    if _app is None:
        return PlainTextResponse("bot not ready", status_code=503)
    data = await request.json()
    upd = Update.de_json(data, _app.bot)
    u = upd.effective_user
    if u:   # شناسه در لاگ می‌ماند تا پشتیبانی بتواند کاربر را پیدا کند
        text = (upd.message.text if upd.message else None) or \
               (upd.callback_query.data if upd.callback_query else "")
        logger.info(f"آپدیت از {u.id} (@{u.username or '—'}): {str(text)[:40]}")
    await _app.process_update(upd)
    return PlainTextResponse("ok")
