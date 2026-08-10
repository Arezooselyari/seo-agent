/**
 * validate_article.js — اعتبارسنجی برنامه‌ای مقاله سئوی فارسی
 *
 * دو حالت مصرف:
 *   1) Claude Code:  node scripts/validate_article.js content/my-slug.json
 *   2) n8n Code node: محتوای تابع validateArticle را کپی کن (پایین فایل توضیح داده شده)
 *
 * خروجی: { passed, errors[], stats{} }
 */

const BANNED = [
  'در دنیای امروز', 'در عصر حاضر', 'در دنیای پرشتاب امروز', 'با پیشرفت روزافزون',
  'همان‌طور که می‌دانید', 'در این مقاله قصد داریم', 'بیایید با هم بررسی کنیم',
  'شایان ذکر است', 'لازم به ذکر است', 'بدون شک', 'بی‌شک', 'قابل ذکر است',
  'نکته حائز اهمیت', 'باید توجه داشت که', 'می‌باشد', 'گردید', 'گشت',
  'بی‌نظیر', 'شگفت‌انگیز', 'انقلابی', 'خارق‌العاده', 'فوق‌العاده', 'چشمگیر',
  'نقش بسزایی', 'بی‌سابقه', 'باز کردن قفل', 'سفری به دنیای', 'غواصی عمیق',
  'تغییردهنده بازی', 'نقشه راه به سوی موفقیت', 'چشم‌انداز در حال تحول',
  'امیدواریم این مقاله', 'در نهایت می‌توان گفت', 'به‌طور کلی می‌توان نتیجه گرفت',
  'اگر سؤالی دارید در بخش نظرات'
];

const THRESHOLDS = {
  keywordDensityMin: 0.8,
  keywordDensityMax: 1.5,
  sentenceStdDevMin: 5,
  bulletRatioMax: 30,
  titleMin: 50,
  titleMax: 60,
  metaMin: 140,
  metaMax: 158,
  h2Min: 5,
  h2Max: 9,
  faqMin: 4
};

function stripTags(html) {
  return String(html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

function validateArticle(article) {
  const errors = [];
  const html = article.body_html || '';
  const text = stripTags(html);
  const words = text.split(/\s+/).filter(Boolean);
  const wordCount = words.length || 1;

  // ۱ — عبارات ممنوع
  const found = BANNED.filter((p) => text.includes(p));
  if (found.length) errors.push({ rule: 'banned_phrases', severity: 'high', found });

  // ۲ — چگالی کلیدواژه
  const kw = article.focus_keyword || '';
  let density = 0;
  if (kw) {
    const hits = text.split(kw).length - 1;
    density = (hits / wordCount) * 100;
    if (density < THRESHOLDS.keywordDensityMin || density > THRESHOLDS.keywordDensityMax) {
      errors.push({ rule: 'keyword_density', severity: 'high', value: +density.toFixed(2), expected: '0.8–1.5%' });
    }
    // حضور در ۱۰۰ کلمه اول
    if (!words.slice(0, 100).join(' ').includes(kw.split(' ')[0])) {
      errors.push({ rule: 'keyword_missing_in_intro', severity: 'medium' });
    }
  }

  // ۳ — نیم‌فاصله
  if (/\sمی\s/.test(text) || /\sنمی\s/.test(text)) {
    errors.push({ rule: 'zwnj_missing_prefix', severity: 'high', hint: 'می / نمی با فاصله کامل نوشته شده' });
  }

  // ۴ — تنوع طول جمله (قوی‌ترین سیگنال متن AI)
  const lens = text.split(/[.!?؟]/).map((s) => s.trim()).filter(Boolean).map((s) => s.split(/\s+/).length);
  let sd = 0;
  if (lens.length > 1) {
    const mean = lens.reduce((a, b) => a + b, 0) / lens.length;
    sd = Math.sqrt(lens.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / lens.length);
    if (sd < THRESHOLDS.sentenceStdDevMin) {
      errors.push({ rule: 'low_burstiness', severity: 'high', sd: +sd.toFixed(2), hint: 'متن یکنواخت است — طول جمله‌ها را نامنظم کن' });
    }
  }

  // ۵ — سلسله‌مراتب هدینگ
  const levels = (html.match(/<h[2-4]/g) || []).map((t) => Number(t.slice(2)));
  for (let i = 1; i < levels.length; i++) {
    if (levels[i] - levels[i - 1] > 1) {
      errors.push({ rule: 'heading_jump', severity: 'medium', at: i });
      break;
    }
  }
  const h2Count = levels.filter((l) => l === 2).length;
  if (h2Count < THRESHOLDS.h2Min || h2Count > THRESHOLDS.h2Max) {
    errors.push({ rule: 'h2_count', severity: 'low', value: h2Count });
  }

  // ۶ — نسبت بولت‌پوینت
  const liBlocks = html.match(/<li[^>]*>[\s\S]*?<\/li>/g) || [];
  const liWords = liBlocks.reduce((sum, b) => sum + stripTags(b).split(/\s+/).filter(Boolean).length, 0);
  const bulletRatio = (liWords / wordCount) * 100;
  if (bulletRatio > THRESHOLDS.bulletRatioMax) {
    errors.push({ rule: 'bullet_ratio_high', severity: 'medium', value: +bulletRatio.toFixed(1) });
  }

  // ۷ — متادیتا
  const title = article.title || '';
  if (title.length < THRESHOLDS.titleMin || title.length > THRESHOLDS.titleMax) {
    errors.push({ rule: 'title_length', severity: 'medium', value: title.length });
  }
  const meta = article.meta_description || '';
  if (meta.length < THRESHOLDS.metaMin || meta.length > THRESHOLDS.metaMax) {
    errors.push({ rule: 'meta_length', severity: 'medium', value: meta.length });
  }
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(article.slug || '')) {
    errors.push({ rule: 'invalid_slug', severity: 'medium', value: article.slug });
  }

  // ۸ — بخش‌های اجباری
  if (!Array.isArray(article.faq) || article.faq.length < THRESHOLDS.faqMin) {
    errors.push({ rule: 'faq_too_few', severity: 'medium', value: (article.faq || []).length });
  }
  if (!article.featured_snippet) {
    errors.push({ rule: 'missing_featured_snippet', severity: 'medium' });
  }

  // ۹ — em dash
  const emDashes = (text.match(/—/g) || []).length;
  if (emDashes > 2) errors.push({ rule: 'em_dash_overuse', severity: 'low', value: emDashes });

  const highSeverity = errors.filter((e) => e.severity === 'high');

  return {
    passed: highSeverity.length === 0,
    blocking: highSeverity.length,
    errors,
    stats: {
      word_count: wordCount,
      keyword_density_percent: +density.toFixed(2),
      sentence_length_stddev: +sd.toFixed(2),
      bullet_ratio_percent: +bulletRatio.toFixed(1),
      h2_count: h2Count,
      title_length: title.length,
      meta_length: meta.length
    }
  };
}

module.exports = { validateArticle, BANNED, THRESHOLDS };

// اجرای مستقیم از CLI
if (require.main === module) {
  const fs = require('fs');
  const path = process.argv[2];
  if (!path) {
    console.error('usage: node validate_article.js <article.json>');
    process.exit(2);
  }
  const result = validateArticle(JSON.parse(fs.readFileSync(path, 'utf8')));
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.passed ? 0 : 1);
}
