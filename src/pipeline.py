"""موتور اصلی — اجرای end-to-end تمام‌خودکار.

sync → ingest → topic select [LLM ۱] → extract → research [LLM ۲]
→ internal links → write [LLM ۳] → WP draft → telegram

بازبینی انسانی در خود ادیتور وردپرس انجام می‌شود (پست draft است)؛
جاب sync در ابتدای اجرای بعدی، انتشارهای دستی را در DB ثبت می‌کند.
هر خطا به تلگرام گزارش می‌شود — هیچ مرحله‌ای بی‌صدا fail نمی‌شود.
"""
from __future__ import annotations

from .config import Secrets, TenantConfig
from . import db, sync
from .ingest import fetch_new_articles
from .rank import select_articles
from .extract import extract_article
from .research import build_brief
from .internal_links import find_candidates
from .generate import generate_article
from .humanize import humanize_article
from .notify import notify_draft, notify_error, notify_pipeline_start, send_document
from .render import save_article_html
from .images import fetch_pexels_images


def _validate_article(article, html_path) -> str:
    """تست پیش از ارسال — مقاله باید واقعی و کامل باشد.

    اگر مشکلی بود، توضیحِ مشکل را برمی‌گرداند (رشته‌ی غیرخالی = ردّ ارسال).
    رشته‌ی خالی یعنی مقاله سالم است و می‌توان فرستاد.
    """
    from pathlib import Path

    if not (article.title or "").strip():
        return "عنوان مقاله خالی است."
    # باید حداقل دو بخش واقعی با بدنه‌ی معنادار داشته باشد
    real_sections = [
        s for s in (article.sections or [])
        if (s.get("body") or "").strip() and (s.get("h2") or "").strip()
    ]
    if len(real_sections) < 2:
        return f"بدنه‌ی مقاله ناکافی است (فقط {len(real_sections)} بخش معتبر)."
    body_chars = sum(len((s.get("body") or "")) for s in real_sections)
    if body_chars < 600:
        return f"متن مقاله خیلی کوتاه است ({body_chars} کاراکتر)."
    if not (article.conclusion or "").strip():
        return "جمع‌بندی مقاله خالی است."
    # فایل HTML باید ساخته شده و کامل باشد
    p = Path(html_path)
    if not p.exists():
        return "فایل HTML ساخته نشد."
    size = p.stat().st_size
    if size < 1500:
        return f"فایل HTML ناقص است ({size} بایت)."
    return ""


def run(cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> list[int]:
    """یک دور کامل موتور را اجرا می‌کند. لیست id مقاله‌های ساخته‌شده را برمی‌گرداند."""
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    db.init_db(secrets)

    # پیام شروع اجرا به تلگرام
    notify_pipeline_start(cfg.articles_per_run, secrets)

    # ۰) همگام‌سازی انتشارهای دستی قبلی از وردپرس
    try:
        synced = sync.run(cfg, secrets)
        if synced:
            print(f"[sync] {synced} مقاله published شد.")
    except Exception as e:  # noqa: BLE001
        print(f"[sync] خطا: {e}")

    # ۱) جمع‌آوری موضوع‌های جدید
    try:
        new_count = len(fetch_new_articles(cfg, secrets))
        print(f"[ingest] {new_count} موضوع جدید ثبت شد.")
    except Exception as e:  # noqa: BLE001
        notify_error("ingest", str(e), secrets)
        raise

    # ۲) امتیازدهی و انتخاب موضوع روز [LLM ۱]
    try:
        selected = select_articles(cfg, secrets)
        print(f"[select] {len(selected)} موضوع برای تولید انتخاب شد.")
    except Exception as e:  # noqa: BLE001
        notify_error("topic-select", str(e), secrets)
        raise

    article_ids: list[int] = []

    for sel in selected:
        # به محض رسیدن به سهمیه‌ی روز، بقیه‌ی استخر را دست‌نخورده (new) رها کن
        if len(article_ids) >= cfg.articles_per_run:
            break

        # ۳) استخراج متن کامل منبع
        content = extract_article(sel.url)
        if not content or not content.ok:
            print(f"[extract] رد شد (متن ناکافی): {sel.title[:50]}")
            with db.connect(secrets) as client:
                db.set_topic_status(client, sel.article_id, "skipped")
            continue

        try:
            # ۴) Research Brief از متن کامل [LLM ۲]
            brief = build_brief(content, sel.source, cfg=cfg, secrets=secrets)
            print(f"[research] brief با {len(brief.claims)} ادعای مستند آماده شد.")

            # ۵) کاندیدهای لینک داخلی از سایت‌مپ (rule-based)
            links = find_candidates(f"{sel.title} {brief.summary}", secrets)
            print(f"[links] {len(links)} کاندیدای لینک داخلی.")

            # ۶) نوشتن مقاله‌ی فارسی [LLM ۳]
            article = generate_article(
                brief=brief,
                source_name=sel.source,
                source_url=sel.url,
                original_title=content.title or sel.title,
                topic_reason=sel.reason,
                internal_links=links,
                cfg=cfg,
                secrets=secrets,
            )

            # ۶.۵) انسانی‌سازی لحن [LLM ۴]
            article = humanize_article(article, cfg=cfg, secrets=secrets)
        except Exception as e:  # noqa: BLE001
            err_low = str(e).lower().replace(" ", "")
            if "perday" in err_low or "requestsperday" in err_low:
                # سهمیه‌ی روزانه تمام شد — تلاش بیشتر بی‌فایده است، raise کن
                # تا run_with_check.py پیام تلگرام بفرستد
                raise
            print(f"[generate] خطا برای «{sel.title[:40]}»: {e}")
            notify_error("generate", f"{sel.title[:60]}\n{e}", secrets)
            continue

        # ۷) ذخیره در DB (مسیر موقت: به‌جای وردپرس، فایل HTML + تلگرام)
        try:
            with db.connect(secrets) as client:
                brief_id = db.insert_research_brief(
                    client,
                    tenant_id=cfg.tenant_id,
                    topic_id=sel.article_id,
                    summary=brief.summary,
                    key_points=brief.key_points,
                    claims=brief.claims,
                    angles=brief.angles,
                    hallucination_risks=brief.hallucination_risks,
                )
                article_id = db.insert_article(
                    client,
                    tenant_id=cfg.tenant_id,
                    topic_id=sel.article_id,
                    research_brief_id=brief_id,
                    title_fa=article.title,
                    body_html=article.to_html(),
                    meta_description=article.meta_description,
                    slug=article.slug,
                    tags=article.tags,
                    internal_links=article.internal_links_used,
                )
                # نشانه‌گذاری مقاله برای بازبینی در ربات
                db.set_article_status(client, article_id, "pending_review")
                db.set_topic_status(client, sel.article_id, "drafted")
        except Exception as e:  # noqa: BLE001
            print(f"[save-article] خطا: {e}")
            notify_error("save-article", f"{article.title[:60]}\n{e}", secrets)
            continue

        # ۸) دریافت دو عکس استوک از Pexels (فقط اگر مقاله نیاز داشت)
        image = None
        inline_image = None
        if article.needs_image and article.image_query:
            imgs = fetch_pexels_images(article.image_query, secrets, count=2)
            if imgs:
                image = imgs[0]
                inline_image = imgs[1] if len(imgs) > 1 else None
                print(f"[images] {len(imgs)} عکس دریافت شد: {article.image_query}")
            else:
                print(f"[images] نتوانست عکس برای '{article.image_query}' پیدا کند — بدون عکس ادامه.")
        elif not article.needs_image:
            print("[images] این مقاله عکس نیاز ندارد.")

        # ۹) ساخت فایل HTML کامل
        html_path = save_article_html(article, image=image, inline_image=inline_image)

        # ۹.۵) تست پیش از ارسال: مطمئن شو مقاله واقعاً و کامل ساخته شده
        problem = _validate_article(article, html_path)
        if problem:
            print(f"[verify] مقاله ناقص است، ارسال نشد: {problem}")
            notify_error("verify", f"{article.title[:60]}\n{problem}", secrets)
            continue

        # ۱۰) ارسال به تلگرام برای بازبینی
        notify_draft(
            title=article.title,
            meta_description=article.meta_description,
            score=sel.score,
            reason=sel.reason,
            secrets=secrets,
        )
        send_document(
            html_path,
            caption=f"📄 مقاله‌ی کامل: {article.title}\nبرای خواندن، فایل را در مرورگر باز کن.",
            secrets=secrets,
        )
        article_ids.append(article_id)
        print(f"[draft #{article_id}] آماده‌ی بازبینی: {article.title}")
        print(f"  📄 {html_path}")

    print(f"\n✅ {len(article_ids)} پیش‌نویس ساخته شد.")
    return article_ids


if __name__ == "__main__":
    run()
