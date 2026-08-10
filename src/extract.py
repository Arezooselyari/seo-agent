"""مرحله ۲ — Extract: استخراج متن تمیز مقاله از روی URL.

از trafilatura استفاده می‌شود که متن اصلی را بدون منو/تبلیغ/فوتر بیرون می‌کشد.
تابع stateless است: URL می‌گیرد، متن تمیز (و متادیتا) می‌دهد.
"""
from __future__ import annotations

from dataclasses import dataclass

import trafilatura


@dataclass
class ExtractedContent:
    url: str
    title: str
    text: str
    author: str = ""
    date: str = ""

    @property
    def ok(self) -> bool:
        # متن خیلی کوتاه معمولاً یعنی استخراج شکست خورده یا paywall
        return bool(self.text) and len(self.text) > 250


def extract_article(url: str) -> ExtractedContent | None:
    """متن کامل یک مقاله را از URL استخراج می‌کند.
    در صورت شکست (paywall، صفحه‌ی خالی، خطای شبکه) None برمی‌گرداند."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        return None

    meta = trafilatura.extract_metadata(downloaded)
    return ExtractedContent(
        url=url,
        title=(meta.title if meta and meta.title else ""),
        text=text,
        author=(meta.author if meta and meta.author else ""),
        date=(meta.date if meta and meta.date else ""),
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m src.extract <url>")
        raise SystemExit(1)

    result = extract_article(sys.argv[1])
    if not result:
        print("❌ استخراج ناموفق بود.")
        raise SystemExit(1)

    print(f"عنوان: {result.title}")
    print(f"نویسنده: {result.author}  | تاریخ: {result.date}")
    print(f"طول متن: {len(result.text)} کاراکتر  | معتبر: {result.ok}")
    print("-" * 60)
    print(result.text[:800], "...")
