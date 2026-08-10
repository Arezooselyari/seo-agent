"""مرحله ۴ — Research Brief: تحقیق روی متن کامل منبع. [LLM ۲]

روی *متن کامل استخراج‌شده* کار می‌کند، نه خلاصه‌ی RSS — این سد اصلی
هالوسینیشن است. هر ادعا باید با نقل‌قول از منبع پشتیبانی شود.
خروجی در جدول research_briefs ذخیره می‌شود و ورودی نویسنده است.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Secrets, TenantConfig
from .extract import ExtractedContent
from .llm import structured_call

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "prompts" / "research_brief.md"

MAX_SOURCE_CHARS = 12_000  # متن کامل، ولی با سقف برای کنترل هزینه

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "خلاصه‌ی ۳-۴ جمله‌ای فارسی"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "ادعا به فارسی"},
                    "quote": {"type": "string", "description": "نقل‌قول پشتیبان از متن منبع"},
                },
                "required": ["claim", "quote"],
            },
        },
        "angles": {"type": "array", "items": {"type": "string"}},
        "hallucination_risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_points", "claims", "angles", "hallucination_risks"],
}


@dataclass
class ResearchBrief:
    summary: str
    key_points: list[str]
    claims: list[dict]
    angles: list[str]
    hallucination_risks: list[str] = field(default_factory=list)
    brief_id: int | None = None

    def to_prompt_text(self) -> str:
        """نمایش متنی brief برای تزریق به prompt نویسنده."""
        parts = [f"خلاصه: {self.summary}", "", "نکات کلیدی:"]
        parts += [f"- {p}" for p in self.key_points]
        parts += ["", "ادعاهای مستند (با نقل‌قول منبع):"]
        parts += [f"- {c['claim']}\n  («{c['quote']}»)" for c in self.claims]
        parts += ["", "زاویه‌های پیشنهادی:"]
        parts += [f"- {a}" for a in self.angles]
        if self.hallucination_risks:
            parts += ["", "⚠️ درباره‌ی این‌ها ادعا نکن (داده‌ی ناکافی):"]
            parts += [f"- {r}" for r in self.hallucination_risks]
        return "\n".join(parts)


def build_brief(
    content: ExtractedContent,
    source_name: str,
    cfg: TenantConfig | None = None,
    secrets: Secrets | None = None,
) -> ResearchBrief:
    """از متن کامل منبع یک Research Brief ساختاریافته می‌سازد."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        template.replace("{source_name}", source_name)
        .replace("{source_url}", content.url)
        .replace("{original_title}", content.title)
        .replace("{article_text}", content.text[:MAX_SOURCE_CHARS])
    )
    data = structured_call(prompt, BRIEF_SCHEMA, cfg=cfg, secrets=secrets,
                           tool_name="research_brief", max_tokens=8192)
    # دفاعی: اگر خروجی نصفه قطع شد، کلیدهای لازم را با مقدار پیش‌فرض پر کن
    data.setdefault("summary", "")
    for key in ("key_points", "claims", "angles", "hallucination_risks"):
        data.setdefault(key, [])
    return ResearchBrief(**{k: data[k] for k in
                            ("summary", "key_points", "claims", "angles",
                             "hallucination_risks") if k in data})


if __name__ == "__main__":
    import sys

    from .extract import extract_article

    if len(sys.argv) < 2:
        print("usage: python -m src.research <url> [source_name]")
        raise SystemExit(1)

    content = extract_article(sys.argv[1])
    if not content or not content.ok:
        print("استخراج ناموفق بود.")
        raise SystemExit(1)

    brief = build_brief(content, sys.argv[2] if len(sys.argv) > 2 else "منبع")
    print(brief.to_prompt_text())
