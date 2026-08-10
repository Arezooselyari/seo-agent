"""ارزیابی مقالات و تعیین تایید یا ردّ.

این ماژول:
1. مقالات pending را می‌خواند
2. seo_grade را استخراج می‌کند
3. تصمیم می‌گیرد: score > 90 → تایید (Approve) ، وگرنه needs_review
4. برای approved، به Telegram اطلاع می‌دهد
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from . import db

logger = logging.getLogger(__name__)


def get_pending_articles(conn) -> list[dict]:
    """تمام مقالات pending را می‌خواند."""
    rows = conn.execute(
        "SELECT * FROM articles WHERE status = 'pending' ORDER BY created_at DESC"
    ).fetchall()

    out = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def get_seo_grade(article: dict) -> int:
    """نمره‌ی SEO را از payload استخراج می‌کند."""
    payload = article.get("payload", {})
    grade = payload.get("seo_grade", 0)
    return int(grade) if grade else 0


def should_approve(seo_grade: int, threshold: int = 90) -> bool:
    """تصمیم می‌گیرد: آیا مقاله تایید شود؟"""
    return seo_grade >= threshold


def evaluate_article(article: dict, threshold: int = 90) -> dict:
    """یک مقاله را ارزیابی می‌کند و نتیجه برمی‌گرداند.

    Returns:
        {
            'article_id': int,
            'title': str,
            'seo_grade': int,
            'recommendation': 'approve' | 'needs_review',
            'preview': str (first 200 chars of body)
        }
    """
    grade = get_seo_grade(article)
    payload = article.get("payload", {})

    recommendation = "approve" if should_approve(grade, threshold) else "needs_review"

    # Extract first 200 chars of body as preview (strip HTML tags)
    body_html = payload.get("body_html", "")
    preview = body_html[:200].replace("<p>", "").replace("</p>", "")
    if len(preview) >= 200:
        preview = preview[:197] + "..."

    return {
        "article_id": article["id"],
        "title": payload.get("title_seo", ""),
        "seo_grade": grade,
        "recommendation": recommendation,
        "preview": preview,
        "payload": payload,
        "threshold": threshold,
    }


def evaluate_pending_articles(conn, threshold: int = 90) -> dict:
    """تمام pending articles را ارزیابی می‌کند.

    Returns:
        {
            'total': int,
            'approved': [{...}, ...],
            'needs_review': [{...}, ...],
        }
    """
    pending = get_pending_articles(conn)

    approved = []
    needs_review = []

    for article in pending:
        result = evaluate_article(article, threshold)
        if result["recommendation"] == "approve":
            approved.append(result)
        else:
            needs_review.append(result)

    return {
        "total": len(pending),
        "approved": approved,
        "needs_review": needs_review,
    }


def log_evaluation(article_id: int, seo_grade: int, action: str, reason: str = "") -> None:
    """ارزیابی را در لاگ ثبت می‌کند.

    Args:
        article_id: ID مقاله
        seo_grade: نمره‌ی SEO
        action: approve | reject | needs_review
        reason: دلیل (optional)
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    log_msg = f"[{timestamp}] Article #{article_id}: score={seo_grade}, action={action}"
    if reason:
        log_msg += f", reason={reason}"
    logger.info(log_msg)
