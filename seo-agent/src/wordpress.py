"""انتشارِ مقاله در وردپرس از طریقِ REST API (Application Password / Basic auth).

جریان:
    check_connection()            → تستِ اعتبارِ رمز بدونِ انتشار (GET users/me)
    publish_article(id, payload)  → آپلودِ عکسِ شاخص → ساختِ پست → برگرداندنِ URL

نشانگرهای [[anchor|...]] / [[external|...]] به <a> تبدیل می‌شوند. عکسِ شاخص (اگر در
payload باشد) از URLِ Pexels دانلود و در کتابخانه‌ی رسانه‌ی وردپرس آپلود می‌شود و به
featured_media بسته می‌شود. فوکوس‌کیوردِ RankMath به‌صورتِ best-effort ست می‌شود.

اعتبار در config/.env یا D:\\prjcluade\\.env:
    WP_URL=https://sagharnazari.ir
    WP_USER=<نامِ کاربری>
    WP_APP_PASSWORD=<Application Password: ۲۴ کاراکتر / ۶ گروهِ ۴تایی>

اجرا (از پوشه‌ی seo-agent):
    python -m src.wordpress --check                 # فقط تستِ اتصال/رمز
    python -m src.wordpress 39 --dry-run            # همه‌چیز جز POSTِ نهایی
    python -m src.wordpress 39 --status draft       # انتشارِ واقعی به‌صورتِ پیش‌نویس
    python -m src.wordpress 39                       # با وضعیتِ پیش‌فرضِ settings
"""
import io
import logging
import re

import requests
from requests.auth import HTTPBasicAuth

from . import db
from .config import env, load_settings

logger = logging.getLogger(__name__)


class WPError(RuntimeError):
    """خطای قابلِ‌فهم برای مشکلاتِ وردپرس (رمز، اتصال، پاسخِ نامعتبر)."""


def _config() -> tuple[str, HTTPBasicAuth]:
    """(api_base, auth) را از env می‌سازد یا خطای واضح می‌دهد (بدونِ چاپِ رمز)."""
    base = (env("WP_URL") or "").strip().rstrip("/")
    user = (env("WP_USER") or "").strip()
    pw = (env("WP_APP_PASSWORD") or "").strip()
    if not base or not user or not pw:
        raise WPError("WP_URL / WP_USER / WP_APP_PASSWORD در .env کامل نیست.")
    # Application Password واقعی ۲۴ کاراکتر است (۶ گروهِ ۴تایی، با یا بدونِ فاصله).
    if len(pw.replace(" ", "")) < 20:
        raise WPError(
            f"WP_APP_PASSWORD نامعتبر است (طول={len(pw.replace(' ', ''))}). "
            "باید Application Password باشد: کاربران → پروفایل → Application Passwords "
            "(۲۴ کاراکتر / ۶ گروهِ ۴تایی)."
        )
    api = f"{base}/wp-json/wp/v2"
    return api, HTTPBasicAuth(user, pw)


def _markers_to_links(body: str) -> str:
    """[[anchor: متن | مسیر]] (به صفحه‌ی **واقعیِ** سایت) و [[external: نام | URL]] را به <a> تبدیل می‌کند.

    مسیرِ anchor را LLM حدس می‌زند و ممکن است صفحه‌ای با آن اسلاگ وجود نداشته باشد؛
    برای همین از `internal_links.linkify_internal` استفاده می‌شود که فقط به صفحاتِ
    واقعاً منتشرشده‌ی وردپرس لینک می‌دهد (وگرنه متنِ ساده می‌ماند — نه لینکِ شکسته).
    """
    from . import internal_links
    body = internal_links.linkify_internal(body or "")

    def _repl(m):
        inner = m.group(1).split("|")
        text = inner[0].split(":", 1)[-1].strip()
        url = inner[1].strip() if len(inner) > 1 else "#"
        return f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'
    return re.sub(r"\[\[(external:[^\]]*)\]\]", _repl, body)


def check_connection() -> tuple[bool, str]:
    """اعتبارِ رمز را بدونِ انتشار می‌سنجد (GET users/me). (ok, پیام)."""
    try:
        api, auth = _config()
    except WPError as e:
        return False, str(e)
    try:
        r = requests.get(f"{api}/users/me", auth=auth,
                         params={"context": "edit"}, timeout=20)
    except Exception as e:
        return False, f"اتصال به {api} برقرار نشد: {e}"
    if r.status_code == 200:
        name = r.json().get("name", "?")
        return True, f"اتصال برقرار است — کاربر: {name}"
    if r.status_code == 401:
        return False, "۴۰۱ — رمز/کاربر نامعتبر (Application Password را بررسی کن)."
    return False, f"پاسخِ غیرمنتظره {r.status_code}: {r.text[:160]}"


def _upload_media(session: requests.Session, api: str, auth: HTTPBasicAuth,
                  image_url: str, alt: str = "", filename: str = "featured.jpg") -> dict | None:
    """عکس را از URL دانلود و در کتابخانه‌ی رسانه آپلود می‌کند. {id, source_url} یا None."""
    if not image_url:
        return None
    try:
        img = session.get(image_url, timeout=30)
        if img.status_code != 200 or not img.content:
            logger.warning(f"wordpress: دانلودِ عکس نشد ({img.status_code}).")
            return None
        ctype = img.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        ext = {"image/png": ".png", "image/webp": ".webp"}.get(ctype, ".jpg")
        if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            filename += ext
        r = session.post(
            f"{api}/media", auth=auth, data=img.content,
            headers={
                "Content-Type": ctype,
                "Content-Disposition": f'attachment; filename="{filename}"',
            }, timeout=60,
        )
        if r.status_code not in (200, 201):
            logger.warning(f"wordpress: آپلودِ رسانه نشد ({r.status_code}): {r.text[:160]}")
            return None
        media = r.json()
        mid = media.get("id")
        # alt_text را ست کن (best-effort)
        if mid and alt:
            try:
                session.post(f"{api}/media/{mid}", auth=auth,
                             json={"alt_text": alt}, timeout=20)
            except Exception:
                pass
        return {"id": mid, "source_url": media.get("source_url")}
    except Exception as e:
        logger.warning(f"wordpress: خطا در آپلودِ رسانه ({e}).")
        return None


def publish_article(article_id: int, payload: dict, *,
                    status: str | None = None,
                    category_ids: list[int] | None = None) -> dict:
    """مقاله را در وردپرس منتشر می‌کند. {post_id, url, status} برمی‌گرداند یا WPError.

    status: 'publish' | 'draft' | 'pending' — اگر None از settings.publish خوانده می‌شود.
    """
    api, auth = _config()
    pub = load_settings().get("publish", {})
    status = status or pub.get("default_status", "draft")
    if category_ids is None:
        category_ids = pub.get("category_ids") or []

    # تضمینِ بخشِ «منابع» (idempotent) — حتی اگر مراحلِ بالادست اضافه‌اش نکرده باشند
    from . import references
    payload = references.add_references_to_payload(dict(payload))

    title = payload.get("title_seo") or payload.get("h1") or payload.get("topic") or "(بدون عنوان)"
    body = _markers_to_links(payload.get("body_html", ""))
    if not body.strip():
        raise WPError("body_html خالی است — چیزی برای انتشار نیست.")

    session = requests.Session()

    # ۱) عکسِ شاخص
    featured_media = None
    fimg = payload.get("featured_image_url")
    if fimg:
        slug = payload.get("slug") or f"article-{article_id}"
        media = _upload_media(session, api, auth, fimg,
                              alt=payload.get("featured_image_alt", ""),
                              filename=str(slug)[:60])
        if media:
            featured_media = media["id"]
            logger.info(f"wordpress: عکسِ شاخص آپلود شد (media #{featured_media}).")

    # ۲) بدنه‌ی پست
    post = {
        "title": title,
        "content": body,
        "status": status,
        "excerpt": payload.get("meta_description", ""),
    }
    if payload.get("slug"):
        post["slug"] = payload["slug"]
    if featured_media:
        post["featured_media"] = featured_media
    if category_ids:
        post["categories"] = category_ids

    r = session.post(f"{api}/posts", auth=auth, json=post, timeout=60)
    if r.status_code not in (200, 201):
        raise WPError(f"ساختِ پست نشد ({r.status_code}): {r.text[:240]}")
    data = r.json()
    post_id, url = data.get("id"), data.get("link")
    logger.info(f"wordpress: پست #{post_id} ساخته شد ({status}) — {url}")

    # ۳) فوکوس‌کیوردِ RankMath (best-effort — اگر ثبت‌نشده باشد نادیده گرفته می‌شود)
    tk = payload.get("target_keywords") or {}
    focus = tk.get("primary_fa") or tk.get("primary") if isinstance(tk, dict) else None
    if post_id and focus:
        try:
            session.post(f"{api}/posts/{post_id}", auth=auth,
                         json={"meta": {"rank_math_focus_keyword": focus}}, timeout=20)
        except Exception:
            pass

    return {"post_id": post_id, "url": url, "status": status}


def publish_by_id(article_id: int, *, status: str | None = None,
                  dry_run: bool = False, force: bool = False) -> dict:
    """مقاله را از agent.db می‌خواند، منتشر می‌کند و در صورتِ موفقیت DB را علامت می‌زند."""
    conn = db.connect()
    try:
        art = db.get_article(conn, article_id)
        if not art:
            raise WPError(f"مقاله #{article_id} در دیتابیس نیست.")
        # هر بار POST به /posts یک پستِ *تازه* می‌سازد؛ وردپرس با پسوندِ ‎-2/-3 به slug
        # جلوی خطا را می‌گیرد ولی نسخه‌ی تکراری روی سایت زنده می‌ماند — که برای سئو
        # دقیقاً همان چیزی است که نباید بشود. پس انتشارِ دوباره باید صریح خواسته شود.
        if not dry_run and not force and art.get("published_at"):
            raise WPError(
                f"مقاله #{article_id} قبلاً در {art['published_at']} منتشر شده"
                f"{' — ' + art['wp_post_url'] if art.get('wp_post_url') else ''}. "
                "برای ساختِ نسخه‌ی دوم --force بده، وگرنه پستِ موجود را ویرایش کن."
            )
        payload = art["payload"]
        if dry_run:
            ok, cfg_msg = check_connection()  # اعتبارِ رمز را جدا گزارش کن (غیرمسدودکننده)
            body = _markers_to_links(payload.get("body_html", ""))
            return {
                "dry_run": True,
                "config_valid": ok,
                "config_note": cfg_msg,
                "title": payload.get("title_seo"),
                "slug": payload.get("slug"),
                "status": status or load_settings().get("publish", {}).get("default_status"),
                "already_published": art.get("published_at"),
                "featured_image": bool(payload.get("featured_image_url")),
                "body_chars": len(body),
                "markers_remaining": body.count("[["),
            }
        result = publish_article(article_id, payload, status=status)
        if result.get("url"):
            db.mark_published(conn, article_id, result["url"])
            logger.info(f"مقاله #{article_id} → published ({result['url']}).")
        return result
    finally:
        conn.close()


def _post_id_from_url(url: str) -> int | None:
    """شناسه‌ی پست را از URLِ `?p=NNN` بیرون می‌کشد (permalinkِ ساده)."""
    m = re.search(r"[?&]p=(\d+)", url or "")
    return int(m.group(1)) if m else None


def update_post(post_id: int, payload: dict, *, status: str | None = None,
                focus_keyword: str | None = None) -> dict:
    """محتوای یک پستِ موجود را به‌روزرسانی می‌کند (منابع idempotent اضافه می‌شود)."""
    api, auth = _config()
    from . import references
    payload = references.add_references_to_payload(dict(payload))
    data = {"content": _markers_to_links(payload.get("body_html", ""))}
    if payload.get("title_seo"):
        data["title"] = payload["title_seo"]
    if payload.get("meta_description"):
        data["excerpt"] = payload["meta_description"]
    if status:
        data["status"] = status
    if focus_keyword:
        data["meta"] = {"rank_math_focus_keyword": focus_keyword}
    r = requests.post(f"{api}/posts/{post_id}", auth=auth, json=data, timeout=60)
    if r.status_code not in (200, 201):
        raise WPError(f"به‌روزرسانیِ پست #{post_id} نشد ({r.status_code}): {r.text[:240]}")
    d = r.json()
    logger.info(f"wordpress: پست #{post_id} به‌روزرسانی شد.")
    return {"post_id": d.get("id"), "url": d.get("link"), "status": d.get("status")}


def main() -> None:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = sys.argv[1:]
    if "--check" in args:
        ok, msg = check_connection()
        print(("✅ " if ok else "❌ ") + msg)
        sys.exit(0 if ok else 1)
    ids = [a for a in args if a.isdigit()]
    if not ids:
        print("استفاده: python -m src.wordpress --check | <article_id> [--dry-run] [--force] [--status draft|publish]")
        sys.exit(2)
    status = None
    if "--status" in args:
        i = args.index("--status")
        if i + 1 < len(args):
            status = args[i + 1]
    dry = "--dry-run" in args
    try:
        result = publish_by_id(int(ids[0]), status=status, dry_run=dry,
                               force="--force" in args)
        print(result)
        sys.exit(0)
    except WPError as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
