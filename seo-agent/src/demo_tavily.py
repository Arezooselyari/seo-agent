"""گراندینگِ عمومی برای دموی کلاینت — جست‌وجوی وب با Tavily.

چرا این ماژول لازم است: منابعِ RSS پروژه (`config/sources.yaml`) همگی
AI/tech هستند. دموی کلاینت باید هر حوزه‌ای (پزشکی، حقوقی، املاک، زیبایی...) را
پوشش بدهد، پس `collector.collect` جواب نمی‌دهد و منبعی برنمی‌گرداند.

Tavily برای هر موضوعی منابعِ واقعی با متنِ کامل برمی‌گرداند. خروجی این ماژول
عمداً همان شکلِ دیکشنری‌ای است که `analyzer.analyze_article` می‌خواهد
(`{title, source, text, url}`)، تا بدونِ هیچ تغییری در تحلیل‌گر جا بیفتد.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from .config import env

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.tavily.com/search"

# متنِ کمتر از این مقدار برای تحلیلِ سئو بی‌فایده است (اغلب صفحه‌ی خالی/جاوااسکریپتی)
_MIN_TEXT = 400
# سقفِ متنِ هر منبع — هم‌تراز با `generate_daily._collect_for_type`
_MAX_TEXT = 15000


def _source_name(url: str) -> str:
    """نامِ خوانای دامنه برای نمایش در بخشِ «منابع»."""
    host = (urlparse(url).hostname or "").replace("www.", "")
    return host or "منبع وب"


def search(query: str, max_results: int = 4) -> list[dict]:
    """منابعِ واقعیِ وب برای این موضوع. خروجی: [{source, url, title, text}].

    خطا را بالا نمی‌دهد؛ در صورت مشکل لیست خالی برمی‌گرداند تا فراخوان بتواند
    پیامِ روشن به کاربر بدهد.
    """
    key = (env("TAVILY_API_KEY") or "").strip()
    if not key:
        logger.warning("TAVILY_API_KEY تنظیم نشده — گراندینگ ممکن نیست.")
        return []

    try:
        resp = requests.post(
            _ENDPOINT,
            json={
                "api_key": key,
                "query": query,
                # advanced متنِ کامل‌تری برمی‌گرداند — برای تحلیلِ سئو لازم است
                "search_depth": "advanced",
                "include_raw_content": True,
                # چند نتیجه‌ی اضافه می‌گیریم چون بعضی‌شان متنِ کافی ندارند
                "max_results": max_results + 3,
            },
            timeout=90,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"جست‌وجوی Tavily نشد ({query[:40]}): {e}")
        return []

    out: list[dict] = []
    for item in results:
        # raw_content متنِ کاملِ صفحه است؛ content فقط خلاصه‌ی Tavily.
        text = (item.get("raw_content") or item.get("content") or "").strip()
        url = item.get("url") or ""
        if len(text) < _MIN_TEXT or not url:
            continue
        out.append({
            "source": _source_name(url),
            "url": url,
            "title": (item.get("title") or _source_name(url)).strip(),
            "text": text[:_MAX_TEXT],
        })
        if len(out) >= max_results:
            break

    logger.info(f"Tavily: {len(out)} منبع با متنِ کافی برای «{query[:40]}»")
    return out
