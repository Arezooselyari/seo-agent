"""دموی وب — نسخه‌ی آزمایشی SaaS.

بازدیدکننده حوزه‌ی تخصصی‌اش را انتخاب می‌کند و یک مقاله‌ی نمونه دریافت می‌کند
که **دقیقاً مثل مقاله‌ی واقعیِ تلگرام** است: همان پرامپت `persian_writer.md`،
همان ساختار، همان مرحله‌ی انسانی‌سازی، و همان رندرِ `render.py`.

اجرا:  python -m uvicorn src.demo_api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import mimetypes
import os
import time
from pathlib import Path

# بعضی محیط‌ها woff2 را نمی‌شناسند و text/plain می‌فرستند؛ سافاری/iOS فونت را رد
# می‌کند. MIME درست را ثبت می‌کنیم تا فونت روی همه‌ی مرورگرها لود شود.
mimetypes.add_type("font/woff2", ".woff2")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Secrets, TenantConfig
from .llm import structured_call
from .generate import ARTICLE_SCHEMA, GeneratedArticle
from .humanize import humanize_article
from .render import render_full_page
from .images import fetch_pexels_images

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo"
LIBRARY_DIR = DEMO_DIR / "library"
FONTS_DIR = DEMO_DIR / "fonts"
PROMPT_PATH = ROOT / "prompts" / "persian_writer.md"

app = FastAPI(title="دموی ایجنت تولید محتوای SEO")

# اجازه‌ی فراخوانی از سایت‌های دیگر (مثلاً وقتی HTML روی وردپرس sagharnazari.ir
# جاسازی شده ولی API روی Railway است). دمو عمومی و rate-limited است، پس بازِ کامل.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

# فونت Vazirmatn را خودمان host می‌کنیم (Google Fonts در ایران اغلب مسدود است،
# پس بازدیدکننده فونت را نمی‌دید). این فایل‌ها مستقیم از همین سرور سرو می‌شوند.
if FONTS_DIR.exists():
    app.mount("/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")

# ── محافظت از کوتا (همه از env قابل تنظیم روی Railway، بدون تغییر کد) ──
# سقف تولیدِ *جدید* برای هر IP در روز (کش به حساب نمی‌آید)
_MAX_PER_IP_PER_DAY = int(os.environ.get("DEMO_MAX_PER_IP", "3"))
# سقف کلِ تولیدِ زنده در کل روز — تا کوتای Gemini برای ایجنت روزانه هم بماند
_DEMO_DAILY_CAP = int(os.environ.get("DEMO_DAILY_CAP", "10"))
# مدت اعتبار کش (ساعت) — درخواست‌های تکراری در این بازه رایگان‌اند
_CACHE_TTL = int(os.environ.get("DEMO_CACHE_HOURS", "24")) * 3600

# مدلِ دمو — جدا از config.yaml.
# کلید Gemini جداگانه‌ی دمو (رایگان، پروژه‌ی تازه) به gemini-2.5-flash دسترسی
# ندارد («no longer available to new users»). پس دمو از یک مدلِ در-دسترس استفاده
# می‌کند، در حالی که پایپ‌لاین اصلی (config.yaml + کلید قدیمی) روی مدل خودش می‌ماند.
# «gemini-flash-latest» یک aliasِ گوگل است که همیشه به یک مدلِ flashِ موجود اشاره
# می‌کند، پس هیچ‌وقت خطای «مدل حذف شد» نمی‌دهد. با env قابلِ تغییر است.
_DEMO_MODEL = os.environ.get("DEMO_MODEL", "gemini-flash-latest")

_ip_log: dict[str, list[float]] = {}
_global_log: list[float] = []           # زمانِ تولیدهای زنده‌ی امروز (برای سقف کلی)
_cache: dict[str, tuple[float, dict]] = {}   # key -> (زمان، payload)


def _rate_limited(ip: str) -> bool:
    now = time.time()
    day_ago = now - 86400
    hits = [t for t in _ip_log.get(ip, []) if t > day_ago]
    _ip_log[ip] = hits
    if len(hits) >= _MAX_PER_IP_PER_DAY:
        return True
    hits.append(now)
    return False


def _global_capacity_left() -> int:
    """چند تولیدِ زنده‌ی دیگر امروز مجاز است (کش این را مصرف نمی‌کند)."""
    global _global_log
    day_ago = time.time() - 86400
    _global_log = [t for t in _global_log if t > day_ago]
    return _DEMO_DAILY_CAP - len(_global_log)


def _cache_key(niche: str, topic: str) -> str:
    return niche.strip().lower() + "|" + " ".join(topic.strip().lower().split())


def _cache_get(key: str) -> dict | None:
    v = _cache.get(key)
    if v and (time.time() - v[0]) < _CACHE_TTL:
        return v[1]
    return None


# ── حوزه‌های آماده ───────────────────────────────────────────────────
NICHES = {
    "medical":   "پزشکی و سلامت",
    "business":  "کسب‌وکار و مدیریت",
    "finance":   "مالی و سرمایه‌گذاری",
    "tech":      "فناوری و هوش مصنوعی",
    "news":      "خبر و تحلیل صنعت",
    "beauty":    "زیبایی و پوست",
    "legal":     "حقوقی و وکالت",
    "realestate":"املاک و مسکن",
    "education": "آموزش و مهارت",
}


import re as _re


def _extract_title(html: str) -> str:
    m = _re.search(r"<title>(.*?)</title>", html, _re.IGNORECASE | _re.DOTALL)
    return m.group(1).strip() if m else "مقاله‌ی نمونه"


def _load_seed_library() -> dict[str, dict]:
    """کتابخانه‌ی مقالاتِ از پیش‌ساخته (بدون نیاز به API).

    هر فایل `demo/library/<niche>.html` یک صفحه‌ی کاملِ رندرشده است (همان خروجی
    render_full_page). بازدیدکننده که آن حوزه را انتخاب کند، این مقاله‌ی واقعی و
    باکیفیت را فوری می‌بیند — مستقل از سهمیه‌ی Gemini.
    """
    lib: dict[str, dict] = {}
    if not LIBRARY_DIR.exists():
        return lib
    for path in LIBRARY_DIR.glob("*.html"):
        niche = path.stem
        html = path.read_text(encoding="utf-8")
        lib[niche] = {
            "ok": True,
            "title": _extract_title(html),
            "html": html,
            "niche": NICHES.get(niche, niche),
            "sample": True,
        }
    return lib


_SEED_LIBRARY = _load_seed_library()


def _demo_brief(niche_label: str, topic: str) -> str:
    """یک «Research Brief» ساختگی برای دمو — جای منبع واقعی.

    به نویسنده می‌گوید از دانشِ عمومی و معتبر بنویسد و آمار/نقل‌قولِ دقیقِ
    غیرقابل‌راستی‌آزمایی نسازد (کنترل هالوسینیشن در نبود منبع).
    """
    subject = topic.strip() or niche_label
    return (
        f"خلاصه: یک مقاله‌ی جامع، کاربردی و سئوشده درباره‌ی «{subject}» "
        f"در حوزه‌ی «{niche_label}» برای مخاطب فارسی‌زبان.\n\n"
        "نکات کلیدی:\n"
        f"- موضوع اصلی مقاله دقیقاً «{subject}» است و کل متن باید به همین بپردازد.\n"
        "- از دانشِ عمومیِ معتبر و به‌روز استفاده کن.\n"
        "- آمار یا رقمِ دقیقِ ساختگی نساز؛ اگر عددی مطمئن نیستی، کیفی بنویس.\n\n"
        "زاویه‌های پیشنهادی:\n"
        f"- تعریف و اهمیت «{subject}»\n"
        "- راهکارها و نکات کاربردی\n"
        "- اشتباهات رایج و پاسخ به پرسش‌های متداول\n"
    )


def _build_demo_prompt(niche_label: str, topic: str) -> str:
    """همان پرامپت واقعیِ persian_writer.md، با placeholderهای دمو پر شده."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    subject = topic.strip() or niche_label
    return (
        template.replace("{source_name}", "")
        .replace("{source_url}", "")
        .replace("{original_title}", subject)
        .replace("{topic_reason}", "نمونه‌ی نمایشی برای معرفی سرویس تولید محتوا")
        .replace("{internal_links}", "(لینک داخلی کاندیدی موجود نیست — لینک داخلی نگذار)")
        .replace("{research_brief}", _demo_brief(niche_label, topic))
    )


class DemoRequest(BaseModel):
    niche: str = ""
    topic: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = DEMO_DIR / "index.html"
    body = (
        html_path.read_text(encoding="utf-8")
        if html_path.exists()
        else "<h1>demo/index.html یافت نشد</h1>"
    )
    # no-cache تا هر بازدیدکننده همیشه آخرین نسخه‌ی صفحه را بگیرد (نه کپیِ قدیمی).
    return HTMLResponse(
        content=body,
        headers={"Cache-Control": "no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.post("/api/demo")
def generate_demo(req: DemoRequest, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"

    # ۰) کتابخانه‌ی از پیش‌ساخته: اگر برای این حوزه مقاله‌ی آماده داریم،
    #    فوری و بدون هیچ تماس با API برگردان (پایدار و سریع).
    seeded = _SEED_LIBRARY.get(req.niche)
    if seeded is not None:
        return JSONResponse(content=seeded)

    # حوزه‌هایی که هنوز نمونه‌ی آماده ندارند: پیام «به‌زودی» به‌جای خطای سهمیه.
    if req.niche not in _SEED_LIBRARY:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "error": "نمونه‌ی این حوزه به‌زودی اضافه می‌شود. "
                         "فعلاً یکی از حوزه‌های فعال را امتحان کنید یا برای نسخه‌ی کامل تماس بگیرید.",
            },
        )

    # ۰) کش: اگر همین حوزه/موضوع اخیراً ساخته شده، رایگان و فوری برگردان
    ckey = _cache_key(req.niche, req.topic)
    cached = _cache_get(ckey)
    if cached is not None:
        return JSONResponse(content={**cached, "cached": True})

    # ۱) سقف هر IP (فقط برای تولیدِ جدید)
    if _rate_limited(ip):
        return JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "error": "سقف نمونه‌ی رایگان امروز برای شما پر شد. "
                         "برای نسخه‌ی کامل با ما تماس بگیرید.",
            },
        )

    # ۲) سقف کلی روزانه — تا کوتای Gemini برای ایجنت روزانه هم بماند
    if _global_capacity_left() <= 0:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "نمونه‌های رایگانِ امروز تکمیل شد. فردا دوباره امتحان کنید "
                         "یا برای نسخه‌ی کامل با ما تماس بگیرید.",
            },
        )

    niche_label = NICHES.get(req.niche, req.niche or "عمومی")

    try:
        cfg = TenantConfig.load()
        cfg.ai_model = _DEMO_MODEL  # مدلِ دمو، جدا از پایپ‌لاین اصلی
        secrets = Secrets()
        # ۱) نوشتن مقاله با همان پرامپت و ساختار واقعی
        data = structured_call(
            _build_demo_prompt(niche_label, req.topic),
            ARTICLE_SCHEMA,
            cfg=cfg,
            secrets=secrets,
            tool_name="publish_article",
            max_tokens=16384,
        )
        article = GeneratedArticle(source_url="", source_name="", **data)

        # ۲) انسانی‌سازی لحن (همان مرحله‌ی پایپ‌لاین)
        article = humanize_article(article, cfg=cfg, secrets=secrets)

        # ۳) عکس Pexels (اگر کلید ست شده و مقاله نیاز داشت) — مثل تلگرام
        image = inline_image = None
        if article.needs_image and article.image_query:
            imgs = fetch_pexels_images(article.image_query, secrets, count=2)
            if imgs:
                image = imgs[0]
                inline_image = imgs[1] if len(imgs) > 1 else None

        # ۴) رندر با همان صفحه‌ی زیبای تلگرام
        html = render_full_page(article, image=image, cfg=cfg, inline_image=inline_image)
    except Exception as e:  # noqa: BLE001
        # لاگِ خطای خام برای عیب‌یابی (کلید API در پیام خطای Gemini نیست)
        print(f"[demo-error] {type(e).__name__}: {e}", flush=True)
        msg = str(e).lower()
        if "quota" in msg or "429" in msg or "perday" in msg.replace(" ", ""):
            friendly = ("سرویس نمونه موقتاً به سقف روزانه رسیده است. "
                        "کمی بعد دوباره امتحان کنید یا برای نسخه‌ی کامل تماس بگیرید.")
        else:
            friendly = "خطایی در تولید نمونه رخ داد. لطفاً دوباره تلاش کنید."
        return JSONResponse(status_code=503, content={"ok": False, "error": friendly})

    # موفق بود: در سقف روزانه ثبت کن و در کش بگذار
    _global_log.append(time.time())
    payload = {
        "ok": True,
        "title": article.title,
        "html": html,
        "niche": niche_label,
    }
    _cache[ckey] = (time.time(), payload)
    return JSONResponse(content=payload)


@app.get("/api/niches")
def list_niches() -> dict:
    return {"niches": [{"id": k, "label": v} for k, v in NICHES.items()]}
