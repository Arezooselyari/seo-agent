"""ارکستراتورِ تولیدِ روزانه — انتخابِ موضوع → زنجیره‌ی تولید → ذخیره‌ی pending.

زنجیره: انتخابِ موضوع → collector.collect (+ گراندینگِ رسمی برای آموزشی) →
analyzer.analyze (+fact_research) → writer.write_article → db.save_article(status=pending).
سپس evaluate_and_sync (زمان‌بندِ جدا) مقاله‌ی pending را ارزیابی و در صورتِ عبور به تلگرام می‌فرستد.

منبعِ موضوع: settings→generation.topic_source:
    rss    — فقط خبری (از فیدهای RSS)
    queue  — فقط آموزشی/معرفیِ ابزار (از config/tool_topics.yaml)
    mixed  — هردو، با نسبتِ هدفِ settings→generation.content_mix (پیش‌فرض: توصیه‌شده)

اجرا (از پوشه‌ی seo-agent):
    python -m src.generate_daily                 # موضوع خودکار طبقِ topic_source
    python -m src.generate_daily "موضوعِ دستی"    # override برای تست (content_type=news)
"""
import json
import logging
import re
import sys

from . import analyzer, collector, db, llm, writer
from .config import load_settings

logger = logging.getLogger(__name__)

_TOPIC_PROMPT = """از میانِ عناوینِ تازه‌ی زیر (فیدهای RSS)، یک «موضوعِ مقاله‌ی وبلاگیِ سئو»
به فارسی انتخاب کن که چند تا از این عناوین به آن مربوط باشند (تا منابعِ کافی برای نگارش پیدا شود).

قوانین:
- موضوع باید مشخص باشد و به حوزه‌ی کسب‌وکار/فناوری/هوش مصنوعیِ کاربردی نزدیک بماند.
- علاوه بر موضوع، یک «کیوردِ اصلی» بده: یک عبارتِ **کوتاهِ ۲ تا ۴ کلمه‌ای** که مردم واقعاً
  در گوگل جستجو می‌کنند (نه جمله‌ی توصیفیِ بلند). مثال: «امنیت هوش مصنوعی»، «چت‌بات فروش».
- فقط JSON برگردان: {{"topic": "موضوعِ فارسی", "keyword": "کیوردِ کوتاهِ قابلِ‌جستجو", "why": "یک جمله دلیل"}}
{avoid}
عناوینِ تازه:
{listing}"""

_AVOID_BLOCK = """
**این کیوردها قبلاً پوشش داده شده‌اند — کیوردِ تازه‌ای بده که با هیچ‌کدام یکی نباشد**
(دو مقاله روی یک کیورد با هم رقابت می‌کنند و رتبه‌ی هر دو را پایین می‌آورند):
{keywords}
"""


def derive_topic_from_rss(candidates: list[dict]) -> dict | None:
    """از عناوینِ تازه‌ی RSS یک {topic, keyword} فارسی می‌سازد (یک تماسِ ارزانِ LLM)."""
    limit = int(load_settings().get("generation", {}).get("max_topic_candidates", 25))
    listing = "\n".join(f"{i}. {c['title']}" for i, c in enumerate(candidates[:limit]) if c.get("title"))
    if not listing.strip():
        return None
    # کیوردهای پوشش‌داده‌شده به پرامپت داده می‌شوند تا انتخابگر سراغشان نرود
    covered = recent_keywords()
    avoid = _AVOID_BLOCK.format(
        keywords="\n".join(f"- {k}" for k in dict.fromkeys(covered))) if covered else ""
    try:
        result = llm.ask(
            step="topic_selection",
            user_content=_TOPIC_PROMPT.format(listing=listing, avoid=avoid),
            model_tier="cheap",
            json_output=True,
            max_tokens=512,
        )
    except Exception as e:
        logger.warning(f"انتخابِ موضوع با LLM نشد ({e}) — fallback به تازه‌ترین عنوان.")
        title = candidates[0].get("title") or None
        return {"topic": title, "keyword": title} if title else None
    topic = (result.get("topic") or "").strip()
    keyword = (result.get("keyword") or "").strip() or topic
    if topic:
        logger.info(f"موضوعِ RSS: «{topic}» | کیورد: «{keyword}» — {result.get('why', '')}")
        return {"topic": topic, "keyword": keyword}
    return None


def _norm_kw(s: str) -> str:
    """نرمال‌سازی برای مقایسه‌ی کیورد: عربی/فارسی، نیم‌فاصله، فاصله‌ی اضافه."""
    s = (s or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def recent_keywords(limit: int = 40) -> list[str]:
    """کیوردِ اصلیِ مقاله‌های اخیر.

    چرا لازم است: انتخابگرِ موضوع هیچ حافظه‌ای ندارد و وقتی خبرهای مشابه
    می‌آیند دوباره همان کیورد را می‌سازد — چهار مقاله روی «چت‌بات هوش مصنوعی
    برای رستوران» و دو مقاله روی «هوش مصنوعی کاربردی» در یک روز، نتیجه‌ی همین
    بود. دو مقاله روی یک کیورد در گوگل با هم رقابت می‌کنند (cannibalization).
    """
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT payload FROM articles ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        payload_json = row[0]
        try:
            tk = json.loads(payload_json).get("target_keywords") or {}
        except Exception:  # noqa: BLE001 — payloadِ خراب نباید انتخابِ موضوع را بکُشد
            continue
        kw = (tk.get("primary_fa") or tk.get("primary") or "").strip()
        if kw:
            out.append(kw)
    return out


def is_duplicate_keyword(keyword: str, limit: int = 40) -> str | None:
    """اگر این کیورد بینِ مقاله‌های اخیر باشد، همان را برمی‌گرداند؛ وگرنه None."""
    target = _norm_kw(keyword)
    if not target:
        return None
    for kw in recent_keywords(limit):
        if _norm_kw(kw) == target:
            return kw
    return None


def _recent_content_types(limit: int = 10) -> list[str]:
    """نوعِ آخرین N مقاله را از DB می‌خواند (برای سنجشِ نسبتِ آموزشی/خبری)."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT payload FROM articles ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    out = []
    for (payload_json,) in rows:
        try:
            d = json.loads(payload_json)
        except Exception:
            out.append("news")
            continue
        ctype = d.get("content_type")
        if not ctype:
            # مقاله‌های قدیمی content_type ندارند (ویراستار آن را از payload می‌انداخت).
            # حدسِ «news» برای همه‌شان سهمِ آموزشی را مصنوعاً پایین نشان می‌داد و
            # انتخابگر را در حلقه‌ی «هر روز آموزش» قفل می‌کرد؛ پس از موضوع تشخیص بده.
            topic = f"{d.get('topic', '')} {d.get('title_seo', '')}"
            ctype = "tutorial" if ("آموزش" in topic or d.get("tool_name")) else "news"
        out.append(ctype)
    return out


def _pick_content_type() -> str:
    """نسبتِ هدف (settings.generation.content_mix) را روی تاریخچه‌ی اخیر می‌سنجد.

    قطعی و خودتنظیم است (نه تصادفی): اگر سهمِ آموزشی از هدف عقب باشد، «tutorial»
    انتخاب می‌شود؛ وگرنه «news». همگرا به نسبتِ هدف بدونِ نیاز به شمارنده‌ی جداگانه.
    """
    gen = load_settings().get("generation", {})
    mix = gen.get("content_mix", {}) or {}
    target_tutorial = float(mix.get("tutorial", 0.3))
    window = int(gen.get("ratio_window", 10))
    recent = _recent_content_types(window)
    if not recent:
        return "tutorial"  # شروع با آموزشی — رشدِ اصلی
    actual_tutorial = recent.count("tutorial") / len(recent)
    return "tutorial" if actual_tutorial < target_tutorial else "news"


def derive_topic_from_tool_queue() -> dict | None:
    """موضوعِ «آموزشی/معرفیِ ابزار» بعدی را از صفِ چرخشیِ config/tool_topics.yaml می‌سازد."""
    from . import tool_queue
    tool = tool_queue.next_tool()
    if not tool:
        logger.warning("صفِ ابزارها خالی است (config/tool_topics.yaml) — به rss برمی‌گردیم.")
        return None
    name = tool["name"]
    return {
        "topic": f"آموزش استفاده از {name}: راهنمای شروع به کار",
        "keyword": tool.get("keyword_seed") or f"آموزش {name}",
        "content_type": "tutorial",
        "tool_name": name,
        "official_url": tool.get("official_url"),
    }


def pick_topic() -> dict | None:
    """منبعِ موضوع را طبقِ settings انتخاب می‌کند. {topic, keyword, content_type, ...}."""
    source = load_settings().get("generation", {}).get("topic_source", "rss")

    def _from_rss() -> dict | None:
        candidates = collector.gather_candidates()
        logger.info(f"{len(candidates)} آیتمِ تازه در RSS.")
        if not candidates:
            logger.warning("هیچ آیتمِ تازه‌ای در RSS نبود.")
            return None
        picked = derive_topic_from_rss(candidates)
        if picked:
            picked["content_type"] = "news"
        return picked

    if source == "rss":
        return _from_rss()
    if source == "queue":
        return derive_topic_from_tool_queue()
    if source == "mixed":
        ctype = _pick_content_type()
        logger.info(f"انتخابِ نوعِ محتوا (طبقِ نسبتِ هدف): «{ctype}»")
        if ctype == "tutorial":
            picked = derive_topic_from_tool_queue()
            return picked or _from_rss()  # صفِ ابزار خالی بود → fallback به خبری
        return _from_rss()
    logger.warning(f"topic_source='{source}' ناشناخته — به rss برمی‌گردیم.")
    return _from_rss()


def _wikipedia_extract(title: str) -> str | None:
    """خلاصه‌ی متنیِ ویکی‌پدیای انگلیسی برای این ابزار (fallback گراندینگِ قابلِ‌اتکا —
    صفحاتِ فرودِ رسمیِ ابزارها اغلب جاوااسکریپتی/کم‌متن‌اند و trafilatura چیزی از آن‌ها
    استخراج نمی‌کند؛ ویکی‌پدیا برای اکثرِ ابزارهای شناخته‌شده مقاله‌ی متنیِ واقعی دارد).
    """
    import requests
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "prop": "extracts", "explaintext": 1,
                    "titles": title, "format": "json", "redirects": 1},
            timeout=15, headers=collector.HEADERS,  # بدونِ UAِ مرورگر، ویکی‌پدیا ۴۰۳/پاسخِ خالی می‌دهد
        )
        pages = (r.json().get("query", {}) or {}).get("pages", {}) or {}
        for p in pages.values():
            extract = (p.get("extract") or "").strip()
            if extract and "may refer to" not in extract[:200]:  # صفحه‌ی ابهام‌زدایی نیست
                return extract
    except Exception as e:
        logger.warning(f"ویکی‌پدیا برای «{title}» نشد: {e}")
    return None


def _collect_for_type(topic: str, content_type: str, official_url: str | None,
                      tool_name: str | None = None) -> list[dict]:
    """منابع را جمع می‌کند. برای «tutorial»، صفحه‌ی رسمیِ ابزار (اگر متنِ کافی داشت) یا
    fallback ویکی‌پدیا هم گراندینگ می‌شود — تضمین می‌کند ابزارهای کم‌پوشش در RSS هم
    منبعِ واقعیِ حداقلی داشته باشند (نه صرفاً وابسته به تطابقِ خبری).
    """
    articles = []
    if content_type == "tutorial" and official_url:
        try:
            text = collector.download_full_text({"url": official_url})
            if text and len(text) > 300:
                articles.append({
                    "source": "صفحه‌ی رسمی",
                    "url": official_url,
                    # عنوانِ خوانا (نه URL) — چون در بخشِ «منابع» نمایش داده می‌شود
                    "title": f"صفحه‌ی رسمی {tool_name or ''}".strip(),
                    "text": text[:15000],
                })
                logger.info(f"صفحه‌ی رسمی گراندینگ شد: {official_url} (~{len(text)} کاراکتر)")
        except Exception as e:
            logger.warning(f"دانلودِ صفحه‌ی رسمی نشد ({official_url}): {e}")
    if content_type == "tutorial" and tool_name and not articles:
        wiki = _wikipedia_extract(tool_name)
        if wiki and len(wiki) > 300:
            articles.append({
                "source": "ویکی‌پدیا",
                "url": f"https://en.wikipedia.org/wiki/{tool_name.replace(' ', '_')}",
                "title": f"{tool_name} در ویکی‌پدیا",
                "text": wiki[:15000],
            })
            logger.info(f"ویکی‌پدیا گراندینگ شد: «{tool_name}» (~{len(wiki)} کاراکتر)")
    try:
        relevance_topic = tool_name if content_type == "tutorial" else None
        articles.extend(collector.collect(topic, relevance_topic=relevance_topic))
    except Exception as e:
        logger.warning(f"جمع‌آوریِ RSS نشد ({e}).")
    return articles


_SHORT_KEYWORD_PROMPT = """از موضوعِ زیر یک «کیوردِ اصلیِ سئو» بساز.

قوانین:
- **۲ تا ۴ کلمه**، همان‌طور که مردم واقعاً در گوگل جستجو می‌کنند.
- جمله‌ی توصیفی نده. نامِ خاص را فقط اگر خودش پرجستجوست نگه دار.
- مثال: از «شکایت سونی موزیک و وارنر از Anthropic بر سر نقض کپی‌رایت» →
  «کپی‌رایت هوش مصنوعی».

فقط JSON برگردان: {{"keyword": "کیوردِ کوتاه"}}

موضوع: {topic}"""


def derive_keyword_from_topic(topic: str) -> str:
    """کیوردِ کوتاهِ قابلِ‌جستجو از یک موضوعِ توصیفی.

    چرا لازم است: `keyword_free.research_topic` هرچه را seed بگیرد عیناً
    primary می‌کند. اگر موضوعِ بلند مستقیم seed شود، کیورد یک جمله‌ی ۱۵ کلمه‌ای
    می‌شود و چک‌لیستِ سئو سه قانون را رد می‌کند (کیورد در H2، در جمع‌بندی، و
    پوششِ LSI) — چون هیچ H2ای یک جمله‌ی کامل را در خود ندارد.
    """
    topic = (topic or "").strip()
    words = [w for w in topic.split() if w]
    if len(words) <= 4:
        return topic                      # از قبل کوتاه است
    try:
        result = llm.ask(
            step="keyword_shorten",
            user_content=_SHORT_KEYWORD_PROMPT.format(topic=topic),
            model_tier="cheap", json_output=True, max_tokens=128,
        )
        kw = (result.get("keyword") or "").strip()
        if kw and len(kw.split()) <= 6:
            logger.info(f"کیوردِ کوتاه‌شده: «{topic}» → «{kw}»")
            return kw
    except Exception as e:  # noqa: BLE001 — نبودِ کیوردِ خوب نباید تولید را بکُشد
        logger.warning(f"کوتاه‌سازیِ کیورد نشد ({e}) — به سه کلمه‌ی نخست برمی‌گردیم.")
    # fallback قطعی: سه کلمه‌ی محتواییِ نخست
    sig = [w for w in words if len(w) > 1][:3]
    return " ".join(sig) or topic


def generate_one(topic: str | None = None, keyword: str | None = None) -> int | None:
    """یک مقاله را تولید و به‌عنوان pending ذخیره می‌کند. Returns article_id یا None."""
    content_type, tool_name, official_url = "news", None, None
    if topic is None:
        picked = pick_topic()
        if not picked:
            return None
        topic, keyword = picked["topic"], picked.get("keyword")
        content_type = picked.get("content_type", "news")
        tool_name = picked.get("tool_name")
        official_url = picked.get("official_url")
    # موضوعِ دستی معمولاً کیورد ندارد؛ کلِ جمله را کیورد نکن (باگِ مقاله‌ی #۵۱)
    keyword = keyword or derive_keyword_from_topic(topic)

    # تورِ ایمنی: پرامپت به انتخابگر می‌گوید سراغِ کیوردهای پوشش‌داده‌شده نرود،
    # ولی مدل گاهی نادیده می‌گیرد. مقاله‌ی دومِ یک کیورد در گوگل با اولی رقابت
    # می‌کند و رتبه‌ی هر دو را پایین می‌آورد؛ پس تولید نکردن بهتر از تولیدِ رقیب است.
    dup = is_duplicate_keyword(keyword)
    if dup:
        logger.warning(
            f"⛔ کیوردِ «{keyword}» قبلاً پوشش داده شده («{dup}») — تولید انجام نشد "
            "تا دو مقاله روی یک کیورد با هم رقابت نکنند.")
        return None

    logger.info(f"شروعِ تولید برای موضوع: «{topic}» (کیورد: «{keyword}»، نوع: «{content_type}»)")

    articles = _collect_for_type(topic, content_type, official_url, tool_name)
    if not articles:
        logger.warning("هیچ منبعی با متنِ قابلِ‌استخراج جمع نشد — تولید لغو شد.")
        return None

    brief = analyzer.analyze(topic, articles)
    # کیوردِ رایگان با seedِ تمیزِ LLM (نه موضوعِ توصیفیِ بلند)
    keywords = None
    try:
        from . import keyword_free
        keywords = keyword_free.research_topic(topic, seed=keyword)
    except Exception as e:
        logger.warning(f"کیوردِ رایگان نشد ({e}) — نویسنده خودش کیورد را برمی‌دارد.")
    payload = writer.write_article(brief, keywords=keywords, content_type=content_type)

    # تضمینِ حداقل ۲ لینکِ داخلی (به نوشته‌های واقعیِ سایت) — قبل از «منابع» تا ترتیبِ
    # انتهای مقاله این باشد: نثر → مطالب مرتبط → منابع
    try:
        from . import internal_links
        payload = internal_links.ensure_min_internal_links(payload, minimum=2)
    except Exception as e:
        logger.warning(f"تضمینِ لینکِ داخلی نشد ({e}).")

    # بخشِ «منابع» — لینک به منابعِ واقعیِ جمع‌آوری‌شده (E-E-A-T)
    try:
        from . import references
        payload = references.add_references_to_payload(payload)
    except Exception as e:
        logger.warning(f"افزودنِ منابع نشد ({e}) — مقاله بدونِ بخشِ منابع ادامه می‌یابد.")

    # تصاویرِ استوکِ رایگان (شاخص + inline) — قبل از ذخیره تا در تلگرام هم دیده شوند
    try:
        from . import images
        payload = images.add_images_to_payload(payload, inline=1)
    except Exception as e:
        logger.warning(f"افزودنِ تصاویر نشد ({e}) — مقاله بدونِ تصویر ادامه می‌یابد.")

    conn = db.connect()
    try:
        aid = db.save_article(conn, topic, payload)
    finally:
        conn.close()
    logger.info(f"✅ مقاله‌ی #{aid} به‌عنوان pending ذخیره شد: «{payload.get('title_seo')}»")

    if tool_name:  # فقط بعد از ذخیره‌ی موفق — نوبتِ ابزارهای بعدی برسد
        try:
            from . import tool_queue
            tool_queue.mark_used(tool_name)
        except Exception as e:
            logger.warning(f"علامت‌زدنِ استفاده‌ی ابزار نشد ({e}).")

    return aid


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    topic = sys.argv[1] if len(sys.argv) > 1 else None
    aid = generate_one(topic)
    if aid is None:
        logger.warning("تولیدِ روزانه نتیجه‌ای نداشت.")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
