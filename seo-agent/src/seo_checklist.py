"""چک‌لیستِ عینیِ عواملِ رتبه‌ی گوگل (On-Page SEO) — قطعی و بدونِ LLM.

فلسفه (مصوب کاربر): «از گوگل سخت‌گیرتر نباش؛ فقط عواملی را که واقعاً به رتبه کمک
می‌کنند بررسی کن.» گوگل نمره/آستانه ندارد؛ این ماژول فقط عواملِ *داخلِ صفحه* را که یک
ایجنتِ محتوا می‌تواند کنترل کند به‌صورتِ هست/نیست می‌سنجد و یک نمره‌ی ۰-۱۰۰ می‌دهد.

عواملِ *خارجِ صفحه* (بک‌لینک، اعتبارِ دامنه، سرعتِ سایت) عمداً اینجا نیستند — کارِ مقاله
نیستند و مقاله نباید به‌خاطرشان جریمه شود.

خروجی: {"seo_score": float, "factors": {name: {passed, weight, detail}},
        "critical_misses": [...], "passed_factors": int, "total_factors": int}
هیچ فراخوانی LLM و هیچ I/O — فقط محاسبه روی payload.
"""
import re

# ارقام فارسی/عربی → لاتین برای شمارش/تطبیق یکنواخت
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# stopwordهای فارسیِ پرتکرار — از تطبیقِ کیورد کنار گذاشته می‌شوند (وزن معنایی ندارند)
_STOP = frozenset("و در به از با برای که را این آن یک های ها یا تا هم بر می را".split())

# عواملی که نبودشان «شکستِ بحرانی» است (بیشترین اثر بر رتبه)
_CRITICAL = frozenset({"keyword_in_title", "keyword_in_h1", "keyword_in_first_100",
                       "meta_optimized", "word_count_adequate"})


def _norm(s: str) -> str:
    s = (s or "").translate(_DIGIT_MAP)
    s = s.replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"[\s‌]+", " ", s).strip()


def _strip_html(s: str) -> str:
    s = re.sub(r"\[\[(?:anchor|external):[^\]]*\]\]", " ", s or "")  # نشانگرهای لینک
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _kw_tokens(keyword: str) -> list[str]:
    toks = [t for t in re.split(r"\s+", _norm(keyword)) if t and t not in _STOP and len(t) > 1]
    return toks


def _kw_hit(region: str, keyword: str, ratio: float = 0.6) -> bool:
    """کیورد در ناحیه هست؟ عبارتِ کامل، یا حداقل ratioِ کلماتِ محتواییِ کیورد."""
    region_n = _norm(region)
    kw_n = _norm(keyword)
    if not kw_n:
        return False
    if kw_n in region_n:
        return True
    toks = _kw_tokens(keyword)
    if not toks:
        return False
    hits = sum(1 for t in toks if t in region_n)
    return hits / len(toks) >= ratio


def _primary_keyword(payload: dict) -> str:
    kw = payload.get("target_keywords") or {}
    return (kw.get("primary_fa") or kw.get("primary")
            or (payload.get("topic") or "") or payload.get("h1", ""))


def _secondary_keywords(payload: dict) -> list[str]:
    kw = payload.get("target_keywords") or {}
    out = list(kw.get("secondary") or [])
    fa_map = kw.get("fa_map") or {}
    out += [fa_map.get(s, s) for s in (kw.get("secondary") or [])]
    out += list(payload.get("lsi_keywords") or [])
    return [s for s in out if s]


def score(payload: dict) -> dict:
    """نمره‌ی عواملِ داخلِ صفحه‌ی گوگل را می‌سنجد. تابعِ خالص."""
    title = payload.get("title_seo") or ""
    h1 = payload.get("h1") or title
    meta = payload.get("meta_description") or ""
    body_raw = payload.get("body_html") or payload.get("body_markdown") or ""
    text = _strip_html(body_raw)
    words = text.split()
    wc = len(words)
    first_100 = " ".join(words[:100])
    conclusion = " ".join(words[-150:])
    # سرفصل‌ها — سازگار با HTML (<h2>) و Markdown (## ...) هر دو
    h2s = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<h2[^>]*>(.*?)</h2>", body_raw, re.DOTALL)]
    h3s = re.findall(r"<h3[^>]*>(.*?)</h3>", body_raw, re.DOTALL)
    if not h2s:
        h2s = [m.strip() for m in re.findall(r"(?m)^\s*##(?!#)\s*(.+?)\s*$", body_raw)]
    if not h3s:
        h3s = [m.strip() for m in re.findall(r"(?m)^\s*###\s*(.+?)\s*$", body_raw)]
    paras = [_strip_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body_raw, re.DOTALL)]
    paras = [p for p in paras if p]
    if not paras:  # Markdown/متنِ ساده: پاراگراف = بلوکِ متنی بین خطوطِ خالی، بدونِ خطِ سرفصل
        paras = [_strip_html(b).strip() for b in re.split(r"\n\s*\n", body_raw)
                 if b.strip() and not b.lstrip().startswith("#")]
        paras = [p for p in paras if p]

    primary = _primary_keyword(payload)
    secondary = _secondary_keywords(payload)

    internal_links = len(re.findall(r"\[\[anchor:", body_raw))
    external_links = len(re.findall(r"\[\[external:", body_raw))
    facts = payload.get("verified_facts") or payload.get("citable_facts") or []

    # چگالیِ کیوردِ اصلی (برای تشخیص keyword stuffing)
    kw_toks = _kw_tokens(primary)
    text_n = _norm(text)
    density = 0.0
    if kw_toks and wc:
        # شمارشِ رخدادِ توکنِ اصلی‌ترین کلمه‌ی کیورد
        main_tok = max(kw_toks, key=len)
        occur = len(re.findall(re.escape(main_tok), text_n))
        density = occur / max(wc, 1)

    # اسکن‌پذیری: بیشترِ پاراگراف‌ها نباید خیلی بلند باشند (<~۹۰ کلمه)
    long_paras = sum(1 for p in paras if len(p.split()) > 90)
    scannable = bool(paras) and (long_paras / len(paras)) <= 0.25

    # پوششِ LSI: چند درصدِ کیوردهای پشتیبان در متن آمده‌اند
    lsi_hit = sum(1 for s in secondary if _kw_hit(text, s, ratio=0.7))
    lsi_ok = (not secondary) or (lsi_hit / max(len(secondary), 1) >= 0.3)

    # جمله‌ی پایانی کامل — بخشِ «منابع» (لیستِ ساخت‌یافته، نه نثر) از سنجش کنار می‌رود
    from .references import strip_references
    _prose = strip_references(body_raw)
    tail = re.sub(r"(?:<[^>]+>|\s)+$", "", re.sub(r"\[\[[^\]]*\]\]", "", _prose)).rstrip("]})*_>#- \n\t«»\"'")
    complete_sentence = bool(tail) and tail[-1] in ".!?۔؟:،"

    # ── تعریفِ عوامل: (نام, passed, وزن, توضیح) ──
    F = []

    def add(name, passed, weight, detail=""):
        F.append((name, bool(passed), weight, detail))

    add("keyword_in_title", _kw_hit(title, primary), 10, f"عنوان: {title[:40]}")
    add("keyword_in_h1", _kw_hit(h1, primary), 8)
    add("keyword_in_first_100", _kw_hit(first_100, primary), 8)
    add("keyword_in_h2", any(_kw_hit(h, primary) for h in h2s), 6, f"{len(h2s)} H2")
    add("keyword_in_conclusion", _kw_hit(conclusion, primary), 5)
    add("title_length", 20 <= len(title) <= 60, 5, f"{len(title)} کاراکتر")
    add("meta_optimized", 120 <= len(meta) <= 170 and _kw_hit(meta, primary), 7, f"{len(meta)} کاراکتر")
    add("heading_structure", len(h2s) >= 3, 7, f"{len(h2s)} H2 / {len(h3s)} H3")
    add("faq_present", len(h3s) >= 3, 6, f"{len(h3s)} H3")
    add("word_count_adequate", wc >= 700, 6, f"{wc} کلمه")
    add("internal_links", internal_links >= 2, 5, f"{internal_links} لینک داخلی")
    add("external_citation", external_links >= 1, 5, f"{external_links} لینک خارجی")
    add("data_citations_eeat", len(facts) >= 1, 8, f"{len(facts)} فکت/منبع")
    add("scannability", scannable, 5, f"{long_paras} پاراگرافِ بلند از {len(paras)}")
    add("lsi_coverage", lsi_ok, 5, f"{lsi_hit}/{len(secondary)} کیوردِ پشتیبان")
    add("no_keyword_stuffing", density < 0.035, 4, f"چگالی≈{density:.1%}")
    add("complete_last_sentence", complete_sentence, 3)
    add("image_keywords", bool(payload.get("image_keywords")), 2)

    total_w = sum(w for _, _, w, _ in F)
    got_w = sum(w for _, p, w, _ in F if p)
    seo_score = round(100.0 * got_w / total_w, 1) if total_w else 0.0

    factors = {n: {"passed": p, "weight": w, "detail": d} for n, p, w, d in F}
    critical_misses = [n for n, p, _, _ in F if n in _CRITICAL and not p]

    return {
        "seo_score": seo_score,
        "factors": factors,
        "critical_misses": critical_misses,
        "passed_factors": sum(1 for _, p, _, _ in F if p),
        "total_factors": len(F),
        "primary_keyword": primary,
    }


def evaluate(payload: dict, min_score: float = 75.0) -> dict:
    """score + تصمیمِ pass. passed یعنی: نمره ≥ آستانه و هیچ شکستِ بحرانی نباشد."""
    r = score(payload)
    r["passed"] = r["seo_score"] >= min_score and not r["critical_misses"]
    r["min_score"] = min_score
    return r
