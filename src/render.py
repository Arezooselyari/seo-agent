"""ساختِ یک صفحه‌ی HTML کاملِ راست‌به‌چپ و زیبا از مقاله — سبک دیجیاتو.

`to_html()` در generate.py فقط قطعه‌ی بدنه برای وردپرس است. اینجا یک صفحه‌ی
مستقلِ کامل (با عنوان H1، استایل Vazirmatn، عکس شاخص) می‌سازیم تا کاربر بتواند
آن را در مرورگر دقیقاً مثل یک مقاله‌ی واقعی بخواند.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .generate import GeneratedArticle
from .config import TenantConfig

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "outputs"

_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{meta}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --radius: 14px;
    --ease: cubic-bezier(.22,.61,.36,1);
    /* پالت vlumis — گرم، لاکچری، روزنامه‌نگارانه */
    --ink: #1E1408;
    --gold: #B8853A;
    --gold-light: #C99A52;
    --cream: #FAF6F0;
    --sand: #F3EBE0;
    --gold-fill: #F5EDD8;
    --teal: #4A8B7E;
    --teal-light: #EAF3F1;
    --rose: #B86A52;
    --rose-light: #F5EAE6;
    /* خطوط نازک به‌جای سایه‌ی سنگین + سایه‌های گرم با ته‌رنگِ ink (نه خاکستری سرد) */
    --hairline: 1px solid rgba(30,20,8,.09);
    --hairline-gold: 1px solid rgba(184,133,58,.22);
    --shadow-sm: 0 2px 10px -4px rgba(30,20,8,.08);
    --shadow-md: 0 10px 30px -14px rgba(30,20,8,.16), 0 2px 6px -3px rgba(30,20,8,.06);
    --shadow-lg: 0 18px 44px -18px rgba(30,20,8,.20), 0 4px 12px -6px rgba(30,20,8,.08);
    --shadow-hover: 0 22px 50px -18px rgba(30,20,8,.24), 0 6px 16px -7px rgba(30,20,8,.10);
  }}
  body {{
    font-family: 'Vazirmatn', Tahoma, 'Segoe UI', sans-serif;
    font-size: 17px;
    line-height: 1.95;
    color: var(--ink);
    background: var(--cream);
    min-height: 100vh;
  }}
  /* متن فارسی تمام‌چین (justified) — استاندارد روزنامه‌نگاری */
  .article-intro,
  .article-body p,
  .faq-item p {{
    text-align: justify;
    text-justify: inter-word;
  }}
  .container {{
    max-width: 780px;
    margin: 0 auto;
    padding: 0 20px 60px;
  }}
  /* ─── header ─── */
  .article-header {{
    padding: 36px 0 20px;
    border-bottom: 1px solid rgba(184,133,58,.28);
    margin-bottom: 28px;
  }}
  .article-breadcrumb {{
    font-size: 13px;
    color: #8a7a63;
    margin-bottom: 14px;
  }}
  .article-breadcrumb a {{ color: var(--gold); text-decoration: none; }}
  .article-title {{
    font-size: 1.85rem;
    font-weight: 700;
    line-height: 1.55;
    color: var(--ink);
    margin-bottom: 14px;
  }}
  .article-meta {{
    display: flex;
    gap: 18px;
    align-items: center;
    font-size: 13.5px;
    color: #8a7a63;
    flex-wrap: wrap;
  }}
  .article-meta .site-name {{ font-weight: 600; color: var(--gold); }}
  /* ─── hero image ─── */
  .hero-image {{
    width: 100%;
    margin-bottom: 28px;
    border-radius: var(--radius);
    overflow: hidden;
    position: relative;
    border: var(--hairline);
    box-shadow: var(--shadow-md);
    transition: box-shadow .3s var(--ease);
  }}
  .hero-image:hover {{ box-shadow: var(--shadow-lg); }}
  .hero-image img {{
    width: 100%;
    max-height: 420px;
    object-fit: cover;
    display: block;
    transition: transform .5s var(--ease);
  }}
  .hero-image:hover img {{ transform: scale(1.04); }}
  .hero-credit {{
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(transparent, rgba(0,0,0,0.55));
    color: rgba(255,255,255,0.85);
    font-size: 11.5px;
    padding: 24px 12px 8px;
    text-align: left;
    direction: ltr;
  }}
  .hero-credit a {{ color: rgba(255,255,255,0.85); text-decoration: none; }}
  /* ─── content ─── */
  .article-intro {{
    position: relative;
    overflow: hidden;
    font-size: 1.07rem;
    font-weight: 500;
    color: var(--ink);
    background: var(--gold-fill);
    border: var(--hairline-gold);
    border-right: 4px solid var(--gold);
    padding: 18px 22px;
    border-radius: var(--radius);
    margin-bottom: 30px;
    line-height: 1.9;
    box-shadow: var(--shadow-sm);
    transition: box-shadow .3s var(--ease);
  }}
  .article-intro:hover {{ box-shadow: var(--shadow-md); }}
  .article-body h2 {{
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--ink);
    margin: 36px 0 10px;
    padding-right: 14px;
    border-right: 4px solid var(--gold);
  }}
  .article-body h3 {{
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--gold);
    margin: 24px 0 8px;
  }}
  .article-body p {{
    margin-bottom: 16px;
    color: #3a2f1f;
  }}
  .article-body .answer-box {{
    position: relative;
    overflow: hidden;
    background: var(--teal-light);
    border: 1px solid rgba(74,139,126,.22);
    border-right: 4px solid var(--teal);
    border-radius: var(--radius);
    padding: 14px 18px;
    font-weight: 600;
    color: #234a43;
    margin-bottom: 16px;
    box-shadow: var(--shadow-sm);
    transition: box-shadow .3s var(--ease);
  }}
  .article-body .answer-box:hover {{ box-shadow: var(--shadow-md); }}
  .article-body blockquote {{
    background: var(--rose-light);
    border: 1px solid rgba(184,106,82,.22);
    border-right: 4px solid var(--rose);
    padding: 14px 20px;
    margin: 18px 0;
    border-radius: var(--radius);
    font-style: normal;
    color: #7a3d2c;
    box-shadow: var(--shadow-sm);
  }}
  .article-body a {{ color: var(--gold); text-decoration: underline; text-underline-offset: 3px; }}
  .article-body a:hover {{ color: #936420; }}
  img.inline-img {{
    width: 100%;
    border-radius: var(--radius);
    margin: 0;
    display: block;
    transition: transform .5s var(--ease);
  }}
  .inline-figure {{
    margin: 28px 0;
    border-radius: var(--radius);
    overflow: hidden;
    border: var(--hairline);
    box-shadow: var(--shadow-md);
    transition: box-shadow .3s var(--ease);
  }}
  .inline-figure:hover {{ box-shadow: var(--shadow-lg); }}
  .inline-figure:hover img.inline-img {{ transform: scale(1.04); }}
  .inline-credit {{
    font-size: 11.5px;
    color: #94a3b8;
    text-align: left;
    direction: ltr;
    margin-top: 6px;
  }}
  .inline-credit a {{ color: #94a3b8; text-decoration: none; }}
  /* ─── tags ─── */
  .tags-row {{
    margin: 28px 0 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .tag {{
    display: inline-block;
    background: var(--gold-fill);
    color: #8a5e1f;
    border: var(--hairline-gold);
    border-radius: 20px;
    padding: 5px 15px;
    font-size: 13px;
    font-weight: 500;
    transition: background .2s var(--ease), color .2s var(--ease);
  }}
  .tag:hover {{
    background: var(--gold);
    color: var(--cream);
  }}
  /* ─── FAQ ─── */
  .faq-section {{
    position: relative;
    margin: 38px 0;
    border-radius: var(--radius);
    overflow: hidden;
    background: #fffdf9;
    border: var(--hairline);
    box-shadow: var(--shadow-sm);
  }}
  .faq-section h2 {{
    background: var(--sand);
    margin: 0;
    padding: 16px 22px;
    font-size: 1.1rem;
    border-right: none;
    color: var(--ink);
  }}
  .faq-item {{
    border-top: 1px solid rgba(30,20,8,.07);
    padding: 16px 22px;
    transition: background .2s var(--ease);
  }}
  .faq-item:hover {{ background: var(--gold-fill); }}
  .faq-item h3 {{ font-size: 1rem; color: var(--gold); margin-bottom: 6px; }}
  .faq-item p {{ margin: 0; color: #3a2f1f; }}
  /* ─── source ─── */
  .source-box {{
    position: relative;
    overflow: hidden;
    background: var(--sand);
    border: var(--hairline);
    border-radius: var(--radius);
    padding: 16px 20px;
    font-size: 14px;
    color: #6b5c45;
    margin-top: 34px;
    box-shadow: var(--shadow-sm);
  }}
  .source-box a {{ color: var(--gold); }}
  .footer-meta {{
    margin-top: 16px;
    font-size: 13px;
    color: #9a8a72;
    text-align: center;
  }}
  /* روی موبایل/لمسی، lift غیرفعال تا کادرها نپرند */
  @media (hover: none), (max-width: 768px) {{
    .article-intro:hover, .answer-box:hover, .hero-image:hover,
    .inline-figure:hover, .tag:hover {{
      transform: none;
    }}
  }}
  /* ─── افکت اسکرول: ظاهر شدن نرمِ کادرها هنگام پایین آمدن ─── */
  .reveal {{
    opacity: 0;
    transform: translateY(28px);
    transition: opacity .6s var(--ease), transform .6s var(--ease);
    will-change: opacity, transform;
  }}
  .reveal.is-visible {{
    opacity: 1;
    transform: translateY(0);
  }}
  @media (prefers-reduced-motion: reduce) {{
    .reveal {{ opacity: 1; transform: none; transition: none; }}
  }}
  /* ─── افکت spotlight — هاله‌ی سفیدِ درخشانِ کمرنگ که دنبال ماوس روی کادر حرکت می‌کند (سبک vlumis) ─── */
  .article-intro,
  .article-body .answer-box,
  .faq-section,
  .source-box,
  .hero-image,
  .inline-figure {{
    position: relative;
  }}
  .article-intro::before,
  .article-body .answer-box::before,
  .faq-section::before,
  .source-box::before,
  .hero-image::before,
  .inline-figure::before {{
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: radial-gradient(
      220px circle at var(--mx, 50%) var(--my, 50%),
      rgba(255,249,235,.55),
      rgba(184,133,58,.14) 38%,
      rgba(184,133,58,0) 68%
    );
    opacity: 0;
    transition: opacity .3s var(--ease);
    pointer-events: none;
    z-index: 4;
  }}
  .article-intro:hover::before,
  .article-body .answer-box:hover::before,
  .faq-section:hover::before,
  .source-box:hover::before,
  .hero-image:hover::before,
  .inline-figure:hover::before {{
    opacity: 1;
  }}
  @media (hover: none) {{
    .article-intro::before, .article-body .answer-box::before,
    .faq-section::before, .source-box::before,
    .hero-image::before, .inline-figure::before {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="container">

  <header class="article-header">
    <div class="article-breadcrumb">
      {breadcrumb}
    </div>
    <h1 class="article-title">{title}</h1>
    <div class="article-meta">
      <span class="site-name">{site_name}</span>
      <span>📅 {date}</span>
      <span>🏷️ {tags_text}</span>
    </div>
  </header>

{hero_html}

  <div class="article-intro">
    {intro}
  </div>

  <div class="article-body">
    {body}
  </div>

  <div class="tags-row">
    {tags_html}
  </div>

{faq_html}

  <div class="source-box">
    {source_html}
  </div>

  <p class="footer-meta">تولیدشده توسط ایجنت محتوا — {date}</p>
</div>
<script>
(function () {{
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var sel = '.article-intro, .hero-image, .article-body > h2, .article-body > p, .inline-figure, .tags-row, .faq-section, .source-box';
  var els = [].slice.call(document.querySelectorAll(sel));
  if (!els.length) return;
  // کلاس مخفی فقط با JS اضافه می‌شود تا بدون JS هم محتوا دیده شود
  els.forEach(function (el) {{ el.classList.add('reveal'); }});
  function show(el) {{
    el.classList.add('is-visible');
    // بعد از پایان انیمیشن، کلاس‌ها را پاک کن تا hover سه‌بعدی سالم بماند
    setTimeout(function () {{ el.classList.remove('reveal', 'is-visible'); }}, 700);
  }}
  if (!('IntersectionObserver' in window)) {{
    els.forEach(show);
    return;
  }}
  var io = new IntersectionObserver(function (entries) {{
    entries.forEach(function (entry) {{
      if (entry.isIntersecting) {{
        show(entry.target);
        io.unobserve(entry.target);
      }}
    }});
  }}, {{ threshold: 0.12, rootMargin: '0px 0px -40px 0px' }});
  els.forEach(function (el) {{ io.observe(el); }});
}})();
(function () {{
  // افکت spotlight — هاله‌ی سفید دنبالِ ماوس روی هر کادر حرکت می‌کند
  var glowSel = '.article-intro, .article-body .answer-box, .faq-section, .source-box, .hero-image, .inline-figure';
  [].slice.call(document.querySelectorAll(glowSel)).forEach(function (card) {{
    card.addEventListener('mousemove', function (e) {{
      var r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      card.style.setProperty('--my', (e.clientY - r.top) + 'px');
    }});
  }});
}})();
</script>
</body>
</html>
"""


def _hero_html(image: dict | None) -> str:
    if not image:
        return ""
    credit = (
        f'Photo by <a href="{image["photographer_url"]}" target="_blank">'
        f'{image["photographer"]}</a> on '
        f'<a href="{image["pexels_url"]}" target="_blank">Pexels</a>'
    )
    return (
        f'  <div class="hero-image">\n'
        f'    <img src="{image["url"]}" alt="{image["alt"]}" loading="lazy">\n'
        f'    <div class="hero-credit">{credit}</div>\n'
        f'  </div>\n'
    )


def _inline_image_html(image: dict | None) -> str:
    """عکس دوم — داخل متن (با کپشن کوچک اعتبار عکاس)."""
    if not image:
        return ""
    credit = (
        f'Photo by <a href="{image["photographer_url"]}" target="_blank">'
        f'{image["photographer"]}</a> on '
        f'<a href="{image["pexels_url"]}" target="_blank">Pexels</a>'
    )
    return (
        f'<figure class="inline-figure">'
        f'<img class="inline-img" src="{image["url"]}" alt="{image["alt"]}" loading="lazy">'
        f'<figcaption class="inline-credit">{credit}</figcaption>'
        f'</figure>'
    )


def _build_body(article: GeneratedArticle, inline_image: dict | None = None) -> str:
    """بدنه را می‌سازد؛ عکس دوم را وسط متن (بعد از بخش دوم) جا می‌دهد."""
    parts: list[str] = []
    # نقطه‌ی درج عکس دوم: بعد از بخش دوم تا میانه‌ی مقاله بیفتد
    insert_after = 1 if len(article.sections) >= 3 else len(article.sections)
    for i, s in enumerate(article.sections):
        parts.append(f'<h2>{s["h2"]}</h2>')
        parts.append(f'<p class="answer-box">{s["answer"]}</p>')
        parts.append(f'<p>{s["body"]}</p>')
        if inline_image and i == insert_after:
            parts.append(_inline_image_html(inline_image))
    parts.append(f'<h2>جمع‌بندی</h2><p>{article.conclusion}</p>')
    return "\n    ".join(parts)


def _faq_html(faq: list[dict]) -> str:
    if not faq:
        return ""
    items = "\n".join(
        f'    <div class="faq-item"><h3>{item["q"]}</h3><p>{item["a"]}</p></div>'
        for item in faq
    )
    schema_items = [
        {
            "@type": "Question",
            "name": item["q"],
            "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
        }
        for item in faq
    ]
    import json
    schema = json.dumps(
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": schema_items},
        ensure_ascii=False,
    )
    return (
        f'  <div class="faq-section">\n'
        f'    <h2>پرسش‌های متداول</h2>\n'
        f'{items}\n'
        f'  </div>\n'
        f'  <script type="application/ld+json">{schema}</script>\n'
    )


def _safe_filename(slug: str) -> str:
    slug = slug.strip() or "article"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug).strip("-")
    return slug[:60] or "article"


def render_full_page(
    article: GeneratedArticle,
    image: dict | None = None,
    cfg: TenantConfig | None = None,
    inline_image: dict | None = None,
) -> str:
    """یک صفحه‌ی HTML کامل به سبک دیجیاتو می‌سازد.

    image = عکس شاخص (hero)؛ inline_image = عکس دوم وسط متن.
    """
    cfg = cfg or TenantConfig.load()
    _now = datetime.now(timezone.utc)
    today = f"{_now.day} {_now.strftime('%B %Y')}"
    tags_text = " | ".join(article.tags[:4])
    tags_html = " ".join(f'<span class="tag">{t}</span>' for t in article.tags)

    site_name = cfg.site_name or "وبسایت"
    site_url = cfg.site_url or "#"
    cat_url = cfg.site_category_url or site_url
    cat_name = cfg.site_category_name or "هوش مصنوعی"
    breadcrumb = (
        f'<a href="{site_url}">{site_name}</a> ← '
        f'<a href="{cat_url}">{cat_name}</a>'
    )

    source_html = ""
    if article.source_url:
        source_html = (
            f'منبع: <a href="{article.source_url}" rel="nofollow" target="_blank">'
            f'{article.source_name or article.source_url}</a>'
        )

    return _PAGE_TEMPLATE.format(
        title=article.title,
        meta=article.meta_description,
        date=today,
        site_name=site_url.replace("https://", "").replace("http://", ""),
        breadcrumb=breadcrumb,
        tags_text=tags_text,
        tags_html=tags_html,
        hero_html=_hero_html(image),
        intro=article.intro,
        body=_build_body(article, inline_image=inline_image),
        faq_html=_faq_html(article.faq),
        source_html=source_html,
    )


def save_article_html(
    article: GeneratedArticle,
    image: dict | None = None,
    cfg: TenantConfig | None = None,
    out_dir: Path | None = None,
    inline_image: dict | None = None,
) -> Path:
    """صفحه‌ی کامل را در outputs/<slug>.html ذخیره می‌کند و مسیر را برمی‌گرداند."""
    cfg = cfg or TenantConfig.load()
    out_dir = out_dir or OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_safe_filename(article.slug)}.html"
    path.write_text(
        render_full_page(article, image=image, cfg=cfg, inline_image=inline_image),
        encoding="utf-8",
    )
    return path
