"""Google Trends integration for real-time trending keywords."""
from __future__ import annotations

from pytrends.request import TrendReq
from .config import TenantConfig


def get_trending_keywords(cfg: TenantConfig | None = None, limit: int = 5) -> list[dict]:
    """دریافت کلیدواژه‌های ترندی از Google Trends (یا fallback)."""
    cfg = cfg or TenantConfig.load()

    try:
        pytrends = TrendReq(hl='fa-IR', tz=240)
        trending = pytrends.trending_searches(pn='iran')

        # فیلتر برای کلیدواژه‌های AI
        ai_keywords = cfg.ai_keywords or []
        filtered = []

        for keyword in trending[:20]:
            if any(ai_kw.lower() in keyword.lower() for ai_kw in ai_keywords):
                filtered.append({
                    'keyword': keyword,
                    'trend_score': 100,
                    'trend_source': 'google_trends',
                })
            elif any(x in keyword.lower() for x in ['ai', 'هوش', 'مصنوعی', 'chatgpt', 'claude', 'gemini', 'آی', 'بات']):
                filtered.append({
                    'keyword': keyword,
                    'trend_score': 95,
                    'trend_source': 'google_trends',
                })

        return filtered[:limit]

    except Exception as e:
        print(f"[trends] خطا (fallback): {e}")
        # fallback: popular AI keywords
        return [
            {'keyword': 'هوش مصنوعی', 'trend_score': 90, 'trend_source': 'fallback'},
            {'keyword': 'ChatGPT', 'trend_score': 85, 'trend_source': 'fallback'},
        ]


if __name__ == "__main__":
    trends = get_trending_keywords()
    for t in trends:
        print(f"  • {t['keyword']} (score: {t['trend_score']})")
