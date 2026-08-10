"""تست‌های آفلاین — بدون شبکه و بدون کلید API قابل اجرا هستند.

اجرا: python -m tests.test_offline
"""
from src.internal_links import _xml_locs, _slug_to_title, _tokens
from src.research import ResearchBrief
from src.generate import GeneratedArticle, _build_prompt
from src.rank import _build_prompt as rank_prompt


def test_sitemap_parse():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://x.com/ai-business-guide/</loc></url>"
        "<url><loc>https://x.com/sub.xml</loc></url>"
        "</urlset>"
    )
    locs = _xml_locs(xml)
    assert locs == ["https://x.com/ai-business-guide/", "https://x.com/sub.xml"], locs
    assert _slug_to_title("https://x.com/ai-business-guide/") == "ai business guide"
    assert "business" in _tokens("AI business guide")
    # تطبیق توکن فارسی
    assert "کسب" in _tokens("هوش مصنوعی برای کسب و کار")


def test_research_brief_text():
    b = ResearchBrief(
        summary="خلاصه",
        key_points=["نکته۱"],
        claims=[{"claim": "ادعا", "quote": "quote text"}],
        angles=["زاویه"],
        hallucination_risks=["ریسک"],
    )
    t = b.to_prompt_text()
    assert "نکته۱" in t and "quote text" in t and "ریسک" in t
    return b


def test_article_html_and_prompt(brief):
    art = GeneratedArticle(
        title="عنوان",
        intro="مقدمه.",
        sections=[{"h2": "پرسش؟", "answer": "پاسخ.",
                   "body": 'متن <a href="https://x.com/p">لینک داخلی</a>'}],
        conclusion="جمع‌بندی",
        meta_description="متا",
        slug="test-slug",
        tags=["برچسب"],
        faq=[{"q": "س۱", "a": "ج۱"}],
        internal_links_used=["https://x.com/p"],
        source_url="https://src.com",
        source_name="Src",
    )
    html = art.to_html()
    assert "<h2>پرسش؟</h2>" in html
    assert "FAQPage" in html
    assert "https://src.com" in html
    assert 'href="https://x.com/p"' in html

    p = _build_prompt(
        brief=brief, source_name="Src", source_url="u", original_title="ot",
        topic_reason="tr", internal_links=[{"url": "https://x.com/p", "title": "p"}],
    )
    for ph in ("{source_name}", "{source_url}", "{original_title}",
               "{topic_reason}", "{internal_links}", "{research_brief}"):
        assert ph not in p, f"placeholder جایگزین نشده: {ph}"
    assert "https://x.com/p" in p


def test_rank_prompt():
    rp = rank_prompt([{"id": 1, "source": "S", "title": "T", "summary": "sum"}])
    assert "id=1" in rp and "{candidates}" not in rp


if __name__ == "__main__":
    test_sitemap_parse()
    b = test_research_brief_text()
    test_article_html_and_prompt(b)
    test_rank_prompt()
    print("✅ همه‌ی تست‌های آفلاین پاس شدند.")
