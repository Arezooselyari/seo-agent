"""مرحله ۵ — Internal Links: کاندیدهای لینک داخلی از سایت‌مپ. (بدون LLM)

سایت‌مپ وردپرس fetch می‌شود، URLها استخراج و با تطبیق کلیدواژه‌ای علیه
موضوع مقاله امتیاز می‌گیرند. ۵-۱۰ کاندیدای برتر به prompt نویسنده تزریق
می‌شوند تا خودش انکر طبیعی بسازد (طبیعی‌تر از پس‌پردازش).
کش روزانه در cache/sitemap.json تا هر اجرا سایت‌مپ را دوباره نکشد.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

import httpx

from .config import Secrets

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "cache" / "sitemap.json"

SITEMAP_CANDIDATES = ["wp-sitemap.xml", "sitemap.xml", "sitemap_index.xml"]
MAX_SUB_SITEMAPS = 5
MAX_CANDIDATES = 10

# کلمات بی‌ارزش برای تطبیق
_STOPWORDS = {"the", "and", "for", "with", "how", "what", "why", "from", "this",
              "که", "از", "به", "در", "با", "برای", "است", "های", "یک", "چه"}


def _xml_locs(xml_text: str) -> list[str]:
    """همه‌ی <loc>ها را از یک سند sitemap درمی‌آورد (با هر namespace)."""
    try:
        root = ElementTree.fromstring(xml_text.encode("utf-8"))
    except ElementTree.ParseError:
        return []
    return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]


def _fetch_sitemap_urls(site_url: str) -> list[str]:
    base = site_url.rstrip("/")
    with httpx.Client(timeout=20, follow_redirects=True) as http:
        for name in SITEMAP_CANDIDATES:
            try:
                resp = http.get(f"{base}/{name}")
            except httpx.HTTPError:
                continue
            if resp.status_code != 200:
                continue
            locs = _xml_locs(resp.text)
            if not locs:
                continue
            # اگر sitemap index بود، زیر-سایت‌مپ‌ها را هم بخوان
            if all(l.endswith(".xml") for l in locs):
                urls: list[str] = []
                for sub in locs[:MAX_SUB_SITEMAPS]:
                    try:
                        sub_resp = http.get(sub)
                        if sub_resp.status_code == 200:
                            urls += [l for l in _xml_locs(sub_resp.text) if not l.endswith(".xml")]
                    except httpx.HTTPError:
                        continue
                return urls
            return [l for l in locs if not l.endswith(".xml")]
    return []


def _load_cached_urls(site_url: str) -> list[str]:
    """سایت‌مپ با کش روزانه — هر روز فقط یک‌بار fetch می‌شود."""
    today = date.today().isoformat()
    if CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if cached.get("date") == today and cached.get("site") == site_url:
                return cached.get("urls", [])
        except (json.JSONDecodeError, OSError):
            pass
    urls = _fetch_sitemap_urls(site_url)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"date": today, "site": site_url, "urls": urls}, ensure_ascii=False),
        encoding="utf-8",
    )
    return urls


def _slug_to_title(url: str) -> str:
    path = unquote(urlparse(url).path).strip("/")
    last = path.split("/")[-1] if path else ""
    return re.sub(r"[-_]+", " ", last)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[\w؀-ۿ]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def find_candidates(topic_text: str, secrets: Secrets | None = None,
                    max_links: int = MAX_CANDIDATES) -> list[dict]:
    """۵-۱۰ URL داخلی مرتبط با موضوع — خروجی: [{url, title}, ...]"""
    secrets = secrets or Secrets()
    if not secrets.wp_url:
        return []
    urls = _load_cached_urls(secrets.wp_url)
    topic_tokens = _tokens(topic_text)
    if not topic_tokens:
        return []

    scored: list[tuple[int, str, str]] = []
    for url in urls:
        title = _slug_to_title(url)
        if not title:
            continue
        overlap = len(topic_tokens & _tokens(title))
        if overlap > 0:
            scored.append((overlap, url, title))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"url": u, "title": t} for _, u, t in scored[:max_links]]


if __name__ == "__main__":
    import sys

    topic = sys.argv[1] if len(sys.argv) > 1 else "هوش مصنوعی برای کسب‌وکار AI business"
    links = find_candidates(topic)
    if not links:
        print("کاندیدایی پیدا نشد (WP_URL تنظیم است؟ سایت‌مپ در دسترس است؟)")
    for l in links:
        print(f"- {l['title']}\n  {l['url']}")
