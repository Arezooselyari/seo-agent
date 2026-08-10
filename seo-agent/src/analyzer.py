"""گام ۲ — تحلیل سئوی مقالات رقیب با Haiku و ساخت بریف رقابتی."""
from . import llm

ANALYSIS_PROMPT = """مقاله‌ی زیر را از نظر سئو تحلیل کن و فقط JSON با این ساختار برگردان:
{{
  "primary_keyword": "کلیدواژه‌ی اصلی (انگلیسی)",
  "lsi_keywords": ["کلیدواژه‌های مرتبط معنایی"],
  "search_intent": "informational | comparison | transactional",
  "headings": ["ساختار سرفصل‌های مقاله به ترتیب"],
  "strengths": ["نقاط قوت محتوایی"],
  "gaps": ["خلأهای محتوا — آنچه پوشش نداده"],
  "facts": ["آمار و داده‌های قابل استناد با ذکر مقدار دقیق"]
}}

عنوان: {title}
منبع: {source}

متن مقاله:
{text}"""


def analyze_article(article: dict) -> dict:
    result = llm.ask(
        step="seo_analysis",
        user_content=ANALYSIS_PROMPT.format(
            title=article["title"], source=article["source"], text=article["text"]
        ),
        model_tier="cheap",
        max_tokens=2048,
    )
    result["source_url"] = article["url"]
    result["source_title"] = article["title"]
    return result


def build_brief(topic: str, analyses: list[dict]) -> dict:
    """ادغام تحلیل‌ها در یک بریف رقابتی واحد — کد خالص، بدون LLM."""
    lsi, gaps, facts, headings, sources = set(), [], [], [], []
    source_titles = {}   # {url: عنوانِ واقعی} — برای نمایشِ خوانا در بخشِ «منابع»
    for a in analyses:
        lsi.update(a.get("lsi_keywords", []))
        gaps.extend(a.get("gaps", []))
        facts.extend(a.get("facts", []))
        headings.append({"title": a["source_title"], "headings": a.get("headings", [])})
        sources.append(a["source_url"])
        if a.get("source_title"):
            source_titles[a["source_url"]] = a["source_title"]
    intents = [a.get("search_intent", "informational") for a in analyses]
    return {
        "topic": topic,
        "primary_keywords": [a.get("primary_keyword", "") for a in analyses],
        "lsi_keywords": sorted(lsi),
        "search_intent": max(set(intents), key=intents.count),
        "competitor_headings": headings,
        "content_gaps": gaps,
        "citable_facts": facts,
        "source_urls": sources,
        "source_titles": source_titles,
    }


def analyze(topic: str, articles: list[dict]) -> dict:
    analyses = []
    for art in articles:
        try:
            analyses.append(analyze_article(art))
            print(f"[analyzer] ✓ تحلیل شد: {art['title'][:60]}")
        except Exception as e:
            print(f"[analyzer] ✗ خطا در تحلیل {art['url']}: {e}")
    if not analyses:
        raise RuntimeError("هیچ مقاله‌ای با موفقیت تحلیل نشد")
    brief = build_brief(topic, analyses)

    # خط‌لوله‌ی فکتِ معتبر: آمارِ عددیِ واقعی و منبع‌دار را از متنِ *همان* مقالات
    # استخراج می‌کند تا مقاله غیرعمومی و آمارمحور شود (ضدجعل: فقط آمارِ عیناً موجود در منبع).
    # جایگزینِ facts موقعیتیِ ضعیفِ build_brief؛ در نبودِ فکتِ معتبر، رفتارِ قبلی حفظ می‌شود.
    try:
        from . import fact_research
        fr = fact_research.research_facts(topic, articles)
        if fr["count"]:
            brief["citable_facts"] = fr["citable_facts"]
            brief["verified_facts"] = fr["verified_facts"]      # نگاشتِ دقیقِ claim↔source
            brief["source_urls"] = list(dict.fromkeys(fr["source_urls"] + brief["source_urls"]))
            print(f"[fact_research] ✓ {fr['count']} فکتِ عددیِ معتبر با منبع استخراج شد")
        else:
            print("[fact_research] هیچ آمارِ عددیِ معتبری یافت نشد — مقاله خنثی/کیفی نوشته می‌شود")
    except Exception as e:
        print(f"[fact_research] نادیده گرفته شد (خطا): {e}")

    return brief
