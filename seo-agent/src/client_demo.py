"""دموی تعاملی برای کلاینت — تولیدِ زنده‌ی مقاله.

کلاینت حوزه، نوعِ محتوا (خبری/آموزشی) و کلیدواژه‌ی دلخواهش را می‌دهد و یک مقاله‌ی
اختصاصی برایش تولید می‌شود. چون تولید ~۲ تا ۳ دقیقه طول می‌کشد، کار در یک ترد
پس‌زمینه اجرا می‌شود و صفحه با polling مرحله‌ی واقعی را نشان می‌دهد.

اجرا: python -m uvicorn src.client_demo:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import mimetypes
import os
import sys
import threading
import time
import uuid
from pathlib import Path

# ماژول‌های پایپ‌لاین با print و کاراکترهای «✓/✗» لاگ می‌گیرند. روی کنسولِ ویندوز
# (cp1256) این printها UnicodeEncodeError می‌دهند و چون داخلِ مسیرِ تولیدند، کلِ
# مقاله را می‌کُشند. خروجی را همین‌جا UTF-8 می‌کنیم تا لاگ هیچ‌وقت عاملِ شکست نشود.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # پایپ/استریمِ بدونِ reconfigure
        pass

# بعضی محیط‌ها woff2 را text/plain می‌فرستند و سافاری فونت را رد می‌کند.
mimetypes.add_type("font/woff2", ".woff2")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm

# ── پروایدرِ این پروسه: OpenRouter (claude-sonnet-5) ────────────────────────
# فقط درون‌پروسه‌ای — settings.yaml دست نمی‌خورد، پس پایپ‌لاینِ روزانه (پروسه‌ی
# جدا) همچنان با تنظیماتِ خودش کار می‌کند.
_DEMO_PROVIDER = os.environ.get("DEMO_PROVIDER", "openrouter")
llm._settings["provider"] = _DEMO_PROVIDER

from . import demo_render, generation  # noqa: E402
from .generation import NICHES  # noqa: E402  — تعریفِ یکتا در موتورِ مشترک

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo"
FONTS_DIR = DEMO_DIR / "fonts"

app = FastAPI(title="دموی تولید مقاله — نسخه‌ی کلاینت")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

if FONTS_DIR.exists():
    app.mount("/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")

# ── محدودیت‌ها (همه از env قابل تنظیم) ──────────────────────────────────────
# کدهای دسترسی، کاما-جدا. اگر خالی باشد، هیچ‌کس نمی‌تواند تولید کند (fail-closed).
_CODES = {c.strip().lower() for c in os.environ.get("DEMO_ACCESS_CODES", "").split(",") if c.strip()}
# هر کلاینت فقط **یک** مقاله تولید می‌کند؛ درخواستِ دوم به «فعال‌سازی اشتراک» می‌رسد.
_MAX_PER_CODE = int(os.environ.get("DEMO_MAX_PER_CODE", "1"))
_DAILY_CAP = int(os.environ.get("DEMO_DAILY_CAP", "25"))          # سقفِ کلِ سرویس در روز
_CACHE_TTL = int(os.environ.get("DEMO_CACHE_HOURS", "12")) * 3600
_MAX_KEYWORD_LEN = 80        # ورودی بلند = پرامپتِ گران و در معرضِ سوءاستفاده

_jobs: dict[str, dict] = {}
_global_log: list[float] = []
_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()

# ── توکن‌های یک‌بارمصرف ─────────────────────────────────────────────────────
# هر لینکی که در دایرکت اینستاگرام می‌رود یک توکنِ یکتا دارد: با اولین تولید
# می‌سوزد. وضعیت روی دیسک است نه حافظه، چون ری‌دیپلویِ Railway پروسه را از نو
# بالا می‌آورد و لینک‌های سوخته نباید دوباره زنده شوند.
_TOKENS_DB = Path(os.environ.get("DEMO_DB", str(ROOT / "data" / "demo_tokens.db")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_tokens (
    token      TEXT PRIMARY KEY,
    label      TEXT,
    created_at TEXT NOT NULL,
    used_at    TEXT,
    niche      TEXT,
    ctype      TEXT,
    keyword    TEXT,
    title      TEXT,
    html       TEXT
)
"""


def tokens_conn():
    import sqlite3
    _TOKENS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_TOKENS_DB, timeout=15)
    conn.execute(_SCHEMA)
    return conn


def _token_state(token: str) -> dict:
    """وضعیتِ لینک: valid | used | invalid (+ مقاله‌ی تولیدشده اگر هست)."""
    if not token:
        return {"state": "invalid"}
    try:
        with tokens_conn() as conn:
            row = conn.execute(
                "SELECT used_at, title, html FROM demo_tokens WHERE token=?",
                (token,)).fetchone()
    except Exception as e:  # noqa: BLE001
        logger.error(f"خواندنِ توکن نشد ({e}).")
        return {"state": "invalid"}      # fail-closed
    if row is None:
        return {"state": "invalid"}
    used_at, title, html = row
    if not used_at:
        return {"state": "valid"}
    return {"state": "used", "title": title or "", "html": html or ""}


def _burn_token(token: str, niche: str, ctype: str, keyword: str) -> bool:
    """توکن را اتمیک می‌سوزاند. False یعنی قبلاً سوخته یا اصلاً وجود ندارد.

    شرطِ `used_at IS NULL` داخلِ خودِ UPDATE است تا دو کلیکِ هم‌زمان نتوانند هر دو
    رد شوند (چکِ جدا از نوشتن، مسابقه‌ی زمانی می‌سازد).
    """
    try:
        with tokens_conn() as conn:
            cur = conn.execute(
                "UPDATE demo_tokens SET used_at=datetime('now'), niche=?, ctype=?, keyword=? "
                "WHERE token=? AND used_at IS NULL", (niche, ctype, keyword, token))
            return cur.rowcount == 1
    except Exception as e:  # noqa: BLE001
        logger.error(f"سوزاندنِ توکن نشد ({e}).")
        return False


def _save_token_article(token: str, title: str, html: str) -> None:
    """مقاله را کنارِ توکن نگه می‌دارد تا بازکردنِ دوباره‌ی لینک آن را نشان بدهد."""
    try:
        with tokens_conn() as conn:
            conn.execute("UPDATE demo_tokens SET title=?, html=? WHERE token=?",
                         (title, html, token))
    except Exception as e:  # noqa: BLE001
        logger.error(f"ذخیره‌ی مقاله‌ی توکن نشد ({e}).")


def _release_token(token: str) -> None:
    """اگر تولید شکست خورد، لینک را برگردان — کلاینت نباید بی‌دلیل بسوزد."""
    try:
        with tokens_conn() as conn:
            conn.execute("UPDATE demo_tokens SET used_at=NULL WHERE token=? AND html IS NULL",
                         (token,))
    except Exception as e:  # noqa: BLE001
        logger.error(f"آزادسازیِ توکن نشد ({e}).")


# ── کمکی‌ها ─────────────────────────────────────────────────────────────────
def _within_day(stamps: list[float]) -> list[float]:
    day_ago = time.time() - 86400
    return [t for t in stamps if t > day_ago]


# ── خطِ تولید (در ترد پس‌زمینه) ─────────────────────────────────────────────
def _run_job(job_id: str, token: str, niche: str, ctype: str, keyword: str) -> None:
    job = _jobs[job_id]

    def step(name: str, percent: int) -> None:
        job.update(step=name, percent=percent)
        logger.info(f"[job {job_id[:8]}] {percent}% — {name}")

    try:
        payload = generation.generate(niche, ctype, keyword, on_step=step)

        step("در حال آماده‌سازی نمایش…", 96)
        # مقاله‌ی کامل و بدونِ قفل — این لینک یک‌بارمصرف است، پس محدودیتِ نمایش ندارد.
        html = demo_render.render_page(payload, paywall=False)
        title = payload.get("title_seo", "")

        # مقاله کنارِ توکن ذخیره می‌شود: اگر کلاینت تب را ببندد و بعداً همان لینک را
        # باز کند، مقاله‌اش را دوباره می‌بیند (بدونِ تولیدِ دوباره).
        _save_token_article(token, title, html)

        job.update(status="done", percent=100, step="آماده شد", html=html, title=title)
        logger.info(f"[job {job_id[:8]}] ✅ «{title}»")

    except Exception as e:  # noqa: BLE001
        logger.exception(f"[job {job_id[:8]}] شکست خورد")
        # تولید نشد ⇒ لینک نباید سوخته بماند؛ کلاینت باید بتواند دوباره تلاش کند.
        _release_token(token)
        job.update(status="error", error=str(e) or "خطای ناشناخته در تولید مقاله.")


# ── API ─────────────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    niche: str = ""
    content_type: str = "tutorial"
    keyword: str = ""
    token: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    path = DEMO_DIR / "index.html"
    body = path.read_text(encoding="utf-8") if path.exists() else "<h1>index.html یافت نشد</h1>"
    return HTMLResponse(body, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/api/niches")
def list_niches() -> dict:
    return {"niches": [{"id": k, "label": v} for k, v in NICHES.items()]}


@app.get("/api/token/{token}")
def token_status(token: str) -> JSONResponse:
    """صفحه با این تماس تصمیم می‌گیرد فرم را نشان بدهد یا مقاله‌ی قبلی را."""
    st = _token_state(token.strip())
    if st["state"] == "valid":
        return JSONResponse({"ok": True, "state": "valid"})
    if st["state"] == "used":
        return JSONResponse({"ok": True, "state": "used",
                             "html": st.get("html", ""), "title": st.get("title", "")})
    return JSONResponse(status_code=404, content={"ok": False, "state": "invalid"})


@app.post("/api/generate")
def generate(req: GenerateRequest) -> JSONResponse:
    token = (req.token or "").strip()
    st = _token_state(token)
    if st["state"] == "invalid":
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "این لینک معتبر نیست."})
    if st["state"] == "used":
        return JSONResponse(status_code=403, content={
            "ok": False, "used": True,
            "error": "این لینک قبلاً استفاده شده است."})

    ctype = "news" if req.content_type == "news" else "tutorial"
    niche = req.niche if req.niche in NICHES else ""
    keyword = (req.keyword or "").strip()[:_MAX_KEYWORD_LEN]
    if not niche and not keyword:
        return JSONResponse(status_code=400, content={
            "ok": False, "error": "لطفاً حوزه را انتخاب کنید یا کلیدواژه بنویسید."})

    with _lock:
        global _global_log
        _global_log = _within_day(_global_log)
        if len(_global_log) >= _DAILY_CAP:
            return JSONResponse(status_code=503, content={
                "ok": False, "error": "ظرفیت امروزِ سرویس تکمیل شد. لطفاً فردا دوباره امتحان کنید."})

        # سوزاندنِ اتمیک: اگر کلاینت دو بار پشتِ‌هم کلیک کند، فقط یکی رد می‌شود
        if not _burn_token(token, niche, ctype, keyword):
            return JSONResponse(status_code=403, content={
                "ok": False, "used": True, "error": "این لینک قبلاً استفاده شده است."})

        _global_log.append(time.time())
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {"status": "running", "percent": 5,
                         "step": "در حال آماده‌سازی…", "html": "", "error": ""}

    threading.Thread(target=_run_job, args=(job_id, token, niche, ctype, keyword),
                     daemon=True).start()
    return JSONResponse({"ok": True, "job_id": job_id})


@app.get("/api/job/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    job = _jobs.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "درخواست پیدا نشد."})
    return JSONResponse({"ok": True, **job})


# ── پنلِ مدیریت (ساختِ لینک) ────────────────────────────────────────────────
# توکن‌ها در دیتابیسِ همین سرور می‌نشینند، پس ساختشان باید از خودِ سرویس انجام شود.
_ADMIN_KEY = os.environ.get("DEMO_ADMIN_KEY", "").strip()


def _admin_ok(key: str) -> bool:
    import hmac
    # بدونِ کلیدِ تنظیم‌شده، پنل کاملاً بسته است (fail-closed)
    return bool(_ADMIN_KEY) and hmac.compare_digest(key or "", _ADMIN_KEY)


@app.get("/admin/mint")
def admin_mint(key: str = "", count: int = 1, label: str = "") -> JSONResponse:
    """`count` لینکِ تازه می‌سازد و برمی‌گرداند."""
    if not _admin_ok(key):
        return JSONResponse(status_code=403, content={"ok": False, "error": "کلید معتبر نیست."})
    import secrets
    count = max(1, min(int(count), 50))
    base = os.environ.get("DEMO_BASE_URL", "").rstrip("/")
    toks = []
    with tokens_conn() as conn:
        for _ in range(count):
            t = secrets.token_urlsafe(12)
            conn.execute("INSERT INTO demo_tokens(token, label, created_at) "
                         "VALUES(?,?,datetime('now'))", (t, label))
            toks.append(t)
    return JSONResponse({"ok": True, "links": [f"{base}/?t={t}" for t in toks]})


@app.get("/admin", response_class=HTMLResponse)
def admin_page(key: str = "") -> HTMLResponse:
    if not _admin_ok(key):
        return HTMLResponse("<p style='font-family:sans-serif'>دسترسی مجاز نیست.</p>",
                            status_code=403)
    base = os.environ.get("DEMO_BASE_URL", "").rstrip("/")
    with tokens_conn() as conn:
        rows = conn.execute(
            "SELECT token, label, used_at, title FROM demo_tokens "
            "ORDER BY created_at DESC LIMIT 200").fetchall()

    ready = [r for r in rows if not r[2]]
    used = [r for r in rows if r[2]]

    def li_ready(r):
        link = f"{base}/?t={r[0]}"
        return (f'<li><input readonly value="{link}" onclick="this.select()">'
                f'<button onclick="navigator.clipboard.writeText(\'{link}\')">کپی</button>'
                f'<span class="lbl">{_h(r[1] or "")}</span></li>')

    def li_used(r):
        return f'<li class="u"><b>{_h(r[3] or "بدون عنوان")}</b><span class="lbl">{_h(r[1] or "")}</span></li>'

    html = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>لینک‌های دمو</title>
<style>
body{{font-family:Tahoma,sans-serif;background:#f6f8f7;color:#17282c;padding:20px;
 max-width:820px;margin:0 auto;line-height:1.9}}
h2{{margin:26px 0 10px}} ul{{list-style:none;padding:0}}
li{{display:flex;gap:8px;align-items:center;background:#fff;border:1px solid #e2eae6;
 border-radius:10px;padding:9px 12px;margin-bottom:8px;flex-wrap:wrap}}
li.u{{opacity:.65}} input{{flex:1;min-width:220px;border:0;font-size:13px;
 font-family:monospace;direction:ltr;text-align:left;background:transparent;color:#0e6b54}}
button{{border:0;background:#12876a;color:#fff;border-radius:8px;padding:7px 14px;
 cursor:pointer;font-family:inherit;font-size:13px}}
button:hover{{filter:brightness(1.1))}}
.lbl{{font-size:12px;color:#5c6e72}}
.bar{{background:#fff;border:1px solid #e2eae6;border-radius:12px;padding:16px;
 display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.bar input{{border:1px solid #e2eae6;border-radius:8px;padding:8px;direction:rtl;text-align:right}}
.count{{color:#5c6e72;font-size:13.5px}}
</style></head><body>
<h1 style="font-size:20px">لینک‌های یک‌بارمصرف دمو</h1>
<div class="bar">
  <span>تعداد:</span><input id="c" type="number" value="5" min="1" max="50" style="width:70px">
  <span>برچسب:</span><input id="l" placeholder="مثلاً: کلاینت‌های اینستاگرام">
  <button onclick="mint()">ساخت لینک تازه</button>
</div>
<h2>آماده ({len(ready)})</h2><ul>{''.join(li_ready(r) for r in ready) or '<li>لینک آماده‌ای نیست.</li>'}</ul>
<h2>استفاده‌شده ({len(used)})</h2><ul>{''.join(li_used(r) for r in used) or '<li>هنوز هیچ‌کدام استفاده نشده.</li>'}</ul>
<script>
const KEY = new URLSearchParams(location.search).get('key');
async function mint(){{
  const c = document.getElementById('c').value, l = document.getElementById('l').value;
  const r = await fetch(`/admin/mint?key=${{encodeURIComponent(KEY)}}&count=${{c}}&label=${{encodeURIComponent(l)}}`);
  const d = await r.json();
  if (d.ok) location.reload(); else alert(d.error || 'نشد');
}}
</script></body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _h(s: str) -> str:
    import html as _esc
    return _esc.escape(str(s))
