"""مرحله ۷ — Publish: انتشار مقاله در وردپرس via REST API.

اصل SaaS-ready #4: انتشار پشت یک interface (Publisher) است تا فردا
CMSهای دیگر (Ghost, Webflow, ...) فقط یک کلاس جدید باشند.
"""
from __future__ import annotations

import base64
from typing import Protocol

import httpx

from .config import Secrets
from .generate import GeneratedArticle


class Publisher(Protocol):
    def publish(self, article: GeneratedArticle, *, status: str = "draft") -> int:
        """مقاله را منتشر می‌کند و شناسه‌ی پست را برمی‌گرداند."""
        ...


class WordPressPublisher:
    """انتشار در وردپرس با Application Password (Basic Auth)."""

    def __init__(self, secrets: Secrets | None = None):
        self.secrets = secrets or Secrets()

    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self.secrets.wp_user}:{self.secrets.wp_app_password}".encode()
        ).decode()
        return {"Authorization": f"Basic {token}"}

    def publish(self, article: GeneratedArticle, *, status: str = "draft") -> int:
        """مقاله را به‌صورت پیش‌نویس (draft) یا منتشرشده (publish) می‌فرستد.
        پیش‌فرض draft است تا قبل از تأیید چیزی روی سایت زنده نرود."""
        url = f"{self.secrets.wp_url.rstrip('/')}/wp-json/wp/v2/posts"
        payload = {
            "title": article.title,
            "content": article.to_html(),
            "slug": article.slug,
            "status": status,  # 'draft' یا 'publish'
            "excerpt": article.meta_description,
        }
        resp = httpx.post(url, json=payload, headers=self._auth_header(), timeout=30)
        resp.raise_for_status()
        return resp.json()["id"]


def get_publisher(secrets: Secrets | None = None) -> Publisher:
    """فعلاً فقط وردپرس. در آینده بر اساس config، CMS مقصد انتخاب می‌شود."""
    return WordPressPublisher(secrets)
