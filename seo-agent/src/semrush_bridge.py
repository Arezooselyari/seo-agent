"""پل بین SEMrush (کانکتور MCP، دست Claude) و کد پایتون.

نکته‌ی معماری: SEMrush یک تول MCP است و فقط وقتی Claude در جلسه حاضر است در
دسترس است. کد پایتونِ standalone نمی‌تواند مستقیماً SEMrush را صدا بزند. پس:

    Claude تماس SEMrush را می‌زند  →  نتیجه را اینجا در فایل JSON می‌ریزد
    کد پایتون (writer / evaluator)  →  همان فایل را می‌خواند

این ماژول فقط I/O فایل است؛ هیچ تماس شبکه‌ای/SEMrush ندارد.

فایل‌های واسط در DATA_DIR:
- semrush_keywords.json           → کیوردهای هدفِ همه‌ی موضوع‌ها (dict: topic → data)
- semrush_analysis_<article_id>.json → تحلیل سئوی SEMrush برای یک مقاله‌ی مشخص
"""
import json
from pathlib import Path

from .config import DATA_DIR

_KEYWORDS_FILE = DATA_DIR / "semrush_keywords.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── کیوردهای هدف (فاز A — قبل از تولید) ──────────────────────────

def save_keywords(topic: str, data: dict) -> None:
    """کیوردهای انتخاب‌شده‌ی یک موضوع را ذخیره می‌کند (Claude بعد از SEMrush صدا می‌زند).

    ساختار پیشنهادی data:
        {
          "primary": "AI automation",
          "primary_fa": "اتوماسیون هوش مصنوعی",
          "secondary": ["...", "..."],
          "longtail": ["how to ...?", "..."],
          "per_kw": {"AI automation": {"volume": 12000, "kd": 34, "cpc": 3.1}},
          "fa_map": {"AI automation": "اتوماسیون هوش مصنوعی"},
          "market": "us",
          "note": "کیوردها از دیتابیس انگلیسی SEMrush؛ معادل فارسی دستی."
        }
    """
    all_kw = _read_json(_KEYWORDS_FILE)
    all_kw[topic] = data
    _write_json(_KEYWORDS_FILE, all_kw)


def load_keywords(topic: str) -> dict | None:
    """کیوردهای هدف یک موضوع را برمی‌گرداند، یا None اگر هنوز ساخته نشده."""
    all_kw = _read_json(_KEYWORDS_FILE)
    return all_kw.get(topic)


def keywords_prompt_block(data: dict | None) -> str:
    """کیوردها را به یک بلوک متنی برای تزریق در پرامپت نویسنده تبدیل می‌کند."""
    if not data:
        return "کیورد هدف مشخصی تعیین نشده؛ کیورد اصلی را خودت از موضوع استخراج کن."

    primary = data.get("primary_fa") or data.get("primary", "")
    secondary = data.get("secondary", []) or []
    longtail = data.get("longtail", []) or []
    fa_map = data.get("fa_map", {}) or {}
    sec_fa = [fa_map.get(s, s) for s in secondary]

    lines = [
        f"- کیورد اصلی (باید در H1، ۱۰۰ کلمه‌ی اول، حداقل یک H2 و جمع‌بندی بیاید): «{primary}»",
    ]
    if sec_fa:
        lines.append("- کیوردهای پشتیبان (طبیعی در متن پخش شوند): " + "، ".join(f"«{s}»" for s in sec_fa))
    if longtail:
        lines.append("- سوال‌های long-tail (برای H2/FAQ استفاده شوند): " + "؛ ".join(longtail))
    return "\n".join(lines)


# ── تحلیل سئوی مقاله (فاز C — بعد از تولید) ──────────────────────

def _analysis_path(article_id: int) -> Path:
    return DATA_DIR / f"semrush_analysis_{article_id}.json"


def save_analysis(article_id: int, report: dict) -> None:
    """گزارش تحلیل SEMrush یک مقاله را ذخیره می‌کند (Claude بعد از SEMrush صدا می‌زند).

    ساختار پیشنهادی report:
        {
          "targeted_keywords": ["..."],
          "per_kw": {"kw": {"volume": .., "kd": .., "competition": ..}},
          "avg_kd": 38,
          "opportunities": ["کیوردهای کم‌رقابتی که مقاله جا انداخته"],
          "verdict": "GOOD | WEAK",
          "notes": "..."
        }
    """
    _write_json(_analysis_path(article_id), report)


def load_analysis(article_id: int) -> dict | None:
    """گزارش تحلیل SEMrush یک مقاله را برمی‌گرداند، یا None."""
    path = _analysis_path(article_id)
    if not path.exists():
        return None
    return _read_json(path)
