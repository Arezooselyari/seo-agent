"""مرحله ۶ — Persian Writer: نوشتن مقاله‌ی فارسی از روی Research Brief. [LLM ۳]

دستورالعمل SEO/GEO و استراتژی محتوای فارسی، بخش ثابت prompt هستند —
ایجنت جدا نیستند (prompts/persian_writer.md). لینک‌های داخلی کاندید هم
به همین prompt تزریق می‌شوند تا نویسنده خودش انکر طبیعی بسازد.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Secrets, TenantConfig
from .llm import structured_call

if TYPE_CHECKING:
    # فقط برای type-hint؛ در زمان اجرا import نمی‌شود تا زنجیره‌ی
    # research → extract → trafilatura روی دیپلوی سبکِ دمو کشیده نشود.
    from .research import ResearchBrief

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "prompts" / "persian_writer.md"

# طرح ساختاری خروجی — هر سه provider مجبور می‌شوند این شکل را پر کنند.
ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "H1 فارسی شامل کلیدواژه"},
        "intro": {"type": "string", "description": "مقدمه‌ی دقیقاً دو جمله‌ای"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "h2": {"type": "string"},
                    "answer": {"type": "string", "description": "پاسخ مستقیم ۱-۲ جمله"},
                    "body": {"type": "string", "description": "متن کامل؛ لینک داخلی به شکل تگ <a>"},
                },
                "required": ["h2", "answer", "body"],
            },
        },
        "conclusion": {"type": "string"},
        "meta_description": {"type": "string", "description": "حداکثر ۱۵۵ کاراکتر"},
        "slug": {"type": "string", "description": "اسلاگ انگلیسی با خط تیره"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "faq": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                "required": ["q", "a"],
            },
        },
        "internal_links_used": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URLهای داخلی که در متن استفاده شدند",
        },
        "needs_image": {
            "type": "boolean",
            "description": "آیا این مقاله برای درک بهتر به عکس visual احتیاج دارد؟ (مثل: dashboard، chart، interface، tool، trend)",
        },
        "image_query": {
            "type": "string",
            "description": "اگر needs_image=true: عبارت انگلیسی ۲-۴ کلمه برای جستجوی عکس (مثال: artificial intelligence server room). درغیر اینصورت: خالی بگذار",
        },
    },
    "required": ["title", "intro", "sections", "conclusion", "meta_description",
                 "slug", "tags", "faq", "internal_links_used", "needs_image", "image_query"],
}


@dataclass
class GeneratedArticle:
    title: str
    intro: str
    sections: list[dict]
    conclusion: str
    meta_description: str
    slug: str
    tags: list[str]
    needs_image: bool = False
    faq: list[dict] = field(default_factory=list)
    internal_links_used: list[str] = field(default_factory=list)
    image_query: str = ""
    source_url: str = ""
    source_name: str = ""

    def to_html(self) -> str:
        """تبدیل ساختار به HTML آماده‌ی انتشار در وردپرس + FAQ schema."""
        parts = [f"<p>{self.intro}</p>"]
        for s in self.sections:
            parts.append(f"<h2>{s['h2']}</h2>")
            parts.append(f"<p><strong>{s['answer']}</strong></p>")
            parts.append(f"<p>{s['body']}</p>")
        parts.append(f"<h2>جمع‌بندی</h2><p>{self.conclusion}</p>")
        if self.faq:
            parts.append("<h2>پرسش‌های متداول</h2>")
            for item in self.faq:
                parts.append(f"<h3>{item['q']}</h3><p>{item['a']}</p>")
            schema = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {"@type": "Question", "name": item["q"],
                     "acceptedAnswer": {"@type": "Answer", "text": item["a"]}}
                    for item in self.faq
                ],
            }
            parts.append(f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>')
        if self.source_url:
            parts.append(
                f'<p><em>منبع: <a href="{self.source_url}" rel="nofollow" target="_blank">'
                f'{self.source_name or self.source_url}</a></em></p>'
            )
        return "\n".join(parts)


def _format_links(links: list[dict]) -> str:
    if not links:
        return "(لینک داخلی کاندیدی موجود نیست — لینک داخلی نگذار)"
    return "\n".join(f"- {l['title']}: {l['url']}" for l in links)


def _build_prompt(*, brief: ResearchBrief, source_name: str, source_url: str,
                  original_title: str, topic_reason: str,
                  internal_links: list[dict]) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{source_name}", source_name)
        .replace("{source_url}", source_url)
        .replace("{original_title}", original_title)
        .replace("{topic_reason}", topic_reason or "-")
        .replace("{internal_links}", _format_links(internal_links))
        .replace("{research_brief}", brief.to_prompt_text())
    )


def generate_article(
    *,
    brief: ResearchBrief,
    source_name: str,
    source_url: str,
    original_title: str,
    topic_reason: str = "",
    internal_links: list[dict] | None = None,
    cfg: TenantConfig | None = None,
    secrets: Secrets | None = None,
) -> GeneratedArticle:
    """از Research Brief یک مقاله‌ی فارسی ساختاریافته‌ی سئو/GEO می‌سازد."""
    prompt = _build_prompt(
        brief=brief,
        source_name=source_name,
        source_url=source_url,
        original_title=original_title,
        topic_reason=topic_reason,
        internal_links=internal_links or [],
    )
    data = structured_call(prompt, ARTICLE_SCHEMA, cfg=cfg, secrets=secrets,
                           tool_name="publish_article", max_tokens=16384)
    return GeneratedArticle(source_url=source_url, source_name=source_name, **data)


if __name__ == "__main__":
    import sys

    from .extract import extract_article
    from .research import build_brief

    if len(sys.argv) < 2:
        print("usage: python -m src.generate <url> [source_name]")
        raise SystemExit(1)

    url = sys.argv[1]
    source_name = sys.argv[2] if len(sys.argv) > 2 else "منبع"
    content = extract_article(url)
    if not content:
        print("استخراج ناموفق بود.")
        raise SystemExit(1)

    brief = build_brief(content, source_name)
    article = generate_article(
        brief=brief,
        source_name=source_name,
        source_url=content.url,
        original_title=content.title,
    )
    print("عنوان (H1):", article.title)
    print("مقدمه:", article.intro)
    print("متا:", article.meta_description)
    print("اسلاگ:", article.slug)
    print("برچسب‌ها:", "، ".join(article.tags))
    print(f"بخش‌ها: {len(article.sections)} | FAQ: {len(article.faq)}")
    print("\n--- HTML ---\n")
    print(article.to_html()[:1000])
