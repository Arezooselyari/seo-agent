"""رندرِ مقاله‌ی دمو در یک صفحه‌ی کاملِ هم‌رنگِ برند.

پوسته عمداً self-contained است (CSS داخلِ همان فایل) چون داخلِ iframe با srcdoc
نمایش داده می‌شود. فونت Vazirmatn از همین سرور سرو می‌شود — Google Fonts در ایران
اغلب مسدود است و بازدیدکننده فونت را نمی‌بیند.
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

# تگ‌هایی که یک «بلوکِ مستقلِ سطحِ بالا» می‌سازند — مبنای بریدنِ مقاله برای پی‌وال
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "ul", "ol", "table", "figure",
               "blockquote", "div", "pre", "section"}
# تگ‌های خودبسته که نباید عمق را زیاد کنند
_VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source"}


class _BlockSplitter(HTMLParser):
    """مقاله را به بلوک‌های سطحِ بالا می‌شکند (با ردیابیِ عمق، نه regex).

    regex ساده روی `</p>` و امثال آن، لیستِ تودرتو یا `<table>` داخلِ `<div>` را
    وسط می‌بُرد و HTML خراب تولید می‌کند؛ این پارسر عمق را می‌شمارد.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._depth = 0
        self._buf: list[str] = []

    # هرچه خارج از یک بلوکِ باز است (مثلاً متنِ لخت) هم نگه داشته می‌شود
    def _emit(self) -> None:
        chunk = "".join(self._buf).strip()
        if chunk:
            self.blocks.append(chunk)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            self._buf.append(self.get_starttag_text() or "")
            return
        if self._depth == 0 and tag in _BLOCK_TAGS:
            self._emit()
        self._depth += 1
        self._buf.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag, attrs):
        self._buf.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        self._depth = max(0, self._depth - 1)
        self._buf.append(f"</{tag}>")
        if self._depth == 0:
            self._emit()

    def handle_data(self, data):
        self._buf.append(data)

    def handle_entityref(self, name):
        self._buf.append(f"&{name};")

    def handle_charref(self, name):
        self._buf.append(f"&#{name};")

    def close(self):  # noqa: A003
        super().close()
        self._emit()


def _split_blocks(body: str) -> list[str]:
    p = _BlockSplitter()
    p.feed(body)
    p.close()
    return p.blocks


def _text_len(html_fragment: str) -> int:
    return len(re.sub(r"<[^>]+>", "", html_fragment).strip())


def apply_paywall(body: str, ratio: float = 0.5, teaser_blocks: int = 3) -> tuple[str, bool]:
    """نیمه‌ی اول را آزاد می‌گذارد و بقیه را حذف می‌کند (به‌جز چند بندِ تارِ تیزر).

    مهم: بخشِ قفل‌شده **اصلاً به مرورگر فرستاده نمی‌شود** — نه اینکه با CSS پنهان
    شود. وگرنه کلاینت با View Source کلِ مقاله را برمی‌دارد و پی‌وال بی‌معنی است.

    خروجی: (بدنه‌ی نهایی، آیا واقعاً چیزی قفل شد)
    """
    blocks = _split_blocks(body)
    if len(blocks) < 4:
        return body, False

    total = sum(_text_len(b) for b in blocks)
    if total < 400:
        return body, False

    target = total * ratio
    running = 0
    cut = len(blocks)
    for i, b in enumerate(blocks):
        running += _text_len(b)
        if running >= target:
            cut = i + 1
            break
    if cut >= len(blocks):          # چیزی برای قفل‌کردن نماند
        return body, False

    free = "".join(blocks[:cut])
    teaser = "".join(blocks[cut:cut + teaser_blocks])
    return free + _LOCKED_TEMPLATE.format(teaser=teaser), True


_LOCKED_TEMPLATE = """
<div class="locked">
  <div class="locked-body" aria-hidden="true">{teaser}</div>
  <div class="paywall">
    <div class="paywall-card">
      <b>ادامه این مقاله در دسترس نیست</b>
      <p>این بخش نمونه‌ی رایگان شماست. برای خواندن متن کامل و دریافت مقاله‌های
         روزانه، اشتراک را فعال کنید.</p>
      <a class="paywall-btn" href="https://sagharnazari.ir/" target="_blank" rel="noopener">
        فعال‌سازی اشتراک</a>
    </div>
  </div>
</div>
"""

# ─────────────────────────────────────────────────────────────────────────────
# قالبِ صفحه. توجه: این رشته با .format() پر می‌شود، پس هر آکولادِ CSS دوبل است.
# ─────────────────────────────────────────────────────────────────────────────
_SHELL = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<style>
@font-face{{font-family:'Naskh';src:url('/fonts/naskh-arabic.woff2') format('woff2');
 font-weight:400 700;font-display:swap;
 unicode-range:U+0600-06FF,U+0750-077F,U+0870-088E,U+08A0-08FF,U+200C-200D,U+FB50-FDFF,U+FE70-FEFF;}}
@font-face{{font-family:'Naskh';src:url('/fonts/naskh-latin.woff2') format('woff2');
 font-weight:400 700;font-display:swap;
 unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+2000-206F,U+2074,U+20AC,U+2122,U+2190-2193,U+2212;}}
:root{{--paper:#FCFCFA;--ink:#14161A;--muted:#6A6862;--faint:#9A968E;
 --rule:#E2DFD8;--rule-strong:#C9C5BC;--lapis:#1C3F6E;--lapis-deep:#142E51;
 --lapis-wash:#F0F3F7;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Naskh',Tahoma,serif;background:var(--paper);color:var(--ink);
 line-height:2.05;font-size:16.5px;-webkit-font-smoothing:antialiased;
 overflow-wrap:anywhere;word-break:break-word}}
.page{{max-width:720px;margin:0 auto;padding:0 24px 72px}}
.hero{{margin:0 -24px 36px}}
.hero img{{width:100%;height:clamp(190px,32vw,320px);object-fit:cover;display:block;
 filter:saturate(.82)}}
.kicker{{display:block;font-size:12px;font-weight:700;color:var(--muted);
 letter-spacing:.14em;margin:34px 0 18px;padding-bottom:14px;
 border-bottom:1px solid var(--rule)}}
h1{{font-size:clamp(26px,4.2vw,40px);line-height:1.5;font-weight:700;
 letter-spacing:-.005em;margin:0 0 32px}}
h2{{font-size:clamp(19px,2.8vw,24px);line-height:1.6;font-weight:700;margin:46px 0 16px}}
h3{{font-size:clamp(16.5px,2.2vw,19px);font-weight:700;margin:32px 0 12px;color:var(--lapis-deep)}}
p{{margin:0 0 19px;color:#22242A}}
ul,ol{{margin:0 0 21px;padding-inline-start:22px}}
li{{margin-bottom:9px}}
a{{color:var(--lapis);text-decoration:none;border-bottom:1px solid rgba(28,63,110,.32)}}
a:hover{{color:var(--lapis-deep);border-bottom-color:var(--lapis)}}
.tablewrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:30px 0}}
table{{width:100%;border-collapse:collapse;font-size:15px;
 border-top:2px solid var(--ink);border-bottom:1px solid var(--rule-strong)}}
.tablewrap table{{margin:0}}
th,td{{padding:13px 14px;text-align:start;border-bottom:1px solid var(--rule)}}
th{{font-weight:700;font-size:13.5px;letter-spacing:.03em;color:var(--muted)}}
tr:last-child td{{border-bottom:0}}
figure{{margin:34px 0}}
figure img{{width:100%;display:block;filter:saturate(.82)}}
figcaption{{font-size:13px;color:var(--faint);margin-top:10px;
 padding-inline-start:12px;border-inline-start:2px solid var(--rule)}}
blockquote{{margin:30px 0;padding:4px 20px;border-inline-start:2px solid var(--lapis);
 color:var(--muted)}}
.wm{{margin-top:56px;padding-top:20px;border-top:1px solid var(--rule);
 font-size:12.5px;color:var(--faint)}}

/* ── بخشِ قفل‌شده ── */
.locked{{position:relative;margin-top:28px}}
.locked-body{{filter:blur(5.5px);opacity:.5;user-select:none;pointer-events:none;
 max-height:300px;overflow:hidden}}
.paywall{{position:absolute;inset:0;display:flex;align-items:flex-start;
 justify-content:center;padding-top:30px;
 background:linear-gradient(180deg,rgba(252,252,250,.3) 0%,rgba(252,252,250,.93) 44%,var(--paper) 76%)}}
.paywall-card{{max-width:420px;text-align:start;background:var(--paper);
 border-top:2px solid var(--ink);padding:24px 0 0}}
.paywall-card b{{display:block;font-size:18px;font-weight:700;margin-bottom:10px}}
.paywall-card p{{font-size:14.5px;color:var(--muted);line-height:1.9;margin:0 0 20px}}
.paywall-btn{{display:inline-block;padding:13px 32px;font-weight:700;font-size:15px;
 color:var(--paper);background:var(--ink);border:0}}
.paywall-btn:hover{{background:var(--lapis-deep)}}
</style>
</head>
<body>
<article class="page">
  {hero}
  <span class="kicker">{kicker}</span>
  <h1>{h1}</h1>
  {body}
  <div class="wm">این مقاله به‌صورت خودکار توسط سامانه تولید محتوا نوشته شده است.</div>
</article>
</body>
</html>
"""


def _strip_first_h1(body: str) -> str:
    """H1 داخلِ متن حذف می‌شود چون پوسته خودش H1 را می‌گذارد (دو H1 = خطای سئو)."""
    return re.sub(r"<h1[^>]*>.*?</h1>", "", body, count=1, flags=re.S)


def _markers_to_links(body: str) -> str:
    """`[[anchor: متن | url]]` را به لینکِ واقعی تبدیل می‌کند.

    بدونِ این کار، نشانگرها **خام و به‌شکلِ متن** در مقاله دیده می‌شوند — عیبی که
    کلاینت مستقیماً می‌بیند.
    """
    def rep(m: re.Match) -> str:
        parts = m.group(1).split("|")
        text = parts[0].strip()
        url = parts[1].strip() if len(parts) > 1 else ""
        if not url:
            return text
        return f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'

    return re.sub(r"\[\[(?:anchor|external):([^\]]*)\]\]", rep, body)


def _wrap_tables(body: str) -> str:
    """جدول در قابِ اسکرول‌دار — وگرنه روی موبایل صفحه سرریزِ افقی می‌گیرد."""
    body = re.sub(r"<table", '<div class="tablewrap"><table', body)
    return re.sub(r"</table>", "</table></div>", body)


def render_page(payload: dict, kicker: str = "نمونه‌ی اختصاصی شما",
                paywall: bool = True, paywall_ratio: float = 0.5) -> str:
    """payloadِ نویسنده را به یک صفحه‌ی HTML کاملِ آماده‌ی نمایش تبدیل می‌کند.

    paywall: نیمه‌ی دوم مقاله حذف و با کارتِ «فعال‌سازی اشتراک» جایگزین می‌شود.
    """
    title = payload.get("title_seo") or payload.get("h1") or "مقاله‌ی نمونه"
    h1 = payload.get("h1") or title

    body = payload.get("body_html") or payload.get("body_markdown") or ""
    body = _strip_first_h1(body)
    body = _markers_to_links(body)
    body = _wrap_tables(body)
    locked = False
    if paywall:
        body, locked = apply_paywall(body, ratio=paywall_ratio)

    img = payload.get("featured_image_url") or ""
    alt = _html.escape(payload.get("featured_image_alt") or h1, quote=True)
    hero = f'<div class="hero"><img src="{img}" alt="{alt}"></div>' if img else ""

    return _SHELL.format(
        title=_html.escape(title),
        desc=_html.escape(payload.get("meta_description") or "", quote=True),
        kicker=_html.escape(kicker),
        h1=_html.escape(h1),
        hero=hero,
        body=body,
    )
