"""Sync — همگام‌سازی وضعیت انتشار از وردپرس به دیتابیس.

بازبینی و دکمه‌ی Publish در خود ادیتور وردپرس انجام می‌شود؛ این جاب
پست‌های draft را از WP REST می‌خواند و اگر منتشر شده بودند، وضعیت را در
Supabase به published می‌برد. در ابتدای هر اجرای روزانه هم صدا زده می‌شود.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx

from .config import Secrets, TenantConfig
from . import db


def _auth_header(secrets: Secrets) -> dict[str, str]:
    token = base64.b64encode(
        f"{secrets.wp_user}:{secrets.wp_app_password}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def run(cfg: TenantConfig | None = None, secrets: Secrets | None = None) -> int:
    """وضعیت همه‌ی پیش‌نویس‌های در انتظار را چک می‌کند. تعداد منتشرشده‌ها را برمی‌گرداند."""
    cfg = cfg or TenantConfig.load()
    secrets = secrets or Secrets()
    published = 0

    with db.connect(secrets) as client:
        pending = db.pending_publishing(client, cfg.tenant_id)
        if not pending:
            return 0

        base = secrets.wp_url.rstrip("/")
        headers = _auth_header(secrets)
        with httpx.Client(timeout=20) as http:
            for row in pending:
                try:
                    resp = http.get(
                        f"{base}/wp-json/wp/v2/posts/{row['wp_post_id']}",
                        params={"context": "edit"},
                        headers=headers,
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    print(f"[sync] خطا برای پست {row['wp_post_id']}: {e}")
                    continue

                if resp.json().get("status") == "publish":
                    db.mark_published(
                        client,
                        row["id"],
                        row["article_id"],
                        datetime.now(timezone.utc).isoformat(),
                    )
                    published += 1
                    print(f"[sync] پست {row['wp_post_id']} منتشر شد ✅")

    return published


if __name__ == "__main__":
    n = run()
    print(f"{n} مقاله به وضعیت published منتقل شد.")
