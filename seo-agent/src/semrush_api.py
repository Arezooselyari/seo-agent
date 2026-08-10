"""کلاینت واقعی SEMrush Analytics API (خودکار — بدون نیاز به MCP/Claude).

از endpoint استاندارد https://api.semrush.com/ استفاده می‌کند. خروجی CSV با جداکننده‌ی «؛»
است. کلید در .env → SEMRUSH_API_KEY.

توابع سطح‌بالا خروجی را در قالبی می‌دهند که semrush_bridge انتظار دارد، پس بقیه‌ی سیستم
(writer / evaluate_and_sync) بدون تغییر کار می‌کند.

مستند API: https://developer.semrush.com/api/v3/analytics/
"""
import json
import logging
import urllib.parse
import urllib.request

from . import llm, semrush_bridge
from .config import env, load_settings

logger = logging.getLogger(__name__)

_BASE = "https://api.semrush.com/"

# ستون‌های خروجی: Ph=کیورد، Nq=حجم ماهانه، Cp=CPC، Co=رقابت، Nr=تعداد نتایج، Kd=سختی
_COLS_OVERVIEW = "Ph,Nq,Cp,Co,Nr"
_COLS_RELATED = "Ph,Nq,Cp,Co,Kd,Nr"
_COLS_QUESTIONS = "Ph,Nq,Kd"


def _market() -> str:
    return load_settings().get("semrush", {}).get("market", "us")


def _api_get(params: dict) -> list[dict]:
    """یک تماس به SEMrush می‌زند و ردیف‌های CSV را به list[dict] تبدیل می‌کند."""
    key = env("SEMRUSH_API_KEY", required=True)
    params = {**params, "key": key}
    url = _BASE + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8", errors="replace").strip()

    # خطاهای SEMrush به‌صورت متن ساده برمی‌گردند (مثلاً "ERROR 50 :: NOTHING FOUND")
    if not text or text.upper().startswith("ERROR"):
        logger.warning(f"SEMrush پاسخ خالی/خطا: {text[:80]!r}")
        return []

    lines = text.split("\n")
    header = [h.strip() for h in lines[0].split(";")]
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        vals = line.split(";")
        rows.append(dict(zip(header, vals)))
    return rows


def _to_num(s: str, cast=float):
    try:
        return cast(s)
    except (ValueError, TypeError):
        return None


# ── فاز A: کیوردریسرچ ────────────────────────────────────────────

def research_keywords(topic: str, seed: str, limit: int = 15) -> dict:
    """برای یک seed، کیورد اصلی + پشتیبان + سوال‌های long-tail را از SEMrush می‌گیرد
    و در فایل واسط ذخیره می‌کند. dict ذخیره‌شده را برمی‌گرداند.
    """
    db = _market()
    kd_max = load_settings().get("semrush", {}).get("kd_max", 40)

    overview = _api_get({
        "type": "phrase_this", "phrase": seed, "database": db,
        "export_columns": _COLS_OVERVIEW,
    })
    related = _api_get({
        "type": "phrase_related", "phrase": seed, "database": db,
        "export_columns": _COLS_RELATED, "display_limit": limit,
        "display_sort": "nq_desc",
    })
    questions = _api_get({
        "type": "phrase_questions", "phrase": seed, "database": db,
        "export_columns": _COLS_QUESTIONS, "display_limit": 5,
        "display_sort": "nq_desc",
    })

    per_kw = {}
    for r in overview + related:
        ph = r.get("Keyword") or r.get("Ph")
        if not ph:
            continue
        per_kw[ph] = {
            "volume": _to_num(r.get("Search Volume") or r.get("Nq"), int),
            "kd": _to_num(r.get("Keyword Difficulty Index") or r.get("Kd"), float),
            "cpc": _to_num(r.get("CPC") or r.get("Cp"), float),
        }

    # انتخاب کیورد اصلی: ترجیحاً کیوردی با KD واقعیِ ≤ سقف و بیشترین حجم (قابل‌رنک).
    # این با گیت SEMrush (KD بالا → رد) هماهنگ است: از اول کیورد کم‌رقابت هدف می‌گیریم.
    winnable = [
        (ph, m) for ph, m in per_kw.items()
        if m["kd"] is not None and m["kd"] <= kd_max
    ]
    winnable.sort(key=lambda x: (x[1]["volume"] or 0), reverse=True)

    if winnable:
        candidates = winnable
    else:
        # هیچ کیورد کم‌رقابتی با KD معلوم نبود → آن‌هایی که KD نامعلوم دارند، بر حجم
        candidates = sorted(
            ((ph, m) for ph, m in per_kw.items() if m["kd"] is None),
            key=lambda x: (x[1]["volume"] or 0), reverse=True,
        )

    primary = seed if not candidates else candidates[0][0]
    secondary = [ph for ph, _ in candidates[1:4]]
    # اگر هیچ کیورد کم‌سختی نبود، کم‌سختی‌ترین‌های مرتبط را بردار (تا دست خالی نمانیم)
    if not secondary:
        by_kd = sorted(
            ((ph, m) for ph, m in per_kw.items() if ph != primary and m.get("kd") is not None),
            key=lambda x: x[1]["kd"],
        )
        secondary = [ph for ph, _ in by_kd[:3]]
    longtail = [r.get("Keyword") or r.get("Ph") for r in questions if (r.get("Keyword") or r.get("Ph"))][:3]

    data = {
        "primary": primary,
        "primary_fa": None,   # معادل فارسی: توسط نویسنده/مدل حین تولید ساخته می‌شود
        "secondary": secondary,
        "longtail": longtail,
        "per_kw": per_kw,
        "fa_map": {},
        "market": db,
        "note": f"داده از SEMrush API (دیتابیس {db}). معادل فارسی هنگام تولید ساخته می‌شود.",
    }
    semrush_bridge.save_keywords(topic, data)
    logger.info(f"SEMrush کیوردریسرچ «{topic}»: اصلی={primary}، {len(secondary)} پشتیبان، {len(longtail)} سوال")
    return data


# ── فاز C: تحلیل سئوی مقاله ──────────────────────────────────────

def analyze_article_keywords(article_id: int, keywords: list[str]) -> dict:
    """کیوردهای مقاله‌ی تولیدشده را با SEMrush چک می‌کند و گزارش را ذخیره می‌کند."""
    db = _market()
    kd_max = load_settings().get("semrush", {}).get("kd_max", 40)

    per_kw = {}
    for kw in keywords:
        rows = _api_get({
            "type": "phrase_this", "phrase": kw, "database": db,
            "export_columns": _COLS_RELATED,
        })
        if rows:
            r = rows[0]
            per_kw[kw] = {
                "volume": _to_num(r.get("Search Volume") or r.get("Nq"), int),
                "kd": _to_num(r.get("Keyword Difficulty Index") or r.get("Kd"), float),
                "competition": _to_num(r.get("Competition") or r.get("Co"), float),
            }

    # فقط KDهای واقعی (>0)؛ صفر یعنی داده‌ی معتبر نیست
    kds = [m["kd"] for m in per_kw.values() if m.get("kd")]
    avg_kd = round(sum(kds) / len(kds), 1) if kds else None
    if avg_kd is None:
        verdict = "UNKNOWN"      # داده‌ی KD نداریم → گیت را مسدود نکن
    elif avg_kd <= kd_max:
        verdict = "GOOD"
    else:
        verdict = "WEAK"

    report = {
        "targeted_keywords": keywords,
        "per_kw": per_kw,
        "avg_kd": avg_kd,
        "verdict": verdict,
        "notes": f"میانگین KD={avg_kd} (سقف {kd_max}). داده از SEMrush API دیتابیس {db}.",
    }
    semrush_bridge.save_analysis(article_id, report)
    logger.info(f"SEMrush تحلیل مقاله #{article_id}: verdict={verdict}, avg_kd={avg_kd}")
    return report


# ── ترجمه‌ی خودکار (فارسی ↔ انگلیسی) با Gemini ───────────────────

def derive_english_seed(topic_fa: str) -> str:
    """موضوع فارسی را به یک seed کیورد انگلیسی کوتاه تبدیل می‌کند (برای SEMrush)."""
    out = llm.ask(
        step="semrush_seed",
        user_content=(
            "این موضوع فارسی را به یک عبارت کلیدواژه‌ی انگلیسی کوتاه و پرجستجو "
            "(۲ تا ۴ کلمه، مناسب کیوردریسرچ) تبدیل کن.\n"
            f"موضوع: {topic_fa}\n"
            'فقط JSON: {"seed": "english keyword"}'
        ),
        model_tier="cheap",
        json_output=True,
        max_tokens=200,
    )
    seed = (out or {}).get("seed", "").strip()
    return seed or topic_fa


def _translate_keywords_to_fa(keywords: list[str]) -> dict:
    """برای فهرست کیوردهای انگلیسی، معادل فارسی طبیعی می‌سازد. dict{en: fa}."""
    kws = [k for k in keywords if k]
    if not kws:
        return {}
    out = llm.ask(
        step="semrush_kw_translate",
        user_content=(
            "برای هر کلیدواژه‌ی انگلیسی زیر، معادل فارسی طبیعی و رایج در جستجو بنویس "
            "(نه ترجمه‌ی تحت‌اللفظی).\n"
            + "\n".join(f"- {k}" for k in kws)
            + '\nفقط JSON: {"map": {"english": "فارسی", ...}}'
        ),
        model_tier="cheap",
        json_output=True,
        max_tokens=800,
    )
    return (out or {}).get("map", {}) or {}


def research_topic(topic_fa: str, limit: int = 12) -> dict:
    """فاز A کاملاً خودکار: موضوع فارسی → seed انگلیسی → کیوردریسرچ SEMrush →
    ساخت معادل فارسی → ذخیره در فایل واسط. dict نهایی را برمی‌گرداند.
    """
    seed = derive_english_seed(topic_fa)
    logger.info(f"seed انگلیسی برای «{topic_fa}»: {seed}")
    data = research_keywords(topic_fa, seed, limit=limit)

    # معادل فارسی برای کیورد اصلی + پشتیبان
    to_translate = [data["primary"]] + list(data.get("secondary", []))
    fa_map = _translate_keywords_to_fa(to_translate)
    data["fa_map"] = fa_map
    data["primary_fa"] = fa_map.get(data["primary"]) or data["primary"]
    semrush_bridge.save_keywords(topic_fa, data)
    logger.info(f"کیورد اصلی فارسی: {data['primary_fa']}")
    return data
