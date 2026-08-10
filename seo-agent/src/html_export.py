"""ذخیره‌ی مقاله‌ی نهایی (بازنویسی‌شده) به‌صورت فایل HTML برای تحلیل دستی.

هر مقاله‌ی عبورکرده در پوشه‌ی output/ به‌صورت article-<id>-<slug>.html ذخیره می‌شود.
شامل عنوان، متا، نمره، بدنه، FAQ و گزارش QA است.
"""
import html
import re

from .config import OUTPUT_DIR


def _md_to_html(text: str) -> str:
    """تبدیل ساده‌ی markdown به HTML (اگر متن قبلاً HTML باشد دست‌نخورده می‌ماند)."""
    if "<p>" in text or "<h2" in text:
        return text  # قبلاً HTML است

    # نشانگرهای لینک داخلی/خارجی پرامپت را قابل‌خواندن کن
    text = re.sub(r"\[\[anchor:\s*([^|\]]+)\|([^\]]+)\]\]", r"<a href='#'>\1</a> <small>(لینک داخلی: \2)</small>", text)
    text = re.sub(r"\[\[external:\s*([^|\]]+)\|([^\]]+)\]\]", r"<a href='\2'>\1</a>", text)

    lines = text.split("\n")
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            out.append(f"<h3>{s[4:]}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{s[3:]}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{s[2:]}</h1>")
        else:
            out.append(f"<p>{s}</p>")
    return "\n".join(out)


def export_article(article_id: int, payload: dict) -> str:
    """مقاله را به یک فایل HTML می‌نویسد و مسیر آن را برمی‌گرداند."""
    title = payload.get("title_seo") or payload.get("h1", "بدون عنوان")
    meta = payload.get("meta_description", "")
    slug = payload.get("slug", f"article-{article_id}")
    score = payload.get("seo_grade", "-")
    body_raw = payload.get("body_markdown") or payload.get("body_html", "")
    body_html = _md_to_html(body_raw)

    faq = payload.get("faq", [])
    faq_html = ""
    if faq:
        items = "\n".join(
            f"<details><summary>{html.escape(f.get('q',''))}</summary><p>{html.escape(f.get('a',''))}</p></details>"
            for f in faq
        )
        faq_html = f"<section class='faq'><h2>پرسش‌های متداول</h2>{items}</section>"

    qa = payload.get("qa_analysis", {})

    # لایه‌ی نمره‌ی نهایی متمرکز — رکوردهای قدیمی این فیلدها را ندارند و بخش حذف می‌شود
    final_html = ""
    fs_meta = ""
    fscore = payload.get("final_score")
    fverdict = payload.get("final_verdict")
    breakdown = payload.get("score_breakdown") or {}
    if fscore is not None:
        verdict_fa = {"approved": "✔ تایید خودکار", "needs_review": "⚠ نیاز به بررسی"}.get(
            fverdict, html.escape(str(fverdict))
        )
        fs_meta = (f" &nbsp;|&nbsp; <strong>نمره‌ی نهایی:</strong> {fscore} ({verdict_fa})")

        comps = breakdown.get("components", {}) or {}
        comp_rows = "\n".join(
            f"<tr><td>{lbl}</td><td>{comps.get(k) if comps.get(k) is not None else '—'}</td></tr>"
            for k, lbl in [("qa", "QA فنی"), ("gate", "دروازه‌ی کیفیت"), ("semrush", "SEMrush")]
        )
        gates = breakdown.get("hard_gates", {}) or {}
        _g = {True: "✔ پاس", False: "✘ ردّ", None: "—"}
        gate_rows = "\n".join(
            f"<tr><td>{lbl}</td><td>{_g.get(gates.get(k), '—')}</td></tr>"
            for k, lbl in [("qa_passed", "QA"), ("quality_gate_passed", "دروازه‌ی کیفیت"),
                           ("code_checks_ok", "چک‌های کد"), ("semrush_ok", "SEMrush"),
                           ("score_ok", "آستانه‌ی نمره‌ی نهایی")]
        )
        reasons_items = "\n".join(
            f"<li>{html.escape(str(r))}</li>" for r in (breakdown.get("reasons") or [])
        )
        final_html = (
            f"<section class='qa'><h2>نمره‌ی نهایی: {fscore}/100 — {verdict_fa}</h2>"
            f"<h3>اجزای نمره (۰-۱۰۰)</h3>"
            f"<table><tr><th>جزء</th><th>نمره</th></tr>{comp_rows}</table>"
            f"<h3>گیت‌های سخت</h3>"
            f"<table><tr><th>گیت</th><th>وضعیت</th></tr>{gate_rows}</table>"
            + (f"<h3>دلایل</h3><ul>{reasons_items}</ul>" if reasons_items else "")
            + "</section>"
        )

    # بخش تحلیل SEMrush (فاز C) — اگر موجود باشد
    semrush_html = ""
    sr = qa.get("semrush")
    if sr:
        per = sr.get("per_kw", {}) or {}
        rows = "\n".join(
            f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v.get('volume','-')))}</td>"
            f"<td>{html.escape(str(v.get('kd','-')))}</td></tr>"
            for k, v in per.items()
        )
        semrush_html = (
            f"<section class='semrush'><h2>تحلیل SEMrush</h2>"
            f"<p><strong>نتیجه:</strong> {html.escape(str(sr.get('verdict','-')))} "
            f"&nbsp;|&nbsp; <strong>میانگین سختی (KD):</strong> {html.escape(str(sr.get('avg_kd','-')))}</p>"
            f"<table><tr><th>کیورد</th><th>حجم</th><th>KD</th></tr>{rows}</table>"
            f"<p><small>{html.escape(str(sr.get('notes','')))}</small></p></section>"
        )

    # دروازه‌ی کیفیت محتوا (لحن انسانی / E-E-A-T / Conversion)
    gate_html = ""
    gate = qa.get("quality_gate")
    if gate:
        s = gate.get("scores", {}) or {}
        score_rows = "\n".join(
            f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}/10</td></tr>"
            for k, v in s.items()
        )
        cliche_items = "\n".join(
            f"<li>«{html.escape(str(c.get('quote','')))}» ← <em>{html.escape(str(c.get('better','')))}</em></li>"
            for c in (gate.get("cliches") or [])[:10]
        )
        recs = gate.get("recommendations", {}) or {}
        rec_html = ""
        for key, label in [("high_priority", "ضروری قبل از انتشار"),
                           ("medium_priority", "برای افزایش رتبه"),
                           ("long_term", "برای Authority شدن")]:
            items = recs.get(key) or []
            if items:
                lis = "\n".join(f"<li>{html.escape(str(i))}</li>" for i in items)
                rec_html += f"<h3>{label}</h3><ul>{lis}</ul>"
        gate_html = (
            f"<section class='qa'><h2>دروازه‌ی کیفیت محتوا "
            f"({'✔ عبور' if gate.get('passed') else '✘ ردّ'} — وزنی {gate.get('weighted_score','-')}/10)</h2>"
            f"<table><tr><th>بُعد</th><th>امتیاز</th></tr>{score_rows}</table>"
            + (f"<h3>کلیشه‌های یافت‌شده</h3><ul>{cliche_items}</ul>" if cliche_items else "")
            + rec_html
            + "</section>"
        )

    # تاریخچه‌ی ویرایش تحریریه (حلقه‌ی اصلاح)
    revision_html = ""
    history = qa.get("revision_history") or []
    remaining = qa.get("issues_remaining") or []
    if history or remaining:
        hist_rows = "\n".join(
            f"<tr><td>{h.get('revision','-')}</td>"
            f"<td>{h.get('score_before','-')} → {h.get('score_after','-')}</td>"
            f"<td>{h.get('issues_before','-')} → {h.get('issues_after','-')}</td>"
            f"<td>{h.get('patches','-')}</td>"
            f"<td>{html.escape(str(h.get('plan_summary','')))}</td></tr>"
            for h in history
        )
        remain_items = "\n".join(
            f"<li><strong>{html.escape(str(i.get('category','')))}</strong> "
            f"({html.escape(str(i.get('severity','')))}) — "
            f"{html.escape(str(i.get('problem','')))}</li>"
            for i in remaining
        )
        remain_block = (
            f"<h3>ایرادات باقی‌مانده ({len(remaining)})</h3><ul>{remain_items}</ul>"
            if remaining else "<p>✔ هیچ ایراد بازی نمانده است.</p>"
        )
        revision_html = (
            f"<section class='qa'><h2>تاریخچه‌ی ویرایش تحریریه</h2>"
            f"<p><strong>تعداد دورهای اصلاح:</strong> {len(history)} "
            f"&nbsp;|&nbsp; <strong>نمره‌ی نهایی:</strong> {score}</p>"
            + (
                f"<table><tr><th>دور</th><th>نمره</th><th>ایرادات</th>"
                f"<th>پچ‌ها</th><th>خلاصه</th></tr>{hist_rows}</table>"
                if history else ""
            )
            + remain_block
            + "</section>"
        )

    qa_html = ""
    if qa:
        checks = qa.get("qa_report", {}).get("checks", [])
        rows = "\n".join(
            f"<tr><td>{html.escape(c.get('check',''))}</td><td>{html.escape(str(c.get('status','')))}</td></tr>"
            for c in checks
        )
        qa_html = (
            f"<section class='qa'><h2>گزارش QA (نمره: {score})</h2>"
            f"<table><tr><th>چک</th><th>وضعیت</th></tr>{rows}</table></section>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(meta)}">
<style>
  body {{ font-family: Tahoma, Vazirmatn, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; line-height: 1.9; color: #1a1a1a; }}
  .meta-box {{ background: #f5f5f5; border-right: 4px solid #2a9d5c; padding: 1rem; margin-bottom: 2rem; font-size: .9rem; }}
  h1 {{ color: #1a5c38; }}
  h2 {{ color: #2a9d5c; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }}
  .qa table {{ border-collapse: collapse; width: 100%; }}
  .qa td, .qa th {{ border: 1px solid #ccc; padding: .4rem .8rem; text-align: right; }}
  details {{ margin: .5rem 0; }}
  summary {{ cursor: pointer; font-weight: bold; }}
</style>
</head>
<body>
  <div class="meta-box">
    <strong>عنوان سئو:</strong> {html.escape(title)} ({len(title)} کاراکتر)<br>
    <strong>متا:</strong> {html.escape(meta)} ({len(meta)} کاراکتر)<br>
    <strong>Slug:</strong> {html.escape(slug)} &nbsp;|&nbsp; <strong>نمره:</strong> {score}{fs_meta}
  </div>
  {final_html}
  <article>
    {body_html}
  </article>
  {faq_html}
  {semrush_html}
  {gate_html}
  {revision_html}
  {qa_html}
</body>
</html>
"""
    safe_slug = re.sub(r"[^a-zA-Z0-9\-]", "-", slug)[:50]
    path = OUTPUT_DIR / f"article-{article_id}-{safe_slug}.html"
    path.write_text(doc, encoding="utf-8")
    return str(path)
