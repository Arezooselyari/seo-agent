"""مرحله ۳ — Topic Selector: امتیازدهی هوشمند و انتخاب موضوع روز. [LLM ۱]

همه‌ی کاندیدهای ۴۸ ساعت اخیر در *یک* فراخوانی LLM امتیاز می‌گیرند
(تازگی، اهمیت بیزنسی، جذب مخاطب، ظرفیت سئو، ارزش توضیح به فارسی)
و بهترین‌ها (articles_per_run) برای تولید انتخاب می‌شوند.
امتیاز و دلیل هر کاندیدا در جدول topics ذخیره می‌شود.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Secrets, TenantConfig
from . import db

ROOT = Path(__file__).resolve().parent.parent

CANDIDATE_WINDOW_HOURS = 48
# اگر در ۴۸ ساعت اخیر خبر تازه‌ای نبود، از بک‌لاگِ موضوع‌های new تا «۵ روز اخیر»
# استفاده می‌کنیم — نه قدیمی‌تر. خبر کهنه (مثلاً یک‌ماهه) هرگز تولید نمی‌شود؛
# فقط موضوع‌های تازه‌ای که به صدر جدول امتیاز رسیده‌اند مقاله می‌شوند.
FALLBACK_WINDOW_HOURS = 24 * 5
MIN_SCORE = 40

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "score", "reason"],
            },
        },
    },
    "required": ["scores"],
}


@dataclass
class SelectedArticle:
    article_id: int
    source: str
    url: str
    title: str
    score: float = 0.0
    reason: str = ""


def select_articles(cfg: TenantConfig, secrets: Secrets | None = None) -> list[SelectedArticle]:
    """Select best articles for generation."""
    secrets = secrets or Secrets()
    since = (datetime.now(timezone.utc) - timedelta(hours=CANDIDATE_WINDOW_HOURS)).isoformat()

    from .trends import get_trending_keywords
    trending = get_trending_keywords(cfg, limit=5)
    print(f"[trends] {len(trending)} ترند یافت شد")

    with db.connect(secrets) as client:
        candidates = db.candidate_topics(client, cfg.tenant_id, since)
        if not candidates:
            # fallback: خبر تازه‌ای نبود → از بک‌لاگِ موضوع‌های new قدیمی‌تر استفاده کن
            fallback_since = (
                datetime.now(timezone.utc) - timedelta(hours=FALLBACK_WINDOW_HOURS)
            ).isoformat()
            candidates = db.candidate_topics(client, cfg.tenant_id, fallback_since)
            if candidates:
                print(f"[select] خبر ۴۸ساعته نبود؛ از بک‌لاگ {len(candidates)} موضوع استفاده می‌شود.")
        if not candidates:
            return []

        # Build prompt
        lines = ["Rank these candidates by relevance to AI business:"]
        for c in candidates[:10]:
            lines.append(f"- id={c['id']} | {c['source']} | {c['title'][:60]}")

        if trending:
            lines.append("\nTrending now:")
            for t in trending:
                lines.append(f"- {t['keyword']}")

        prompt = "\n".join(lines)
        prompt += (
            "\n\nReturn ONLY valid JSON array:\n"
            '[{"id": 1, "score": 85, "reason": "brief reason"}]'
        )

        # Call Gemini (با تلاش مجدد در برابر قطعیِ موقتِ VPN)
        import google.generativeai as genai
        from .llm import call_with_retry
        genai.configure(api_key=secrets.gemini_api_key)
        model = genai.GenerativeModel(cfg.ai_model or "gemini-2.5-flash")
        response = call_with_retry(lambda: model.generate_content(prompt))
        text = response.text

        # Extract JSON
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            print(f"[rank] No JSON found in response")
            return []

        try:
            scores = json.loads(match.group())
        except json.JSONDecodeError as e:
            print(f"[rank] JSON parse error: {str(e)[:80]}")
            return []

        by_id = {c["id"]: c for c in candidates}
        scored = [s for s in scores if isinstance(s, dict) and s.get("id") in by_id]
        scored.sort(key=lambda s: float(s.get("score", 0)), reverse=True)

        # یک «استخر» رتبه‌بندی‌شده برمی‌گردانیم (نه فقط articles_per_run تا).
        # وضعیت موضوع‌ها را new نگه می‌داریم؛ pipeline خودش هرکدام را که
        # واقعاً به مقاله رسید drafted و هرکدام که extract شکست خورد skipped می‌کند.
        # این‌طور اگر استخراجِ بهترین موضوع شکست خورد، موضوع بعدی امتحان می‌شود.
        pool_size = max(cfg.articles_per_run * 4, 8)
        selected: list[SelectedArticle] = []
        for s in scored:
            if float(s.get("score", 0)) < MIN_SCORE:
                continue
            db.set_topic_score(
                client,
                s["id"],
                score=float(s.get("score", 0)),
                reason=s.get("reason", ""),
                status="new",
            )
            topic = by_id[s["id"]]
            selected.append(SelectedArticle(
                article_id=s["id"],
                source=topic["source"],
                url=topic["url"],
                title=topic["title"] or "",
                score=float(s.get("score", 0)),
                reason=s.get("reason", ""),
            ))
            if len(selected) >= pool_size:
                break
        return selected


if __name__ == "__main__":
    cfg = TenantConfig.load()
    picks = select_articles(cfg)
    if not picks:
        print("کاندیدای جدیدی برای امتیازدهی نیست.")
    for s in picks:
        print(f"#{s.article_id} [{s.source}] {s.score:.0f}\n  {s.title[:80]}")
