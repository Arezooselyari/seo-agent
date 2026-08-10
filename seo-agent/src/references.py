"""بخشِ «منابع» — لیستِ لینک‌دارِ منابعِ واقعیِ مقاله در انتهای متن (برای E-E-A-T).

`source_urls` (منابعی که collector جمع کرده) به یک بلوکِ `<h2>منابع</h2><ol>...` تبدیل
می‌شود و به انتهای body_html اضافه می‌شود. idempotent است (اگر قبلاً منابع باشد، دوباره
اضافه نمی‌شود). بدونِ LLM — نامِ منبع از دامنه ساخته می‌شود (نگاشتِ دامنه‌های معروف).
"""
import re
from urllib.parse import urlparse



# نگاشتِ دامنه‌های پرتکرار به نامِ خوانا (بقیه از خودِ دامنه ساخته می‌شوند)
_NICE = {
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
    "wired.com": "WIRED",
    "arstechnica.com": "Ars Technica",
    "venturebeat.com": "VentureBeat",
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "theguardian.com": "The Guardian",
    "nytimes.com": "The New York Times",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "forbes.com": "Forbes",
    "cnbc.com": "CNBC",
    "engadget.com": "Engadget",
    "zdnet.com": "ZDNet",
    "mashable.com": "Mashable",
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "blog.google": "Google",
    "google.com": "Google",
    "microsoft.com": "Microsoft",
    "en.wikipedia.org": "ویکی‌پدیا",
    "fa.wikipedia.org": "ویکی‌پدیای فارسی",
    "statista.com": "Statista",
    "gartner.com": "Gartner",
    "mckinsey.com": "McKinsey",
    "hbr.org": "Harvard Business Review",
}

_REF_MARK = "<h2>منابع</h2>"


def _label(url: str) -> str:
    """نامِ خوانای منبع را از دامنه می‌سازد."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return _NICE.get(host, host or url)


def build_references_html(source_urls: list[str] | None,
                          titles: dict | None = None) -> str:
    """منابع را به `<h2>منابع</h2><ol>...</ol>` تبدیل می‌کند (خالی اگر منبعی نباشد).

    titles: نگاشتِ {url: عنوانِ واقعیِ مقاله}. با آن، متنِ لینک «عنوانِ مقاله — منبع»
    می‌شود (نه فقط نامِ سایت) تا خواننده بفهمد هر منبع دقیقاً به چه چیزی اشاره دارد
    و دو مقاله‌ی مختلف از یک سایت قابلِ‌تفکیک باشند.
    """
    urls = [u for u in dict.fromkeys(source_urls or [])
            if isinstance(u, str) and u.startswith("http")]
    if not urls:
        return ""
    titles = titles or {}
    items = []
    for u in urls:
        site = _label(u)
        title = (titles.get(u) or "").strip()
        text = f"{title} — {site}" if title else site
        items.append(f'<li><a href="{u}" target="_blank" rel="noopener">{text}</a></li>')
    return f'{_REF_MARK}\n<ol class="article-references">{"".join(items)}</ol>'


def has_references(body_html: str) -> bool:
    """آیا متن از قبل بخشِ منابع دارد؟ (برای idempotency)."""
    return bool(body_html) and (_REF_MARK in body_html or ">منابع</h2>" in body_html)


def strip_references(body_html: str) -> str:
    """بلوک‌های ساخت‌یافته‌ی انتهایی («منابع» و «مطالب مرتبط») را جدا می‌کند تا فقط
    «نثرِ مقاله» بماند — برای چک‌هایی که کیفیتِ نوشتار را می‌سنجند.

    بدونِ این، چکِ «جمله‌ی آخر کامل است؟» به آخرین آیتمِ لیست (مثلاً «TechCrunch»)
    نگاه می‌کند که طبیعتاً نقطه ندارد و مقاله‌ی سالم را رد می‌کند.
    """
    if not body_html:
        return body_html or ""
    return re.split(r"<h2[^>]*>\s*(?:منابع|مطالب مرتبط)\s*</h2>", body_html)[0]


def add_references_to_payload(payload: dict) -> dict:
    """بخشِ منابع را به انتهای body_html اضافه می‌کند (اگر منبع باشد و قبلاً نباشد)."""
    body = payload.get("body_html", "") or ""
    if has_references(body):
        return payload
    refs = build_references_html(payload.get("source_urls"),
                                 titles=payload.get("source_titles"))
    if not refs:
        return payload
    payload["body_html"] = body.rstrip() + "\n" + refs
    return payload
