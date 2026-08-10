"""کاشفِ خودکارِ ابزارهای جدیدِ هوش مصنوعی → افزودن به صفِ `config/tool_topics.yaml`.

چرا: صفِ ابزارها دستی بود و «ابزارهای جدید» را کشف نمی‌کرد. این ماژول هر بار چند
منبعِ کشف را می‌خواند، نام‌های ابزارِ تازه را درمی‌آورد، تکراری‌ها را حذف می‌کند و
ابزارهای جدید را به انتهای صف می‌افزاید (تا در چرخشِ tool_queue نوبتشان برسد).

منابعِ کشف (به ترتیبِ اولویت؛ هر کدام در دسترس بود استفاده می‌شود):
  1. Tavily Search API — کلید `TAVILY_API_KEY` (رایگان تا سقفِ ماهانه)
  2. SerpAPI          — کلید `SERPAPI_API_KEY`
  3. Hacker News (Algolia) — بدونِ کلید، همیشه در دسترس (fallback پیش‌فرض)

اجرا (از پوشه‌ی seo-agent):
    python -m src.tool_discovery            # کشف و افزودن به صف
    python -m src.tool_discovery --dry-run  # فقط نمایش، بدونِ تغییرِ فایل
"""
import logging
import re

import requests

from . import llm, tool_queue
from .config import env

logger = logging.getLogger(__name__)

_QUERIES = [
    "new AI tools launched this week",
    "best new AI tools for productivity",
    "new AI app release",
]

# نام‌هایی که ابزار نیستند (شرکت/مفهومِ عمومی) — از نتایج کنار می‌روند
_NOT_A_TOOL = {
    "ai", "artificial intelligence", "openai", "google", "microsoft", "meta",
    "anthropic", "nvidia", "apple", "amazon", "startup", "llm", "gpt", "api",
    "chatbot", "machine learning", "the verge", "techcrunch", "product hunt",
}


def _tavily(query: str, max_results: int = 10) -> list[dict]:
    """جستجوی Tavily — خروجی: [{title, url, content}]."""
    key = (env("TAVILY_API_KEY") or "").strip()
    if not key:
        return []
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": max_results,
                  "search_depth": "basic", "topic": "news", "days": 30},
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"tool_discovery: Tavily {r.status_code} — {r.text[:120]}")
            return []
        return [{"title": x.get("title", ""), "url": x.get("url", ""),
                 "content": (x.get("content") or "")[:400]}
                for x in r.json().get("results", [])]
    except Exception as e:
        logger.warning(f"tool_discovery: Tavily نشد ({e}).")
        return []


def _serpapi(query: str, max_results: int = 10) -> list[dict]:
    """جستجوی SerpAPI (گوگل) — خروجی هم‌شکلِ Tavily."""
    key = (env("SERPAPI_API_KEY") or env("SERP_API_KEY") or "").strip()
    if not key:
        return []
    try:
        r = requests.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": key, "engine": "google",
                    "num": max_results, "tbs": "qdr:m"},
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"tool_discovery: SerpAPI {r.status_code}")
            return []
        return [{"title": x.get("title", ""), "url": x.get("link", ""),
                 "content": (x.get("snippet") or "")[:400]}
                for x in r.json().get("organic_results", [])]
    except Exception as e:
        logger.warning(f"tool_discovery: SerpAPI نشد ({e}).")
        return []


def _hackernews(query: str, max_results: int = 15) -> list[dict]:
    """Hacker News (Algolia) — بدونِ کلید؛ fallback همیشه‌در‌دسترس برای «Show HN» ابزارها."""
    try:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": query, "tags": "story", "hitsPerPage": max_results},
            timeout=25,
        )
        if r.status_code != 200:
            return []
        return [{"title": h.get("title") or "", "url": h.get("url") or "",
                 "content": (h.get("story_text") or "")[:400]}
                for h in r.json().get("hits", []) if h.get("title")]
    except Exception as e:
        logger.warning(f"tool_discovery: Hacker News نشد ({e}).")
        return []


def gather_results() -> list[dict]:
    """نتایجِ کشف را از بهترین منبعِ در دسترس جمع می‌کند."""
    results = []
    for q in _QUERIES:
        batch = _tavily(q) or _serpapi(q) or _hackernews(q)
        results.extend(batch)
    # حذفِ تکراری بر اساسِ URL
    seen, out = set(), []
    for r in results:
        u = r.get("url") or ""
        if u and u not in seen:
            seen.add(u)
            out.append(r)
    return out


_EXTRACT_PROMPT = """از نتایجِ جستجوی زیر، نامِ **ابزارهای هوش مصنوعیِ واقعی و قابلِ‌استفاده**
را استخراج کن (محصولاتی که یک کاربر می‌تواند برود و با آن‌ها کار کند).

قوانین:
- فقط نامِ محصول/ابزار — نه نامِ شرکت، نه مفهومِ عمومی، نه عنوانِ خبر.
- ابزارهایی که واقعاً وجود دارند و در متن معرفی شده‌اند. چیزی از خودت اضافه نکن.
- برای هر ابزار، اگر آدرسِ رسمی در متن هست بیاور؛ اگر نیست، فیلد را خالی بگذار.
- حداکثر ۱۲ مورد.

فقط JSON برگردان:
{{"tools": [{{"name": "نامِ ابزار", "official_url": "https://... یا رشته‌ی خالی", "what": "یک جمله: چه کاری می‌کند"}}]}}

نتایجِ جستجو:
{listing}"""


def extract_tools(results: list[dict]) -> list[dict]:
    """با یک تماسِ ارزانِ LLM، نامِ ابزارهای واقعی را از نتایج بیرون می‌کشد."""
    if not results:
        return []
    listing = "\n".join(
        f"- {r['title']} | {r.get('url','')} | {r.get('content','')[:200]}"
        for r in results[:40]
    )
    try:
        out = llm.ask(
            step="tool_discovery",
            user_content=_EXTRACT_PROMPT.format(listing=listing),
            model_tier="cheap", json_output=True, max_tokens=2048,
        )
    except Exception as e:
        logger.warning(f"tool_discovery: استخراجِ LLM نشد ({e}).")
        return []
    tools = out.get("tools") if isinstance(out, dict) else out
    clean = []
    for t in tools or []:
        name = (t.get("name") or "").strip()
        if not name or name.lower() in _NOT_A_TOOL or len(name) > 40:
            continue
        if not re.search(r"[A-Za-z؀-ۿ]", name):
            continue
        clean.append({
            "name": name,
            "official_url": (t.get("official_url") or "").strip(),
            "what": (t.get("what") or "").strip(),
        })
    return clean


def has_search_demand(name: str, min_hits: int = 2) -> bool:
    """آیا مردم واقعاً **این ابزار** را جستجو می‌کنند؟ (فیلترِ کیفیتِ رایگان)

    منابعِ کشف (به‌ویژه Show HN) پر از ابزارهای گمنام‌اند که هیچ تقاضای جستجویی
    ندارند؛ مقاله درباره‌شان ترافیک نمی‌آورد.

    نکته‌ی کلیدی: نامِ خام را نمی‌سنجیم — نام‌های عمومی («Klaus»، «Multiplayer») به‌خاطرِ
    معنای دیگرشان پیشنهاد می‌گیرند و فیلتر را دور می‌زنند. پس نام را در **بافتِ ابزار**
    می‌سنجیم و فقط پیشنهادهایی را می‌شماریم که واقعاً شاملِ نامِ ابزار باشند.
    """
    try:
        from .keyword_free import _suggest
        low = name.lower()
        hits = 0
        probes = [(f"{name} ai", "en", "us"), (f"{name} app", "en", "us"),
                  (f"آموزش {name}", "fa", "ir"), (f"{name} چیست", "fa", "ir")]
        for q, hl, gl in probes:
            for s in _suggest(q, hl=hl, gl=gl):
                if low in s.lower():      # پیشنهاد واقعاً درباره‌ی همین ابزار است
                    hits += 1
        logger.info(f"tool_discovery: «{name}» → {hits} پیشنهادِ مرتبط")
        return hits >= min_hits
    except Exception as e:
        logger.warning(f"tool_discovery: سنجشِ تقاضای «{name}» نشد ({e}) — رد می‌شود.")
        return False


def discover(dry_run: bool = False, check_demand: bool = True) -> list[dict]:
    """کشف → فیلترِ تکراری → فیلترِ تقاضای جستجو → افزودن به صف.

    فهرستِ ابزارهای **جدیدِ دارای تقاضا** را برمی‌گرداند.
    """
    results = gather_results()
    logger.info(f"tool_discovery: {len(results)} نتیجه‌ی جستجو جمع شد.")
    found = extract_tools(results)
    logger.info(f"tool_discovery: {len(found)} ابزار از نتایج استخراج شد.")

    existing = {(t.get("name") or "").strip().lower()
                for t in (tool_queue._load().get("tools") or [])}
    new = [t for t in found if t["name"].lower() not in existing]

    if new and check_demand:
        before = len(new)
        new = [t for t in new if has_search_demand(t["name"])]
        logger.info(f"tool_discovery: فیلترِ تقاضا — {len(new)} از {before} ابزار "
                    f"تقاضای جستجوی واقعی دارند.")

    if not new:
        logger.info("tool_discovery: ابزارِ جدیدِ دارای تقاضا نبود.")
        return []

    if dry_run:
        return new

    data = tool_queue._load()
    data.setdefault("tools", [])
    for t in new:
        data["tools"].append({
            "name": t["name"],
            "keyword_seed": f"آموزش {t['name']}",
            "official_url": t["official_url"] or "",
            "usage_count": 0,
            "discovered": True,     # نشانه‌ی اینکه خودکار کشف شده (نه دستی)
        })
    tool_queue._save(data)
    logger.info(f"tool_discovery: ✅ {len(new)} ابزارِ جدید به صف افزوده شد: "
                + "، ".join(t["name"] for t in new))
    return new


def main() -> None:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry = "--dry-run" in sys.argv
    new = discover(dry_run=dry)
    if not new:
        print("ابزارِ جدیدی پیدا نشد.")
        return
    for t in new:
        print(f"  + {t['name']} — {t.get('what','')[:70]} {t.get('official_url','')}")
    if dry:
        print("\n(dry-run — چیزی به صف اضافه نشد)")


if __name__ == "__main__":
    main()
